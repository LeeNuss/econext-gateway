#!/usr/bin/env python3
"""Passive Modbus RTU bus sniffer.

Captures traffic on an RS-485 bus and records every frame (good or bad
CRC) into compact gzipped chunk files, one per hour, kept in a local
cache directory. A separate daily job ships finished days to the NAS
(see deploy/modbus-sniffer-ship.sh). Nothing is written to the network
by this tool.

While capturing, frames that do not look like the normal controller
poll cycle (unexpected function code, slave address, frame length, or a
burst of CRC failures) raise an alert: a line in the alerts log, a
warning in the journal, an optional webhook, and an immediate flush of
the open chunk so the evidence is on disk right away.

Chunk format: gzip text, one frame per line, "<epoch_ms> <hex>" for a
frame with a valid CRC and "<epoch_ms> ? <hex>" for bytes that did not
parse. Lines starting with "#" are headers. Concatenated chunks form a
valid multi-member gzip file, so a daily file is a plain "cat" of its
hourly chunks and reads back with the same code.

Usage:
    # Capture to a local cache (systemd service does this)
    python tools/modbus_sniffer.py capture --port /dev/heatpump --baud 9600 \
        --stopbits 2 --cache-dir /var/lib/modbus-sniffer/cache \
        --alerts /var/lib/modbus-sniffer/alerts.log

    # Interactive capture with decoded frames on the console
    python tools/modbus_sniffer.py capture --port /dev/heatpump --baud 9600 --stopbits 2 -v

    # Build a throwaway SQLite database from chunk or daily files
    python tools/modbus_sniffer.py import /mnt/nas/modbus/2026/09/*.gz --db /tmp/sept.db

    # What changed in the last 10 minutes (after a SIGUSR1 flush), and every write
    python tools/modbus_sniffer.py changes /var/lib/modbus-sniffer/cache --since 10m

    # Analyze / export the database
    python tools/modbus_sniffer.py analyze --db /tmp/sept.db
    python tools/modbus_sniffer.py analyze --db /tmp/sept.db --register 100 --slave 251
    python tools/modbus_sniffer.py export --db /tmp/sept.db --format pivot
"""

import argparse
import glob
import gzip
import io
import json
import logging
import os
import signal
import socket
import sqlite3
import struct
import sys
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import serial

log = logging.getLogger("modbus-sniffer")

# -- Modbus constants --------------------------------------------------------

FC_READ_COILS = 0x01
FC_READ_DISCRETE_INPUTS = 0x02
FC_READ_HOLDING_REGISTERS = 0x03
FC_READ_INPUT_REGISTERS = 0x04
FC_WRITE_SINGLE_COIL = 0x05
FC_WRITE_SINGLE_REGISTER = 0x06
FC_WRITE_MULTIPLE_COILS = 0x0F
FC_WRITE_MULTIPLE_REGISTERS = 0x10

FC_NAMES = {
    FC_READ_COILS: "ReadCoils",
    FC_READ_DISCRETE_INPUTS: "ReadDiscreteInputs",
    FC_READ_HOLDING_REGISTERS: "ReadHoldingRegs",
    FC_READ_INPUT_REGISTERS: "ReadInputRegs",
    FC_WRITE_SINGLE_COIL: "WriteSingleCoil",
    FC_WRITE_SINGLE_REGISTER: "WriteSingleReg",
    FC_WRITE_MULTIPLE_COILS: "WriteMultiCoils",
    FC_WRITE_MULTIPLE_REGISTERS: "WriteMultiRegs",
}

# What the wiring centre's normal poll cycle looks like. Anything else is
# worth an alert: a firmware push would show up as 0x10 writes, a vendor
# function code, long frames, or a different slave address.
NORMAL_FUNCTION_CODES = frozenset({FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS, FC_WRITE_SINGLE_REGISTER})
DEFAULT_EXPECTED_SLAVE = 251
DEFAULT_MAX_FRAME_LEN = 30
DEFAULT_BAD_CRC_PER_MINUTE = 30

CHUNK_FORMAT = "modbus-sniffer chunk v1"

# ANSI colors
C_RESET = "\033[0m"
C_REQ = "\033[36m"
C_RESP = "\033[33m"
C_ERR = "\033[31m"
C_DIM = "\033[90m"
C_HDR = "\033[1;37m"


# -- Helpers -----------------------------------------------------------------


def modbus_crc16(data: bytes) -> int:
    """Compute Modbus CRC16 (reflected, poly 0xA001)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def inter_frame_gap(baud: int) -> float:
    """Inter-frame silence threshold for USB-RS485 adapters.

    The Modbus spec says 3.5 char times, but USB adapters introduce
    latency that creates artificial gaps within frames.  Use a larger
    minimum (15ms) so that frames aren't split mid-stream.  Real
    request-to-response gaps are typically 30-50ms.
    """
    char_time = 11.0 / baud
    return max(3.5 * char_time, 0.015)


def utc_now_iso() -> str:
    """ISO 8601 timestamp with milliseconds in UTC."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def epoch_to_iso(ts: float) -> str:
    """Convert epoch float to ISO 8601 UTC string."""
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fc_name(code: int) -> str:
    fc = code & 0x7F
    name = FC_NAMES.get(fc, f"FC_0x{fc:02X}")
    if code & 0x80:
        name += "_ERR"
    return name


def parse_frame(raw: bytes, ts: float) -> dict | None:
    """Parse raw bytes as a Modbus RTU frame, checking the CRC."""
    if len(raw) < 4:
        return None
    payload = raw[:-2]
    received_crc = struct.unpack("<H", raw[-2:])[0]
    if modbus_crc16(payload) != received_crc:
        return None
    return {
        "timestamp": ts,
        "slave_addr": raw[0],
        "function_code": raw[1],
        "data": raw[2:-2],
        "raw": raw,
        "is_error": bool(raw[1] & 0x80),
    }


# -- Chunk files -------------------------------------------------------------


def _utc_parts(ts: float) -> tuple[str, str, str]:
    """(day 'YYYY-MM-DD', hour 'HH', time 'HHMMSS') in UTC."""
    t = time.gmtime(ts)
    return time.strftime("%Y-%m-%d", t), time.strftime("%H", t), time.strftime("%H%M%S", t)


