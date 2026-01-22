"""Unit tests for CRC-16 calculation."""

from econet_gm3_gateway.protocol.crc import calculate_crc16, verify_crc16


def test_crc_empty_data():
    """Test CRC calculation with empty data."""
    result = calculate_crc16(b"")
    assert result == 0


def test_crc_single_byte():
    """Test CRC calculation with single byte."""
    result = calculate_crc16(b"\x00")
    assert isinstance(result, int)
    assert 0 <= result <= 0xFFFF


def test_crc_multiple_bytes():
    """Test CRC calculation with multiple bytes."""
    result = calculate_crc16(b"\x01\x02\x03\x04")
    assert isinstance(result, int)
    assert 0 <= result <= 0xFFFF


def test_crc_deterministic():
    """Test that CRC calculation is deterministic."""
    data = b"\x04\x00\x01\x00\x83\x00\x40\x00\x00\x01\x00"
    result1 = calculate_crc16(data)
    result2 = calculate_crc16(data)
    assert result1 == result2


def test_crc_different_data():
    """Test that different data produces different CRC."""
    data1 = b"\x01\x02\x03"
    data2 = b"\x01\x02\x04"
    result1 = calculate_crc16(data1)
    result2 = calculate_crc16(data2)
    assert result1 != result2


def test_verify_crc_valid():
    """Test CRC verification with valid CRC."""
    data = b"\x04\x00\x01\x00\x83\x00\x40"
    crc = calculate_crc16(data)
    assert verify_crc16(data, crc) is True


def test_verify_crc_invalid():
    """Test CRC verification with invalid CRC."""
    data = b"\x04\x00\x01\x00\x83\x00\x40"
    crc = calculate_crc16(data)
    assert verify_crc16(data, crc + 1) is False


def test_crc_range():
    """Test that CRC is always 16-bit."""
    for i in range(256):
        data = bytes([i])
        result = calculate_crc16(data)
        assert 0 <= result <= 0xFFFF
