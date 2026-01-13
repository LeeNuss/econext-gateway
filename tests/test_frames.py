"""Unit tests for frame construction and parsing."""

import pytest

from econet_gm3_gateway.protocol.constants import BEGIN_FRAME, Command, END_FRAME, SRC_ADDRESS
from econet_gm3_gateway.protocol.frames import Frame


class TestFrameConstruction:
    """Tests for frame construction (to_bytes)."""

    def test_frame_basic_structure(self):
        """Test basic frame structure."""
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        frame_bytes = frame.to_bytes()

        assert frame_bytes[0] == BEGIN_FRAME
        assert frame_bytes[-1] == END_FRAME
        assert len(frame_bytes) >= 10

    def test_frame_with_no_data(self):
        """Test frame with no payload data."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = frame.to_bytes()

        assert len(frame_bytes) == 11  # Minimum frame length

    def test_frame_with_data(self):
        """Test frame with payload data."""
        data = b"\x00\x00\x01\x00"
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=data)
        frame_bytes = frame.to_bytes()

        assert len(frame_bytes) == 11 + len(data)

    def test_frame_destination_address(self):
        """Test destination address is encoded correctly (little-endian)."""
        frame = Frame(destination=0x0102, command=0x00, data=b"")
        frame_bytes = frame.to_bytes()

        # Bytes 3-4 are destination address (little-endian)
        assert frame_bytes[3] == 0x02
        assert frame_bytes[4] == 0x01

    def test_frame_source_address(self):
        """Test source address is set correctly."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = frame.to_bytes()

        # Byte 5 is source address
        assert frame_bytes[5] == SRC_ADDRESS

    def test_frame_command(self):
        """Test command byte is encoded correctly."""
        frame = Frame(destination=1, command=0x40, data=b"")
        frame_bytes = frame.to_bytes()

        # Byte 7 is command
        assert frame_bytes[7] == 0x40

    def test_frame_length_calculation(self):
        """Test length field is calculated correctly."""
        data = b"\x01\x02\x03\x04\x05"
        frame = Frame(destination=1, command=0x00, data=data)
        frame_bytes = frame.to_bytes()

        # Length = total bytes - 6 header bytes
        # Frame: BEGIN(1) + LEN(2) + DEST(2) + SRC(1) = 6 bytes header
        # Then: RSV(1) + CMD(1) + DATA(5) + CRC(2) + END(1) = 10 bytes
        # Total = 16 bytes, Length field should be 16 - 6 = 10
        length = frame_bytes[1] + (frame_bytes[2] << 8)
        expected_length = len(frame_bytes) - 6
        assert length == expected_length


class TestFrameParsing:
    """Tests for frame parsing (from_bytes)."""

    def test_parse_valid_frame(self):
        """Test parsing a valid frame."""
        # Create a frame and parse it back
        original = Frame(destination=1, command=Command.GET_PARAMS, data=b"\x00\x00\x01\x00")
        frame_bytes = original.to_bytes()

        parsed = Frame.from_bytes(frame_bytes)

        assert parsed is not None
        assert parsed.destination == 1
        assert parsed.command == Command.GET_PARAMS
        assert parsed.data == b"\x00\x00\x01\x00"

    def test_parse_too_short(self):
        """Test parsing frame that's too short returns None."""
        short_data = b"\x68\x00"
        result = Frame.from_bytes(short_data)
        assert result is None

    def test_parse_invalid_begin_marker(self):
        """Test parsing frame with invalid BEGIN marker returns None."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = bytearray(frame.to_bytes())
        frame_bytes[0] = 0x00  # Invalid BEGIN marker

        result = Frame.from_bytes(bytes(frame_bytes))
        assert result is None

    def test_parse_invalid_end_marker(self):
        """Test parsing frame with invalid END marker returns None."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = bytearray(frame.to_bytes())
        frame_bytes[-1] = 0x00  # Invalid END marker

        result = Frame.from_bytes(bytes(frame_bytes))
        assert result is None

    def test_parse_invalid_crc(self):
        """Test parsing frame with invalid CRC returns None."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = bytearray(frame.to_bytes())
        frame_bytes[-3] ^= 0xFF  # Corrupt CRC

        result = Frame.from_bytes(bytes(frame_bytes))
        assert result is None

    def test_parse_wrong_length(self):
        """Test parsing frame with incorrect length field returns None."""
        frame = Frame(destination=1, command=0x00, data=b"")
        frame_bytes = bytearray(frame.to_bytes())
        frame_bytes[1] = 99  # Invalid length

        result = Frame.from_bytes(bytes(frame_bytes))
        assert result is None


class TestFrameRoundTrip:
    """Tests for encoding then parsing frames."""

    @pytest.mark.parametrize(
        "destination,command,data",
        [
            (1, 0x00, b""),
            (1, 0x40, b"\x00\x00\x01\x00"),
            (237, 0x02, b"\x00\x00\x64\x00"),
            (100, 0x29, b"\x67\x00\x2d\x00"),
            (65535, 0xFF, b"\x01\x02\x03\x04\x05"),
        ],
    )
    def test_roundtrip(self, destination, command, data):
        """Test encoding then parsing returns equivalent frame."""
        original = Frame(destination=destination, command=command, data=data)
        frame_bytes = original.to_bytes()
        parsed = Frame.from_bytes(frame_bytes)

        assert parsed is not None
        assert parsed.destination == destination
        assert parsed.command == command
        assert parsed.data == data

    def test_roundtrip_large_payload(self):
        """Test roundtrip with large payload."""
        large_data = bytes(range(256))
        original = Frame(destination=1, command=0x00, data=large_data)
        frame_bytes = original.to_bytes()
        parsed = Frame.from_bytes(frame_bytes)

        assert parsed is not None
        assert parsed.data == large_data


class TestFrameRepr:
    """Tests for frame string representation."""

    def test_repr(self):
        """Test __repr__ returns useful debug string."""
        frame = Frame(destination=1, command=0x40, data=b"\x01\x02")
        repr_str = repr(frame)

        assert "Frame" in repr_str
        assert "dest=1" in repr_str
        assert "cmd=0x40" in repr_str
        assert "data_len=2" in repr_str
