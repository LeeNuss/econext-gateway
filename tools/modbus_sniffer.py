#!/usr/bin/env python3
"""Passive Modbus RTU bus sniffer.

Captures traffic on an RS-485 bus, decodes Modbus RTU frames, pairs
requests with responses, and stores everything in a SQLite database for
long-term analysis and correlation with emoncms data.

Usage:
    # Capture (auto-detect bus params)
    python tools/modbus_sniffer.py capture --port /dev/modbus_sniff --auto-detect

    # Capture (known params)
    python tools/modbus_sniffer.py capture --port /dev/modbus_sniff --baud 9600 --parity E

    # Analyze captured data
    python tools/modbus_sniffer.py analyze --db modbus_capture.db
    python tools/modbus_sniffer.py analyze --db modbus_capture.db --register 100 --slave 1

    # Export register timeseries to CSV (for joining with emoncms)
    python tools/modbus_sniffer.py export --db modbus_capture.db --format csv
"""

import argparse
import sqlite3
import struct
import sys
import time
from datetime import UTC, datetime

import serial

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


# -- Database ----------------------------------------------------------------

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
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# -- Sniffer -----------------------------------------------------------------


class ModbusSniffer:
    """Captures and decodes Modbus RTU frames from a serial port."""

    def __init__(self, port: str, baud: int, parity: str, db_path: str, stopbits: int = 1):
        self.port = port
        self.baud = baud
        self.parity = parity
        self._stopbits = stopbits
        self.db = open_db(db_path)
        self.db_path = db_path
        self.frame_count = 0
        self.error_count = 0
        self.last_request = None  # (frame_data, timestamp)
        self._running = False

        # Frame assembly
        self._buf = bytearray()
        self._last_byte_time = 0.0
        self._gap = inter_frame_gap(baud)

        # Start session
        cur = self.db.execute(
            "INSERT INTO sessions (started_at, port, baud, parity) VALUES (?, ?, ?, ?)",
            (utc_now_iso(), port, baud, parity),
        )
        self.session_id = cur.lastrowid
        self.db.commit()

    def _open_serial(self) -> serial.Serial:
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN}
        stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
        return serial.Serial(
            port=self.port,
            baudrate=self.baud,
            parity=parity_map.get(self.parity, serial.PARITY_NONE),
            stopbits=stop_map.get(self._stopbits, serial.STOPBITS_ONE),
            bytesize=serial.EIGHTBITS,
            timeout=0.05,
        )

    def _parse_frame(self, raw: bytes) -> dict | None:
        """Parse raw bytes, check CRC. Returns dict or None."""
        if len(raw) < 4:
            return None
        payload = raw[:-2]
        received_crc = struct.unpack("<H", raw[-2:])[0]
        if modbus_crc16(payload) != received_crc:
            return None
        return {
            "slave_addr": raw[0],
            "function_code": raw[1],
            "data": raw[2:-2],
            "raw": raw,
            "is_error": bool(raw[1] & 0x80),
            "timestamp": time.time(),
        }

    def _store_frame(self, frame: dict, is_request: bool, response_ms: float | None = None):
        """Write frame to database."""
        ts = epoch_to_iso(frame["timestamp"])
        self.db.execute(
            "INSERT INTO frames "
            "(session_id, timestamp, slave_addr, function_code, fc_name, "
            " is_request, is_error, data_hex, raw_hex, response_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.session_id,
                ts,
                frame["slave_addr"],
                frame["function_code"],
                fc_name(frame["function_code"]),
                int(is_request),
                int(frame["is_error"]),
                frame["data"].hex(),
                frame["raw"].hex(),
                response_ms,
            ),
        )

    def _store_registers(self, slave: int, reg_type: str, start: int, values: list[int], direction: str, ts: float):
        """Write register values to timeseries table."""
        iso = epoch_to_iso(ts)
        self.db.executemany(
            "INSERT INTO register_values "
            "(session_id, timestamp, slave_addr, reg_type, address, value, direction) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(self.session_id, iso, slave, reg_type, start + i, val, direction) for i, val in enumerate(values)],
        )

    def _process_frame(self, frame: dict):
        """Decode, display, and store a frame."""
        self.frame_count += 1
        ts_str = _format_ts(frame["timestamp"])
        fc = frame["function_code"] & 0x7F
        data = frame["data"]

        if frame["is_error"]:
            self.error_count += 1
            self._store_frame(frame, is_request=False)
            exc_code = data[0] if data else 0
            _print_error(ts_str, frame, exc_code)
            self.last_request = None
            self.db.commit()
            return

        # Pair request/response
        is_response = (
            self.last_request is not None
            and self.last_request["slave_addr"] == frame["slave_addr"]
            and (self.last_request["function_code"] & 0x7F) == fc
            and (frame["timestamp"] - self.last_request["timestamp"]) < 1.0
        )

        if is_response:
            req = self.last_request
            delta_ms = (frame["timestamp"] - req["timestamp"]) * 1000
            self._store_frame(frame, is_request=False, response_ms=delta_ms)
            self._handle_response(frame, req, ts_str, delta_ms)
            self.last_request = None
        else:
            self._store_frame(frame, is_request=True)
            self._handle_request(frame, ts_str)
            self.last_request = frame

        self.db.commit()

    def _handle_request(self, frame: dict, ts: str):
        fc = frame["function_code"]
        data = frame["data"]

        if fc in (FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS) and len(data) >= 4:
            start = struct.unpack(">H", data[0:2])[0]
            count = struct.unpack(">H", data[2:4])[0]
            print(f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} start={start} count={count}{C_RESET}")
        elif fc == FC_WRITE_SINGLE_REGISTER and len(data) >= 4:
            reg = struct.unpack(">H", data[0:2])[0]
            val = struct.unpack(">H", data[2:4])[0]
            print(
                f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} "
                f"{fc_name(fc)} reg={reg} value={val} (0x{val:04X}){C_RESET}"
            )
            self._store_registers(frame["slave_addr"], "holding", reg, [val], "write", frame["timestamp"])
        elif fc == FC_WRITE_MULTIPLE_REGISTERS and len(data) >= 5:
            start = struct.unpack(">H", data[0:2])[0]
            count = struct.unpack(">H", data[2:4])[0]
            values = []
            for i in range(count):
                off = 5 + i * 2
                if off + 2 <= len(data):
                    values.append(struct.unpack(">H", data[off : off + 2])[0])
            vals_str = " ".join(str(v) for v in values[:8])
            if len(values) > 8:
                vals_str += f" ... (+{len(values) - 8})"
            print(
                f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} "
                f"{fc_name(fc)} start={start} count={count} "
                f"values=[{vals_str}]{C_RESET}"
            )
            self._store_registers(frame["slave_addr"], "holding", start, values, "write", frame["timestamp"])
        elif fc in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS) and len(data) >= 4:
            start = struct.unpack(">H", data[0:2])[0]
            count = struct.unpack(">H", data[2:4])[0]
            print(f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} start={start} count={count}{C_RESET}")
        else:
            print(f"{C_REQ}[{ts}] --> slave={frame['slave_addr']} {fc_name(fc)} data={data.hex()}{C_RESET}")

    def _handle_response(self, frame: dict, req: dict, ts: str, delta_ms: float):
        fc = frame["function_code"]
        data = frame["data"]

        if fc in (FC_READ_HOLDING_REGISTERS, FC_READ_INPUT_REGISTERS) and len(data) >= 1:
            byte_count = data[0]
            values = []
            for i in range(byte_count // 2):
                off = 1 + i * 2
                if off + 2 <= len(data):
                    values.append(struct.unpack(">H", data[off : off + 2])[0])

            start_reg = 0
            reg_type = "holding" if fc == FC_READ_HOLDING_REGISTERS else "input"
            if len(req["data"]) >= 2:
                start_reg = struct.unpack(">H", req["data"][0:2])[0]

            vals_str = " ".join(str(v) for v in values[:8])
            if len(values) > 8:
                vals_str += f" ... (+{len(values) - 8})"

            print(
                f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} "
                f"{fc_name(fc)} regs {start_reg}-{start_reg + len(values) - 1}: "
                f"[{vals_str}] {C_DIM}({delta_ms:.1f}ms){C_RESET}"
            )
            self._store_registers(frame["slave_addr"], reg_type, start_reg, values, "read", frame["timestamp"])
        elif fc in (FC_WRITE_SINGLE_REGISTER, FC_WRITE_MULTIPLE_REGISTERS):
            print(f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} {fc_name(fc)} OK {C_DIM}({delta_ms:.1f}ms){C_RESET}")
        else:
            print(
                f"{C_RESP}[{ts}] <-- slave={frame['slave_addr']} "
                f"{fc_name(fc)} data={data.hex()} "
                f"{C_DIM}({delta_ms:.1f}ms){C_RESET}"
            )

    def _process_buffer(self):
        """Try to parse accumulated buffer as a Modbus frame."""
        raw = bytes(self._buf)
        self._buf.clear()

        frame = self._parse_frame(raw)
        if frame:
            self._process_frame(frame)
        elif len(raw) >= 4:
            print(f"{C_DIM}[?] {len(raw)}B raw: {raw[:32].hex(' ')}{'...' if len(raw) > 32 else ''} (bad CRC){C_RESET}")

    def run(self):
        """Main capture loop."""
        self._running = True
        ser = self._open_serial()

        print(f"{C_HDR}Modbus RTU Sniffer{C_RESET}")
        print(f"Port: {self.port}  Baud: {self.baud}  Parity: {self.parity}")
        print(f"Database: {self.db_path}")
        print(f"Session: {self.session_id}")
        print(f"Inter-frame gap: {self._gap * 1000:.2f}ms")
        print("Press Ctrl+C to stop\n")
        print("=" * 70)

        ser.reset_input_buffer()

        try:
            while self._running:
                chunk = ser.read(ser.in_waiting or 1)
                now = time.monotonic()

                if not chunk:
                    if self._buf and (now - self._last_byte_time) > self._gap * 2:
                        self._process_buffer()
                    continue

                if self._buf and (now - self._last_byte_time) > self._gap:
                    self._process_buffer()
                    now = time.monotonic()  # refresh after DB commit

                self._buf.extend(chunk)
                self._last_byte_time = now

        except KeyboardInterrupt:
            if self._buf:
                self._process_buffer()

            # Finalize session
            self.db.execute(
                "UPDATE sessions SET ended_at=?, frame_count=?, error_count=? WHERE id=?",
                (utc_now_iso(), self.frame_count, self.error_count, self.session_id),
            )
            self.db.commit()

            print(f"\n\nSession {self.session_id} complete")
            print(f"Captured {self.frame_count} frames ({self.error_count} errors)")
            print(f"Database: {self.db_path}")

            # Quick register summary
            _print_register_summary(self.db, self.session_id)
        finally:
            self.db.close()
            ser.close()