class ChunkWriter:
    """Accumulates frames in an in-memory gzip stream and writes one chunk
    file per UTC hour under cache_dir/YYYY-MM-DD/HH-HHMMSS.gz.

    The file name's second part is the chunk's first frame time, so a
    forced flush or a restart within the same hour gets its own file and
    the daily "cat" keeps them in order. Day directories beyond max_days
    are pruned oldest first so an unreachable NAS can never fill the
    disk.
    """

    def __init__(self, cache_dir: Path, meta: dict | None = None, max_days: int = 14):
        self.cache_dir = Path(cache_dir)
        self.meta = meta or {}
        self.max_days = max_days
        self.total_frames = 0
        self.total_bad = 0
        self._buf: io.BytesIO | None = None
        self._gz: gzip.GzipFile | None = None
        self._start_ts: float | None = None
        self._hour: tuple[str, str] | None = None
        self.frames = 0
        self.bad = 0

    def _open(self, ts: float) -> None:
        self._buf = io.BytesIO()
        self._gz = gzip.GzipFile(fileobj=self._buf, mode="wb", compresslevel=6, mtime=0)
        self._start_ts = ts
        day, hour, _ = _utc_parts(ts)
        self._hour = (day, hour)
        self.frames = 0
        self.bad = 0
        meta = " ".join(f"{k}={v}" for k, v in self.meta.items())
        header = f"# {CHUNK_FORMAT} started={epoch_to_iso(ts)} {meta}".rstrip() + "\n"
        self._gz.write(header.encode())

    def write(self, ts: float, raw: bytes, ok: bool) -> None:
        """Record one frame. ok=False marks bytes that failed to parse."""
        day, hour, _ = _utc_parts(ts)
        if self._gz is None:
            self._open(ts)
        elif (day, hour) != self._hour:
            self.rotate("hour")
            self._open(ts)
        line = f"{int(ts * 1000)} {raw.hex()}\n" if ok else f"{int(ts * 1000)} ? {raw.hex()}\n"
        self._gz.write(line.encode())
        if ok:
            self.frames += 1
            self.total_frames += 1
        else:
            self.bad += 1
            self.total_bad += 1

    def rotate(self, reason: str) -> Path | None:
        """Close the open chunk and write it to the cache. Returns the path."""
        if self._gz is None or self._buf is None or self._start_ts is None:
            return None
        if self.frames == 0 and self.bad == 0:
            self._gz.close()
            self._gz = self._buf = None
            return None
        self._gz.close()
        data = self._buf.getvalue()
        day, hour, hms = _utc_parts(self._start_ts)
        day_dir = self.cache_dir / day
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / f"{hour}-{hms}.gz"
        n = 1
        while path.exists():  # second chunk within the same second; "_" sorts after "." so cat order holds
            path = day_dir / f"{hour}-{hms}_{n}.gz"
            n += 1
        tmp = path.with_suffix(".gz.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(day_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        log.info(
            "chunk %s/%s: %d frames, %d bad crc, %d bytes (%s)",
            day,
            path.name,
            self.frames,
            self.bad,
            len(data),
            reason,
        )
        self._gz = self._buf = None
        self.frames = 0
        self.bad = 0
        self.prune()
        return path

    def close(self) -> None:
        self.rotate("close")

    def prune(self) -> None:
        """Drop the oldest day directories beyond max_days."""
        if not self.cache_dir.is_dir():
            return
        days = sorted(p for p in self.cache_dir.iterdir() if p.is_dir() and len(p.name) == 10 and p.name[4] == "-")
        while len(days) > self.max_days:
            victim = days.pop(0)
            for f in victim.iterdir():
                f.unlink()
            victim.rmdir()
            log.warning("pruned unshipped cache day %s (cache over %d days)", victim.name, self.max_days)


def iter_chunk_records(path: str | Path) -> Iterator[tuple[float, bytes, bool]]:
    """Yield (timestamp, raw, ok) from a chunk or a concatenated daily file."""
    with gzip.open(path, "rt", encoding="ascii", errors="replace") as f:
        for line in f:
            if not line or line[0] == "#":
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            ts = int(parts[0]) / 1000.0
            if parts[1] == "?":
                if len(parts) >= 3:
                    yield ts, bytes.fromhex(parts[2]), False
            else:
                yield ts, bytes.fromhex(parts[1]), True


def chunk_meta(path: str | Path) -> dict:
    """Parse the first header line of a chunk file into a dict."""
    with gzip.open(path, "rt", encoding="ascii", errors="replace") as f:
        first = f.readline()
    meta: dict[str, str] = {}
    if first.startswith("#"):
        for token in first[1:].split():
            if "=" in token:
                k, v = token.split("=", 1)
                meta[k] = v
    return meta


# -- Alerts ------------------------------------------------------------------


class AnomalyDetector:
    """Flags frames outside the normal poll cycle and rate-limits the noise.

    Per rule, the first `detail_limit` hits are written in full, after
    that one summary line per `summary_interval` seconds. Every written
    line goes to the alerts file (if set), the log, and the webhook.
    """

    def __init__(
        self,
        expected_slave: int = DEFAULT_EXPECTED_SLAVE,
        normal_fcs: frozenset[int] = NORMAL_FUNCTION_CODES,
        max_frame_len: int = DEFAULT_MAX_FRAME_LEN,
        bad_crc_per_minute: int = DEFAULT_BAD_CRC_PER_MINUTE,
        alerts_path: Path | None = None,
        webhook: str | None = None,
        detail_limit: int = 5,
        summary_interval: float = 60.0,
        clock: Callable[[], float] = time.time,
    ):
        self.expected_slave = expected_slave
        self.normal_fcs = normal_fcs
        self.max_frame_len = max_frame_len
        self.bad_crc_per_minute = bad_crc_per_minute
        self.alerts_path = Path(alerts_path) if alerts_path else None
        self.webhook = webhook
        self.detail_limit = detail_limit
        self.summary_interval = summary_interval
        self.clock = clock
        self.last_alert_ts: float | None = None
        self.alert_count = 0
        self._bad_window: deque[float] = deque()
        self._bad_burst_active = False
        self._state: dict[str, dict] = {}

    def check(self, ts: float, raw: bytes, ok: bool) -> list[str]:
        """Return the rule keys that fired for this frame (already reported)."""
        fired: list[str] = []
        if not ok:
            self._bad_window.append(ts)
            while self._bad_window and ts - self._bad_window[0] > 60.0:
                self._bad_window.popleft()
            if len(self._bad_window) > self.bad_crc_per_minute:
                if not self._bad_burst_active:
                    self._bad_burst_active = True
                    fired.append("bad_crc_burst")
            else:
                self._bad_burst_active = False
        else:
            if raw[0] != self.expected_slave:
                fired.append("unexpected_slave")
            if (raw[1] & 0x7F) not in self.normal_fcs:
                fired.append("function_code")
            if len(raw) > self.max_frame_len:
                fired.append("long_frame")
        for key in fired:
            self._report(key, ts, raw)
        return fired

    def _report(self, key: str, ts: float, raw: bytes) -> None:
        self.alert_count += 1
        self.last_alert_ts = ts
        st = self._state.setdefault(key, {"count": 0, "pending": 0, "last_summary": None})
        st["count"] += 1
        desc = f"slave={raw[0]} fc=0x{raw[1]:02X} len={len(raw)} raw={raw.hex()}"
        if st["count"] <= self.detail_limit:
            self._write(f"ALERT {key} {epoch_to_iso(ts)} {desc}")
            st["last_summary"] = ts
            return
        st["pending"] += 1
        if st["last_summary"] is None or ts - st["last_summary"] >= self.summary_interval:
            window = f"{self.summary_interval:.0f}s"
            self._write(f"ALERT {key} {epoch_to_iso(ts)} {st['pending']} more in last {window}, last {desc}")
            st["pending"] = 0
            st["last_summary"] = ts

    def _write(self, line: str) -> None:
        log.warning("%s", line)
        if self.alerts_path is not None:
            try:
                self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.alerts_path, "a") as f:
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as exc:
                log.error("cannot write alerts file %s: %s", self.alerts_path, exc)
        if self.webhook:
            threading.Thread(target=self._post, args=(line,), daemon=True).start()

    def _post(self, line: str) -> None:
        body = json.dumps({"source": "modbus-sniffer", "host": socket.gethostname(), "message": line}).encode()
        req = urllib.request.Request(self.webhook, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception as exc:  # noqa: BLE001 - best effort, never fatal
            log.debug("webhook failed: %s", exc)


# -- Decoding (request/response pairing, register extraction) ----------------


def decode_request(frame: dict) -> dict:
    fc = frame["function_code"]
    data = frame["data"]
    out: dict = {}
    if fc in (FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS, FC_READ_COILS, FC_READ_DISCRETE_INPUTS):
        if len(data) >= 4:
            out["start"], out["count"] = struct.unpack(">HH", data[0:4])
    elif fc == FC_WRITE_SINGLE_REGISTER and len(data) >= 4:
        reg, val = struct.unpack(">HH", data[0:4])
        out.update(start=reg, count=1, values=[val], reg_type="holding", direction="write")
    elif fc == FC_WRITE_MULTIPLE_REGISTERS and len(data) >= 5:
        start, count = struct.unpack(">HH", data[0:4])
        values = [struct.unpack(">H", data[o : o + 2])[0] for o in range(5, 5 + 2 * count, 2) if o + 2 <= len(data)]
        out.update(start=start, count=count, values=values, reg_type="holding", direction="write")
    return out


def decode_response(frame: dict, req: dict) -> dict:
    fc = frame["function_code"]
    data = frame["data"]
    out: dict = {}
    if fc in (FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS) and len(data) >= 1:
        byte_count = data[0]
        values = [struct.unpack(">H", data[o : o + 2])[0] for o in range(1, 1 + byte_count, 2) if o + 2 <= len(data)]
        start = struct.unpack(">H", req["data"][0:2])[0] if len(req["data"]) >= 2 else 0
        reg_type = "holding" if fc == FC_READ_HOLDING_REGISTERS else "input"
        out.update(start=start, values=values, reg_type=reg_type, direction="read")
    return out


def looks_like_request(frame: dict) -> bool:
    """Structural check: could this frame be a master request?"""
    fc = frame["function_code"] & 0x7F
    d = frame["data"]
    if fc in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS, FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS):
        return len(d) == 4
    if fc in (FC_WRITE_SINGLE_COIL, FC_WRITE_SINGLE_REGISTER):
        return len(d) == 4
    if fc in (FC_WRITE_MULTIPLE_COILS, FC_WRITE_MULTIPLE_REGISTERS):
        return len(d) >= 5 and d[4] == len(d) - 5
    return True


