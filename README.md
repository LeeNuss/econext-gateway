# econet GM3 Gateway

Local REST API gateway for GM3 protocol heat pump controllers. Provides a simple HTTP interface for Home Assistant and other automation systems.

## Features

- **Local Only**: No cloud dependency required
- **Fast**: Async Python with FastAPI
- **Simple API**: Two core endpoints - get and set parameters
- **Home Assistant**: Designed for seamless HA integration

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

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
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