# -- Display helpers ---------------------------------------------------------


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


# -- Analyze subcommand -----------------------------------------------------


def cmd_analyze(args):
    """Query the database for register summaries and timeseries."""
    db = sqlite3.connect(args.db)

    # Show sessions
    sessions = db.execute(
        "SELECT id, started_at, ended_at, port, baud, parity, frame_count, error_count FROM sessions ORDER BY id"
    ).fetchall()

    print(f"{C_HDR}Sessions{C_RESET}")
    print(f"{'ID':>4s}  {'Started':>24s}  {'Ended':>24s}  {'Frames':>7s}  {'Errors':>6s}  Settings")
    print("-" * 100)
    for sid, start, end, _, baud, parity, frames, errors in sessions:
        end_str = end or "(running)"
        print(f"{sid:4d}  {start:>24s}  {end_str:>24s}  {frames or 0:7d}  {errors or 0:6d}  {baud} 8{parity}1")

    # Overall register map
    session_id = args.session if args.session else None

    if args.register is not None:
        # Show timeseries for specific register
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
        for ts, slave, rtype, val, direction in rows[-100:]:  # last 100
            print(f"{ts:>28s}  {slave:5d}  {rtype:>8s}  {direction:>5s}  {val:7d}")
        if len(rows) > 100:
            print(f"  ... showing last 100 of {len(rows)} rows")
    else:
        _print_register_summary(db, session_id)

    # Polling pattern analysis
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