def is_response_to(frame: dict, req: dict) -> bool:
    """Structural check: does this frame answer the pending request?"""
    fc = frame["function_code"] & 0x7F
    if frame["slave_addr"] != req["slave_addr"] or fc != (req["function_code"] & 0x7F):
        return False
    if frame["timestamp"] - req["timestamp"] >= 1.0:
        return False
    if frame["is_error"]:
        return True
    d = frame["data"]
    rd = req["data"]
    if fc in (FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS):
        count = struct.unpack(">H", rd[2:4])[0] if len(rd) >= 4 else -1
        return len(d) == 1 + 2 * count and d[0] == 2 * count
    if fc in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS):
        return len(d) >= 1 and len(d) == 1 + d[0]
    if fc in (FC_WRITE_SINGLE_COIL, FC_WRITE_SINGLE_REGISTER):
        return d == rd
    if fc in (FC_WRITE_MULTIPLE_COILS, FC_WRITE_MULTIPLE_REGISTERS):
        return len(d) == 4 and d[:4] == rd[:4]
    return True


class Decoder:
    """Pairs requests with responses and hands decoded events to a sink.

    The sink gets `on_event(event)` where event has keys: frame,
    is_request, response_ms, decoded (see decode_request/decode_response)
    and exception (for error responses).
    """

    def __init__(self, sink):
        self.sink = sink
        self.last_request: dict | None = None
        self.frame_count = 0
        self.error_count = 0

    def feed(self, frame: dict) -> dict:
        self.frame_count += 1
        if frame["is_error"]:
            self.error_count += 1
            event = {
                "frame": frame,
                "is_request": False,
                "response_ms": None,
                "decoded": {},
                "exception": frame["data"][0] if frame["data"] else 0,
            }
            self.last_request = None
            self.sink.on_event(event)
            return event

        req = self.last_request
        if req is not None and is_response_to(frame, req):
            delta_ms = (frame["timestamp"] - req["timestamp"]) * 1000
            event = {
                "frame": frame,
                "is_request": False,
                "response_ms": delta_ms,
                "decoded": decode_response(frame, req),
                "exception": None,
            }
            self.last_request = None
        elif looks_like_request(frame):
            event = {
                "frame": frame,
                "is_request": True,
                "response_ms": None,
                "decoded": decode_request(frame),
                "exception": None,
            }
            self.last_request = frame
        else:
            # A response whose request we did not see (capture started
            # mid-exchange, or the request was lost). Keep it, but do not
            # let it poison the pairing of the next request.
            event = {"frame": frame, "is_request": False, "response_ms": None, "decoded": {}, "exception": None}
            self.last_request = None
        self.sink.on_event(event)
        return event


class ConsolePrinter:
    """Prints decoded events like the interactive sniffer always did."""

    def on_event(self, event: dict) -> None:
        frame = event["frame"]
        ts = _format_ts(frame["timestamp"])
        fc = frame["function_code"]
        d = event["decoded"]
        if event["exception"] is not None:
            _print_error(ts, frame, event["exception"])
        elif event["is_request"]:
            if "values" in d:
                vals = _vals_str(d["values"])
                print(
                    f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} "
                    f"start={d['start']} count={d['count']} values=[{vals}]{C_RESET}"
                )
            elif "start" in d:
                print(
                    f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} "
                    f"start={d['start']} count={d['count']}{C_RESET}"
                )
            else:
                data_hex = frame["data"].hex()
                print(f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} data={data_hex}{C_RESET}")
        else:
            ms = f"{C_DIM}({event['response_ms']:.1f}ms){C_RESET}"
            if "values" in d:
                end = d["start"] + len(d["values"]) - 1
                print(
                    f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} {fc_name(fc)} "
                    f"regs {d['start']}-{end}: [{_vals_str(d['values'])}] {ms}"
                )
            elif (fc & 0x7F) in (FC_WRITE_SINGLE_REGISTER, FC_WRITE_MULTIPLE_REGISTERS):
                print(f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} {fc_name(fc)} OK {ms}")
            else:
                print(f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} {fc_name(fc)} data={frame['data'].hex()} {ms}")


def _vals_str(values: list[int]) -> str:
    s = " ".join(str(v) for v in values[:8])
    if len(values) > 8:
        s += f" ... (+{len(values) - 8})"
    return s


def _format_ts(epoch: float) -> str:
    t = time.strftime("%H:%M:%S", time.localtime(epoch))
    ms = int((epoch % 1) * 1000)
    return f"{t}.{ms:03d}"


def _print_error(ts: str, frame: dict, exc_code: int):
    exc_names = {
        1: "ILLEGAL_FUNCTION",
        2: "ILLEGAL_DATA_ADDRESS",
        3: "ILLEGAL_DATA_VALUE",
        4: "SLAVE_DEVICE_FAILURE",
    }
    exc = exc_names.get(exc_code, f"EXCEPTION_{exc_code}")
    print(f"{C_ERR}[{ts}] slave={frame['slave_addr']} {fc_name(frame['function_code'])} exception={exc}{C_RESET}")


# -- Capture -----------------------------------------------------------------


