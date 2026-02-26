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
- Runs as a systemd service
- No cloud dependency

## Hardware Requirements

- **Raspberry Pi** (or any Linux SBC) with a free USB port
- **Plum ecoLINK3 USB-RS485 adapter** (comes with the ecoNET300 package)
- **Supported controller**: ecoTRONIC, ecoMAX, or other compatible heat pump controllers

### Wiring

Connect the ecoLINK3 adapter to the controller's RS-485 bus (A/B terminals) and plug the USB end into the Raspberry Pi. The included udev rule creates a `/dev/econext` symlink automatically.

## Installation

### Quick Install (recommended)

One-liner that downloads the latest release and installs everything:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econext-gateway/main/deploy/bootstrap.sh | sudo bash
```

To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econext-gateway/main/deploy/bootstrap.sh | sudo bash -s -- --version 0.1.0
```

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

All settings are configured via environment variables with the `ECONEXT_` prefix. When using the systemd service, edit `/etc/systemd/system/econext-gateway.service` and run `sudo systemctl daemon-reload && sudo systemctl restart econext-gateway`.

| Variable | Default | Description |
|----------|---------|-------------|
| `ECONEXT_SERIAL_PORT` | `/dev/econext` | Serial port path |
| `ECONEXT_SERIAL_BAUD` | `115200` | Baud rate |
| `ECONEXT_API_HOST` | `0.0.0.0` | API listen address |
| `ECONEXT_API_PORT` | `8000` | API listen port |
| `ECONEXT_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ECONEXT_POLL_INTERVAL` | `10.0` | Parameter poll interval in seconds |
| `ECONEXT_TOKEN_REQUIRED` | `true` | Wait for bus token before sending requests |
| `ECONEXT_DESTINATION_ADDRESS` | `1` | Controller address |
| `ECONEXT_REQUEST_TIMEOUT` | `1.5` | Timeout for individual requests in seconds |
| `ECONEXT_PARAMS_PER_REQUEST` | `100` | Parameters to fetch per poll cycle |
| `ECONEXT_STATE_DIR` | `/var/lib/econext-gateway` | Directory for persistent state (paired address) |

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

- Auto-registration typically completes within one bus cycle (~10 seconds).
- Reserved addresses (1, 2, 100-110, 131, 237) are never claimed.
- Set `ECONEXT_LOG_LEVEL=DEBUG` to see all bus traffic, including IDENTIFY probes and token grants.

## Troubleshooting

**Service won't start**
- Check logs: `journalctl -u econext-gateway -n 50`
- Verify the serial device exists: `ls -la /dev/econext` or `ls -la /dev/ttyUSB0`
- Check permissions: the service user must be in the `dialout` group

**No parameters discovered**
- Make sure the no other process uese the RS-485 device
- Check `ECONEXT_LOG_LEVEL=DEBUG` for bus traffic details
- Verify the ecoLINK3 adapter is plugged in: `lsusb | grep -i plum` or `dmesg | grep ttyUSB`

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

MIT
