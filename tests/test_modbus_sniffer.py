"""Tests for the standalone Modbus sniffer tool (tools/modbus_sniffer.py)."""

import gzip
import importlib.util
import sqlite3
import struct
import sys
import time
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "modbus_sniffer", Path(__file__).resolve().parents[1] / "tools" / "modbus_sniffer.py"
)
sniffer = importlib.util.module_from_spec(_SPEC)
sys.modules["modbus_sniffer"] = sniffer
_SPEC.loader.exec_module(sniffer)

HP = 251
T0 = 1_760_000_000.0  # 2025-10-09 08:53:20 UTC


def frame(slave: int, fc: int, data: bytes) -> bytes:
    payload = bytes([slave, fc]) + data
    return payload + struct.pack("<H", sniffer.modbus_crc16(payload))


def read_req(start: int, count: int, fc: int = 0x04, slave: int = HP) -> bytes:
    return frame(slave, fc, struct.pack(">HH", start, count))


def read_resp(values: list[int], fc: int = 0x04, slave: int = HP) -> bytes:
    return frame(slave, fc, bytes([2 * len(values)]) + b"".join(struct.pack(">H", v) for v in values))


# -- parsing -----------------------------------------------------------------


def test_parse_frame_checks_crc():
    raw = read_req(0, 10)
    parsed = sniffer.parse_frame(raw, T0)
    assert parsed["slave_addr"] == HP
    assert parsed["function_code"] == 0x04
    assert parsed["data"] == struct.pack(">HH", 0, 10)
    assert parsed["timestamp"] == T0
    corrupted = raw[:-1] + bytes([raw[-1] ^ 0xFF])
    assert sniffer.parse_frame(corrupted, T0) is None
    assert sniffer.parse_frame(b"\xfb\x04", T0) is None


# -- chunk writer ------------------------------------------------------------