class Capture:
    """Reads the serial port, assembles frames on inter-frame silence, and
    feeds them to the chunk writer, the anomaly detector and, when
    verbose, the console decoder.

    SIGTERM/SIGINT stop the capture after flushing the open chunk.
    SIGUSR1 flushes the open chunk and continues. An alert forces a
    flush too, at most once per `flush_interval` seconds.
    """

    def __init__(
        self,
        port: str,
        baud: int,
        parity: str,
        stopbits: int,
        writer: ChunkWriter,
        detector: AnomalyDetector,
        printer: ConsolePrinter | None = None,
        flush_interval: float = 300.0,
        serial_factory: Callable[..., serial.Serial] | None = None,
        prober: "Prober | None" = None,
        serial_timeout: float = 0.05,
    ):
        self.port = port
        self.baud = baud
        self.parity = parity
        self.stopbits = stopbits
        self.writer = writer
        self.detector = detector
        self.decoder = Decoder(printer) if printer else None
        self.flush_interval = flush_interval
        self.prober = prober
        self.serial_timeout = serial_timeout
        self._serial_factory = serial_factory or self._open_serial
        self._gap = inter_frame_gap(baud)
        self._buf = bytearray()
        self._buf_ts = 0.0
        self._last_byte_time = 0.0
        self._running = False
        self._flush_requested = False
        self._last_forced_flush: float | None = None

    def _open_serial(self) -> serial.Serial:
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN}
        stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
        return serial.Serial(
            port=self.port,
            baudrate=self.baud,
            parity=parity_map.get(self.parity, serial.PARITY_NONE),
            stopbits=stop_map.get(self.stopbits, serial.STOPBITS_ONE),
            bytesize=serial.EIGHTBITS,
            timeout=self.serial_timeout,
        )

    def request_stop(self, *_args) -> None:
        self._running = False

    def request_flush(self, *_args) -> None:
        self._flush_requested = True

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGUSR1, self.request_flush)

    def _process_buffer(self) -> None:
        raw = bytes(self._buf)
        ts = self._buf_ts
        self._buf.clear()
        frame = parse_frame(raw, ts)
        self.writer.write(ts, raw, frame is not None)
        if frame is not None and self.decoder is not None:
            self.decoder.feed(frame)
        elif frame is None and self.decoder is not None and len(raw) >= 4:
            print(f"{C_DIM}[?] {len(raw)}B raw: {raw[:32].hex(' ')}{'...' if len(raw) > 32 else ''} (bad CRC){C_RESET}")
        if self.detector.check(ts, raw, frame is not None):
            now = time.monotonic()
            if self._last_forced_flush is None or now - self._last_forced_flush >= self.flush_interval:
                self._last_forced_flush = now
                self.writer.rotate("alert")
        if self.prober is not None:
            self.prober.on_frame(frame, raw, time.monotonic())

    def run(self) -> None:
        self._running = True
        ser = self._serial_factory()
        if self.prober is not None:
            self.prober.attach(ser)
        log.info(
            "capturing %s at %d 8%s%d, cache %s, gap %.1fms",
            self.port,
            self.baud,
            self.parity,
            self.stopbits,
            self.writer.cache_dir,
            self._gap * 1000,
        )
        ser.reset_input_buffer()
        try:
            while self._running:
                if self._flush_requested:
                    self._flush_requested = False
                    if self._buf:
                        self._process_buffer()
                    self.writer.rotate("signal")
                if self.prober is not None:
                    self.prober.tick(time.monotonic())
                    if self.prober.finished:
                        break
                try:
                    chunk = ser.read(ser.in_waiting or 1)
                except KeyboardInterrupt:
                    break
                now = time.monotonic()
                if not chunk:
                    if self._buf and (now - self._last_byte_time) > self._gap * 2:
                        self._process_buffer()
                    continue
                if self._buf and (now - self._last_byte_time) > self._gap:
                    self._process_buffer()
                    now = time.monotonic()
                if not self._buf:
                    self._buf_ts = time.time()
                self._buf.extend(chunk)
                self._last_byte_time = now
        finally:
            if self._buf:
                self._process_buffer()
            self.writer.close()
            ser.close()
            log.info(
                "stopped: %d frames, %d bad crc, %d alerts",
                self.writer.total_frames,
                self.writer.total_bad,
                self.detector.alert_count,
            )


# -- Polite second master (probe / scan) --------------------------------------


def build_read_request(slave: int, fc: int, start: int, count: int) -> bytes:
    payload = bytes([slave, fc]) + struct.pack(">HH", start, count)
    return payload + struct.pack("<H", modbus_crc16(payload))


class Prober:
    """Transmits one request per idle gap on a bus that already has a master.

    The wiring centre polls the heat pump in a rigid cycle: request, reply
    after ~47 ms, then at least 330 ms of silence before its next request.
    This class only ever transmits inside that silence, right after it has
    seen the heat pump answer the wiring centre, and never while a wiring
    centre request is still unanswered. One probe per gap, reads only by
    default. It stops itself when the bus looks disturbed: wiring centre
    requests going unanswered, CRC failures, or our own probes timing out.

    Results reach the submitter's callback as ("ok", values),
    ("exception", code), ("timeout", None) or ("dry", None).
    """

    def __init__(
        self,
        slave: int,
        send_window: float = 0.08,
        response_timeout: float = 0.2,
        max_missed: int = 3,
        max_bad_crc: int = 3,
        max_timeouts: int = 5,
        dry_run: bool = False,
    ):
        self.slave = slave
        self.send_window = send_window
        self.response_timeout = response_timeout
        self.max_missed = max_missed
        self.max_bad_crc = max_bad_crc
        self.max_timeouts = max_timeouts
        self.dry_run = dry_run
        self.queue: deque[tuple[bytes, Callable]] = deque()
        self.pending: dict | None = None
        self.stopped = False
        self.stop_reason: str | None = None
        self.finished = False
        self.stats = {"sent": 0, "ok": 0, "exception": 0, "timeout": 0, "wc_missed": 0, "bad_crc": 0, "dry": 0}
        self.gap_samples: list[float] = []  # ms between exchange end and our send
        self._ser = None
        self._last_exchange_end: float | None = None
        self._wc_unanswered: dict | None = None
        self._missed_streak = 0
        self._timeout_streak = 0
        self._bad_window: deque[float] = deque()

    def attach(self, ser) -> None:
        self._ser = ser

    def submit(self, raw_request: bytes, callback: Callable) -> None:
        self.queue.append((raw_request, callback))

    def stop(self, reason: str) -> None:
        if not self.stopped:
            self.stopped = True
            self.stop_reason = reason
            log.error("probe stopped: %s (stats %s)", reason, self.stats)
        self.finished = True

    def on_frame(self, frame: dict | None, raw: bytes, now: float) -> None:
        if frame is None:
            self._bad_window.append(now)
            while self._bad_window and now - self._bad_window[0] > 60.0:
                self._bad_window.popleft()
            self.stats["bad_crc"] += 1
            if len(self._bad_window) >= self.max_bad_crc:
                self.stop("CRC failures on the bus while probing")
            return
        pending = self.pending
        if pending is not None:
            if raw == pending["raw"] and not pending["echoed"]:
                pending["echoed"] = True  # our own transmission read back by the adapter
                return
            if self._wc_unanswered is None and is_response_to(frame, pending["req"]):
                self.pending = None
                self._timeout_streak = 0
                if frame["is_error"]:
                    self.stats["exception"] += 1
                    pending["cb"](("exception", frame["data"][0] if frame["data"] else 0))
                else:
                    self.stats["ok"] += 1
                    pending["cb"](("ok", decode_response(frame, {"data": pending["raw"][2:-2]}).get("values", [])))
                return
        if looks_like_request(frame):
            if self._wc_unanswered is not None:
                self.stats["wc_missed"] += 1
                self._missed_streak += 1
                log.warning("wiring centre request went unanswered (%d in a row)", self._missed_streak)
                if self._missed_streak >= self.max_missed:
                    self.stop("wiring centre requests going unanswered")
            self._wc_unanswered = frame
        else:
            self._wc_unanswered = None
            self._missed_streak = 0
            self._last_exchange_end = now
            self._maybe_send(now)

    def _maybe_send(self, now: float) -> None:
        if self.stopped or self.pending is not None or not self.queue or self._ser is None:
            return
        if self._last_exchange_end is None or now - self._last_exchange_end > self.send_window:
            return
        raw, cb = self.queue.popleft()
        delay_ms = (now - self._last_exchange_end) * 1000
        self.gap_samples.append(delay_ms)
        if self.dry_run:
            self.stats["dry"] += 1
            log.info("dry run: would send %s %.0f ms after the exchange", raw.hex(), delay_ms)
            cb(("dry", None))
            return
        self._ser.write(raw)
        self.stats["sent"] += 1
        req = {"slave_addr": raw[0], "function_code": raw[1], "data": raw[2:-2], "timestamp": time.time()}
        self.pending = {"raw": raw, "req": req, "cb": cb, "sent": now, "echoed": False}
        log.debug("probe sent %s %.0f ms after the exchange", raw.hex(), delay_ms)

    def tick(self, now: float) -> None:
        pending = self.pending
        if pending is not None and now - pending["sent"] > self.response_timeout:
            self.pending = None
            self.stats["timeout"] += 1
            self._timeout_streak += 1
            log.warning("probe %s timed out", pending["raw"].hex())
            pending["cb"](("timeout", None))
            if self._timeout_streak >= self.max_timeouts:
                self.stop("heat pump not answering our probes")


