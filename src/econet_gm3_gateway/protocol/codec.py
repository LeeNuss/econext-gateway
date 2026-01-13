"""Data type encoding and decoding for GM3 protocol."""

import struct
from typing import Any, Union

from .constants import DataType


def encode_value(value: Any, type_code: int) -> bytes:
    """
    Encode a Python value to bytes according to type code.

    All numeric types use little-endian byte order.

    Args:
        value: Python value to encode
        type_code: Protocol type code

    Returns:
        Encoded bytes

    Raises:
        ValueError: If type code is unsupported or value is invalid

    Example:
        >>> encode_value(45, DataType.INT16)
        b'-\\x00'
        >>> encode_value(True, DataType.BOOL)
        b'\\x01'
    """
    if type_code == DataType.INT8:
        return struct.pack("<b", int(value))

    elif type_code == DataType.INT16:
        return struct.pack("<h", int(value))

    elif type_code == DataType.INT32:
        return struct.pack("<i", int(value))

    elif type_code == DataType.INT64:
        return struct.pack("<q", int(value))

    elif type_code == DataType.UINT8:
        return struct.pack("<B", int(value))

    elif type_code == DataType.UINT16:
        return struct.pack("<H", int(value))

    elif type_code == DataType.UINT32:
        return struct.pack("<I", int(value))

    elif type_code == DataType.UINT64:
        return struct.pack("<Q", int(value))

    elif type_code == DataType.FLOAT:
        return struct.pack("<f", float(value))

    elif type_code == DataType.DOUBLE:
        return struct.pack("<d", float(value))

    elif type_code == DataType.BOOL:
        bool_val = 1 if value else 0
        return struct.pack("<B", bool_val)

    elif type_code == DataType.STRING:
        if isinstance(value, str):
            encoded = value.encode("utf-8")
        else:
            encoded = bytes(value)
        return encoded + b"\x00"  # Null terminator

    else:
        raise ValueError(f"Unsupported type code: {type_code}")


def decode_value(data: bytes, type_code: int) -> Union[int, float, bool, str]:
    """
    Decode bytes to Python value according to type code.

    All numeric types use little-endian byte order.
    Float values are rounded to 2 decimal places.

    Args:
        data: Bytes to decode
        type_code: Protocol type code

    Returns:
        Decoded Python value

    Raises:
        ValueError: If type code is unsupported
        struct.error: If data length doesn't match type

    Example:
        >>> decode_value(b'-\\x00', DataType.INT16)
        45
        >>> decode_value(b'\\x01', DataType.BOOL)
        True
    """
    if type_code == DataType.INT8:
        if len(data) < 1:
            raise ValueError("Insufficient data for int8")
        return struct.unpack("<b", data[0:1])[0]

    elif type_code == DataType.INT16:
        if len(data) < 2:
            raise ValueError("Insufficient data for int16")
        return struct.unpack("<h", data[0:2])[0]

    elif type_code == DataType.INT32:
        if len(data) < 4:
            raise ValueError("Insufficient data for int32")
        return struct.unpack("<i", data[0:4])[0]

    elif type_code == DataType.INT64:
        if len(data) < 8:
            raise ValueError("Insufficient data for int64")
        return struct.unpack("<q", data[0:8])[0]

    elif type_code == DataType.UINT8:
        if len(data) < 1:
            raise ValueError("Insufficient data for uint8")
        return struct.unpack("<B", data[0:1])[0]

    elif type_code == DataType.UINT16:
        if len(data) < 2:
            raise ValueError("Insufficient data for uint16")
        return struct.unpack("<H", data[0:2])[0]

    elif type_code == DataType.UINT32:
        if len(data) < 4:
            raise ValueError("Insufficient data for uint32")
        return struct.unpack("<I", data[0:4])[0]

    elif type_code == DataType.UINT64:
        if len(data) < 8:
            raise ValueError("Insufficient data for uint64")
        return struct.unpack("<Q", data[0:8])[0]

    elif type_code == DataType.FLOAT:
        if len(data) < 4:
            raise ValueError("Insufficient data for float")
        value = struct.unpack("<f", data[0:4])[0]
        return round(value, 2)

    elif type_code == DataType.DOUBLE:
        if len(data) < 8:
            raise ValueError("Insufficient data for double")
        value = struct.unpack("<d", data[0:8])[0]
        return round(value, 2)

    elif type_code == DataType.BOOL:
        if len(data) < 1:
            raise ValueError("Insufficient data for bool")
        return struct.unpack("<B", data[0:1])[0] != 0

    elif type_code == DataType.STRING:
        # Find null terminator
        try:
            null_pos = data.index(b"\x00")
            string_data = data[:null_pos]
        except ValueError:
            # No null terminator, use all data
            string_data = data

        return string_data.decode("utf-8", errors="replace")

    else:
        raise ValueError(f"Unsupported type code: {type_code}")
