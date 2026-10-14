# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0b1] - 2026-10-14

### Fixed

- Re-pairing the virtual thermostat at runtime no longer needs a gateway
  restart. The serial RX whitelist kept the old address, so every panel poll
  to the new one was dropped and the circuit's thermostat temperature read
  0.0 until the next restart.
- The gateway can re-register at a new address while a virtual thermostat is
  paired. The RX whitelist used to drop every scanning IDENTIFY probe in that
  case, so registration never happened.

### Changed

- The gateway and the virtual thermostat identify as "ecoNEXT gateway" on the
  bus instead of using the controller vendor's name. The thermostat keeps the
  `ecoSTER_40` model and class `03`, which the panel requires. Existing
  pairings keep working.
- Steady-state operation is quiet in the journal at INFO: lock hold times,
  the periodic alarm read, thermostat submissions from Home Assistant and
  uvicorn access lines moved to DEBUG.

### Added

- Modbus RTU bus sniffer for the wiring centre to outdoor unit link
  (`tools/modbus_sniffer.py`, `deploy/install-sniffer.sh`): continuous
  capture into hourly gzipped chunks with a once-a-day ship to the NAS,
  anomaly alerts, a polite second master that reads and writes outdoor
  unit registers in the bus's idle gaps, register discovery scans, and an
  import/analyze/changes toolchain. See `docs/HEATPUMP_MODBUS.md`.
- Register map of the Grant Aerona R290 (Axen) outdoor unit with the
  controller's own limits (`docs/MODBUS_REGISTER_MAP.md`, `docs/scans/`).
  Holding 6053 is the fan speed maximum.
- `tools/axen_param_match.py`: matches the controller's decoded heat pump
  parameters to its raw `AXEN_REGISTER_*` copies.

## [0.2.0] - 2026-08-16

First stable release since 0.1.0-beta.2. Everything below shipped through the
0.2.0a1-0.2.0b4 pre-releases.

### Upgrade notes

- Run the quick install one-liner again (see README, "Upgrading"). Requires the
  ecoNEXT Home Assistant integration v0.1.2 or later.
- The gateway no longer uses the fixed bus address 131. On the first start it
  registers itself at a free panel address (105-130); this takes 2-3 minutes,
  during which no parameters are available. Later restarts are instant.
- The virtual thermostat is enabled by default. It only becomes active on the
  bus once you pair it from Home Assistant. Disable with
  `ECONEXT_THERMOSTAT_ENABLED=false` if you do not want it.
- The gateway syncs the panel clock from the host once a day (03:30) and after
  DST/NTP jumps. Disable with `ECONEXT_CLOCK_SYNC_ENABLED=false`.
- The installer regenerates the systemd unit and `99-econext.rules`. Move any
  edits to `sudo systemctl edit econext-gateway` and
  `/etc/udev/rules.d/99-econext-local.rules` before upgrading.

### Added

- Automatic bus address registration; the claimed address is persisted in
  `/var/lib/econext-gateway`. Allows running alongside an ecoNET300 on a
  second RS-485 converter (docs/PARALLEL_ECONET300.md).
- Virtual thermostat: the gateway emulates an ecoSTER thermostat so any Home
  Assistant temperature can be used as room temperature. Endpoints
  `POST /api/thermostat/temperature`, `POST /api/thermostat/pair`,
  `GET /api/thermostat/status`. Falls back to a configurable temperature when
  Home Assistant stops sending values, and serves the assigned circuit's real
  schedule so the controller does not zero it.
- Panel clock sync via SERVICE 0x0023 broadcasts, plus `POST /api/clock/sync`.
- Bus silence watchdog that recovers from a dead serial bus.
- `--pre` flag for `bootstrap.sh` / `install.sh` to install pre-releases.
- FT232H / FT232RL udev rule examples.
- emonHub interfacer example (`tools/`).

### Changed

- License changed from MIT to PolyForm Noncommercial 1.0.0: free for
  private, non-profit, educational and government use; commercial use requires
  a paid license.
- Frame dispatching moved off the handler lock, so Home Assistant writes are no
  longer starved by bus traffic.
- Steady-state logging is much quieter at INFO.
- Bus address constants cleaned up; IDENTIFY/SERVICE are part of the Command enum.

### Fixed

- Temperature parameters reporting the 999.0 disconnected-sensor sentinel are
  filtered out.
- Virtual thermostat pairing state no longer gets stuck; temperature no longer
  drops to 0.0 after re-pairing or a restart.
- Ruff/lint clean-ups.

## [0.1.0-beta.2] - 2026-02-07

Initial public beta: token-passing bus protocol, parameter discovery, REST API,
systemd deployment.
