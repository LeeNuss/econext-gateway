# econet GM3 Gateway - Architecture & Design

**Version**: 1.0 (Initial Design)
**Date**: 2026-01-13

This document describes the architecture and design decisions for the econet GM3 Gateway project - a local API server for GM3 protocol heat pump controllers.

## Project Goals

1. **Local API for Home Assistant**: Provide REST API for controlling GM3-compatible heat pumps
2. **Simple & Focused**: Minimal viable product with 2 core endpoints (get/set parameters)
3. **Modern Python**: Use current best practices and async patterns
4. **Docker-First**: Easy deployment alongside Home Assistant
5. **No Cloud Dependency**: Local-only operation (cloud sync optional for future)

## Technology Stack

### Core Technologies

| Component       | Technology       | Version | Rationale                                            |
| --------------- | ---------------- | ------- | ---------------------------------------------------- |
| Language        | Python           | 3.11+   | Modern features, async support, type hints           |
| Web Framework   | FastAPI          | Latest  | Async-native, auto OpenAPI docs, Pydantic validation |
| Serial I/O      | pyserial-asyncio | Latest  | Async serial communication                           |
| ASGI Server     | Uvicorn          | Latest  | High performance, async support                      |
| Package Manager | uv               | Latest  | Fast, reliable dependency management                 |
| Code Formatter  | Ruff             | 0.14.2  | Fast, comprehensive linting and formatting           |

### Development Tools

- **Type Checking**: Built-in Python type hints, validated by Ruff
- **Testing**: pytest with async support
- **Container**: Docker with multi-stage builds
- **CI/CD**: GitHub Actions (if published)

### Configuration

- **Line Length**: 120 characters (ruff configured)
- **Python Version**: Requires 3.11+ for modern async features

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Home Assistant                      │
│               (or other HTTP client)                 │
└────────────────────┬────────────────────────────────┘
                     │ HTTP REST API
                     │ (JSON)
         ┌───────────▼──────────────┐
         │    FastAPI Application    │
         │   ┌──────────────────┐   │
         │   │  API Routes      │   │
         │   │  - GET /params   │   │
         │   │  - POST /params  │   │
         │   └─────────┬────────┘   │
         │             │             │
         │   ┌─────────▼────────┐   │
         │   │  Parameter Cache │   │
         │   │  (in-memory)     │   │
         │   └─────────┬────────┘   │
         │             │             │
         │   ┌─────────▼────────┐   │
         │   │  GM3 Protocol    │   │
         │   │  Handler         │   │
         │   └─────────┬────────┘   │
         │             │             │
         │   ┌─────────▼────────┐   │
         │   │  Serial Manager  │   │
         │   │  (asyncio)       │   │
         │   └─────────┬────────┘   │
         └─────────────┼────────────┘
                       │ Serial
                       │ /dev/ttyUSB0
                       │ 115200 baud
              ┌────────▼────────┐
              │  GM3 Controller │
              │  (Heat Pump)    │
              └─────────────────┘