class Scanner:
    """Reads a register space in blocks through a Prober and records what
    answers. An illegal-address exception on a block is bisected until
    the present and absent registers are told apart."""

    def __init__(
        self,
        prober: Prober,
        slave: int,
        fc: int,
        ranges: list[tuple[int, int]],
        block: int = 8,
        retries: int = 2,
        limit: int | None = None,
    ):
        self.prober = prober
        self.slave = slave
        self.fc = fc
        self.block = block
        self.retries = retries
        self.limit = limit
        self.todo: deque[tuple[int, int, int]] = deque()  # start, count, attempts
        for lo, hi in ranges:
            a = lo
            while a <= hi:
                c = min(block, hi - a + 1)
                self.todo.append((a, c, 0))
                a += c
        self.total = sum(hi - lo + 1 for lo, hi in ranges)
        self.done = 0
        self.probes = 0
        self.present: dict[int, int] = {}
        self.absent: set[int] = set()
        self.failed: list[tuple[int, int]] = []
        self.unsupported = False
        self.finished = False
        self._last_progress = 0

    def start(self) -> None:
        self._next()

    def _next(self) -> None:
        if not self.todo or (self.limit is not None and self.probes >= self.limit):
            self.finished = True
            self.prober.finished = True
            return
        start, count, attempts = self.todo.popleft()
        self.probes += 1
        raw = build_read_request(self.slave, self.fc, start, count)
        self.prober.submit(raw, lambda res, s=start, c=count, a=attempts: self._on_result(s, c, a, res))

    def _on_result(self, start: int, count: int, attempts: int, res: tuple) -> None:
        kind, payload = res
        if kind == "ok":
            for i, v in enumerate(payload):
                self.present[start + i] = v
            self.done += count
        elif kind == "exception":
            if payload == 1:
                self.unsupported = True
                log.error("function 0x%02X rejected as illegal function, stopping", self.fc)
                self.todo.clear()
            elif count > 1:
                half = count // 2
                self.todo.appendleft((start + half, count - half, 0))
                self.todo.appendleft((start, half, 0))
            else:
                self.absent.add(start)
                self.done += 1
        elif kind == "timeout":
            if attempts < self.retries:
                self.todo.appendleft((start, count, attempts + 1))
            else:
                self.failed.append((start, count))
                self.done += count
        else:  # dry run
            self.done += count
        if self.done - self._last_progress >= 200 or not self.todo:
            self._last_progress = self.done
            log.info(
                "scan fc=0x%02X: %d/%d registers, %d present, %d probes",
                self.fc,
                self.done,
                self.total,
                len(self.present),
                self.probes,
            )
        self._next()

    def write_results(self, path: Path) -> None:
        with open(path, "w") as f:
            head = f"slave={self.slave} fc=0x{self.fc:02X} probes={self.probes} present={len(self.present)}"
            f.write(f"# modbus scan {head}\n")
            f.write("address\tvalue\tsigned\thex\n")
            for addr in sorted(self.present):
                v = self.present[addr]
                f.write(f"{addr}\t{v}\t{v - 65536 if v > 32767 else v}\t0x{v:04X}\n")
            if self.failed:
                f.write("# timed out blocks: " + ", ".join(f"{s}+{c}" for s, c in self.failed) + "\n")
        log.info("wrote %s", path)


def parse_ranges(text: str) -> list[tuple[int, int]]:
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        out.append((int(lo), int(hi) if hi else int(lo)))
    return out


# -- Database (import / analyze / export) ------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    port TEXT,
    baud INTEGER,
    parity TEXT,
    frame_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    slave_addr INTEGER NOT NULL,
    function_code INTEGER NOT NULL,
    fc_name TEXT NOT NULL,
    is_request INTEGER NOT NULL,
    is_error INTEGER NOT NULL DEFAULT 0,
    data_hex TEXT,
    raw_hex TEXT NOT NULL,
    response_ms REAL
);

CREATE TABLE IF NOT EXISTS register_values (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    slave_addr INTEGER NOT NULL,
    reg_type TEXT NOT NULL,
    address INTEGER NOT NULL,
    value INTEGER NOT NULL,
    direction TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_regval_time
    ON register_values(timestamp);
CREATE INDEX IF NOT EXISTS idx_regval_addr
    ON register_values(slave_addr, reg_type, address);
CREATE INDEX IF NOT EXISTS idx_frames_time
    ON frames(timestamp);
CREATE INDEX IF NOT EXISTS idx_frames_session
    ON frames(session_id);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    return conn


class SqliteSink:
    """Stores decoded events into the frames and register_values tables."""

    def __init__(self, db: sqlite3.Connection, session_id: int):
        self.db = db
        self.session_id = session_id

    def on_event(self, event: dict) -> None:
        frame = event["frame"]
        self.db.execute(
            "INSERT INTO frames "
            "(session_id, timestamp, slave_addr, function_code, fc_name, "
            " is_request, is_error, data_hex, raw_hex, response_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.session_id,
                epoch_to_iso(frame["timestamp"]),
                frame["slave_addr"],
                frame["function_code"],
                fc_name(frame["function_code"]),
                int(event["is_request"]),
                int(frame["is_error"]),
                frame["data"].hex(),
                frame["raw"].hex(),
                event["response_ms"],
            ),
        )
        d = event["decoded"]
        if "values" in d and d["values"]:
            iso = epoch_to_iso(frame["timestamp"])
            self.db.executemany(
                "INSERT INTO register_values "
                "(session_id, timestamp, slave_addr, reg_type, address, value, direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (self.session_id, iso, frame["slave_addr"], d["reg_type"], d["start"] + i, v, d["direction"])
                    for i, v in enumerate(d["values"])
                ],
            )


