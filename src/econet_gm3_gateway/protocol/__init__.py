"""GM3 protocol implementation."""

from .codec import decode_value, encode_value
from .constants import (
    BEGIN_FRAME,
    END_FRAME,
    SRC_ADDRESS,
    Command,
    DataType,
    Unit,
    UNIT_NAMES,
)
from .crc import calculate_crc16, verify_crc16
from .frames import Frame

__all__ = [
    "Frame",
    "calculate_crc16",
    "verify_crc16",
    "encode_value",
    "decode_value",
    "BEGIN_FRAME",
    "END_FRAME",
    "SRC_ADDRESS",
    "Command",
    "DataType",
    "Unit",
    "UNIT_NAMES",
]
