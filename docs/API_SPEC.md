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

### Future Versions

Planned features for future releases:

- Individual parameter GET endpoint (`GET /api/parameters/{name}`)
- Alarm retrieval (`GET /api/alarms`)
- Schedule management (`GET/POST /api/schedules`)
- WebSocket support for real-time updates
- Authentication and authorization
- Parameter history/logging