def _expand_inputs(inputs: list[str]) -> list[Path]:
    """Files, directories (recursive *.gz) and globs, sorted."""
    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.gz")))
        elif p.exists():
            out.append(p)
        else:
            out.extend(Path(m) for m in sorted(glob.glob(item)))
    return out


def import_files(db: sqlite3.Connection, files: list[Path]) -> int:
    """Import chunk/daily files, one session per file. Returns frames imported."""
    total = 0
    for path in files:
        meta = chunk_meta(path)
        cur = db.execute(
            "INSERT INTO sessions (started_at, port, baud, parity) VALUES (?, ?, ?, ?)",
            (meta.get("started", utc_now_iso()), meta.get("port"), meta.get("baud"), meta.get("parity")),
        )
        session_id = cur.lastrowid
        decoder = Decoder(SqliteSink(db, session_id))
        bad = 0
        last_ts = None
        for ts, raw, ok in iter_chunk_records(path):
            last_ts = ts
            if not ok:
                bad += 1
                continue
            frame = parse_frame(raw, ts)
            if frame is None:
                bad += 1
                continue
            decoder.feed(frame)
        db.execute(
            "UPDATE sessions SET ended_at=?, frame_count=?, error_count=? WHERE id=?",
            (epoch_to_iso(last_ts) if last_ts else None, decoder.frame_count, decoder.error_count, session_id),
        )
        db.commit()
        total += decoder.frame_count
        print(f"{path}: {decoder.frame_count} frames, {decoder.error_count} exceptions, {bad} bad crc")
    return total


def cmd_import(args):
    files = _expand_inputs(args.inputs)
    if not files:
        print("No input files found.")
        sys.exit(1)
    db = open_db(args.db)
    total = import_files(db, files)
    db.close()
    print(f"Imported {total} frames from {len(files)} file(s) into {args.db}")


def _print_register_summary(db: sqlite3.Connection, session_id: int | None = None):
    """Print register map summary from the database."""
    where = "WHERE session_id = ?" if session_id else ""
    params = (session_id,) if session_id else ()

    rows = db.execute(
        f"""
        SELECT slave_addr, reg_type, address, direction,
               COUNT(*) as cnt,
               MIN(value) as min_val,
               MAX(value) as max_val,
               -- last value: max rowid for this group
               (SELECT value FROM register_values rv2
                WHERE rv2.slave_addr = rv.slave_addr
                  AND rv2.reg_type = rv.reg_type
                  AND rv2.address = rv.address
                  AND rv2.direction = rv.direction
                  {"AND rv2.session_id = ?" if session_id else ""}
                ORDER BY rv2.id DESC LIMIT 1) as last_val,
               COUNT(DISTINCT value) as unique_vals
        FROM register_values rv
        {where}
        GROUP BY slave_addr, reg_type, address, direction
        ORDER BY slave_addr, reg_type, address, direction
        """,
        params * 2 if session_id else (),
    ).fetchall()

    if not rows:
        print("\nNo register data captured.")
        return

    print(f"\n{'=' * 80}")
    print(f"{C_HDR}REGISTER MAP{C_RESET}")
    print(f"{'=' * 80}")

    current_slave = None
    current_type = None
    for slave, reg_type, addr, direction, cnt, min_v, max_v, last_v, uniq in rows:
        if slave != current_slave:
            current_slave = slave
            current_type = None
            print(f"\n{C_HDR}Slave {slave}{C_RESET}")
        if reg_type != current_type:
            current_type = reg_type
            print(f"\n  {reg_type} registers:")
            print(f"  {'Addr':>6s}  {'Dir':>5s}  {'Count':>7s}  {'Last':>7s}  {'Min':>7s}  {'Max':>7s}  {'Unique':>6s}")
            print(f"  {'-' * 58}")
        print(f"  {addr:6d}  {direction:>5s}  {cnt:7d}  {last_v:7d}  {min_v:7d}  {max_v:7d}  {uniq:6d}")


def cmd_analyze(args):
    """Query the database for register summaries and timeseries."""
    db = sqlite3.connect(args.db)

    sessions = db.execute(
        "SELECT id, started_at, ended_at, port, baud, parity, frame_count, error_count FROM sessions ORDER BY id"
    ).fetchall()

    print(f"{C_HDR}Sessions{C_RESET}")
    print(f"{'ID':>4s}  {'Started':>24s}  {'Ended':>24s}  {'Frames':>7s}  {'Errors':>6s}  Settings")
    print("-" * 100)
    for sid, start, end, _, baud, parity, frames, errors in sessions:
        end_str = end or "(running)"
        print(f"{sid:4d}  {start:>24s}  {end_str:>24s}  {frames or 0:7d}  {errors or 0:6d}  {baud} 8{parity}")

    session_id = args.session if args.session else None

    if args.register is not None:
        where_parts = ["address = ?"]
        params = [args.register]
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        if args.slave:
            where_parts.append("slave_addr = ?")
            params.append(args.slave)

        where = " AND ".join(where_parts)
        rows = db.execute(
            f"SELECT timestamp, slave_addr, reg_type, value, direction FROM register_values WHERE {where} ORDER BY id",
            params,
        ).fetchall()

        print(f"\n{C_HDR}Register {args.register} timeseries ({len(rows)} samples){C_RESET}")
        print(f"{'Timestamp':>28s}  {'Slave':>5s}  {'Type':>8s}  {'Dir':>5s}  {'Value':>7s}")
        print("-" * 60)
        for ts, slave, rtype, val, direction in rows[-100:]:
            print(f"{ts:>28s}  {slave:5d}  {rtype:>8s}  {direction:>5s}  {val:7d}")
        if len(rows) > 100:
            print(f"  ... showing last 100 of {len(rows)} rows")
    else:
        _print_register_summary(db, session_id)

    if not args.register:
        print(f"\n{C_HDR}Polling patterns (request frequency){C_RESET}")
        where = "WHERE is_request = 1"
        params = ()
        if session_id:
            where += " AND session_id = ?"
            params = (session_id,)

        rows = db.execute(
            f"SELECT fc_name, slave_addr, COUNT(*) as cnt "
            f"FROM frames {where} "
            f"GROUP BY fc_name, slave_addr ORDER BY cnt DESC",
            params,
        ).fetchall()
        for fname, slave, cnt in rows:
            print(f"  slave={slave} {fname}: {cnt} requests")

    db.close()


