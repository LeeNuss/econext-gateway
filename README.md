# ecoNEXT Gateway

Local REST API gateway for heat pump controllers using a serial protocol. Runs on a Raspberry Pi (or similar) connected to the controller via RS-485, providing an HTTP API for Home Assistant and other automation systems.

```
[Home Assistant] --HTTP--> [econext-gateway] --RS-485--> [Heat Pump Controller]
```

## Features

- Full token-passing bus protocol for reliable, fast parameter access
- 1870 parameters discovered in ~7 seconds
- Read and write controller parameters via REST API
- Alarm history support
- Virtual thermostat emulation (submit HA temperature readings to the heat pump)
- Runs as a systemd service
- No cloud dependency

## Hardware Requirements

- **Raspberry Pi** (or any Linux SBC) with a free USB port
- **USB-RS485 adapter**: Plum ecoLINK3 (recommended, auto-detected) or FTDI-based adapters (see [Troubleshooting](#troubleshooting))
- **Supported controller**: ecoTRONIC, ecoMAX, or other compatible heat pump controllers

### Wiring

Connect the USB-RS485 adapter to the controller's RS-485 bus (A/B terminals) and plug the USB end into the Raspberry Pi. The included udev rule creates a `/dev/econext` symlink automatically for ecoLINK3 adapters. For other adapters, see [Troubleshooting](#troubleshooting).

The simplest option is to unplug the ecoLINK3 cable from your ecoNET300 module and plug it into the Pi. If you want to keep the ecoNET300 (and the econet24 cloud/app) working at the same time, see [Running Alongside ecoNET300](#running-alongside-econet300).

## Installation

### Quick Install (recommended)

One-liner that downloads the latest release and installs everything:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econext-gateway/main/deploy/bootstrap.sh | sudo bash
```

To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econext-gateway/main/deploy/bootstrap.sh | sudo bash -s -- --version 0.2.0
```

### Upgrading

Re-run the quick install one-liner. It stops the service, installs the new version into the existing `/opt/econext-gateway`, and starts it again. Persistent state (`/var/lib/econext-gateway`), `systemctl edit` overrides and any `/etc/udev/rules.d/99-econext-local.rules` you created are kept. The service unit and `/etc/udev/rules.d/99-econext.rules` are regenerated, so put customisations in the override / local files, not there.

The installer prints `Installed version: ...` at the end. Give the gateway a couple of minutes, then check that parameters are flowing:

```bash
curl http://<gateway-ip>:8000/health
```

Version-specific notes are in [CHANGELOG.md](CHANGELOG.md). Update the Home Assistant integration through HACS as usual; the required minimum is listed there.

### Manual Install

Prerequisites: Python 3.11+ (uses [uv](https://docs.astral.sh/uv/) if available, otherwise falls back to pip)

```bash
git clone https://github.com/LeeNuss/econext-gateway.git
cd econext-gateway
sudo ./deploy/install.sh
```

This will:
1. Install the package to `/opt/econext-gateway`
2. Create a Python venv and install dependencies
3. Install a systemd service and udev rule
4. Start the service

### Docker

```bash
docker build -t econext-gateway .
docker run -d \
  --device /dev/ttyUSB0 \
  -p 8000:8000 \
  -e ECONEXT_SERIAL_PORT=/dev/ttyUSB0 \
  econext-gateway
```

## Configuration

All settings are configured via environment variables with the `ECONEXT_` prefix. When using the systemd service, add them as an override so they survive upgrades:

```bash
sudo systemctl edit econext-gateway
```

```ini
[Service]
Environment=ECONEXT_LOG_LEVEL=DEBUG
```

Then `sudo systemctl restart econext-gateway`. Do not edit `/etc/systemd/system/econext-gateway.service` directly; the installer regenerates it on every upgrade.

| Variable                      | Default                    | Description                                     |
| ----------------------------- | -------------------------- | ----------------------------------------------- |
| `ECONEXT_SERIAL_PORT`         | `/dev/econext`             | Serial port path                                |
| `ECONEXT_SERIAL_BAUD`         | `115200`                   | Baud rate                                       |
| `ECONEXT_API_HOST`            | `0.0.0.0`                  | API listen address                              |
| `ECONEXT_API_PORT`            | `8000`                     | API listen port                                 |
| `ECONEXT_LOG_LEVEL`           | `INFO`                     | Log level (DEBUG, INFO, WARNING, ERROR)         |
| `ECONEXT_POLL_INTERVAL`       | `10.0`                     | Parameter poll interval in seconds              |
| `ECONEXT_TOKEN_REQUIRED`      | `true`                     | Wait for bus token before sending requests      |
| `ECONEXT_DESTINATION_ADDRESS` | `1`                        | Controller address                              |
| `ECONEXT_REQUEST_TIMEOUT`     | `1.5`                      | Timeout for individual requests in seconds      |
| `ECONEXT_PARAMS_PER_REQUEST`  | `100`                      | Parameters to fetch per poll cycle              |
| `ECONEXT_STATE_DIR`           | `/var/lib/econext-gateway` | Directory for persistent state (paired address) |
| `ECONEXT_THERMOSTAT_ENABLED`  | `true`                     | Enable the virtual thermostat (see below)       |
| `ECONEXT_THERMOSTAT_MAX_AGE`  | `300.0`                    | Seconds before a submitted temperature is stale |
| `ECONEXT_THERMOSTAT_STALE_FALLBACK` | `19.0`               | Temperature reported on the bus when stale      |
| `ECONEXT_CLOCK_SYNC_ENABLED`  | `true`                     | Sync the panel clock from the host once a day   |
| `ECONEXT_CLOCK_SYNC_HOUR`     | `3`                        | Hour (local time) of the daily clock sync       |
| `ECONEXT_CLOCK_SYNC_MINUTE`   | `30`                       | Minute of the daily clock sync                  |

## API

### Get all parameters

```bash
curl http://<gateway-ip>:8000/api/parameters
```

Returns JSON with all discovered parameters keyed by index, including name, current value, type, unit, and writable flag:

```json
{
  "timestamp": "2025-01-15T12:00:00",
  "parameters": {
    "42": {
      "index": 42,
      "name": "TempCWU",
      "value": 45.5,
      "type": 2,
      "unit": 1,
      "writable": false,
      "min": null,
      "max": null
    }
  }
}
```

### Set a parameter

```bash
curl -X POST http://<gateway-ip>:8000/api/parameters/HDWTSetPoint \
  -H "Content-Type: application/json" \
  -d '{"value": 50.0}'
```

### Health check

```bash
curl http://<gateway-ip>:8000/health
```

## Home Assistant Integration

### ecoNEXT Integration

Install the [econext](https://github.com/LeeNuss/econext) custom integration for full Home Assistant support with climate entities, sensors, switches, and more.

1. Open HACS in Home Assistant
2. Go to **Integrations** > three-dot menu > **Custom repositories**
3. Add `https://github.com/LeeNuss/econext` as type **Integration**
4. Click **Download** and restart Home Assistant
5. Go to **Settings** > **Devices & Services** > **Add Integration**
6. Search for **ecoNEXT** and enter your gateway's IP address and port

### Schedule Card

For weekly heating schedule management, install the [econext-schedule-card](https://github.com/LeeNuss/econext-schedule-card) Lovelace card via HACS:

1. Open HACS > **Frontend** > three-dot menu > **Custom repositories**
2. Add `https://github.com/LeeNuss/econext-schedule-card` as type **Dashboard**
3. Click **Download** and reload your browser

## Service Management

```bash
# Check status
sudo systemctl status econext-gateway

# View logs
journalctl -u econext-gateway -f

# Restart
sudo systemctl restart econext-gateway

# Stop
sudo systemctl stop econext-gateway
```

## Bus Address Registration

On first startup, the gateway automatically registers itself on the bus by claiming a free address from the panel's IDENTIFY scan. The claimed address is persisted to `ECONEXT_STATE_DIR/paired_address` so subsequent restarts are instant.

1. Gateway listens passively for the panel's scanning IDENTIFY probe
2. When the panel probes a free address, the gateway claims it and responds
3. The panel registers the gateway and grants it a token in the same cycle
4. On subsequent restarts, the persisted address is loaded immediately

This means the gateway never uses a hardcoded bus address and coexists with any other device (ecoNET300, thermostats, etc.) without manual configuration.

### Re-pairing

To force the gateway to claim a new address, delete the persisted address file and restart:

```bash
sudo rm /var/lib/econext-gateway/paired_address
sudo systemctl restart econext-gateway
```

### Notes

- First auto-registration typically takes 2-3 minutes. Subsequent restarts reuse the persisted address instantly.
- Only addresses in the panel peripheral range (105-130) are claimed.
- Addresses already occupied by other devices on the bus are skipped.
- Set `ECONEXT_LOG_LEVEL=DEBUG` to see all bus traffic, including IDENTIFY probes and token grants.

## Running Alongside ecoNET300

The gateway can share the RS-485 bus with the ecoNET300, keeping the econet24 cloud/app and installer access working. Requires gateway v0.2.0 or later.

1. Leave the ecoNET300 on the controller's **G3** socket.
2. Wire a second USB-RS485 converter (e.g. Waveshare FT232RL, `0403:6001`) to the **G1** socket, in parallel with the touch panel. Power the controller down for wiring.
3. Add a udev rule for the converter in `/etc/udev/rules.d/99-econext-local.rules` (see [Troubleshooting](#troubleshooting)) or set `ECONEXT_SERIAL_PORT`.
4. If the gateway previously ran standalone, `sudo rm -f /var/lib/econext-gateway/paired_address`.
5. Power the controller up and start the gateway. It auto-registers at a free address (2-3 min); no further configuration needed.

Details, bus trace of a healthy setup and troubleshooting: [docs/PARALLEL_ECONET300.md](docs/PARALLEL_ECONET300.md).

## Virtual Thermostat

The gateway can emulate a thermostat on the RS-485 bus, allowing Home Assistant to submit a room temperature that the heat pump controller uses for heating control. This is useful if you have multiple temperature sensors (e.g. Aqara) and want to use a weighted average instead of a single-point reading from a physical thermostat.

### Setup

The virtual thermostat is enabled by default. To disable it, set `ECONEXT_THERMOSTAT_ENABLED=false` via `sudo systemctl edit econext-gateway` (see [Configuration](#configuration)).

1. Submit a temperature (e.g. from Home Assistant — the [HA integration](#home-assistant-integration) does this for you):
   ```bash
   curl -X POST http://your-gateway:8000/api/thermostat/temperature \
     -H 'Content-Type: application/json' -d '{"temperature": 21.0}'
   ```

2. Trigger pairing via the API:
   ```bash
   curl -X POST http://your-gateway:8000/api/thermostat/pair
   ```

3. Put the panel into pairing mode within 60 seconds. On the Grant Aerona Smart Controller, the quickest path is:

   - From the main menu, tap the **current temperature** of the circuit you want to assign the thermostat to.
   - On the screen that opens, tap the **thermostat-with-plus** icon in the bottom-left corner. The pairing wizard starts.

   (Alternative path: **System settings -> Circuit settings -> [target circuit] -> Thermostat**, confirm overwrite if prompted.)

   The wizard waits for a thermostat to announce itself — tap `>` on the panel to accept. The panel will show `END` / `Succ` on success, and the gateway pairs as an `ecoSTER_40` thermostat assigned to that circuit.

### API Endpoints

| Method | Endpoint                      | Description                                                 |
| ------ | ----------------------------- | ----------------------------------------------------------- |
| POST   | `/api/thermostat/temperature` | Submit temperature reading (`{"temperature": 21.0}`)        |
| POST   | `/api/thermostat/pair`        | Request bus pairing (panel must be in pairing mode)         |
| GET    | `/api/thermostat/status`      | Get thermostat status (temperature, staleness, bus address) |

### Home Assistant Integration

The [ecoNEXT HA integration](https://github.com/LeeNuss/econext) (main branch, install via HACS) adds:

- **Virtual Thermostat** device with Pair button, Reported temperature, State, and Source sensor entities
- **Entity selector** in integration settings to automatically submit a temperature sensor reading every 10 seconds
- Configure via: Settings -> Integrations -> ecoNEXT -> gear icon -> select temperature sensor

See the integration's README for entity descriptions and full setup instructions.

### Notes

- The virtual thermostat coexists with real ecoSTER thermostats on separate circuits
- The last submitted temperature is persisted to disk and survives gateway restarts
- If Home Assistant stops sending updates for longer than `ECONEXT_THERMOSTAT_MAX_AGE` (default 300s), the reading is marked stale and the gateway falls back to `ECONEXT_THERMOSTAT_STALE_FALLBACK` (default 19.0 C) on the bus
- Re-pairing: press the Pair button (or POST `/api/thermostat/pair`) again to claim a new bus address. The previous address is released
- To force a re-pair from the gateway side, delete `/var/lib/econext-gateway/thermostat_address` and restart the service

### Troubleshooting

**Pair request times out / "Pairing requested" stays stuck**
- The panel was not in pairing mode within the 60s window. Re-trigger the request and confirm the panel shows pairing-mode UI before the window expires
- Check `journalctl -u econext-gateway -n 100` for `pairing beacon` log lines — these confirm the panel is actually broadcasting pairing beacons (`SERVICE 0x2004`)
- If beacons are absent, the panel is not in pairing mode

**No address assigned after pairing**
- Verify with `curl http://your-gateway:8000/api/thermostat/status`
- Check logs for `thermostat paired` / `assigned address` entries
- Try deleting `/var/lib/econext-gateway/thermostat_address` and pairing again

**Temperature not appearing on the panel**
- Confirm the new thermostat is assigned to a heating circuit on the panel
- POST `/api/thermostat/status` should return a recent `temperature` and `is_stale: false`
- Set `ECONEXT_LOG_LEVEL=DEBUG` to see the temperature being read by the panel

## Troubleshooting

**Service won't start**
- Check logs: `journalctl -u econext-gateway -n 50`
- Verify the serial device exists: `ls -la /dev/econext` or `ls -la /dev/ttyUSB0`
- Check permissions: the service user must be in the `dialout` group

**No parameters discovered**
- Make sure no other process uses the RS-485 device
- Check `ECONEXT_LOG_LEVEL=DEBUG` for bus traffic details
- Verify the adapter is plugged in: `lsusb | grep -i plum` or `dmesg | grep ttyUSB`

**Using a non-ecoLINK3 adapter (e.g. FTDI FT232H)**

The default udev rule only matches the Plum ecoLINK3 adapter. For other USB-RS485
adapters you have two options:

*Option A: Add a udev rule (creates the `/dev/econext` symlink)*

1. Identify your adapter's attributes:
   ```bash
   udevadm info -a /dev/ttyUSB0 | grep -E 'idVendor|idProduct|serial|manufacturer|product'
   ```
2. Create `/etc/udev/rules.d/99-econext-local.rules` with a line matching your adapter
   (this file survives upgrades; `99-econext.rules` is overwritten by the installer).
   FT232H (USB ID `0403:6014`):
   ```
   SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6014", SYMLINK+="econext", MODE="0666"
   ```
   FT232RL, e.g. Waveshare (`0403:6001`):
   ```
   SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="econext", MODE="0666"
   ```
   If you have several FTDI devices on the same system, add `ATTRS{serial}=="YOUR_SERIAL"`
   to target the right one.
3. Reload rules and verify:
   ```bash
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ls -la /dev/econext
   ```

*Option B: Skip the symlink and point directly at the device*

If the udev rule is inconvenient (e.g. generic adapter with no unique serial), you can
bypass it entirely and set the serial port path directly:
```bash
sudo systemctl edit econext-gateway
```
```ini
[Service]
Environment=ECONEXT_SERIAL_PORT=/dev/ttyUSB0
```
Note that `/dev/ttyUSBx` numbering can change across reboots if multiple USB-serial
devices are present, so a udev symlink is preferred when possible.

**Gateway stuck at "Waiting for token from panel"**
- On first boot, the gateway must auto-register; this takes up to one bus cycle (~10s)
- If a previous address was persisted, try re-pairing: `sudo rm /var/lib/econext-gateway/paired_address && sudo systemctl restart econext-gateway`
- Enable `ECONEXT_LOG_LEVEL=DEBUG` to see which addresses the panel is probing with IDENTIFY

**Stale parameter values**
- The gateway polls every `ECONEXT_POLL_INTERVAL` seconds (default 10)
- Force a re-read by restarting the service

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/LeeNuss/econext-gateway.git
cd econext-gateway
uv sync --group dev

# Run tests
uv run pytest tests/ -x -q

# Lint
uv run ruff check .

# Run locally
uv run uvicorn econext_gateway.main:app --host 0.0.0.0 --port 8000
```

## License

Copyright 2026 Linus Reitmayr. Licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Free** for personal / private use, and for non-profit, educational, research and government use. You may use, modify and redistribute the gateway for those purposes.
- **Commercial use requires a paid license.** This includes use by heating installers, heat pump manufacturers or distributors, energy service providers, or bundling the gateway into a product or service. Contact the author via GitHub ([LeeNuss](https://github.com/LeeNuss)) to arrange one.

By contributing to this repository you agree that your contribution is licensed under the same terms and that the copyright holder may also license it commercially.