# -- Export subcommand -------------------------------------------------------


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
        # Pivot: one column per register, rows are timestamps
        # Useful for direct correlation with emoncms feeds
        output = args.output or f"modbus_pivot_{int(time.time())}.csv"

        # Get all unique register addresses
        addrs = db.execute(
            f"SELECT DISTINCT slave_addr, reg_type, address "
            f"FROM register_values {where} "
            f"ORDER BY slave_addr, reg_type, address",
            params,
        ).fetchall()

        # Get all unique timestamps (rounded to seconds for alignment)
        rows = db.execute(
            f"SELECT timestamp, slave_addr, reg_type, address, value FROM register_values {where} ORDER BY id",
            params,
        ).fetchall()

        # Build pivot: timestamp -> {col_name: value}
        pivot = {}
        col_names = []
        for slave, rtype, addr in addrs:
            col_names.append(f"s{slave}_{rtype}_{addr}")

        for ts, slave, rtype, addr, val in rows:
            # Round to second for alignment
            ts_sec = ts[:19] + "Z"
            if ts_sec not in pivot:
                pivot[ts_sec] = {}
            col = f"s{slave}_{rtype}_{addr}"
            pivot[ts_sec][col] = val

        with open(output, "w") as f:
            f.write("timestamp," + ",".join(col_names) + "\n")
            for ts_sec in sorted(pivot):
                vals = [str(pivot[ts_sec].get(c, "")) for c in col_names]
                f.write(ts_sec + "," + ",".join(vals) + "\n")

        print(f"Exported pivot table ({len(pivot)} timestamps x {len(col_names)} registers) to {output}")

    db.close()


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