def cmd_export(args):
    """Export register timeseries to CSV for correlation with emoncms."""
    db = sqlite3.connect(args.db)

    where_parts = []
    params = []
    if args.session:
        where_parts.append("session_id = ?")
        params.append(args.session)
    if args.slave:
        where_parts.append("slave_addr = ?")
        params.append(args.slave)

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    if args.format == "csv":
        output = args.output or f"modbus_export_{int(time.time())}.csv"
        rows = db.execute(
            f"SELECT timestamp, slave_addr, reg_type, address, value, direction "
            f"FROM register_values {where} ORDER BY id",
            params,
        ).fetchall()

        with open(output, "w") as f:
            f.write("timestamp,slave_addr,reg_type,address,value,direction\n")
            for row in rows:
                f.write(",".join(str(v) for v in row) + "\n")

        print(f"Exported {len(rows)} rows to {output}")

    elif args.format == "pivot":
        output = args.output or f"modbus_pivot_{int(time.time())}.csv"

        addrs = db.execute(
            f"SELECT DISTINCT slave_addr, reg_type, address "
            f"FROM register_values {where} "
            f"ORDER BY slave_addr, reg_type, address",
            params,
        ).fetchall()

        rows = db.execute(
            f"SELECT timestamp, slave_addr, reg_type, address, value FROM register_values {where} ORDER BY id",
            params,
        ).fetchall()

        pivot = {}
        col_names = [f"s{slave}_{rtype}_{addr}" for slave, rtype, addr in addrs]

        for ts, slave, rtype, addr, val in rows:
            ts_sec = ts[:19] + "Z"
            if ts_sec not in pivot:
                pivot[ts_sec] = {}
            pivot[ts_sec][f"s{slave}_{rtype}_{addr}"] = val

        with open(output, "w") as f:
            f.write("timestamp," + ",".join(col_names) + "\n")
            for ts_sec in sorted(pivot):
                vals = [str(pivot[ts_sec].get(c, "")) for c in col_names]
                f.write(ts_sec + "," + ",".join(vals) + "\n")

        print(f"Exported pivot table ({len(pivot)} timestamps x {len(col_names)} registers) to {output}")

    db.close()


# -- Changes (value transitions over time) -----------------------------------


class ChangeTracker:
    """Sink that prints every register value transition and every write."""

    def __init__(self, since: float | None = None, show_initial: bool = False, out=None):
        self.since = since
        self.show_initial = show_initial
        self.out = out or sys.stdout
        self.last: dict[tuple[int, str, int], int] = {}
        self.change_counts: dict[tuple[int, str, int], int] = {}
        self.writes = 0

    def on_event(self, event: dict) -> None:
        d = event["decoded"]
        if "values" not in d:
            return
        frame = event["frame"]
        ts = frame["timestamp"]
        visible = self.since is None or ts >= self.since
        is_write = d.get("direction") == "write"
        if is_write and visible:
            self.writes += 1
            vals = " ".join(str(v) for v in d["values"])
            self.out.write(
                f"{epoch_to_iso(ts)}  s{frame['slave_addr']} {d['reg_type']:>7s} {d['start']:5d}  WRITE {vals}\n"
            )
        for i, value in enumerate(d["values"]):
            key = (frame["slave_addr"], d["reg_type"], d["start"] + i)
            old = self.last.get(key)
            self.last[key] = value
            if old is None:
                if self.show_initial and visible:
                    self.out.write(f"{epoch_to_iso(ts)}  s{key[0]} {key[1]:>7s} {key[2]:5d}  first {value}\n")
                continue
            if old != value and not is_write:
                self.change_counts[key] = self.change_counts.get(key, 0) + 1
                if visible:
                    self.out.write(f"{epoch_to_iso(ts)}  s{key[0]} {key[1]:>7s} {key[2]:5d}  {old} -> {value}\n")

    def summary(self) -> None:
        if not self.change_counts and not self.writes:
            self.out.write("No register changes.\n")
            return
        self.out.write(f"\n{len(self.change_counts)} registers changed, {self.writes} writes:\n")
        for (slave, rtype, addr), n in sorted(self.change_counts.items()):
            self.out.write(f"  s{slave} {rtype:>7s} {addr:5d}  {n} changes, last {self.last[(slave, rtype, addr)]}\n")


def _parse_since(text: str | None, now: float | None = None) -> float | None:
    """'30m', '2h', '1d' relative to now, or an ISO timestamp."""
    if not text:
        return None
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text[-1] in units and text[:-1].isdigit():
        return (now or time.time()) - int(text[:-1]) * units[text[-1]]
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def records_from_db(db: sqlite3.Connection) -> Iterator[tuple[float, bytes, bool]]:
    """Replay frames stored in an imported database in capture order."""
    for iso, raw_hex in db.execute("SELECT timestamp, raw_hex FROM frames ORDER BY id"):
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        yield ts, bytes.fromhex(raw_hex), True


def cmd_changes(args):
    tracker = ChangeTracker(since=_parse_since(args.since), show_initial=args.initial)
    decoder = Decoder(tracker)
    if args.db:
        db = sqlite3.connect(args.db)
        sources: list = [("db", records_from_db(db))]
    else:
        files = _expand_inputs(args.inputs)
        if not files:
            print("No input files found.")
            sys.exit(1)
        sources = [(str(p), iter_chunk_records(p)) for p in files]
    for _name, records in sources:
        for ts, raw, ok in records:
            if not ok:
                continue
            frame = parse_frame(raw, ts)
            if frame is None:
                continue
            if args.slave and frame["slave_addr"] != args.slave:
                continue
            decoder.feed(frame)
    tracker.summary()


# -- Auto-detect -------------------------------------------------------------


def auto_detect(port: str) -> tuple[int, str] | None:
    """Auto-detect baud rate and parity. Returns (baud, parity) or None."""
    from modbus_detect import BAUD_RATES, PARITIES, try_settings

    print("Auto-detecting bus parameters...\n")
    for baud in BAUD_RATES:
        for parity_name, parity_val, stopbits in PARITIES:
            label = f"{baud} 8{parity_name[0]}{stopbits}"
            print(f"  Trying {label}...", end=" ", flush=True)
            frames = try_settings(port, baud, parity_val, stopbits, 3.0)
            if frames:
                parity_char = "N" if parity_val == serial.PARITY_NONE else "E"
                print(f"OK ({len(frames)} frames)")
                return baud, parity_char
            print("no frames")
    return None


# -- CLI ---------------------------------------------------------------------


class _JournalFormatter(logging.Formatter):
    """Prefixes lines with the syslog level so journald keeps priorities."""

    _PREFIX = {logging.DEBUG: "<7>", logging.INFO: "<6>", logging.WARNING: "<4>", logging.ERROR: "<3>"}

    def format(self, record: logging.LogRecord) -> str:
        return self._PREFIX.get(record.levelno, "<6>") + super().format(record)


