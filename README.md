# econet GM3 Gateway

Local REST API gateway for GM3 protocol heat pump controllers. Provides a simple HTTP interface for Home Assistant and other automation systems.

Communicates directly with the controller via RS-485 serial, implementing the full GM3 token-passing bus protocol for reliable, fast parameter access.

## Features

- **Fast Discovery**: 1870 parameters in 6.6 seconds (single token grant)
- **Token-Based Bus Access**: Full IDENTIFY handshake + SERVICE token protocol for 100% response rate
- **Two Address Spaces**: Regulator (WITH_RANGE) + Panel (WITHOUT_RANGE) params
- **Local Only**: No cloud dependency required
- **Async Python**: FastAPI + direct pyserial with run_in_executor
- **Simple API**: GET/POST parameters, health check
- **Home Assistant**: Designed for seamless HA integration via REST sensor/switch

## Quick Start

```bash
# Install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .

# Run server
uvicorn econet_gm3_gateway.main:app --host 0.0.0.0 --port 8000
```

## API Usage

### Get All Parameters

```bash
curl http://localhost:8000/api/parameters
```

### Set Parameter Value

```bash
curl -X POST http://localhost:8000/api/parameters/target_temp \
  -H "Content-Type: application/json" \
  -d '{"value": 45.0}'
```

## Configuration

Configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERIAL_PORT` | `/dev/ttyUSB0` | Serial port path |
| `SERIAL_BAUD` | `115200` | Baud rate |
| `API_HOST` | `0.0.0.0` | API server host |
| `API_PORT` | `8000` | API server port |
| `LOG_LEVEL` | `INFO` | Logging level |

## Performance (HW verified 2026-02-06)

| Metric | Value |
|--------|-------|
| Discovery time | 6.6s (single token grant) |
| Regulator params | 1447 in 4.3s (39 batches) |
| Panel params | 423 in 2.3s (43 batches) |
| Total params | 1870 (matches original webserver) |
| Per-request latency | ~50ms (two-stage serial read) |

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests (241 passing)
pytest

# Format code
ruff format .

# Lint
ruff check .
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed design documentation.

## License

MIT License - see LICENSE file for details.

## Credits

This project implements the GM3 protocol through reverse engineering for interoperability purposes.
