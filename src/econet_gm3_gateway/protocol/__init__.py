"""GM3 protocol implementation."""

from econet_gm3_gateway.protocol.codec import decode_value, encode_value
from econet_gm3_gateway.protocol.constants import (
    BEGIN_FRAME,
    END_FRAME,
    SRC_ADDRESS,
    UNIT_NAMES,
    Command,
    DataType,
    Unit,
)
from econet_gm3_gateway.protocol.crc import calculate_crc16, verify_crc16
from econet_gm3_gateway.protocol.frames import Frame

# ProtocolHandler imported lazily to avoid circular import with serial.reader
# (serial.reader -> protocol.constants -> protocol.__init__ -> handler -> serial.reader)


def __getattr__(name: str):
    if name == "ProtocolHandler":
        from econet_gm3_gateway.protocol.handler import ProtocolHandler

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
    "SRC_ADDRESS",
    "Command",
    "DataType",
    "Unit",
    "UNIT_NAMES",
]