def _setup_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    if sys.stderr.isatty():
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    else:
        handler.setFormatter(_JournalFormatter("%(message)s"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[handler])


def main():
    parser = argparse.ArgumentParser(description="Modbus RTU bus sniffer and analyzer")
    sub = parser.add_subparsers(dest="command")

    cap = sub.add_parser("capture", help="Capture Modbus RTU traffic into a local chunk cache")
    cap.add_argument("--port", default="/dev/heatpump", help="Serial port")
    cap.add_argument("--baud", type=int, help="Baud rate")
    cap.add_argument("--parity", choices=["N", "E"], default="N", help="Parity (default: N)")
    cap.add_argument("--stopbits", type=int, choices=[1, 2], default=1, help="Stop bits (default: 1)")
    cap.add_argument("--auto-detect", action="store_true", help="Auto-detect baud/parity")
    cap.add_argument("--cache-dir", default="modbus_cache", help="Chunk cache directory (default: ./modbus_cache)")
    cap.add_argument("--alerts", help="Alerts log file (default: none, journal only)")
    cap.add_argument(
        "--webhook",
        default=os.environ.get("MODBUS_SNIFFER_WEBHOOK"),
        help="POST alert lines as JSON to this URL (env MODBUS_SNIFFER_WEBHOOK)",
    )
    cap.add_argument("--expect-slave", type=int, default=DEFAULT_EXPECTED_SLAVE, help="Slave address of the heat pump")
    cap.add_argument(
        "--max-frame-len", type=int, default=DEFAULT_MAX_FRAME_LEN, help="Alert on frames longer than this"
    )
    cap.add_argument(
        "--bad-crc-per-minute",
        type=int,
        default=DEFAULT_BAD_CRC_PER_MINUTE,
        help="Alert when more unparsable frames than this arrive within a minute",
    )
    cap.add_argument("--max-days", type=int, default=14, help="Prune cache days beyond this (default: 14)")
    cap.add_argument("--flush-interval", type=float, default=300, help="Min seconds between alert-forced flushes")
    cap.add_argument("-v", "--verbose", action="store_true", help="Print decoded frames to the console")

    scn = sub.add_parser("scan", help="Read-scan the heat pump's register space as a polite second master")
    scn.add_argument("--port", default="/dev/heatpump", help="Serial port (stop the capture service first)")
    scn.add_argument("--baud", type=int, default=9600)
    scn.add_argument("--parity", choices=["N", "E"], default="N")
    scn.add_argument("--stopbits", type=int, choices=[1, 2], default=2)
    scn.add_argument("--slave", type=int, default=DEFAULT_EXPECTED_SLAVE)
    scn.add_argument("--type", choices=["holding", "input"], default="holding", help="Register type to scan")
    scn.add_argument(
        "--ranges",
        default="0-1023,1200-1299,2000-2299,6000-6499",
        help="Address ranges, e.g. 0-511,6000-6499 (default: %(default)s)",
    )
    scn.add_argument("--block", type=int, default=8, help="Registers per read (default: 8)")
    scn.add_argument("--limit", type=int, help="Stop after this many probes")
    scn.add_argument("--dry-run", action="store_true", help="Never transmit, only report when a probe would go out")
    scn.add_argument("--send-window", type=float, default=0.08, help="Max seconds after an exchange to transmit")
    scn.add_argument("--response-timeout", type=float, default=0.2, help="Seconds to wait for the heat pump")
    scn.add_argument("--out", help="Results TSV (default: scan_<type>_<time>.tsv)")
    scn.add_argument("--cache-dir", default="modbus_cache", help="Chunk cache for the frames seen meanwhile")
    scn.add_argument("-v", "--verbose", action="store_true")

    imp = sub.add_parser("import", help="Build a SQLite database from chunk or daily files")
    imp.add_argument("inputs", nargs="+", help="Chunk files, daily files, directories or globs")
    imp.add_argument("--db", default="modbus_import.db", help="Database path (default: modbus_import.db)")

    chg = sub.add_parser("changes", help="List register value transitions and writes over time")
    chg.add_argument("inputs", nargs="*", help="Chunk files, daily files, directories or globs")
    chg.add_argument("--db", help="Read frames from an imported database instead of files")
    chg.add_argument("--since", help="Only show changes after this: 30m, 2h, 1d or an ISO timestamp")
    chg.add_argument("--slave", type=int, help="Filter to specific slave address")
    chg.add_argument("--initial", action="store_true", help="Also print the first value seen for every register")

    ana = sub.add_parser("analyze", help="Analyze an imported database")
    ana.add_argument("--db", default="modbus_import.db", help="Database path")
    ana.add_argument("--session", type=int, help="Filter to specific session ID")
    ana.add_argument("--slave", type=int, help="Filter to specific slave address")
    ana.add_argument("--register", type=int, help="Show timeseries for specific register address")

    exp = sub.add_parser("export", help="Export data for external analysis")
    exp.add_argument("--db", default="modbus_import.db", help="Database path")
    exp.add_argument(
        "--format",
        choices=["csv", "pivot"],
        default="csv",
        help="csv=raw rows, pivot=one column per register (default: csv)",
    )
    exp.add_argument("--session", type=int, help="Filter to specific session ID")
    exp.add_argument("--slave", type=int, help="Filter to specific slave address")
    exp.add_argument("--output", "-o", help="Output file path")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "import":
        cmd_import(args)
    elif args.command == "changes":
        if not args.db and not args.inputs:
            chg.error("Give chunk files/directories or --db")
        cmd_changes(args)
    elif args.command == "scan":
        _setup_logging(args.verbose)
        fc = FC_READ_HOLDING_REGISTERS if args.type == "holding" else FC_READ_INPUT_REGISTERS
        prober = Prober(
            args.slave,
            send_window=args.send_window,
            response_timeout=args.response_timeout,
            dry_run=args.dry_run,
        )
        scanner = Scanner(prober, args.slave, fc, parse_ranges(args.ranges), block=args.block, limit=args.limit)
        writer = ChunkWriter(
            Path(args.cache_dir),
            meta={"port": args.port, "baud": args.baud, "parity": args.parity, "stopbits": args.stopbits, "scan": 1},
        )
        capture = Capture(
            args.port,
            args.baud,
            args.parity,
            args.stopbits,
            writer,
            AnomalyDetector(expected_slave=args.slave),
            printer=ConsolePrinter() if args.verbose else None,
            prober=prober,
            serial_timeout=0.02,
        )
        log.info(
            "scan %s registers %s on slave %d, block %d, %s",
            args.type,
            args.ranges,
            args.slave,
            args.block,
            "DRY RUN (never transmits)" if args.dry_run else "transmitting in idle gaps",
        )
        scanner.start()
        capture.install_signal_handlers()
        capture.run()
        out = Path(args.out or f"scan_{args.type}_{time.strftime('%Y%m%d-%H%M%S')}.tsv")
        scanner.write_results(out)
        if prober.gap_samples:
            gs = sorted(prober.gap_samples)
            log.info("sent %.0f-%.0f ms after the exchange (median %.0f)", gs[0], gs[-1], gs[len(gs) // 2])
        log.info("probe stats: %s%s", prober.stats, f", stopped: {prober.stop_reason}" if prober.stop_reason else "")
    elif args.command == "capture":
        _setup_logging(args.verbose)
        if args.auto_detect:
            result = auto_detect(args.port)
            if result is None:
                print("\nFailed to auto-detect. Check wiring and bus activity.")
                sys.exit(1)
            baud, parity = result
            print(f"\nDetected: {baud} 8{parity}1\n")
        elif args.baud is None:
            cap.error("Either --baud or --auto-detect is required")
        else:
            baud = args.baud
            parity = args.parity

        writer = ChunkWriter(
            Path(args.cache_dir),
            meta={"port": args.port, "baud": baud, "parity": parity, "stopbits": args.stopbits},
            max_days=args.max_days,
        )
        detector = AnomalyDetector(
            expected_slave=args.expect_slave,
            max_frame_len=args.max_frame_len,
            bad_crc_per_minute=args.bad_crc_per_minute,
            alerts_path=Path(args.alerts) if args.alerts else None,
            webhook=args.webhook,
        )
        capture = Capture(
            args.port,
            baud,
            parity,
            args.stopbits,
            writer,
            detector,
            printer=ConsolePrinter() if args.verbose else None,
            flush_interval=args.flush_interval,
        )
        capture.install_signal_handlers()
        capture.run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
