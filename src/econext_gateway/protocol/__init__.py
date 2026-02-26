"""GM3 protocol implementation."""

from econext_gateway.protocol.codec import decode_value, encode_value
from econext_gateway.protocol.constants import (
    BEGIN_FRAME,
    END_FRAME,
    UNIT_NAMES,
    Command,
    DataType,
    Unit,
)
from econext_gateway.protocol.crc import calculate_crc16, verify_crc16
from econext_gateway.protocol.frames import Frame

# ProtocolHandler imported lazily to avoid circular import with serial.reader
# (serial.reader -> protocol.constants -> protocol.__init__ -> handler -> serial.reader)


def __getattr__(name: str):
    if name == "ProtocolHandler":
        from econext_gateway.protocol.handler import ProtocolHandler

        return ProtocolHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Frame",
    "ProtocolHandler",
    "calculate_crc16",
    "verify_crc16",
    "encode_value",
    "decode_value",
    "BEGIN_FRAME",
    "END_FRAME",
    "Command",
    "DataType",
    "Unit",
    "UNIT_NAMES",
]
