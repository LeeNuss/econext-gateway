"""Unit tests for data encoding and decoding."""

import pytest

from econext_gateway.protocol.codec import decode_value, encode_value
from econext_gateway.protocol.constants import DataType


class TestEncoding:
    """Tests for encoding Python values to bytes."""

    def test_encode_int8(self):
        """Test encoding signed 8-bit integer."""
        assert encode_value(45, DataType.INT8) == b"-"
        assert encode_value(-10, DataType.INT8) == b"\xf6"
        assert encode_value(0, DataType.INT8) == b"\x00"

    def test_encode_int16(self):
        """Test encoding signed 16-bit integer."""
        assert encode_value(45, DataType.INT16) == b"-\x00"
        assert encode_value(300, DataType.INT16) == b",\x01"
        assert encode_value(-100, DataType.INT16) == b"\x9c\xff"

    def test_encode_int32(self):
        """Test encoding signed 32-bit integer."""
        assert encode_value(12345, DataType.INT32) == b"90\x00\x00"
        assert encode_value(-12345, DataType.INT32) == b"\xc7\xcf\xff\xff"

    def test_encode_uint8(self):
        """Test encoding unsigned 8-bit integer."""
        assert encode_value(0, DataType.UINT8) == b"\x00"
        assert encode_value(255, DataType.UINT8) == b"\xff"
        assert encode_value(128, DataType.UINT8) == b"\x80"

    def test_encode_uint16(self):
        """Test encoding unsigned 16-bit integer."""
        assert encode_value(0, DataType.UINT16) == b"\x00\x00"
        assert encode_value(65535, DataType.UINT16) == b"\xff\xff"
        assert encode_value(300, DataType.UINT16) == b",\x01"

    def test_encode_float(self):
        """Test encoding 32-bit float."""
        result = encode_value(22.5, DataType.FLOAT)
        assert len(result) == 4

    def test_encode_double(self):
        """Test encoding 64-bit double."""
        result = encode_value(22.5, DataType.DOUBLE)
        assert len(result) == 8

    def test_encode_bool_true(self):
        """Test encoding boolean true."""
        assert encode_value(True, DataType.BOOL) == b"\x01"

    def test_encode_bool_false(self):
        """Test encoding boolean false."""
        assert encode_value(False, DataType.BOOL) == b"\x00"

    def test_encode_string(self):
        """Test encoding string."""
        assert encode_value("test", DataType.STRING) == b"test\x00"
        assert encode_value("", DataType.STRING) == b"\x00"
        assert encode_value("hello world", DataType.STRING) == b"hello world\x00"

    def test_encode_unsupported_type(self):
        """Test encoding with unsupported type raises error."""
        with pytest.raises(ValueError, match="Unsupported type code"):
            encode_value(42, 999)


class TestDecoding:
    """Tests for decoding bytes to Python values."""

    def test_decode_int8(self):
        """Test decoding signed 8-bit integer."""
        assert decode_value(b"-", DataType.INT8) == 45
        assert decode_value(b"\xf6", DataType.INT8) == -10
        assert decode_value(b"\x00", DataType.INT8) == 0

    def test_decode_int16(self):
        """Test decoding signed 16-bit integer."""
        assert decode_value(b"-\x00", DataType.INT16) == 45
        assert decode_value(b",\x01", DataType.INT16) == 300
        assert decode_value(b"\x9c\xff", DataType.INT16) == -100

    def test_decode_int32(self):
        """Test decoding signed 32-bit integer."""
        assert decode_value(b"90\x00\x00", DataType.INT32) == 12345
        assert decode_value(b"\xc7\xcf\xff\xff", DataType.INT32) == -12345

    def test_decode_uint8(self):
        """Test decoding unsigned 8-bit integer."""
        assert decode_value(b"\x00", DataType.UINT8) == 0
        assert decode_value(b"\xff", DataType.UINT8) == 255
        assert decode_value(b"\x80", DataType.UINT8) == 128

    def test_decode_uint16(self):
        """Test decoding unsigned 16-bit integer."""
        assert decode_value(b"\x00\x00", DataType.UINT16) == 0
        assert decode_value(b"\xff\xff", DataType.UINT16) == 65535
        assert decode_value(b",\x01", DataType.UINT16) == 300

    def test_decode_float(self):
        """Test decoding 32-bit float."""
        import struct

        data = struct.pack("<f", 22.5)
        result = decode_value(data, DataType.FLOAT)
        assert result == 22.5

    def test_decode_float_rounding(self):
        """Test that floats are rounded to 2 decimal places."""
        import struct

        data = struct.pack("<f", 22.12345)
        result = decode_value(data, DataType.FLOAT)
        assert result == 22.12

    def test_decode_bool_true(self):
        """Test decoding boolean true."""
        assert decode_value(b"\x01", DataType.BOOL) is True

    def test_decode_bool_false(self):
        """Test decoding boolean false."""
        assert decode_value(b"\x00", DataType.BOOL) is False

    def test_decode_string(self):
        """Test decoding string."""
        assert decode_value(b"test\x00", DataType.STRING) == "test"
        assert decode_value(b"\x00", DataType.STRING) == ""
        assert decode_value(b"hello world\x00", DataType.STRING) == "hello world"

    def test_decode_string_no_terminator(self):
        """Test decoding string without null terminator."""
        assert decode_value(b"test", DataType.STRING) == "test"

    def test_decode_insufficient_data(self):
        """Test decoding with insufficient data raises error."""
        with pytest.raises(ValueError, match="Insufficient data"):
            decode_value(b"\x00", DataType.INT16)

    def test_decode_unsupported_type(self):
        """Test decoding with unsupported type raises error."""
        with pytest.raises(ValueError, match="Unsupported type code"):
            decode_value(b"\x00", 999)


class TestRoundTrip:
    """Tests for encoding then decoding values."""

    @pytest.mark.parametrize(
        "value,type_code",
        [
            (0, DataType.INT8),
            (127, DataType.INT8),
            (-128, DataType.INT8),
            (0, DataType.INT16),
            (32767, DataType.INT16),
            (-32768, DataType.INT16),
            (0, DataType.UINT8),
            (255, DataType.UINT8),
            (0, DataType.UINT16),
            (65535, DataType.UINT16),
            (True, DataType.BOOL),
            (False, DataType.BOOL),
        ],
    )
    def test_roundtrip_integers_and_bool(self, value, type_code):
        """Test encoding then decoding returns original value."""
        encoded = encode_value(value, type_code)
        decoded = decode_value(encoded, type_code)
        assert decoded == value

    @pytest.mark.parametrize(
        "value,type_code",
        [
            (0.0, DataType.FLOAT),
            (22.5, DataType.FLOAT),
            (-10.25, DataType.FLOAT),
            (22.5, DataType.DOUBLE),
        ],
    )
    def test_roundtrip_floats(self, value, type_code):
        """Test encoding then decoding floats (with rounding)."""
        encoded = encode_value(value, type_code)
        decoded = decode_value(encoded, type_code)
        assert abs(decoded - value) < 0.01

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "test",
            "hello world",
            "ecotronic100",
        ],
    )
    def test_roundtrip_strings(self, value):
        """Test encoding then decoding strings."""
        encoded = encode_value(value, DataType.STRING)
        decoded = decode_value(encoded, DataType.STRING)
        assert decoded == value