```

### Component Design

#### 1. API Layer (`src/api/`)
**Responsibility**: HTTP interface, request validation, response formatting

- `routes.py`: Endpoint definitions
- `models.py`: Pydantic models for request/response
- `dependencies.py`: FastAPI dependencies (auth, etc.)

**Key Features**:
- Auto-generated OpenAPI documentation
- Input validation via Pydantic
- Async handlers for non-blocking I/O
- Error handling and status codes

#### 2. Protocol Layer (`src/protocol/`)
**Responsibility**: GM3 protocol implementation, message encoding/decoding

- `frames.py`: Frame construction and parsing
- `messages.py`: Message types and handlers
- `constants.py`: Protocol constants (frame markers, CRC polynomials)
- `codec.py`: Parameter encoding/decoding

**Key Features**:
- Frame format: `0x68 [LEN_L] [LEN_H] [DEST_L] [DEST_H] [SRC] [CMD] [...] [CRC_H] [CRC_L] 0x16`
- CRC-16 validation
- Parameter type handling (int, float, string, bool)
- Async message queue

#### 3. Serial Layer (`src/serial/`)
**Responsibility**: Serial port communication, connection management

- `connection.py`: Serial port management
- `reader.py`: Async frame reading
- `writer.py`: Async frame writing

**Key Features**:
- Asyncio-based I/O
- Automatic reconnection
- Buffer management
- Error recovery

#### 4. Core (`src/core/`)
**Responsibility**: Application state, caching, business logic

- `cache.py`: Parameter cache with TTL
- `state.py`: Application state management
- `config.py`: Configuration loading (env vars, YAML)

**Key Features**:
- Thread-safe parameter cache
- Configurable refresh intervals
- State persistence (optional)

## API Design

### Minimal API (v1.0)

#### GET `/api/parameters`
Get all parameters from the heat pump.

**Response**:
```json
{
  "timestamp": "2026-01-13T12:00:00Z",
  "parameters": {
    "outdoor_temp": {
      "value": 5.2,
      "unit": "°C",
      "writable": false
    },
    "target_temp": {
      "value": 45.0,
      "unit": "°C",
      "writable": true,
      "min": 20.0,
      "max": 55.0
    }
  }
}
```

#### POST `/api/parameters/{param_name}`
Set a parameter value.

**Request**:
```json
{
  "value": 47.0
}
```

**Response**:
```json
{
  "success": true,
  "parameter": "target_temp",
  "old_value": 45.0,
  "new_value": 47.0,
  "timestamp": "2026-01-13T12:00:05Z"
}
```

### Future Endpoints (Not v1.0)

- `GET /api/parameters/{name}` - Get single parameter
- `GET /api/alarms` - Get active alarms
- `GET /api/status` - System health check
- `POST /api/schedules` - Set heating schedules
- WebSocket `/ws/parameters` - Real-time updates

## Data Flow

### Read Parameters Flow

```
1. HTTP Client → GET /api/parameters
2. API Handler → Check cache freshness
3. If stale → Protocol Handler: Request parameters
4. Protocol Handler → Serial: Send GM3 request frame
5. Serial → Controller: 0x68 [GET_PARAMS] ...
6. Controller → Serial: 0x68 [PARAMS_DATA] ...
7. Serial → Protocol Handler: Parse response
8. Protocol Handler → Cache: Update values
9. Cache → API Handler: Return data
10. API Handler → HTTP Client: JSON response
```

### Write Parameter Flow

```
1. HTTP Client → POST /api/parameters/target_temp {value: 47.0}
2. API Handler → Validate input (type, range)
3. API Handler → Protocol Handler: Set parameter
4. Protocol Handler → Serial: Send GM3 set frame
5. Serial → Controller: 0x68 [SET_PARAM] ...
6. Controller → Serial: 0x68 [ACK/NACK] ...
7. Serial → Protocol Handler: Parse response
8. Protocol Handler → Cache: Update value (if ACK)
9. Cache → API Handler: Return result
10. API Handler → HTTP Client: JSON response
```

## Configuration

### Environment Variables

```bash
# Serial Port
SERIAL_PORT=/dev/ttyUSB0
SERIAL_BAUD=115200
SERIAL_TIMEOUT=0.2

# API Server
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1

# Protocol
GM3_SOURCE_ADDRESS=131
GM3_DEST_ADDRESS=1
GM3_RETRY_ATTEMPTS=3

# Cache
CACHE_TTL_SECONDS=10
CACHE_MAX_SIZE=1000

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Configuration File (Optional)

`config.yaml`:
```yaml
serial:
  port: /dev/ttyUSB0
  baud: 115200
  timeout: 0.2

api:
  host: 0.0.0.0
  port: 8000

protocol:
  source_address: 131
  destination_address: 1
  retry_attempts: 3

cache:
  ttl_seconds: 10
  max_size: 1000
```

## Deployment

### Docker Deployment (Primary)

**Dockerfile** (multi-stage):
```dockerfile
# Build stage
FROM python:3.11-slim as builder
RUN pip install uv
COPY pyproject.toml .
RUN uv pip compile pyproject.toml -o requirements.txt
RUN uv pip install -r requirements.txt

# Runtime stage
FROM python:3.11-slim
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY src/ /app/src/
WORKDIR /app
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml**:
```yaml
version: '3.8'
services:
  econet-gateway:
    build: .
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0
    ports:
      - "8000:8000"
    environment:
      - SERIAL_PORT=/dev/ttyUSB0
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

### Systemd Service (Alternative)

For direct installation on Raspberry Pi or similar:

