# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `bootstrap.sh --pre` installs the highest pre-release instead of the most
  recently published one, so a maintenance release on the 0.2 line does not
  replace a 0.3 beta.

## [0.2.1] - 2026-11-20

Maintenance release on top of 0.2.0 with the low-risk fixes from the 0.3.0
pre-releases. No new API and no change to polling. Same code as 0.2.1b1.

### Fixed

- Re-pairing the virtual thermostat at runtime no longer needs a gateway
  restart. The serial RX whitelist kept the old address, so every panel poll
  to the new one was dropped and the circuit's thermostat temperature read
  0.0 until the next restart.
- The gateway can re-register at a new address while a virtual thermostat is
  paired. The RX whitelist used to drop every scanning IDENTIFY probe in that
  case, so registration never happened.
- Writes to panel parameters (index 10000 and up) go to the panel with the
  wire index, instead of to the controller with the cache index, which never
  acknowledged them. Thanks to wsjoanna222 (#10).
- A name that exists at several indices now always resolves to the lowest
  one. Before, it depended on cache order.
- The Docker image builds again: `README.md` is copied in for the package
  metadata (#10).

### Changed

- The gateway and the virtual thermostat identify as "ecoNEXT gateway" on the
  bus instead of using the controller vendor's name. The thermostat keeps the
  `ecoSTER_40` model and class `03`, which the panel requires. Existing
  pairings keep working.
- Steady-state operation is quiet in the journal at INFO: lock hold times,
  the periodic alarm read, thermostat submissions from Home Assistant and
  uvicorn access lines moved to DEBUG.

## [0.3.0b3] - 2026-11-19

### Added

- Data readiness. `GET /api/parameters` carries `ready` and `ready_reason`;
  `/health` carries `data_ready`, `ready_reason`, `reset_counter`,
  `last_valid_poll` and the poll counts `polls_complete`, `polls_incomplete`
  and `polls_discarded`, and reports `degraded` while the data is not ready. The data is not ready from a discarded poll until the
  next valid one, when no valid poll has landed for `ECONEXT_STALE_AFTER`
  seconds (default three poll intervals plus 15), and while the controller is
  not connected. Writes are accepted in either state.
- Settings `ECONEXT_RESET_COUNTER_PARAM`, `ECONEXT_VALIDITY_SENTINELS` and
  `ECONEXT_STALE_AFTER`.
- One log line per hour with the polls that were complete, incomplete (a
  batch failed) and discarded.
- Writes accept a parameter index (a digit string such as `10013`) wherever
  they take a name, in `POST /api/parameters/{name}` and as keys of
  `POST /api/parameters`. This is the only way to reach the second copy of a
  name that exists twice, such as the panel's `FN` or `Circuit2BaseTemp` at 785.

### Changed

- A poll is collected whole and written to the cache in one step, and only
  if it is valid. Before, each batch went to the cache as it arrived. A poll
  that ends in an error is discarded as a whole and counted.
- A poll reads the reset counter once more after its last batch.
- `GET /api/parameters` answers 503 until the first poll in which every batch
  was read, not until the first poll that read anything. When a batch keeps
  failing, the third valid poll opens it.

### Fixed

- A controller restart no longer serves zeros as measurements. The first
  poll after a reset came back with 0 in the cylinder temperature, the flow
  temperature and the pump speed limits, and every client read them as real
  values for as long as the controller then stayed silent. The poll in which
  the reset counter changes is now discarded, and so is a poll in which a
  parameter that never reads 0 in operation reads 0, or in which the
  controller did not answer at all; the cache keeps the last valid values
  and the reply says `ready: false`. A zero that lasts longer than 5 minutes
  is taken as a value again.
- Writes to panel parameters (index 10000 and up) go to the panel with the
  wire index, instead of to the controller with the cache index, which never
  acknowledged them. Thanks to wsjoanna222 (#10).
- A name that exists at several indices now always resolves to the lowest
  one. Before, it depended on cache order.
- The Docker image builds again: `README.md` is copied in for the package
  metadata (#10).

## [0.3.0b2] - 2026-11-17

### Added

- `POST /api/parameters` writes several parameters in one bus token hold.
  Values are validated up front, so a bad entry rejects the batch with
  nothing written, and each write is reported individually. Copying a
  schedule day to the rest of the week drops from about 12 token waits to
  one.
- `/health` reports `parameters_ready`.

### Fixed

- `GET /api/parameters` returns 503 until the first full poll after startup
  has finished, instead of a partly filled cache. Home Assistant starting
  during that window created only the entities whose parameters had loaded
  so far (schedules went missing) until the integration was reloaded; it now
  retries setup until the full set is there.

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
