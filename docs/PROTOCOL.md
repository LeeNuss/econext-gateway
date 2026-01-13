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

| Offset | Size | Field | Value | Description |
|--------|------|-------|-------|-------------|
| 0 | 1 | BEGIN | 0x68 | Frame start marker |
| 1 | 1 | LEN_L | - | Length low byte (frame_len - 6) |
| 2 | 1 | LEN_H | - | Length high byte |
| 3 | 1 | DA_L | - | Destination address low byte |
| 4 | 1 | DA_H | - | Destination address high byte |
| 5 | 1 | SA | 131 | Source address |
| 6 | 1 | RSV | 0x00 | Reserved byte |
| 7 | 1 | CMD | - | Command/frame type |
| 8 | N | DATA | - | Payload (variable length) |
| -3 | 1 | CRC_H | - | CRC-16 high byte |
| -2 | 1 | CRC_L | - | CRC-16 low byte |
| -1 | 1 | END | 0x16 | Frame end marker |

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

**Communication Flow:**
1. Gateway sends request frame
2. Controller responds with data frame
3. Gateway processes response
4. Repeat

### Token Communication

Modern controllers support token-based communication:

1. Gateway requests token (CMD: 0x801 split across CMD and first data byte)
2. Controller grants token with response containing `[0x00, 0x08, 0x00, 0x00]`
3. Gateway performs operations while holding token
4. Gateway returns token when done

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

| Index | Name | Type | Unit | Description |
|-------|------|------|------|-------------|
| 0-50 | System | Various | - | UID, device name, version |
| 100-200 | Temperatures | Float | °C | Boiler, outdoor, return temps |
| 300-400 | Setpoints | Float/Int | °C | Target temperatures |
| 376-388 | Network | Various | - | WiFi, Ethernet status |

## Data Types

### Type Codes

| Code | Type | Size | Description |
|------|------|------|-------------|
| 1 | int8 | 1 | Signed byte (-128 to 127) |
| 2 | int16 | 2 | Signed short (little-endian) |
| 3 | int32 | 4 | Signed int (little-endian) |
| 4 | uint8 | 1 | Unsigned byte (0 to 255) |
| 5 | uint16 | 2 | Unsigned short (little-endian) |
| 6 | uint32 | 4 | Unsigned int (little-endian) |
| 7 | float | 4 | IEEE 754 float (little-endian) |
| 9 | double | 8 | IEEE 754 double (little-endian) |
| 10 | bool | 1 | Boolean (0 or 1) |
| 12 | string | N | Null-terminated UTF-8 string |
| 13 | int64 | 8 | Signed long long (little-endian) |
| 14 | uint64 | 8 | Unsigned long long (little-endian) |

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

| Code | Unit | Description |
|------|------|-------------|
| 0 | - | No unit / dimensionless |
| 1 | °C | Temperature (Celsius) |
| 2 | s | Seconds |
| 3 | min | Minutes |
| 4 | h | Hours |
| 5 | d | Days |
| 6 | % | Percentage |
| 7 | kW | Kilowatts (power) |
| 8 | kWh | Kilowatt-hours (energy) |

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

Recommended retry behavior:
- Timeout: 200-500ms per request
- Retries: 3 attempts before giving up
- Backoff: Exponential backoff on repeated failures

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
