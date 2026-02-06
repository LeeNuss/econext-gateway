# Development Plan

Implementation roadmap for the econet GM3 Gateway project.

## Overview

This document outlines the step-by-step implementation plan, starting with core protocol functionality and building up to a complete API server.

## Phase 1: Foundation (No Hardware Required)

### 1.1 Core Configuration Module

**Files:** `src/core/config.py`

**Tasks:**
- Environment variable loading (SERIAL_PORT, SERIAL_BAUD, API_HOST, API_PORT, LOG_LEVEL)
- Configuration validation
- Logging setup
- Settings class with defaults

**Dependencies:** None

**Testable:** Yes (unit tests)

---

### 1.2 Protocol Layer

**Files:**
- `src/protocol/constants.py` - Protocol constants
- `src/protocol/crc.py` - CRC-16 calculation
- `src/protocol/frames.py` - Frame construction and parsing
- `src/protocol/codec.py` - Data type encoding/decoding

**Tasks:**

**1.2.1 Constants (`constants.py`)**
- Frame markers (BEGIN_FRAME=0x68, END_FRAME=0x16)
- Command codes (GET_PARAMS=0x40, MODIFY_PARAM=0x29, etc.)
- Addresses (SRC_ADDRESS=131, standard destination addresses)
- Data type codes (1=int8, 2=int16, 7=float, etc.)

**1.2.2 CRC Calculation (`crc.py`)**
- Implement CRC-16 algorithm per protocol spec
- Unit tests with known good values

**1.2.3 Frame Handling (`frames.py`)**
- `create_frame(destination, command, data)` - Build binary frame
- `parse_frame(raw_data)` - Parse received frame
- `validate_frame(frame)` - Check CRC, markers, length
- Unit tests for all frame types

**1.2.4 Data Encoding/Decoding (`codec.py`)**
- Encode: int8, int16, int32, uint8, uint16, uint32, float, double, bool, string
- Decode: same types
- Handle little-endian byte order
- Unit tests for all data types

**Dependencies:** None (pure Python + struct)

**Testable:** Yes (extensive unit tests)

---

### 1.3 Parameter Models

**Files:** `src/core/models.py`

**Tasks:**
- Pydantic model for Parameter (index, name, value, type, unit, writable, min/max)
- Pydantic model for ParameterCollection
- Request/Response models for API
- Type definitions and enums

**Dependencies:** Pydantic

**Testable:** Yes (model validation tests)

---

## Phase 2: Communication Layer

### 2.1 Serial Communication

**Files:**
- `src/serial/connection.py` - Serial port management
- `src/serial/reader.py` - Async frame reading
- `src/serial/writer.py` - Async frame writing

**Tasks:**

**2.1.1 Connection Management (`connection.py`)**
- Open/close serial port with direct pyserial + asyncio.run_in_executor()
- Two-stage blocking read: read(1) then read(in_waiting) for fast responses
- Connection state tracking
- Automatic reconnection on disconnect
- Configuration (port, baud, timeout)

**2.1.2 Frame Reader (`reader.py`)**
- Async frame reading loop
- Buffer management
- Frame boundary detection (BEGIN/END markers)
- CRC validation
- Error recovery

**2.1.3 Frame Writer (`writer.py`)**
- Async frame writing
- Write queue management
- Retry logic (3 attempts)
- Timeout handling

**Dependencies:** Phase 1.2 (protocol), pyserial

**Testable:** Yes (mock serial port)

---

### 2.2 Parameter Cache

**Files:** `src/core/cache.py`

**Tasks:**
- In-memory parameter storage (dict)
- Thread-safe access (asyncio locks)
- TTL/expiry logic
- Parameter update notifications
- Cache invalidation

**Dependencies:** Phase 1.3 (models)

**Testable:** Yes (unit tests)

---

### 2.3 Protocol Handler

**Files:** `src/protocol/handler.py`

**Tasks:**
- Request/response correlation
- Parameter read operations (GET_PARAMS, GET_PARAMS_STRUCT_WITH_RANGE)
- Parameter write operations (MODIFY_PARAM)
- Controller identification (GET_SETTINGS)
- Integrate reader/writer/cache

**Dependencies:** Phase 2.1, 2.2

**Testable:** Yes (mock serial)

---

## Phase 3: API Implementation

### 3.1 API Routes

**Files:**
- `src/api/routes.py` - Endpoint implementations
- `src/api/models.py` - Request/Response schemas
- `src/api/dependencies.py` - FastAPI dependencies

**Tasks:**

**3.1.1 Endpoints**
- `GET /` - Root info
- `GET /health` - Health check
- `GET /api/parameters` - Read all parameters
- `POST /api/parameters/{name}` - Write parameter

**3.1.2 Request/Response Models**
- ParametersResponse (timestamp, parameters dict)
- ParameterSetRequest (value)
- ParameterSetResponse (success, old_value, new_value)
- ErrorResponse (success=false, error message)

**3.1.3 Error Handling**
- 404 - Parameter not found
- 400 - Invalid value (type, range)
- 503 - Controller unavailable
- 500 - Internal error

**Dependencies:** Phase 1.3 (models), Phase 2.3 (handler)

**Testable:** Yes (FastAPI TestClient)

---

### 3.2 Main Application

**Files:** `src/econet_gm3_gateway/main.py`

**Tasks:**
- FastAPI app initialization
- Startup events (open serial, initialize protocol)
- Shutdown events (close serial, cleanup)
- Background task for cyclic parameter reading
- Logging configuration
- CORS setup
- Route registration

**Dependencies:** All previous phases

**Testable:** Yes (integration tests)

---

## Phase 4: Testing & Validation

### 4.1 Unit Tests

**Files:** `tests/test_*.py`

**Tasks:**
- Protocol: CRC, frame parsing, encoding/decoding
- Models: Pydantic validation
- Cache: Operations, thread safety
- Configuration: Loading, validation

**Coverage Target:** >80%

---

### 4.2 Integration Tests

**Files:** `tests/integration/test_*.py`

**Tasks:**
- Mock serial communication end-to-end
- API endpoint testing with mock backend
- Error scenarios
- State management

---

### 4.3 Hardware Testing

**Requirements:** Physical GM3 controller

**Tasks:**
- Connect to real controller
- Read parameters successfully
- Write parameters successfully
- Handle disconnects/errors
- Long-running stability test

---

## Phase 5: Deployment & Documentation

### 5.1 Docker

**Files:** `Dockerfile` (already exists)

**Tasks:**
- Build and test container
- Serial device passthrough
- Environment configuration
- Health checks

---

### 5.2 Documentation

**Tasks:**
- Update README with installation instructions
- Add configuration guide
- Troubleshooting section
- Example Home Assistant integration

## Current Status

**Total: 241 tests passing** (as of 2026-02-06)

- [x] Project setup and structure
- [x] Documentation (API, Protocol, Parameters)
- [x] Phase 1.1 - Configuration (13 tests)
- [x] Phase 1.2 - Protocol Layer: frames (20), codec (44), crc (8), captured data (12)
- [x] Phase 1.3 - Models (27 tests)
- [x] Phase 2.1 - Serial Communication (23 tests)
- [x] Phase 2.2 - Parameter Cache (22 tests)
- [x] Phase 2.3 - Protocol Handler (58 tests)
- [x] Phase 3 - API Implementation (14 tests)
- [x] Phase 4.1 - Unit tests (all passing)
- [x] Phase 4.3 - Hardware testing (1870 params discovered in 6.6s, 2026-02-06)
- [ ] Phase 4.2 - Integration tests (mock serial end-to-end)
- [ ] Phase 5 - Deployment (systemd service, udev rules)
