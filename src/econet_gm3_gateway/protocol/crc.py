"""CRC-16 calculation for GM3 protocol frames."""


def calculate_crc16(data: bytes) -> int:
    """
    Calculate CRC-16 for GM3 protocol.

    The CRC is calculated using a polynomial-based algorithm:
    - Each byte is XORed with the high byte of the CRC
    - The result is manipulated through XOR operations
    - Final result is a 16-bit value

    Args:
        data: Bytes to calculate CRC over

    Returns:
        16-bit CRC value

    Example:
        >>> data = b'\\x00\\x01\\x83\\x00\\x02'
        >>> crc = calculate_crc16(data)
        >>> hex(crc)
        '0x...'
    """
    crc = 0

    for byte in data:
        s = byte ^ (crc >> 8)
        t = s ^ (s >> 4)
        crc = (crc << 8) ^ t ^ (t << 5) ^ (t << 12)
        crc = crc & 0xFFFF

    return crc


def verify_crc16(data: bytes, expected_crc: int) -> bool:
    """
    Verify CRC-16 matches expected value.

    Args:
        data: Data bytes (excluding CRC)
        expected_crc: Expected CRC value

    Returns:
        True if CRC matches, False otherwise

    Example:
        >>> data = b'\\x00\\x01\\x83\\x00\\x02'
        >>> crc = calculate_crc16(data)
        >>> verify_crc16(data, crc)
        True
    """
    calculated = calculate_crc16(data)
    return calculated == expected_crc
