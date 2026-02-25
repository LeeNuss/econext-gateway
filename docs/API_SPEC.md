# API Specification

REST API for controlling GM3 protocol heat pump controllers.

## Base URL

```
http://localhost:8000/api
```

## Authentication

Version 1.0 does not implement authentication. The API is intended for use on trusted local networks only.

## Content Type

All requests and responses use `application/json`.

## Endpoints

### GET /api/parameters

Get all parameters from the heat pump controller.

**Response:**

```json
{
  "timestamp": "2026-01-13T12:00:00Z",
  "parameters": {
    "150": {
      "index": 150,
      "name": "OutsideTemp",
      "value": 5.2,
      "type": 2,
      "unit": 1,
      "writable": false,
      "min": null,
      "max": null
    },
    "103": {
      "index": 103,
      "name": "HDWTSetPoint",
      "value": 45,
      "type": 2,
      "unit": 1,
      "writable": true,
      "min": 35,
      "max": 65
    }
  }
}
```

**Response Fields:**

- `timestamp` (string): ISO 8601 timestamp of when data was read
- `parameters` (object): Map of parameter index (as string) to parameter objects. Keyed by index because multiple parameters can share the same name across address spaces.

**Parameter Object Fields:**

- `index` (integer): Protocol parameter index (0-65535)
- `name` (string): Parameter name
- `value` (number|string|boolean): Current parameter value
- `type` (integer): Data type code (1=uint8, 2=int16, 3=int32, 4=bool, 5=string, 6=uint8)
- `unit` (integer): Unit code
- `writable` (boolean): Whether parameter can be modified
- `min` (number|null): Minimum allowed value (null if not applicable)
- `max` (number|null): Maximum allowed value (null if not applicable)

**Status Codes:**

- `200 OK`: Success
- `503 Service Unavailable`: Controller not connected

**Example:**

```bash
curl http://localhost:8000/api/parameters
```

---

### POST /api/parameters/{name}

Set a parameter value.

**Path Parameters:**

- `name` (string): Parameter name (e.g., `HDWTSetPoint`, `OutsideTemp`)

**Request Body:**

```json
{
  "value": 47.0
}
```

**Request Fields:**

- `value` (number|string|boolean): New parameter value

**Response:**

```json
{
  "success": true,
  "parameter": "HDWTSetPoint",
  "index": 103,
  "old_value": 45,
  "new_value": 47,
  "timestamp": "2026-01-13T12:00:05Z"
}
```

**Response Fields:**

- `success` (boolean): Whether operation succeeded
- `parameter` (string): Parameter name that was modified
- `index` (integer): Protocol parameter index
- `old_value` (number|string|boolean): Previous value
- `new_value` (number|string|boolean): New value
- `timestamp` (string): ISO 8601 timestamp of modification

**Status Codes:**

- `200 OK`: Parameter updated successfully
- `400 Bad Request`: Invalid value (out of range, wrong type)
- `404 Not Found`: Parameter does not exist
- `503 Service Unavailable`: Controller not connected

**Error Response:**

```json
{
  "success": false,
  "error": "Value 70.0 out of range [20.0-55.0]"
}
```

**Examples:**

```bash
# Set hot water setpoint
curl -X POST http://localhost:8000/api/parameters/HDWTSetPoint \
  -H "Content-Type: application/json" \
  -d '{"value": 47}'

# Set heating mode
curl -X POST http://localhost:8000/api/parameters/HDWusermode \
  -H "Content-Type: application/json" \
  -d '{"value": 1}'
```

---

## Health Check

### GET /health

Check if the API server is running.

**Response:**

```json
{
  "status": "healthy",
  "uptime": 12345,
  "controller_connected": true
}
```

**Status Codes:**

- `200 OK`: Service is healthy

---

## Root

### GET /

API information.

**Response:**

```json
{
  "name": "ecoNEXT Gateway",
  "version": "0.1.0",
  "status": "running"
}
```

---

## Cycling / Anti-Cycling

### GET /api/cycling/metrics

Get current compressor cycling metrics and state.

**Response:**

```json
{
  "compressor_on": true,
  "current_state_seconds": 342.5,
  "last_run_seconds": 180.0,
  "starts_last_hour": 3,
  "starts_last_24h": 12,
  "avg_run_seconds_1h": 420.0,
  "short_cycle_count_1h": 1,
  "min_work_time": 10,
  "min_break_time": 10,
  "counter_min_work": 5,
  "counter_min_break": null,
  "temp_outlet": 35.2,
  "temp_return": 28.1,
  "temp_weather": 4.5,
  "preset_temp": 35.0
}
```

**Response Fields:**