def test_chunk_writer_rotates_per_utc_hour_and_round_trips(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache", meta={"port": "/dev/x", "baud": 9600})
    good = read_req(0, 10)
    writer.write(T0, good, True)
    writer.write(T0 + 1, b"\xff\x00\x00\x00", False)
    writer.write(T0 + 3600, good, True)  # next hour: rotates the first chunk
    writer.close()

    files = sorted((tmp_path / "cache").rglob("*.gz"))
    assert [f.parent.name for f in files] == ["2025-10-09", "2025-10-09"]
    assert files[0].name == "08-085320.gz"
    assert files[1].name == "09-095320.gz"
    assert not list((tmp_path / "cache").rglob("*.tmp"))

    records = list(sniffer.iter_chunk_records(files[0]))
    assert records == [(T0, good, True), (T0 + 1, b"\xff\x00\x00\x00", False)]
    assert sniffer.chunk_meta(files[0])["port"] == "/dev/x"
    assert sniffer.chunk_meta(files[0])["baud"] == "9600"
    assert writer.total_frames == 2
    assert writer.total_bad == 1


def test_chunk_writer_names_same_second_chunks_in_cat_order(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache")
    for i in range(3):
        writer.write(T0 + i * 0.1, read_req(0, i), True)
        writer.rotate("signal")
    names = [p.name for p in sorted((tmp_path / "cache").rglob("*.gz"))]
    assert names == ["08-085320.gz", "08-085320_1.gz", "08-085320_2.gz"]
    counts = [list(sniffer.iter_chunk_records(p))[0][1] for p in sorted((tmp_path / "cache").rglob("*.gz"))]
    assert counts == [read_req(0, 0), read_req(0, 1), read_req(0, 2)]


def test_chunk_writer_skips_empty_rotation(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache")
    assert writer.rotate("signal") is None
    writer.write(T0, read_req(0, 1), True)
    path = writer.rotate("signal")
    assert path is not None and path.exists()
    assert writer.rotate("signal") is None  # nothing new since
    writer.close()
    assert len(list((tmp_path / "cache").rglob("*.gz"))) == 1


def test_chunk_writer_prunes_oldest_days(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache", max_days=2)
    day = 86400
    for i in range(4):
        writer.write(T0 + i * day, read_req(0, 1), True)
    writer.close()
    days = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert days == ["2025-10-11", "2025-10-12"]


def test_concatenated_chunks_read_as_one_file(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache")
    writer.write(T0, read_req(0, 1), True)
    first = writer.rotate("signal")
    writer.write(T0 + 5, read_req(0, 2), True)
    second = writer.rotate("signal")
    daily = tmp_path / "day.frames.gz"
    daily.write_bytes(first.read_bytes() + second.read_bytes())
    records = list(sniffer.iter_chunk_records(daily))
    assert [r[0] for r in records] == [T0, T0 + 5]
    assert gzip.decompress(daily.read_bytes()).count(b"# modbus-sniffer chunk") == 2


# -- anomaly detector --------------------------------------------------------


def test_anomaly_rules(tmp_path: Path):
    det = sniffer.AnomalyDetector(alerts_path=tmp_path / "alerts.log")
    assert det.check(T0, read_req(0, 10), True) == []
    assert det.check(T0, read_resp([1] * 10), True) == []
    assert det.check(T0, frame(HP, 0x06, struct.pack(">HH", 2100, 1)), True) == []
    assert det.check(T0, frame(HP, 0x84, b"\x02"), True) == []  # exception reply to a normal FC
    assert det.check(T0, frame(HP, 0x10, b"\x00\x00\x00\x02\x04\x00\x01\x00\x02"), True) == ["function_code"]
    assert det.check(T0, read_req(0, 1, slave=1), True) == ["unexpected_slave"]
    assert det.check(T0, read_resp([7] * 20), True) == ["long_frame"]
    assert det.check(T0, frame(2, 0x2B, b"\x00" * 40), True) == ["unexpected_slave", "function_code", "long_frame"]
    lines = (tmp_path / "alerts.log").read_text().splitlines()
    assert len(lines) == 6
    assert lines[0].startswith("ALERT function_code 2025-10-09T08:53:20.000Z slave=251 fc=0x10 len=13 raw=fb10")


def test_bad_crc_burst_fires_once_per_burst():
    det = sniffer.AnomalyDetector(bad_crc_per_minute=3)
    fired = [det.check(T0 + i * 0.5, b"\x00\x01\x02\x03", False) for i in range(6)]
    assert fired == [[], [], [], ["bad_crc_burst"], [], []]
    # window empties after a minute, a new burst fires again
    fired = [det.check(T0 + 120 + i * 0.5, b"\x00\x01\x02\x03", False) for i in range(5)]
    assert fired == [[], [], [], ["bad_crc_burst"], []]


def test_alerts_are_rate_limited(tmp_path: Path):
    det = sniffer.AnomalyDetector(alerts_path=tmp_path / "alerts.log", detail_limit=3, summary_interval=60)
    push = frame(HP, 0x10, b"\x00\x00\x00\x01\x02\x00\x01")
    for i in range(200):
        det.check(T0 + i, push, True)  # one anomalous frame per second for 200 s
    lines = (tmp_path / "alerts.log").read_text().splitlines()
    details = [ln for ln in lines if " more in last " not in ln]
    summaries = [ln for ln in lines if " more in last " in ln]
    assert len(details) == 3
    assert len(summaries) == 3  # at t=62, 122, 182
    assert summaries[0].startswith("ALERT function_code 2025-10-09T08:54:22.000Z 60 more in last 60s")
    assert det.alert_count == 200
    assert det.last_alert_ts == T0 + 199


# -- decoder and import ------------------------------------------------------


class _Collect:
    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event)


def test_decoder_pairs_requests_with_responses():
    sink = _Collect()
    dec = sniffer.Decoder(sink)
    dec.feed(sniffer.parse_frame(read_req(1200, 2, fc=0x03), T0))
    dec.feed(sniffer.parse_frame(read_resp([65036, 42], fc=0x03), T0 + 0.06))
    dec.feed(sniffer.parse_frame(frame(HP, 0x06, struct.pack(">HH", 2100, 15872)), T0 + 1))
    dec.feed(sniffer.parse_frame(frame(HP, 0x06, struct.pack(">HH", 2100, 15872)), T0 + 1.05))
    dec.feed(sniffer.parse_frame(frame(HP, 0x83, b"\x02"), T0 + 2))

    req, resp, wreq, wresp, err = sink.events
    assert req["is_request"] and req["decoded"] == {"start": 1200, "count": 2}
    assert not resp["is_request"]
    assert resp["response_ms"] == pytest.approx(60, abs=1)
    assert resp["decoded"] == {"start": 1200, "values": [65036, 42], "reg_type": "holding", "direction": "read"}
    assert wreq["decoded"]["values"] == [15872] and wreq["decoded"]["direction"] == "write"
    assert not wresp["is_request"] and wresp["decoded"] == {}
    assert err["exception"] == 2 and dec.error_count == 1


def test_decoder_recovers_when_capture_starts_mid_exchange():
    sink = _Collect()
    dec = sniffer.Decoder(sink)
    dec.feed(sniffer.parse_frame(read_resp([1, 2]), T0))  # orphan response first
    dec.feed(sniffer.parse_frame(read_req(10, 2), T0 + 0.3))
    dec.feed(sniffer.parse_frame(read_resp([3, 4]), T0 + 0.35))
    dec.feed(sniffer.parse_frame(read_req(20, 1), T0 + 0.7))
    dec.feed(sniffer.parse_frame(read_resp([5]), T0 + 0.75))
    flags = [(e["is_request"], e["decoded"].get("start")) for e in sink.events]
    assert flags == [(False, None), (True, 10), (False, 10), (True, 20), (False, 20)]


def test_decoder_does_not_pair_mismatched_lengths():
    sink = _Collect()
    dec = sniffer.Decoder(sink)
    dec.feed(sniffer.parse_frame(read_req(0, 10), T0))
    dec.feed(sniffer.parse_frame(read_resp([1] * 4), T0 + 0.05))  # wrong length for count=10
    assert [e["is_request"] for e in sink.events] == [True, False]
    assert sink.events[1]["decoded"] == {}


def test_changes_lists_transitions_and_writes(tmp_path: Path, capsys):
    writer = sniffer.ChunkWriter(tmp_path / "cache")
    writer.write(T0, read_req(40, 3), True)
    writer.write(T0 + 0.05, read_resp([183, 174, 0]), True)
    writer.write(T0 + 10, read_req(40, 3), True)
    writer.write(T0 + 10.05, read_resp([183, 175, 0]), True)
    writer.write(T0 + 20, frame(HP, 0x06, struct.pack(">HH", 2103, 33)), True)
    writer.write(T0 + 20.05, frame(HP, 0x06, struct.pack(">HH", 2103, 33)), True)
    writer.write(T0 + 30, read_req(40, 3), True)
    writer.write(T0 + 30.05, read_resp([184, 175, 0]), True)
    writer.close()

    args = type(
        "A", (), {"db": None, "inputs": [str(tmp_path / "cache")], "since": None, "slave": None, "initial": False}
    )
    sniffer.cmd_changes(args)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "2025-10-09T08:53:30.050Z  s251   input    41  174 -> 175"
    assert out[1] == "2025-10-09T08:53:40.000Z  s251 holding  2103  WRITE 33"
    assert out[2] == "2025-10-09T08:53:50.050Z  s251   input    40  183 -> 184"
    assert "2 registers changed, 1 writes:" in out

    args.since = "2025-10-09T08:53:45Z"
    sniffer.cmd_changes(args)
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("183 -> 184") and len([ln for ln in out if "->" in ln]) == 1


def test_parse_since_relative_and_absolute():
    assert sniffer._parse_since("30m", now=T0) == T0 - 1800
    assert sniffer._parse_since("2h", now=T0) == T0 - 7200
    assert sniffer._parse_since("1d", now=T0) == T0 - 86400
    assert sniffer._parse_since("2025-10-09T08:53:20Z") == T0
    assert sniffer._parse_since(None) is None


def test_import_builds_database_from_chunks(tmp_path: Path):
    writer = sniffer.ChunkWriter(tmp_path / "cache", meta={"port": "/dev/heatpump", "baud": 9600, "parity": "N"})
    writer.write(T0, read_req(0, 2), True)
    writer.write(T0 + 0.05, read_resp([30, 45]), True)
    writer.write(T0 + 0.3, b"\xde\xad\xbe\xef", False)
    writer.write(T0 + 10, read_req(0, 2), True)
    writer.write(T0 + 10.05, read_resp([31, 45]), True)
    writer.close()

    db_path = tmp_path / "out.db"
    db = sniffer.open_db(str(db_path))
    files = sniffer._expand_inputs([str(tmp_path / "cache")])
    assert len(files) == 1
    assert sniffer.import_files(db, files) == 4
    db.close()

    db = sqlite3.connect(db_path)
    assert db.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM frames WHERE is_request=1").fetchone()[0] == 2
    regs = db.execute("SELECT address, value FROM register_values ORDER BY id").fetchall()
    assert regs == [(0, 30), (1, 45), (0, 31), (1, 45)]
    started, port, baud, frames = db.execute("SELECT started_at, port, baud, frame_count FROM sessions").fetchone()
    assert (started, port, baud, frames) == ("2025-10-09T08:53:20.000Z", "/dev/heatpump", 9600, 4)


# -- capture loop ------------------------------------------------------------


class FakeSerial:
    """Replays scripted reads; each entry is one burst of bytes, an empty
    entry is a read timeout. Raises KeyboardInterrupt when exhausted."""

    def __init__(self, script: list[bytes]):
        self.script = list(script)
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self.script[0]) if self.script and self.script[0] else 0

    def read(self, _n: int) -> bytes:
        if not self.script:
            raise KeyboardInterrupt
        chunk = self.script.pop(0)
        if not chunk:
            time.sleep(0.04)  # longer than 2x the 15ms inter-frame gap
        return chunk

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


def test_capture_writes_chunks_and_flushes_on_alert(tmp_path: Path):
    normal_req, normal_resp = read_req(0, 10), read_resp([1] * 10)
    push = frame(HP, 0x10, b"\x08\x34\x00\x02\x04\xde\xad\xbe\xef")
    script = [normal_req, b"", normal_resp, b"", push, b"", normal_req, b""]
    fake = FakeSerial(script)

    writer = sniffer.ChunkWriter(tmp_path / "cache")
    detector = sniffer.AnomalyDetector(alerts_path=tmp_path / "alerts.log")
    cap = sniffer.Capture("/dev/fake", 9600, "N", 2, writer, detector, serial_factory=lambda: fake)
    cap.run()

    assert fake.closed
    files = sorted((tmp_path / "cache").rglob("*.gz"))
    assert len(files) == 2  # alert-forced flush, then the close flush
    first = list(sniffer.iter_chunk_records(files[0]))
    assert [r[1] for r in first] == [normal_req, normal_resp, push]
    second = list(sniffer.iter_chunk_records(files[1]))
    assert [r[1] for r in second] == [normal_req]
    alerts = (tmp_path / "alerts.log").read_text()
    assert alerts.count("ALERT function_code") == 1
    assert "fc=0x10" in alerts and "raw=" + push.hex() in alerts
    assert writer.total_frames == 4 and detector.alert_count == 1


def test_capture_sigusr1_flush_and_stop(tmp_path: Path):
    req = read_req(0, 1)
    fake = FakeSerial([req, b"", req, b""])
    writer = sniffer.ChunkWriter(tmp_path / "cache")
    detector = sniffer.AnomalyDetector()
    cap = sniffer.Capture("/dev/fake", 9600, "N", 2, writer, detector, serial_factory=lambda: fake)

    original_read = fake.read
    reads = 0

    def read(n):
        nonlocal reads
        reads += 1
        if reads == 2:
            cap.request_flush()  # as SIGUSR1 would, between the two frames
        if reads == 5:
            cap.request_stop()  # as SIGTERM would
        return original_read(n)

    fake.read = read
    cap.run()
    files = sorted((tmp_path / "cache").rglob("*.gz"))
    assert len(files) == 2
    assert [len(list(sniffer.iter_chunk_records(f))) for f in files] == [1, 1]


# -- polite second master ----------------------------------------------------


def exception_resp(fc: int, code: int, slave: int = HP) -> bytes:
    return frame(slave, fc | 0x80, bytes([code]))


class FakeBus:
    """A wiring centre polling input 0-9 every round, and a heat pump that
    answers holding-register reads from `registers`, replies with exception
    02 for blocks touching an absent address, and stays silent for `silent`
    addresses. Our own transmissions are echoed back like an RS-485 adapter
    does. Raises KeyboardInterrupt once `rounds` wiring-centre exchanges are
    done."""

    def __init__(self, registers: dict[int, int], rounds: int = 20, silent: set[int] | None = None, answer_wc=True):
        self.registers = registers
        self.rounds = rounds
        self.silent = silent or set()
        self.answer_wc = answer_wc
        self.queue: list[bytes] = []
        self.written: list[bytes] = []
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self.queue[0]) if self.queue and self.queue[0] else 0

    def read(self, _n: int) -> bytes:
        if not self.queue:
            if self.rounds <= 0:
                raise KeyboardInterrupt
            self.rounds -= 1
            self.queue = [read_req(0, 10), b""] + ([read_resp([1] * 10), b""] if self.answer_wc else [])
        chunk = self.queue.pop(0)
        if not chunk:
            time.sleep(0.04)
        return chunk

    def write(self, raw: bytes) -> int:
        self.written.append(raw)
        slave, fc, start, count = raw[0], raw[1], *struct.unpack(">HH", raw[2:6])
        reply: list[bytes] = [raw, b""]  # adapter echo
        addrs = range(start, start + count)
        if not any(a in self.silent for a in addrs):
            if all(a in self.registers for a in addrs):
                reply += [read_resp([self.registers[a] for a in addrs], fc=fc, slave=slave), b""]
            else:
                reply += [exception_resp(fc, 2, slave), b""]
        self.queue = reply + self.queue
        return len(raw)

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


def run_scan(bus: FakeBus, tmp_path: Path, ranges, block=8, dry_run=False, limit=None, **prober_kw):
    prober = sniffer.Prober(HP, dry_run=dry_run, **prober_kw)
    scanner = sniffer.Scanner(prober, HP, 0x03, ranges, block=block, limit=limit)
    cap = sniffer.Capture(
        "/dev/fake",
        9600,
        "N",
        2,
        sniffer.ChunkWriter(tmp_path / "cache"),
        sniffer.AnomalyDetector(),
        prober=prober,
        serial_factory=lambda: bus,
    )
    scanner.start()
    cap.run()
    return prober, scanner


def test_scan_reads_present_registers_and_bisects_absent_ones(tmp_path: Path):
    bus = FakeBus({0: 10, 1: 11, 2: 12, 3: 13, 6: 16, 7: 17, 8: 18}, rounds=30)
    prober, scanner = run_scan(bus, tmp_path, [(0, 8)])
    assert scanner.finished and prober.finished
    assert scanner.present == {0: 10, 1: 11, 2: 12, 3: 13, 6: 16, 7: 17, 8: 18}
    assert scanner.absent == {4, 5}
    # 0-7 (exc), 0-3, 4-7 (exc), 4-5 (exc), 4, 5, 6-7, 8
    assert scanner.probes == 8 and prober.stats["sent"] == 8
    assert prober.stats["ok"] == 3 and prober.stats["exception"] == 5 and prober.stats["timeout"] == 0
    assert all(w[0] == HP and w[1] == 0x03 for w in bus.written)
    out = tmp_path / "scan.tsv"
    scanner.write_results(out)
    lines = out.read_text().splitlines()
    assert lines[2] == "0\t10\t10\t0x000A" and lines[-1] == "8\t18\t18\t0x0012"


def test_prober_only_transmits_right_after_a_wiring_centre_response(tmp_path: Path):
    bus = FakeBus({0: 1}, rounds=3)
    prober, scanner = run_scan(bus, tmp_path, [(0, 0)], block=1)
    assert len(bus.written) == 1
    assert prober.gap_samples and max(prober.gap_samples) < 80  # ms after the exchange end
    # our request went out between the wiring centre's response and its next request
    seen = [r[1] for r in sniffer.iter_chunk_records(next((tmp_path / "cache").rglob("*.gz")))]
    idx = seen.index(bus.written[0])
    assert seen[idx - 1] == read_resp([1] * 10) and seen[idx + 1] == read_resp([1], fc=0x03)


def test_prober_never_transmits_while_wiring_centre_waits_and_stops_on_missed_replies(tmp_path: Path):
    bus = FakeBus({0: 1}, rounds=6, answer_wc=False)
    prober, scanner = run_scan(bus, tmp_path, [(0, 7)])
    assert bus.written == []
    assert prober.stopped and "unanswered" in prober.stop_reason
    assert prober.stats["wc_missed"] >= 3 and prober.stats["sent"] == 0
    assert not scanner.present


def test_prober_times_out_and_scanner_retries_then_gives_up(tmp_path: Path):
    bus = FakeBus({0: 1, 1: 2}, rounds=40, silent={1})
    prober, scanner = run_scan(bus, tmp_path, [(0, 1)], block=2, response_timeout=0.05)
    assert prober.stats["timeout"] == 3  # first try plus two retries
    assert scanner.failed == [(0, 2)] and not scanner.present
    assert not prober.stopped


def test_dry_run_never_writes_to_the_bus(tmp_path: Path):
    bus = FakeBus({0: 1, 1: 2}, rounds=6)
    prober, scanner = run_scan(bus, tmp_path, [(0, 15)], block=8, dry_run=True, limit=2)
    assert bus.written == []
    assert prober.stats == {"sent": 0, "ok": 0, "exception": 0, "timeout": 0, "wc_missed": 0, "bad_crc": 0, "dry": 2}
    assert scanner.probes == 2 and scanner.finished


def test_parse_ranges():
    assert sniffer.parse_ranges("0-7, 100, 6000-6003") == [(0, 7), (100, 100), (6000, 6003)]
