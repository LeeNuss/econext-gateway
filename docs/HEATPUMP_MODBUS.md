# Heat Pump Modbus RTU Interface

The Grant Aerona heat pump exposes a Modbus RTU interface on the ecoNET
wiring centre's **G2 (M-BUS)** terminal. The wiring centre acts as Modbus
master and continuously polls the heat pump outdoor unit.

> **Manufacturer note:** This is the newer Grant Aerona 290 manufactured by
> **Axen**, not the older Chofu-based Aerona3. The same controller family
> drives both, but the Modbus maps are different: the Chofu unit keeps its
> settings in holding registers 0 to 102, the Axen unit in 2100 to 2114 and
> a 275-register block at 6000. Nothing from the
> [Chofu register map](https://github.com/aerona-chofu-ashp/modbus) applies
> here; the verified Axen map is in [MODBUS_REGISTER_MAP.md](MODBUS_REGISTER_MAP.md).

## Bus Settings

| Parameter      | Value               |
|----------------|---------------------|
| Baud rate      | 9600                |
| Data bits      | 8                   |
| Parity         | None                |
| Stop bits      | 2 (8N2)            |
| Slave address  | 251 (0xFB)          |
| Protocol       | Modbus RTU          |

> **Note:** The Chofu documentation states 19200 baud and slave address 1.
> This Axen unit uses 9600 baud and address 251 (0xFB). This may be an
> Axen default or a wiring centre configuration. The settings may be
> configurable via the HP service menu. Confirmed via logic analyzer
> (Saleae Logic Pro 8) and passive bus sniffing.

## Physical Connection

### G2 M-BUS terminal (wiring centre)

Connect a USB-RS485 adapter in **passive sniffer mode** (receive-only,
tapped in parallel):

| G2 Pin | Adapter Pin | Signal  |
|--------|-------------|---------|
| D+     | A+          | RS-485+ |
| D-     | B-          | RS-485- |

A common ground connection is recommended but not strictly required for
short distances. If data appears garbled at all baud rates, check GND
and try swapping A/B (polarity conventions vary between manufacturers).

### Direct HP connection (outdoor unit PCB)

The Chofu documentation describes direct connection to the outdoor unit:

| HP PCB Pin | Signal    |
|------------|-----------|
| 15         | RS-485+   |
| 16         | RS-485-   |
| 32         | RS-485 GND|

## USB Adapter Configuration

FTDI-based USB-RS485 adapters default to a 16ms latency timer, which
fragments Modbus frames longer than ~14 bytes. Reduce it to 1ms:

```bash
# Check which ttyUSB the adapter is on
ls -la /dev/heatpump  # shows e.g. -> ttyUSB2

# Set latency timer to 1ms
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB2/latency_timer
```

To make this persistent, add a udev rule:

```
ACTION=="add", SUBSYSTEM=="usb-serial", ATTR{latency_timer}="1"
```

## Polling Pattern

The wiring centre polls the HP in a repeating cycle of approximately 10
seconds. Each cycle reads:

1. Input registers 0-103 (in blocks of 10)
2. Input register 121
3. Input registers 1201-1238 (in blocks of 10)
4. Holding registers 2100-2155 and others
5. Various holding register reads (func 0x03)

Request-to-response latency is approximately 50-80ms. The bus is idle
for ~300ms between each request/response pair.

## Register Map

The register map lives in [MODBUS_REGISTER_MAP.md](MODBUS_REGISTER_MAP.md): every
register the wiring centre polls, the 6000 block discovered by the scan, current
values, the controller parameter that mirrors each one, and what is known about
its meaning. The Chofu/Aerona3 map that used to be here does not apply to the
Axen unit and was removed.

## Sniffer Usage

### Interactive

```bash
# Set FTDI latency first
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB2/latency_timer

# Capture traffic with decoded frames on the console
python3 tools/modbus_sniffer.py capture \
    --port /dev/heatpump --baud 9600 --stopbits 2 --parity N -v
```

### Continuous capture (systemd)

`deploy/install-sniffer.sh` installs the tool to `/opt/modbus-sniffer` with
two units:

- `modbus-sniffer.service` captures every frame into hourly gzipped chunks
  under `/var/lib/modbus-sniffer/cache/YYYY-MM-DD/HH-HHMMSS.gz` (UTC). The
  bus runs at about 5 frames/s, which is roughly 2 MB a day compressed.
  Chunks are held in RAM and written once an hour, so the SD card sees a
  few writes a day. The NAS is never touched by this unit.
- `modbus-sniffer-ship.timer` runs `modbus-sniffer-ship.sh` once a day at
  02:05 local time (inside the NAS write window). It appends each finished
  day's chunks to `/mnt/nas/modbus/YYYY/MM/YYYY-MM-DD.frames.gz`, syncs,
  then deletes the cached day. If the share is down the cache keeps the
  days (hard cap 14 days) and the next run catches up.

Signals: `SIGTERM` flushes the open chunk and exits, `SIGUSR1` flushes it
and keeps going:

```bash
sudo systemctl kill -s SIGUSR1 modbus-sniffer   # flush now for a look
```

### Alerts

Anything outside the wiring centre's normal poll cycle is an anomaly and is
worth looking at (a firmware push to the outdoor unit, for instance, would
have to travel over this bus):

| Rule               | Trigger                                         |
|--------------------|-------------------------------------------------|
| `function_code`    | function code other than 0x03, 0x04, 0x06       |
| `unexpected_slave` | slave address other than 251 (`--expect-slave`) |
| `long_frame`       | frame longer than 30 bytes (`--max-frame-len`)  |
| `bad_crc_burst`    | more than 30 unparsable frames in a minute      |

Each alert goes to `/var/lib/modbus-sniffer/alerts.log` (shipped to the NAS
with the daily file), to the journal as a warning, and optionally as a JSON
POST to `MODBUS_SNIFFER_WEBHOOK` (set in `/etc/default/modbus-sniffer`).
The first five hits per rule are logged in full, after that one summary
line a minute. The first alert also forces the open chunk to disk, at most
once every five minutes, so the evidence is persisted immediately.

### Register scan and writes (polite second master)

The wiring centre polls only 168 registers. To find what else the outdoor
unit exposes, the sniffer acts as a second master: it transmits one read
per idle gap, right after it has seen the heat pump answer the wiring
centre, and never while a wiring centre request is unanswered. The gap is
a steady 330 ms and a single block read completes in about 100 ms, so the
two masters never overlap. The send window is measured from the wire time
of the wiring centre's reply, so a stall in the Pi skips a gap instead of
transmitting late.

The bus has its own noise bursts (garbage lead bytes and truncated wiring
centre frames for minutes at a time, several times a day, with no probe on
the bus). A corrupted frame or an unanswered wiring centre request is only
held against the scan when it follows one of our transmissions within half
a second; three probes in a row followed by one stop the run. Anything else
pauses probing for 20 s. The heat pump answers a second master normally;
the full discovery run was 13.8k probes without a disturbance of ours.

The capture service holds the port, so stop it for the duration. Every
frame seen meanwhile still goes to the same cache:

```bash
sudo systemctl stop modbus-sniffer

# dry run: reports when a probe would go out, never transmits
modbus-sniffer scan --dry-run --limit 20 -v --cache-dir /var/lib/modbus-sniffer/cache

# fine scan of a range (illegal-address replies are bisected to single addresses)
modbus-sniffer scan --type holding --ranges 6000-6499 --out scan.tsv --cache-dir /var/lib/modbus-sniffer/cache

# sweep: one read every 16 addresses, a hit expands into a fine scan around it
modbus-sniffer scan --type input --ranges "" --sweep 1300-65535 --stride 16 --out sweep.tsv \
    --cache-dir /var/lib/modbus-sniffer/cache

# change one holding register: read, refuse unless it holds --expect, write, read back, log it
modbus-sniffer write --address 6053 --value 800 --expect 850 \
    --cache-dir /var/lib/modbus-sniffer/cache --log /var/lib/modbus-sniffer/writes.log

sudo systemctl start modbus-sniffer
```

Rates: about 2.3 probes a second. Bisecting empty space costs two probes
per address, a sweep one per stride point. `--type coil` and `discrete`
exist but this unit rejects those function codes. The heat pump applies a
function 06 write without answering it within 200 ms, so the write command
decides by the read-back. Every write is appended to the log with the
value before, so it can be undone. Results of the 2026-09-17 discovery
run are under `docs/scans/`.

### Analysis

Chunk and daily files are gzip text, one frame per line
(`<epoch_ms> <hex>`, or `<epoch_ms> ? <hex>` for bytes that failed the
CRC). Build a throwaway SQLite database from them and use the existing
analyze/export commands. A full day is about 200 MB as SQLite, so do this
on a laptop or the NAS rather than the Pi:

```bash
# From the NAS daily files
python3 tools/modbus_sniffer.py import /mnt/nas/modbus/2026/09/*.gz --db /tmp/sept.db

# Or from the Pi's local cache (last two days, no NAS access)
python3 tools/modbus_sniffer.py import /var/lib/modbus-sniffer/cache --db /tmp/recent.db

python3 tools/modbus_sniffer.py analyze --db /tmp/sept.db
python3 tools/modbus_sniffer.py analyze --db /tmp/sept.db --register 1201 --slave 251
python3 tools/modbus_sniffer.py export --db /tmp/sept.db --format pivot
```

## References

- [aerona-chofu-ashp/modbus](https://github.com/aerona-chofu-ashp/modbus) -
  Chofu/Grant Aerona3 Modbus register mappings (community reverse-engineered)
- Chofu service mode manual (accessible via HP installer menu)
