# GM3 Protocol Specification

Serial communication protocol for GM3-compatible heat pump controllers (ecotronic series).

## Table of Contents

- [Overview](#overview)
- [Physical Layer](#physical-layer)
- [Frame Structure](#frame-structure)
- [Communication Model](#communication-model)
- [Frame Types](#frame-types)
- [Parameter System](#parameter-system)
- [Data Types](#data-types)
- [Alarms](#alarms)

## Overview

The GM3 protocol is a binary serial communication protocol used by ecotronic heat pump controllers. The gateway initiates all communication, polling the controller for data and sending commands.

**Key Features:**
- Frame-based binary protocol with CRC-16 validation
- Dual address space: controller (0-9999) and panel (10000+)
- Real-time parameter monitoring and control
- Alarm reporting
- Token-based communication support

**Default Settings:**
- **Baud Rate:** 115200 (some devices use 38400)
- **Data Bits:** 8
- **Stop Bits:** 1
- **Parity:** None
- **Port:** Typically `/dev/ttyUSB0` on Linux

## Physical Layer

### Connection
- **Interface:** RS-232 or RS-485 serial
- **Protocol:** Asynchronous serial (UART)

### Addressing
- **Controller Address:** 1, 2, or 237 (standard addresses)
- **Panel Address:** 100 (display panel)
- **Source Address:** 131 (gateway device)

## Frame Structure

### Standard Frame Format

All communication uses binary frames with the following structure:

```
[BEGIN][LEN_L][LEN_H][DA_L][DA_H][SA][RSV][CMD][DATA...][CRC_H][CRC_L][END]
```

**Field Details:**

| Offset | Size | Field | Value | Description                     |
| ------ | ---- | ----- | ----- | ------------------------------- |
| 0      | 1    | BEGIN | 0x68  | Frame start marker              |
| 1      | 1    | LEN_L | -     | Length low byte (frame_len - 6) |
| 2      | 1    | LEN_H | -     | Length high byte                |
| 3      | 1    | DA_L  | -     | Destination address low byte    |
| 4      | 1    | DA_H  | -     | Destination address high byte   |
| 5      | 1    | SA    | 131   | Source address                  |
| 6      | 1    | RSV   | 0x00  | Reserved byte                   |
| 7      | 1    | CMD   | -     | Command/frame type              |
| 8      | N    | DATA  | -     | Payload (variable length)       |
| -3     | 1    | CRC_H | -     | CRC-16 high byte                |
| -2     | 1    | CRC_L | -     | CRC-16 low byte                 |
| -1     | 1    | END   | 0x16  | Frame end marker                |

**Length Calculation:**
```
frame_length = total_bytes - 6  # Exclude header (6 bytes)
LEN_L = frame_length & 0xFF
LEN_H = (frame_length >> 8) & 0xFF
```

### CRC-16 Calculation

The CRC is calculated over bytes from offset 1 to -3 (inclusive):

```python
def calculate_crc16(data):
    crc = 0
    for byte in data:
        s = byte ^ (crc >> 8)
        t = s ^ (s >> 4)
        crc = (crc << 8) ^ t ^ (t << 5) ^ (t << 12)
        crc = crc & 0xFFFF
    return crc
```

**Usage:**
```python
# Calculate CRC for frame bytes 1 through -3
crc_value = calculate_crc16(frame[1:-3])
frame[-3] = (crc_value >> 8) & 0xFF  # CRC high byte
frame[-2] = crc_value & 0xFF          # CRC low byte
```

### Frame Validation

To validate a received frame:

1. Check minimum length (10 bytes)
2. Verify BEGIN marker (0x68)
3. Verify END marker (0x16)
4. Validate length field matches actual frame length
5. Calculate and verify CRC-16

## Communication Model

### Gateway-Controller Architecture

The gateway initiates all communication, with the controller responding to requests.

**Startup Sequence:**
1. Connect to serial port (115200 baud)
2. Wait for token from panel (respond to IDENTIFY probes; fallback to bus-idle after 1.5s)
3. If token received: send GET_SETTINGS (0x00) to broadcast (0xFFFF) to initialize
4. Discover parameters: GET_PARAMS_STRUCT_WITH_RANGE (0x02) in batches of 100
5. Discovery completes when controller returns empty response or 3 consecutive batch failures
6. Return token to panel

**Ongoing Polling (every 10s):**
1. Wait for token from panel (up to 15s, fallback to bus-idle)
2. Send GET_PARAMS (0x40) in batches of 100 params
3. Update parameter cache with new values
4. Return token to panel

**Observed Performance:**
- With token: Discovery completes in ~5s, polling in ~2s (exclusive bus access)
- Without token: Discovery takes ~60-90s, polling ~15-20s (shared bus, retries needed)

### Token Communication (Bus Arbitration)

On multi-master RS-485 buses, the master panel (device 100) coordinates bus access
using a token-passing protocol. This prevents frame collisions when multiple devices
need to communicate with the same controller.

#### Observed Bus Devices

| Address | Role           | Observed Behavior                                                              |
| ------- | -------------- | ------------------------------------------------------------------------------ |
| 1       | Controller     | Responds to GET_PARAMS, GET_PARAMS_STRUCT, MODIFY_PARAM                        |
| 100     | Master Panel   | Sends IDENTIFY probes, SERVICE frames, MODIFY_PARAM to controller              |
| 131     | Gateway        | Our device - responds to IDENTIFY, sends param requests                        |
| 165     | Unknown device | Panel queries it with GET_PARAMS (0x40), responds with 0xC0/0x7F               |
| 255     | Polling module | Continuously sends GET_PARAMS to controller (responses go to broadcast 0xFFFF) |

#### Device Identification (IDENTIFY)

The master panel periodically probes devices on the bus using IDENTIFY requests.
Devices must respond to register their presence.

**IDENTIFY Request (panel -> device):**
- Command: `0x09` (IDENTIFY_CMD)
- Data: empty
- The panel sends this to each known device address in sequence

**IDENTIFY Response (device -> panel):**
- Command: `0x89` (IDENTIFY_ANS_CMD)
- Data: `"PLUM\x00EcoNET\x00\x00\x00\x00\x00"` (16 bytes)
  - Null-terminated device manufacturer string ("PLUM")
  - Null-terminated device type string ("EcoNET")
  - 4 zero bytes (padding/reserved)

#### Service Frames

Service frames use CMD byte `0x68` (same value as BEGIN_FRAME marker). The function
code is encoded as a little-endian uint16 in the first 2 bytes of the data payload.

**Service Frame Format (CMD: 0x68):**
```
[0x68][LEN_L][LEN_H][DA_L][DA_H][SA][RSV][0x68][FUNC_L][FUNC_H][...][CRC_H][CRC_L][0x16]
```

**Observed Service Functions:**

| Function | Direction          | Destination          | Description                                        |
| -------- | ------------------ | -------------------- | -------------------------------------------------- |
| 0x0801   | Panel -> Device    | Device address (131) | Token grant                                        |
| 0x0023   | Panel -> Broadcast | 0xFFFF               | Clock/timer sync (20 bytes, includes date/time)    |
| 0x2001   | Panel -> Broadcast | 0xFFFF               | Status broadcast (16 bytes, includes temperatures) |

**Token Grant (panel -> gateway):**
- Source: 100 (master panel)
- Destination: 131 (gateway)
- Command: `0x68` (SERVICE_CMD)
- Data: `[0x01, 0x08, ...]` (function 0x0801 LE, followed by additional bytes)

**Token Return (gateway -> panel):**
- Destination: 100 (master panel)
- Command: `0x68` (SERVICE_CMD)
- Data: `[0x00, 0x08, 0x00, 0x00]` (function 0x0800 LE + 2 zero bytes)

#### Observed Bus Cycle

The master panel operates on a ~10-second cycle with the following phases:

```
Phase 1: Device Identification (~0.5s)
  Panel sends IDENTIFY (0x09) to addresses: 32, 131, 165, 168
  Devices that exist respond with IDENTIFY_ANS (0x89)

Phase 2: Polling Module Activity (~3-5s)
  Device 255 sends ~14 GET_PARAMS (0x40) requests to controller
  Controller responds to broadcast (dest=0xFFFF) with 0xC0 responses
  Response sizes: 116-466 bytes each

Phase 3: Panel Operations (~1s)
  Panel queries device 165 (GET_PARAMS)
  Panel writes params to controller (MODIFY_PARAM 0x29, 4 writes)
  Controller ACKs each write (0xA9)

Phase 4: Service Broadcasts
  Panel sends SERVICE 0x0023 (clock sync, dest=0xFFFF)
  Panel sends SERVICE 0x2001 (status, dest=0xFFFF)

Phase 5: Token Grant
  Panel sends SERVICE 0x0801 to gateway (dest=131)
  Gateway holds token for its operations
  Gateway returns token when done
```

#### Token Protocol Flow

```
Master Panel             Gateway                  Controller
     |                      |                          |
     | IDENTIFY (0x09)      |                          |
     |--------------------->|                          |
     |  IDENTIFY_ANS (0x89) |                          |
     |<---------------------|                          |
     |                      |                          |
     | ... panel cycle ...  |                          |
     |                      |                          |
     | SERVICE 0x0801       |                          |
     | (Token Grant)        |                          |
     |--------------------->|                          |
     |                      |  GET_PARAMS (0x40)       |
     |                      |------------------------->|
     |                      |  GET_PARAMS_RESP (0xC0)  |
     |                      |<-------------------------|
     |                      |  ... more requests ...   |
     |                      |                          |
     | SERVICE 0x0800       |                          |
     | (Token Return)       |                          |
     |<---------------------|                          |
     |                      |                          |
```

#### Timing and Behavior

- **Bus turnaround delay:** 20ms sleep before every write (RS-485 half-duplex requirement)
- **Response timeout:** 0.2s per read when holding token (exclusive bus access)
- **Token wait timeout:** 15s max wait for token; falls back to bus-idle detection
- **Bus-idle fallback:** 3 consecutive 0.5s read timeouts (1.5s silence) = bus idle
- **Retry strategy without token:** Send request, break on 0.2s silence, retry up to 5 times
- **Panel cycle time:** ~10 seconds between token grants
- **Token hold time:** Gateway holds token for entire operation (all batches)

#### Without Token (Bus-Idle Fallback)

When the token is not available (panel not present, or timeout exceeded), the gateway
falls back to opportunistic communication:

1. Wait for 1.5s of bus silence (no frames)
2. Send request to controller
3. Read for 0.2s - if bus goes quiet, response likely isn't coming
4. Retry up to 5 times per batch
5. Controller responds to ~40% of requests on first try; most succeed within 3-5 retries
6. Average 2s per successful batch without token (vs immediate with token)

#### Critical Implementation Notes

- **Do NOT clear the reader buffer after IDENTIFY response.** The token frame
  often arrives in the same serial read chunk as the IDENTIFY request. Clearing
  the buffer discards the token.
- **The SERVICE CMD byte (0x68) is the same as BEGIN_FRAME.** The frame parser
  must handle this correctly by validating frame length and END marker, not just
  scanning for 0x68 bytes.
- **Device 255 traffic creates noise.** Its GET_PARAMS responses go to broadcast
  (0xFFFF) and pass through destination filters. The response validator (checking
  start_index) is essential to distinguish our responses from device 255's.

### Request-Response Cycle

```
Gateway                   Controller
     |                          |
     |  Request Frame           |
     |------------------------->|
     |                          |
     |       Response Frame     |
     |<-------------------------|
     |                          |
```

Typical polling interval: 5-10 seconds

## Frame Types

### Read Operations

#### GET_PARAMS_STRUCT_WITH_RANGE (0x02)

Request parameter structure definitions including min/max values.

**Request:**
```
CMD: 0x02
DATA: [first_index_low][first_index_high][count_low][count_high]
```

**Response:**
```
CMD: 0x82
DATA: For each parameter:
  [index_low][index_high]
  [type]
  [unit]
  [multiplier_offset_bytes]
  [min_max_bytes]
  [name_string...][0x00]
```

**Example:** Request params 0-99
```
Request:  68 04 00 01 00 83 00 02 00 00 64 00 [CRC] 16
Response: 68 XX XX 01 00 83 00 82 [param_data...] [CRC] 16
```

#### GET_PARAMS (0x40)

Request current values for a range of parameters.

**Request:**
```
CMD: 0x40
DATA: [first_index_low][first_index_high][count_low][count_high]
```

**Response:**
```
CMD: 0xC0
DATA: For each parameter:
  [index_low][index_high][value_bytes...]
```

Value byte count depends on parameter type.

#### GET_SETTINGS (0x00)

Request controller identification.

**Request:**
```
CMD: 0x00
DATA: (empty or [addr_low][addr_high] for specific device)
```

**Response:**
```
CMD: 0x80
DATA:
  [uid_0][uid_1][uid_2][uid_3]           (4 bytes, little-endian)
  [device_name...][0x00]                  (null-terminated string)
  [software_version...][0x00]             (null-terminated string)
  [product_id_low][product_id_high]       (2 bytes)
  [device_type]                           (1 byte)
```

### Write Operations

#### MODIFY_PARAM (0x29)

Modify a parameter value.

**Request:**
```
CMD: 0x29
DATA: [param_index_low][param_index_high][encoded_value...]
```

Value encoding depends on parameter type (see Data Types section).

**Response:**
```
CMD: 0xA9
DATA: [result_code]
```

**Result Codes:**
- 0x00: Success
- Other: Error (specific error codes vary)

## Parameter System

### Parameter Addressing

Parameters are identified by a 16-bit index:

- **0-999:** Controller identification and system parameters
- **1000-9999:** User and service parameters (temperatures, setpoints, etc.)
- **10000-19999:** Panel/display parameters

### Parameter Structure

Each parameter has these properties:

- **Index** (uint16): Unique parameter identifier
- **Type** (uint8): Data type code (see Data Types)
- **Unit** (uint8): Unit identifier (0=none, 1=°C, 2=seconds, 6=%, etc.)
- **Value**: Current parameter value
- **Min/Max**: Valid range (for editable parameters)
- **Multiplier**: Display scaling (e.g., 0.1 for one decimal place)
- **Offset**: Display offset
- **Name**: Human-readable name (string)
- **Editable**: Boolean flag

### Common Parameters

| Index   | Name         | Type      | Unit | Description                   |
| ------- | ------------ | --------- | ---- | ----------------------------- |
| 0-50    | System       | Various   | -    | UID, device name, version     |
| 100-200 | Temperatures | Float     | °C   | Boiler, outdoor, return temps |
| 300-400 | Setpoints    | Float/Int | °C   | Target temperatures           |
| 376-388 | Network      | Various   | -    | WiFi, Ethernet status         |

## Data Types

### Type Codes

| Code | Type   | Size | Description                        |
| ---- | ------ | ---- | ---------------------------------- |
| 1    | int8   | 1    | Signed byte (-128 to 127)          |
| 2    | int16  | 2    | Signed short (little-endian)       |
| 3    | int32  | 4    | Signed int (little-endian)         |
| 4    | uint8  | 1    | Unsigned byte (0 to 255)           |
| 5    | uint16 | 2    | Unsigned short (little-endian)     |
| 6    | uint32 | 4    | Unsigned int (little-endian)       |
| 7    | float  | 4    | IEEE 754 float (little-endian)     |
| 9    | double | 8    | IEEE 754 double (little-endian)    |
| 10   | bool   | 1    | Boolean (0 or 1)                   |
| 12   | string | N    | Null-terminated UTF-8 string       |
| 13   | int64  | 8    | Signed long long (little-endian)   |
| 14   | uint64 | 8    | Unsigned long long (little-endian) |

### Encoding Examples

**Integer (int16):**
```python
value = 45
encoded = struct.pack('<h', value)  # [0x2D, 0x00]
```

**Float:**
```python
value = 22.5
encoded = struct.pack('<f', value)  # 4 bytes IEEE 754
```

**String:**
```python
value = "ecoTRONIC100"
encoded = value.encode('utf-8') + b'\x00'  # null-terminated
```

**Boolean:**
```python
value = True
encoded = struct.pack('<B', 1 if value else 0)  # [0x01] or [0x00]
```

### Decoding Examples

**Integer (int16):**
```python
value = struct.unpack('<h', data[0:2])[0]
```

**Float:**
```python
value = struct.unpack('<f', data[0:4])[0]
value = round(value, 2)  # Round to 2 decimal places
```

**String:**
```python
value = data[:-1].decode('utf-8')  # Remove null terminator
```

**Boolean:**
```python
value = struct.unpack('<B', data[0:1])[0] != 0
```

### Unit Codes

Common unit identifiers:

| Code | Unit | Description             |
| ---- | ---- | ----------------------- |
| 0    | -    | No unit / dimensionless |
| 1    | °C   | Temperature (Celsius)   |
| 2    | s    | Seconds                 |
| 3    | min  | Minutes                 |
| 4    | h    | Hours                   |
| 5    | d    | Days                    |
| 6    | %    | Percentage              |
| 7    | kW   | Kilowatts (power)       |
| 8    | kWh  | Kilowatt-hours (energy) |

## Alarms

### Alarm Structure

Alarms are read sequentially by index. Each alarm contains:

**Response Data:**
```
[alarm_code]                    (1 byte)
[from_year_low][from_year_high] (2 bytes, little-endian)
[from_month]                    (1 byte, 1-12)
[from_day]                      (1 byte, 1-31)
[from_hour]                     (1 byte, 0-23)
[from_minute]                   (1 byte, 0-59)
[from_second]                   (1 byte, 0-59)
[to_year_low][to_year_high]     (2 bytes)
[to_month]                      (1 byte)
[to_day]                        (1 byte)
[to_hour]                       (1 byte)
[to_minute]                     (1 byte)
[to_second]                     (1 byte)
```

**Null Alarm (no alarm at index):**
All date bytes set to 0xFF indicates no alarm exists at this index.

**Active Alarm:**
`to_date` bytes all 0xFF indicates alarm is still active (not yet resolved).

### Alarm Reading Strategy

1. Request alarm at index 0
2. If valid alarm received, store and increment index
3. Request next alarm
4. Continue until null alarm received
5. After initial read, poll periodically for new alarms

## Error Handling

### Common Errors

**Frame Errors:**
- CRC mismatch: Discard frame, retry
- Invalid length: Discard frame, resync
- Timeout: No response within expected time

**Protocol Errors:**
- 0x7E: Data size error
- 0x7F: Generic error / no data available

### Retry Strategy

**With token (exclusive bus access):**
- Per-read timeout: 200ms (bus should be quiet except for our response)
- Break immediately on bus silence (response isn't coming)
- Retries: 5 attempts per batch
- No delay between retries

**Without token (shared bus):**
- Per-read timeout: 200ms
- Break on bus silence, retry immediately
- Retries: 5 attempts per batch
- 500ms delay between retries (avoid flooding the bus)
- Expect ~40% success rate per attempt; most batches succeed within 3-5 tries

### Connection Recovery

On serial disconnect:
1. Close port
2. Wait 1-2 seconds
3. Reopen port
4. Re-initialize communication (GET_SETTINGS)
5. Resume normal operation

## Implementation Notes

### Frame Construction

```python
def create_frame(destination, command, data):
    frame = bytearray()
    frame.append(0x68)                    # BEGIN
    frame.extend([0, 0])                  # LEN (filled later)
    frame.extend(struct.pack('<H', destination))  # DA
    frame.append(131)                     # SA (source)
    frame.append(0x00)                    # Reserved
    frame.append(command)                 # CMD
    if data:
        frame.extend(data)                # DATA

    # Calculate length
    length = len(frame) - 6
    frame[1] = length & 0xFF
    frame[2] = (length >> 8) & 0xFF

    # Calculate CRC
    crc = calculate_crc16(frame[1:-2])  # Will add CRC position next
    frame.extend([0, 0])                  # Placeholder for CRC
    frame[-3] = (crc >> 8) & 0xFF
    frame[-2] = crc & 0xFF

    frame.append(0x16)                    # END
    return bytes(frame)
```

### Frame Parsing

```python
def parse_frame(raw_data):
    if len(raw_data) < 10:
        return None

    if raw_data[0] != 0x68 or raw_data[-1] != 0x16:
        return None

    # Validate CRC
    expected_crc = struct.unpack('<H', raw_data[-3:-1])[0]
    calculated_crc = calculate_crc16(raw_data[1:-3])

    if expected_crc != calculated_crc:
        return None

    destination = struct.unpack('<H', raw_data[3:5])[0]
    source = raw_data[5]
    command = raw_data[7]
    data = raw_data[8:-3]

    return {
        'destination': destination,
        'source': source,
        'command': command,
        'data': data
    }
```

## Example Communication Sequences

### Read Parameter Value

```
Request:  68 04 00 01 00 83 00 40 64 00 01 00 [CRC] 16
          Read param 100 (1 parameter)

Response: 68 06 00 83 00 01 00 C0 64 00 41 01 [CRC] 16
          Param 100 = value [0x41, 0x01] (321 as int16)
```

### Write Parameter Value

```
Request:  68 06 00 01 00 83 00 29 64 00 2D 00 [CRC] 16
          Set param 100 = 45 (0x002D)

Response: 68 03 00 83 00 01 00 A9 00 [CRC] 16
          Success (result code 0x00)
```

### Identify Controller

```
Request:  68 02 00 01 00 83 00 00 [CRC] 16
          GET_SETTINGS

Response: 68 XX 00 83 00 01 00 80
          [UID 4 bytes]
          "ecoTRONIC100" 00
          "1.2.3" 00
          [Product ID 2 bytes]
          [Type 1 byte]
          [CRC] 16
```

## Reference

This specification was derived through reverse engineering of the GM3 protocol for interoperability purposes.
