"""Frame construction and parsing for GM3 protocol."""

import struct
from typing import Optional

from .constants import BEGIN_FRAME, END_FRAME, FRAME_MIN_LEN, SRC_ADDRESS
from .crc import calculate_crc16


class Frame:
    """
    Represents a GM3 protocol frame.

    Attributes:
        destination: Destination address (16-bit)
        source: Source address (8-bit)
        reserved: Reserved byte (usually 0x00 or 0xFF)
        command: Command byte
        data: Payload data
    """

    def __init__(self, destination: int, command: int, data: bytes = b"", reserved: int = 0x00):
        """
        Initialize a frame.

        Args:
            destination: Destination address (0-65535)
            command: Command byte (0-255)
            data: Optional payload data
            reserved: Reserved byte (default 0x00)
        """
        self.destination = destination
        self.source = SRC_ADDRESS
        self.reserved = reserved
        self.command = command
        self.data = data

    def to_bytes(self) -> bytes:
        """
        Convert frame to bytes for transmission.

        Frame structure:
        [BEGIN][LEN_L][LEN_H][DA_L][DA_H][SA][RSV][CMD][DATA...][CRC_H][CRC_L][END]

        Returns:
            Complete frame as bytes

        Example:
            >>> frame = Frame(destination=1, command=0x40, data=b'\\x00\\x00\\x01\\x00')
            >>> frame_bytes = frame.to_bytes()
            >>> frame_bytes[0] == 0x68  # BEGIN_FRAME
            True
        """
        # Build frame without CRC and END
        frame = bytearray()
        frame.append(BEGIN_FRAME)

        # Length (will be filled after we know data length)
        frame.extend([0, 0])  # LEN_L, LEN_H

        # Destination address (little-endian)
        frame.extend(struct.pack("<H", self.destination))

        # Source address
        frame.append(self.source)

        # Reserved
        frame.append(self.reserved)

        # Command
        frame.append(self.command)

        # Data payload
        if self.data:
            frame.extend(self.data)

        # Calculate and update length (total length - 6 header bytes)
        # Length represents: RSV + CMD + DATA + CRC + END
        # Current frame has: BEGIN + LEN + DEST + SRC + RSV + CMD + DATA
        # Will add: CRC (2 bytes) + END (1 byte) = 3 bytes
        length = len(frame) - 6 + 3  # -6 for header, +3 for CRC and END to be added
        frame[1] = length & 0xFF
        frame[2] = (length >> 8) & 0xFF

        # Calculate CRC over bytes 1 to end (excluding BEGIN, but before CRC and END)
        crc_data = bytes(frame[1:])
        crc = calculate_crc16(crc_data)

        # Append CRC (big-endian)
        frame.append((crc >> 8) & 0xFF)  # CRC_H
        frame.append(crc & 0xFF)  # CRC_L

        # Append END marker
        frame.append(END_FRAME)

        return bytes(frame)

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["Frame"]:
        """
        Parse a frame from received bytes.

        Args:
            data: Raw frame bytes

        Returns:
            Parsed Frame object, or None if invalid

        Example:
            >>> frame_bytes = b'\\x68\\x04\\x00\\x01\\x00\\x83\\x00\\x40...'
            >>> frame = Frame.from_bytes(frame_bytes)
            >>> frame.command
            64
        """
        if len(data) < FRAME_MIN_LEN:
            return None

        # Validate BEGIN marker
        if data[0] != BEGIN_FRAME:
            return None

        # Validate END marker
        if data[-1] != END_FRAME:
            return None

        # Extract length
        length = struct.unpack("<H", data[1:3])[0]

        # Validate frame length
        expected_length = length + 6
        if len(data) != expected_length:
            return None

        # Extract and verify CRC
        crc_data = data[1:-3]
        expected_crc = struct.unpack(">H", data[-3:-1])[0]
        calculated_crc = calculate_crc16(crc_data)

        if expected_crc != calculated_crc:
            return None

        # Extract fields
        destination = struct.unpack("<H", data[3:5])[0]
        source = data[5]
        reserved = data[6]
        command = data[7]
        payload = data[8:-3]

        # Create frame object
        frame = cls(destination=destination, command=command, data=payload, reserved=reserved)
        frame.source = source

        return frame

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Frame(dest={self.destination}, src={self.source}, rsv=0x{self.reserved:02X}, "
            f"cmd=0x{self.command:02X}, data_len={len(self.data)})"
        )