```ini
[Unit]
Description=econet GM3 Gateway
After=network.target

[Service]
Type=simple
User=econet
WorkingDirectory=/opt/econet-gateway
ExecStart=/opt/econet-gateway/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Error Handling

### Serial Communication Errors

| Error               | Strategy                       | Retry      |
| ------------------- | ------------------------------ | ---------- |
| Timeout             | Retry with exponential backoff | 3 attempts |
| CRC Error           | Discard frame, request resend  | 3 attempts |
| Device Disconnected | Reconnect, reinitialize        | Infinite   |
| Invalid Response    | Log error, return cached value | N/A        |

### API Errors

| Error               | HTTP Status | Response                                  |
| ------------------- | ----------- | ----------------------------------------- |
| Parameter not found | 404         | `{"error": "Parameter 'xyz' not found"}`  |
| Invalid value       | 400         | `{"error": "Value out of range [20-55]"}` |
| Serial unavailable  | 503         | `{"error": "Heat pump unavailable"}`      |
| Internal error      | 500         | `{"error": "Internal server error"}`      |

## Testing Strategy

### Unit Tests
- Protocol frame encoding/decoding
- CRC calculation
- Parameter validation
- Cache operations

### Integration Tests
- Mock serial communication
- API endpoint responses
- Error handling
- State management

### Hardware Tests
- Real serial device communication
- End-to-end parameter read/write
- Connection recovery
- Long-running stability

## Performance Targets

| Metric            | Target  | Notes                         |
| ----------------- | ------- | ----------------------------- |
| API Response Time | < 200ms | For cached values             |
| Serial Read Cycle | 5-10s   | Configurable polling interval |
| Memory Usage      | < 100MB | Including Python runtime      |
| CPU Usage (idle)  | < 5%    | On Raspberry Pi 3             |
| Startup Time      | < 5s    | From cold start to ready      |

## Security Considerations

### Initial Version (v1.0)
- **No authentication**: Assumes trusted local network
- **No encryption**: HTTP only (not HTTPS)
- **No authorization**: All clients have full access

### Future Considerations
- API key authentication
- HTTPS with self-signed certificates
- Read-only vs read-write access levels
- Rate limiting

**Rationale for v1.0**:
- Runs on local network only
- Primary use case is single Home Assistant instance
- Complexity vs security trade-off for minimal API
- Can add auth layer via reverse proxy if needed

## Monitoring & Observability

### Logging
- **Format**: Structured JSON logs
- **Levels**: DEBUG, INFO, WARNING, ERROR
- **Key Events**:
  - Serial connection/disconnection
  - Parameter updates
  - API requests (with timing)
  - Protocol errors

### Metrics (Future)
- Prometheus endpoint `/metrics`
- Key metrics:
  - API request count/latency
  - Serial communication success rate
  - Cache hit rate
  - Active connections

### Health Check
- Endpoint: `GET /health`
- Checks:
  - Serial port accessible
  - Recent successful communication
  - Cache operational
- Returns: `{"status": "healthy", "uptime": 12345}`

## Development Workflow

### Project Structure
```
econet-gm3-gateway/
├── src/
│   ├── api/              # FastAPI routes and models
│   ├── protocol/         # GM3 protocol implementation
│   ├── serial/           # Serial communication
│   ├── core/             # Cache, config, state
│   └── main.py           # Application entry point
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
│   └── ARCHITECTURE.md   # This file
├── pyproject.toml        # Project metadata and dependencies
├── Dockerfile
├── docker-compose.yml
├── .gitignore
└── README.md
```

### Development Setup
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest

# Run locally
uvicorn src.main:app --reload
```

## Future Enhancements (Post v1.0)

### Phase 2: Enhanced Features
- Schedule management
- Alarm/error handling
- Parameter history/logging
- WebSocket for real-time updates
- Configuration import/export

### Phase 3: Cloud Integration (Optional)
- Cloud sync as pluggable module
- Completely optional
- Never required for core functionality
- Configuration-driven

### Phase 4: Advanced Features
- Multi-device support
- MQTT integration
- Grafana dashboard templates
- Mobile app API

## Design Principles

1. **Simple First**: Start with minimal viable product
2. **Async Native**: Use asyncio throughout
3. **Type Safe**: Leverage Python type hints
4. **Testable**: Design for easy unit testing
5. **Observable**: Log everything important
6. **Resilient**: Handle errors gracefully
7. **Documented**: Self-documenting code + API docs
8. **Portable**: Docker-first, but works standalone

## References

### Related Projects
- PyPlumIO: Open-source alternative econet (EM protocol only)
- Home Assistant: Target integration platform

### Standards
- GM3 Protocol: Custom proprietary protocol
- REST API: Standard HTTP/JSON patterns
- OpenAPI 3.0: API documentation standard

---

**Document Status**: Living document
**Next Review**: After v1.0 implementation
**Maintainer**: Project team
