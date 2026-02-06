# econet GM3 Gateway

Local REST API gateway for Plum ecoNET heat pump controllers using the GM3 serial protocol. Runs on a Raspberry Pi (or similar) connected to the controller via RS-485, providing an HTTP API for Home Assistant and other automation systems.

```
[Home Assistant] --HTTP--> [econet-gm3-gateway] --RS-485--> [Heat Pump Controller]
```

## Features

- Full GM3 token-passing bus protocol for reliable, fast parameter access
- 1870 parameters discovered in ~7 seconds
- Read and write controller parameters via REST API
- Runs as a systemd service
- No cloud dependency

## Hardware Requirements

- **Raspberry Pi** (or any Linux SBC) with a free USB port
- **Plum ecoLINK3 USB-RS485 adapter** (comes with the ecoNET 300 package)
- **Supported controller**: ecoTRONIC, ecoMAX, or other GM3-compatible heat pump controllers

### Wiring

Connect the ecoLINK3 adapter to the controller's RS-485 bus (A/B terminals) and plug the USB end into the Raspberry Pi. The included udev rule creates a `/dev/econet` symlink automatically.

## Installation

### Quick Install (recommended)

One-liner that downloads the latest release and installs everything:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econet-gm3-gateway/main/deploy/bootstrap.sh | sudo bash
```

To install a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/LeeNuss/econet-gm3-gateway/main/deploy/bootstrap.sh | sudo bash -s -- --version 0.1.0
```

### Manual Install

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/LeeNuss/econet-gm3-gateway.git
cd econet-gm3-gateway
sudo ./deploy/install.sh
```

This will:
1. Install the package to `/opt/econet-gm3-gateway`
2. Create a Python venv and install dependencies
3. Install a systemd service and udev rule
4. Start the service

### Docker

```bash
docker build -t econet-gm3-gateway .
docker run -d \
  --device /dev/ttyUSB0 \
  -p 8000:8000 \
  -e ECONET_SERIAL_PORT=/dev/ttyUSB0 \
  econet-gm3-gateway
```

## Configuration

All settings are configured via environment variables with the `ECONET_` prefix. When using the systemd service, edit `/etc/systemd/system/econet-gm3-gateway.service` and run `sudo systemctl daemon-reload && sudo systemctl restart econet-gm3-gateway`.

| Variable | Default | Description |
|----------|---------|-------------|
| `ECONET_SERIAL_PORT` | `/dev/econet` | Serial port path |
| `ECONET_SERIAL_BAUD` | `115200` | Baud rate |
| `ECONET_API_HOST` | `0.0.0.0` | API listen address |
| `ECONET_API_PORT` | `8000` | API listen port |
| `ECONET_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `ECONET_POLL_INTERVAL` | `10.0` | Parameter poll interval in seconds |
| `ECONET_TOKEN_REQUIRED` | `true` | Wait for bus token before sending requests |

## API

### Get all parameters

```bash
curl http://<gateway-ip>:8000/api/parameters
```

Returns JSON with all discovered parameters, their current values, types, units, and writable flag:

```json
{
  "timestamp": "2025-01-15T12:00:00",
  "parameters": {
    "TempCWU": {
      "index": 42,
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

### ecoNET Next Integration

Install the [econet-next](https://github.com/LeeNuss/econet-next) custom integration for full Home Assistant support with climate entities, sensors, switches, and more.

1. Open HACS in Home Assistant
2. Go to **Integrations** > three-dot menu > **Custom repositories**
3. Add `https://github.com/LeeNuss/econet-next` as type **Integration**
4. Click **Download** and restart Home Assistant
5. Go to **Settings** > **Devices & Services** > **Add Integration**
6. Search for **ecoNET Next** and enter your gateway's IP address and port

### Schedule Card

For weekly heating schedule management, install the [econet-schedule-card](https://github.com/LeeNuss/econet-schedule-card) Lovelace card via HACS:

1. Open HACS > **Frontend** > three-dot menu > **Custom repositories**
2. Add `https://github.com/LeeNuss/econet-schedule-card` as type **Dashboard**
3. Click **Download** and reload your browser

## Service Management

```bash
# Check status
sudo systemctl status econet-gm3-gateway

# View logs
journalctl -u econet-gm3-gateway -f

# Restart
sudo systemctl restart econet-gm3-gateway

# Stop
sudo systemctl stop econet-gm3-gateway
```

## Troubleshooting

**Service won't start**
- Check logs: `journalctl -u econet-gm3-gateway -n 50`
- Verify the serial device exists: `ls -la /dev/econet` or `ls -la /dev/ttyUSB0`
- Check permissions: the service user must be in the `dialout` group

**No parameters discovered**
- Make sure the original ecoNET 300 webserver is stopped (`sudo systemctl stop econet-srv`) -- only one device can use the RS-485 bus at a time
- Check `ECONET_LOG_LEVEL=DEBUG` for bus traffic details
- Verify the ecoLINK3 adapter is plugged in: `lsusb | grep -i plum` or `dmesg | grep ttyUSB`

**Stale parameter values**
- The gateway polls every `ECONET_POLL_INTERVAL` seconds (default 10)
- Force a re-read by restarting the service

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/LeeNuss/econet-gm3-gateway.git
cd econet-gm3-gateway
uv sync --group dev

# Run tests
uv run pytest tests/ -x -q

# Lint
uv run ruff check .

# Run locally
uv run uvicorn econet_gm3_gateway.main:app --host 0.0.0.0 --port 8000
```

## License

MIT