- `compressor_on` (boolean|null): Current compressor state (null if not yet observed)
- `current_state_seconds` (number): Seconds the compressor has been in its current state
- `last_run_seconds` (number|null): Duration of the last completed ON period
- `starts_last_hour` (integer): Compressor starts in the last hour
- `starts_last_24h` (integer): Compressor starts in the last 24 hours
- `avg_run_seconds_1h` (number|null): Average run duration in the last hour
- `short_cycle_count_1h` (integer): Runs shorter than 5 minutes in the last hour
- `min_work_time` (integer|null): Controller minWorkTime setting (minutes), read from cache
- `min_break_time` (integer|null): Controller minBreakTime setting (minutes), read from cache
- `counter_min_work` (integer|null): Controller counterMinWork countdown value
- `counter_min_break` (integer|null): Controller counterMinBreak countdown value
- `temp_outlet` (number|null): Current outlet temperature
- `temp_return` (number|null): Current return temperature
- `temp_weather` (number|null): Current outside temperature
- `preset_temp` (number|null): Current target/preset temperature

**Status Codes:**

- `200 OK`: Success

**Example:**

```bash
curl http://localhost:8000/api/cycling/metrics
```

---

### GET /api/cycling/history

Get recent compressor cycle events (last 24 hours, max 100).

**Response:**

```json
[
  {
    "timestamp": "2026-02-25T10:30:00Z",
    "turned_on": true,
    "duration": 600.0
  },
  {
    "timestamp": "2026-02-25T10:40:00Z",
    "turned_on": false,
    "duration": 600.0
  }
]
```

**Event Fields:**

- `timestamp` (string): ISO 8601 UTC timestamp of the transition
- `turned_on` (boolean): `true` = compressor started (OFF->ON), `false` = compressor stopped (ON->OFF)
- `duration` (number): How long the previous state lasted before this transition (seconds)

**Status Codes:**

- `200 OK`: Success

**Example:**

```bash
curl http://localhost:8000/api/cycling/history
```

---

### GET /api/cycling/settings

Get current anti-cycling timer settings from the controller.

**Response:**

```json
{
  "anticycling_enabled": true,
  "min_work_time": 10,
  "min_break_time": 10,
  "compressor_min_times_sett": 1
}
```

**Response Fields:**

- `anticycling_enabled` (boolean): Whether auto-setting of timers at startup is enabled
- `min_work_time` (integer|null): Current minWorkTime on controller (minutes)
- `min_break_time` (integer|null): Current minBreakTime on controller (minutes)
- `compressor_min_times_sett` (integer|null): Current compressorMinTimesSett value (read-only via this endpoint)

**Status Codes:**

- `200 OK`: Success

**Example:**

```bash
curl http://localhost:8000/api/cycling/settings
```

---

### POST /api/cycling/settings

Write new anti-cycling timer values to the controller.

**Request Body:**

```json
{
  "min_work_time": 15,
  "min_break_time": 10
}
```

**Request Fields:**

- `min_work_time` (integer|null): New minWorkTime value in minutes (0-60)
- `min_break_time` (integer|null): New minBreakTime value in minutes (0-60)

At least one field must be provided.

**Response:** Same as GET /api/cycling/settings (returns updated values).

**Status Codes:**

- `200 OK`: Settings updated successfully
- `400 Bad Request`: No values provided or value out of range
- `503 Service Unavailable`: Controller not connected or write not acknowledged

**Example:**

```bash
curl -X POST http://localhost:8000/api/cycling/settings \
  -H "Content-Type: application/json" \
  -d '{"min_work_time": 15}'
```

---

## Error Handling

All error responses follow this format:

```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

### Common Errors

| Error                  | Status | Description                               |
| ---------------------- | ------ | ----------------------------------------- |
| Parameter not found    | 404    | Requested parameter does not exist        |
| Invalid value type     | 400    | Value type does not match parameter type  |
| Value out of range     | 400    | Value exceeds min/max constraints         |
| Read-only parameter    | 400    | Attempted to write to read-only parameter |
| Controller unavailable | 503    | Serial connection to controller lost      |
| Internal error         | 500    | Unexpected server error                   |

---

## Rate Limiting

No rate limiting is implemented in version 1.0. Clients should avoid excessive polling:

- Recommended polling interval: 5-10 seconds for parameter updates
- Writes should be throttled to avoid overwhelming the controller

---

## CORS

CORS is enabled for all origins in development. Production deployments should configure appropriate CORS policies based on network security requirements.

---

## OpenAPI Schema

The API automatically generates OpenAPI (Swagger) documentation:

- **Interactive docs:** http://localhost:8000/docs
- **OpenAPI JSON:** http://localhost:8000/openapi.json

---

## Version History

### v0.1.0 (Initial Release)

- `GET /api/parameters` - Read all parameters
- `POST /api/parameters/{name}` - Write parameter value
- `GET /health` - Health check
- `GET /` - API information

### v0.2.0 (Anti-Cycling)

- `GET /api/cycling/metrics` - Compressor cycling metrics and state
- `GET /api/cycling/history` - Recent compressor cycle events
- `GET /api/cycling/settings` - Anti-cycling timer settings
- `POST /api/cycling/settings` - Write anti-cycling timer values
- Auto-set `minWorkTime` and `minBreakTime` at startup when disabled (zero)

### Future Versions

Planned features for future releases:

- Individual parameter GET endpoint (`GET /api/parameters/{name}`)
- Schedule management (`GET/POST /api/schedules`)
- WebSocket support for real-time updates
- Authentication and authorization
- Parameter history/logging
