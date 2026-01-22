"""Protocol constants for GM3 communication."""

from enum import IntEnum

# ============================================================================
# Frame Structure
# ============================================================================

BEGIN_FRAME = 0x68
END_FRAME = 0x16
FRAME_HEADER_LEN = 6
FRAME_MIN_LEN = 11  # BEGIN(1) + LEN(2) + DA(2) + SA(1) + RSV(1) + CMD(1) + CRC(2) + END(1)

# ============================================================================
# Addresses
# ============================================================================

SRC_ADDRESS = 131  # Gateway source address
DEST_ADDRESSES = [1, 2, 237]  # Standard controller addresses
PANEL_ADDRESS = 100  # Display panel address

# ============================================================================
# Command Codes
# ============================================================================


class Command(IntEnum):
    """Protocol command codes."""

    # Read operations
    GET_SETTINGS = 0x00
    GET_SETTINGS_RESPONSE = 0x80
    GET_PARAMS_STRUCT_WITH_RANGE = 0x02
    GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE = 0x82
    GET_PARAMS = 0x40
    GET_PARAMS_RESPONSE = 0xC0

    # Write operations
    MODIFY_PARAM = 0x29
    MODIFY_PARAM_RESPONSE = 0xA9


# ============================================================================
# Data Types
# ============================================================================


class DataType(IntEnum):
    """Parameter data type codes."""

    INT8 = 1
    INT16 = 2
    INT32 = 3
    UINT8 = 4
    UINT16 = 5
    UINT32 = 6
    FLOAT = 7
    DOUBLE = 9
    BOOL = 10
    STRING = 12
    INT64 = 13
    UINT64 = 14


# Type metadata
TYPE_NAMES = {
    DataType.INT8: "int8",
    DataType.INT16: "int16",
    DataType.INT32: "int32",
    DataType.UINT8: "uint8",
    DataType.UINT16: "uint16",
    DataType.UINT32: "uint32",
    DataType.FLOAT: "float",
    DataType.DOUBLE: "double",
    DataType.BOOL: "bool",
    DataType.STRING: "string",
    DataType.INT64: "int64",
    DataType.UINT64: "uint64",
}

TYPE_SIZES = {
    DataType.INT8: 1,
    DataType.INT16: 2,
    DataType.INT32: 4,
    DataType.UINT8: 1,
    DataType.UINT16: 2,
    DataType.UINT32: 4,
    DataType.FLOAT: 4,
    DataType.DOUBLE: 8,
    DataType.BOOL: 1,
    DataType.INT64: 8,
    DataType.UINT64: 8,
}

# ============================================================================
# Units
# ============================================================================


class Unit(IntEnum):
    """Parameter unit codes."""

    NONE = 0
    CELSIUS = 1
    SECONDS = 2
    MINUTES = 3
    HOURS = 4
    DAYS = 5
    PERCENT = 6
    KILOWATTS = 7
    KILOWATT_HOURS = 8


# Unit display names
UNIT_NAMES = {
    Unit.NONE: "",
    Unit.CELSIUS: "°C",
    Unit.SECONDS: "s",
    Unit.MINUTES: "min",
    Unit.HOURS: "h",
    Unit.DAYS: "d",
    Unit.PERCENT: "%",
    Unit.KILOWATTS: "kW",
    Unit.KILOWATT_HOURS: "kWh",
}

# ============================================================================
# Communication Settings
# ============================================================================

SERIAL_TIMEOUT = 0.2  # Serial read timeout (seconds)
RETRY_ATTEMPTS = 3  # Number of retry attempts for failed operations
REQUEST_TIMEOUT = 2.0  # Request timeout (seconds)
POLL_INTERVAL = 10.0  # Parameter polling interval (seconds)
