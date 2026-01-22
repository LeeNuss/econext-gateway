"""Unit tests for serial communication layer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from econet_gm3_gateway.protocol.constants import Command
from econet_gm3_gateway.protocol.frames import Frame
from econet_gm3_gateway.serial.connection import SerialConnection
from econet_gm3_gateway.serial.reader import FrameReader
from econet_gm3_gateway.serial.writer import FrameWriter


class TestSerialConnection:
    """Tests for SerialConnection class."""

    @pytest.mark.asyncio
    async def test_connection_init(self):
        """Test connection initialization."""
        conn = SerialConnection("/dev/ttyUSB0", baudrate=9600, timeout=2.0)

        assert conn.port == "/dev/ttyUSB0"
        assert conn.baudrate == 9600
        assert conn.timeout == 2.0
        assert not conn.connected

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.is_closing.return_value = False
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            conn = SerialConnection("/dev/ttyUSB0")
            result = await conn.connect()

            assert result is True
            assert conn.connected is True
            mock_serial.open_serial_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_serial.open_serial_connection = AsyncMock(side_effect=OSError("Port not found"))

            conn = SerialConnection("/dev/ttyUSB0")
            result = await conn.connect()

            assert result is False
            assert conn.connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.is_closing.return_value = False
            mock_writer.wait_closed = AsyncMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            conn = SerialConnection("/dev/ttyUSB0")
            await conn.connect()
            assert conn.connected is True

            await conn.disconnect()

            assert conn.connected is False
            mock_writer.close.assert_called_once()
            mock_writer.wait_closed.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_success(self):
        """Test successful read."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_reader.read = AsyncMock(return_value=b"test data")
            mock_writer = MagicMock()
            mock_writer.is_closing.return_value = False
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            conn = SerialConnection("/dev/ttyUSB0")
            await conn.connect()

            data = await conn.read()

            assert data == b"test data"

    @pytest.mark.asyncio
    async def test_read_not_connected(self):
        """Test read when not connected raises error."""
        conn = SerialConnection("/dev/ttyUSB0")

        with pytest.raises(ConnectionError):
            await conn.read()

    @pytest.mark.asyncio
    async def test_write_success(self):
        """Test successful write."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.is_closing.return_value = False
            mock_writer.drain = AsyncMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            conn = SerialConnection("/dev/ttyUSB0")
            await conn.connect()

            await conn.write(b"test data")

            mock_writer.write.assert_called_once_with(b"test data")
            mock_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_not_connected(self):
        """Test write when not connected raises error."""
        conn = SerialConnection("/dev/ttyUSB0")

        with pytest.raises(ConnectionError):
            await conn.write(b"test")

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with patch("econet_gm3_gateway.serial.connection.serial_asyncio") as mock_serial:
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.is_closing.return_value = False
            mock_writer.wait_closed = AsyncMock()
            mock_serial.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

            async with SerialConnection("/dev/ttyUSB0") as conn:
                assert conn.connected is True

            assert conn.connected is False


class TestFrameReader:
    """Tests for FrameReader class."""

    @pytest.mark.asyncio
    async def test_reader_init(self):
        """Test reader initialization."""
        conn = SerialConnection("/dev/ttyUSB0")
        reader = FrameReader(conn, buffer_size=2048)

        assert reader.connection == conn
        assert reader.buffer_size == 2048
        assert reader.stats["frames_read"] == 0

    @pytest.mark.asyncio
    async def test_read_frame_success(self):
        """Test successful frame read."""
        # Create a valid frame
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"\x00\x00\x01\x00")
        frame_bytes = frame.to_bytes()

        # Create mock connection with mocked read
        conn = MagicMock(spec=SerialConnection)
        conn.read = AsyncMock(return_value=frame_bytes)

        reader = FrameReader(conn)
        result = await reader.read_frame(timeout=1.0)

        assert result is not None
        assert result.destination == 1
        assert result.command == Command.GET_PARAMS
        assert reader.stats["frames_read"] == 1

    @pytest.mark.asyncio
    async def test_read_frame_timeout(self):
        """Test frame read timeout."""
        # Create mock connection that returns empty data (simulating no data)
        conn = MagicMock(spec=SerialConnection)
        conn.read = AsyncMock(return_value=b"")

        reader = FrameReader(conn)
        result = await reader.read_frame(timeout=0.1)

        assert result is None

    @pytest.mark.asyncio
    async def test_read_frame_invalid_crc(self):
        """Test frame with invalid CRC is rejected."""
        # Create frame with corrupted CRC
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        frame_bytes = bytearray(frame.to_bytes())
        frame_bytes[-3] ^= 0xFF  # Corrupt CRC
        corrupted_bytes = bytes(frame_bytes)

        # Mock connection - first return corrupted data, then timeout
        call_count = 0

        async def mock_read(n):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return corrupted_bytes
            # After first call, return empty to trigger timeout
            await asyncio.sleep(0.2)
            return b""

        conn = MagicMock(spec=SerialConnection)
        conn.read = mock_read

        reader = FrameReader(conn)
        result = await reader.read_frame(timeout=0.3)

        assert result is None
        assert reader.stats["frames_invalid"] >= 1

    @pytest.mark.asyncio
    async def test_reset_buffer(self):
        """Test buffer reset."""
        conn = MagicMock(spec=SerialConnection)
        reader = FrameReader(conn)

        reader._buffer.extend(b"some data")
        assert len(reader._buffer) > 0

        reader.reset_buffer()
        assert len(reader._buffer) == 0

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        """Test statistics reset."""
        conn = MagicMock(spec=SerialConnection)
        reader = FrameReader(conn)

        reader._stats["frames_read"] = 10
        reader._stats["frames_invalid"] = 5

        reader.reset_stats()

        assert reader.stats["frames_read"] == 0
        assert reader.stats["frames_invalid"] == 0


class TestFrameWriter:
    """Tests for FrameWriter class."""

    @pytest.mark.asyncio
    async def test_writer_init(self):
        """Test writer initialization."""
        conn = MagicMock(spec=SerialConnection)
        writer = FrameWriter(conn, max_retries=5, retry_delay=0.2)

        assert writer.connection == conn
        assert writer.max_retries == 5
        assert writer.retry_delay == 0.2
        assert writer.stats["frames_written"] == 0

    @pytest.mark.asyncio
    async def test_write_frame_success(self):
        """Test successful frame write."""
        conn = MagicMock(spec=SerialConnection)
        conn.write = AsyncMock()

        writer = FrameWriter(conn)
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        result = await writer.write_frame(frame, timeout=1.0)

        assert result is True
        assert writer.stats["frames_written"] == 1
        assert writer.stats["frames_failed"] == 0
        conn.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_frame_retry(self):
        """Test frame write with retry."""
        conn = MagicMock(spec=SerialConnection)
        # Fail first attempt, succeed on second
        conn.write = AsyncMock(side_effect=[TimeoutError(), None])

        writer = FrameWriter(conn, max_retries=3, retry_delay=0.01)
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        result = await writer.write_frame(frame, timeout=0.5)

        assert result is True
        assert writer.stats["frames_written"] == 1
        assert writer.stats["retries"] == 1

    @pytest.mark.asyncio
    async def test_write_frame_all_retries_fail(self):
        """Test frame write when all retries fail."""
        conn = MagicMock(spec=SerialConnection)
        conn.write = AsyncMock(side_effect=TimeoutError())

        writer = FrameWriter(conn, max_retries=3, retry_delay=0.01)
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        result = await writer.write_frame(frame, timeout=0.1)

        assert result is False
        assert writer.stats["frames_written"] == 0
        assert writer.stats["frames_failed"] == 1

    @pytest.mark.asyncio
    async def test_write_frames_multiple(self):
        """Test writing multiple frames."""
        conn = MagicMock(spec=SerialConnection)
        conn.write = AsyncMock()

        writer = FrameWriter(conn)
        frames = [
            Frame(destination=1, command=Command.GET_PARAMS, data=b""),
            Frame(destination=1, command=Command.GET_PARAMS, data=b""),
            Frame(destination=1, command=Command.GET_PARAMS, data=b""),
        ]

        written = await writer.write_frames(frames, timeout=1.0)

        assert written == 3
        assert writer.stats["frames_written"] == 3

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        """Test statistics reset."""
        conn = MagicMock(spec=SerialConnection)
        writer = FrameWriter(conn)

        writer._stats["frames_written"] = 10
        writer._stats["frames_failed"] = 5

        writer.reset_stats()

        assert writer.stats["frames_written"] == 0
        assert writer.stats["frames_failed"] == 0