def main():
    parser = argparse.ArgumentParser(description="Modbus RTU bus sniffer and analyzer")
    sub = parser.add_subparsers(dest="command")

    # -- capture
    cap = sub.add_parser("capture", help="Capture Modbus RTU traffic")
    cap.add_argument("--port", default="/dev/modbus_sniff", help="Serial port")
    cap.add_argument("--baud", type=int, help="Baud rate")
    cap.add_argument("--parity", choices=["N", "E"], default="N", help="Parity (default: N)")
    cap.add_argument("--stopbits", type=int, choices=[1, 2], default=1, help="Stop bits (default: 1)")
    cap.add_argument("--auto-detect", action="store_true", help="Auto-detect baud/parity")
    cap.add_argument("--db", default="modbus_capture.db", help="SQLite database path (default: modbus_capture.db)")

    # -- analyze
    ana = sub.add_parser("analyze", help="Analyze captured data")
    ana.add_argument("--db", default="modbus_capture.db", help="Database path")
    ana.add_argument("--session", type=int, help="Filter to specific session ID")
    ana.add_argument("--slave", type=int, help="Filter to specific slave address")
    ana.add_argument("--register", type=int, help="Show timeseries for specific register address")

    # -- export
    exp = sub.add_parser("export", help="Export data for external analysis")
    exp.add_argument("--db", default="modbus_capture.db", help="Database path")
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
    elif args.command == "capture":
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

        sniffer = ModbusSniffer(args.port, baud, parity, args.db, args.stopbits)
        sniffer.run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
