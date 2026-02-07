"""Unit tests for serial communication layer (GM3Protocol + GM3SerialTransport)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from econext_gateway.protocol.constants import Command
from econext_gateway.protocol.frames import Frame
from econext_gateway.serial.connection import GM3SerialTransport
from econext_gateway.serial.protocol import GM3Protocol

# ============================================================================
# TestGM3Protocol
# ============================================================================


class TestGM3Protocol:
    """Tests for GM3Protocol -- asyncio.Protocol for GM3 framing."""

    def _make_protocol(self) -> tuple[GM3Protocol, MagicMock]:
        """Create a protocol with a mock transport."""
        protocol = GM3Protocol()
        transport = MagicMock()
        transport.serial = MagicMock()
        protocol.connection_made(transport)
        return protocol, transport

    def test_connection_made(self):
        """connection_made stores transport and sets connected."""
        protocol = GM3Protocol()
        assert protocol.connected is False

        transport = MagicMock()
        protocol.connection_made(transport)

        assert protocol.connected is True

    def test_connection_lost(self):
        """connection_lost clears transport and pushes sentinel."""
        protocol, transport = self._make_protocol()
        assert protocol.connected is True

        protocol.connection_lost(None)

        assert protocol.connected is False

    @pytest.mark.asyncio
    async def test_connection_lost_pushes_sentinel(self):
        """connection_lost pushes None onto the frame queue."""
        protocol, _ = self._make_protocol()
        protocol.connection_lost(None)

        frame = await asyncio.wait_for(protocol._frame_queue.get(), timeout=0.1)
        assert frame is None

    @pytest.mark.asyncio
    async def test_complete_frame_arrives_on_queue(self):
        """Feed a complete frame via data_received -> appears on queue."""
        protocol, _ = self._make_protocol()

        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"\x00\x00\x01\x00")
        protocol.data_received(frame.to_bytes())

        result = await asyncio.wait_for(protocol._frame_queue.get(), timeout=0.1)
        assert result is not None
        assert result.destination == 1
        assert result.command == Command.GET_PARAMS
        assert protocol.stats["frames_read"] == 1

    @pytest.mark.asyncio
    async def test_partial_then_complete(self):
        """Feed partial data, then the rest -- frame appears after second call."""
        protocol, _ = self._make_protocol()

        frame_bytes = Frame(destination=1, command=Command.GET_PARAMS, data=b"\x01\x02").to_bytes()
        mid = len(frame_bytes) // 2

        protocol.data_received(frame_bytes[:mid])
        assert protocol._frame_queue.empty()

        protocol.data_received(frame_bytes[mid:])
        result = await asyncio.wait_for(protocol._frame_queue.get(), timeout=0.1)
        assert result is not None
        assert result.command == Command.GET_PARAMS

    @pytest.mark.asyncio
    async def test_garbage_before_frame(self):
        """Garbage bytes before a valid frame are discarded."""
        protocol, _ = self._make_protocol()

        frame_bytes = Frame(destination=1, command=Command.GET_PARAMS, data=b"").to_bytes()
        protocol.data_received(b"\xff\xfe\xfd" + frame_bytes)

        result = await asyncio.wait_for(protocol._frame_queue.get(), timeout=0.1)
        assert result is not None
        assert result.command == Command.GET_PARAMS

    @pytest.mark.asyncio
    async def test_invalid_crc_rejected(self):
        """Frame with corrupted CRC is rejected and counted."""
        protocol, _ = self._make_protocol()

        frame_bytes = bytearray(Frame(destination=1, command=Command.GET_PARAMS, data=b"").to_bytes())
        frame_bytes[-3] ^= 0xFF  # corrupt CRC
        protocol.data_received(bytes(frame_bytes))

        assert protocol._frame_queue.empty()
        assert protocol.stats["frames_invalid"] >= 1

    @pytest.mark.asyncio
    async def test_receive_frame_timeout(self):
        """receive_frame returns None on timeout."""
        protocol, _ = self._make_protocol()

        result = await protocol.receive_frame(timeout=0.05)
        assert result is None

    @pytest.mark.asyncio
    async def test_receive_frame_returns_frame(self):
        """receive_frame returns a parsed frame from the queue."""
        protocol, _ = self._make_protocol()

        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"\x01")
        protocol.data_received(frame.to_bytes())

        result = await protocol.receive_frame(timeout=0.1)
        assert result is not None
        assert result.command == Command.GET_PARAMS

    @pytest.mark.asyncio
    async def test_write_frame_calls_transport_write(self):
        """write_frame calls transport.write with correct bytes."""
        protocol, transport = self._make_protocol()

        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        result = await protocol.write_frame(frame)

        assert result is True
        transport.write.assert_called_once_with(frame.to_bytes())
        assert protocol.stats["frames_written"] == 1

    @pytest.mark.asyncio
    async def test_write_frame_flush_after(self):
        """write_frame with flush_after=True flushes TX then clears RX."""
        protocol, transport = self._make_protocol()

        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        await protocol.write_frame(frame, flush_after=True)

        transport.serial.flush.assert_called_once()
        transport.serial.reset_input_buffer.assert_called_once()
        # flush() must come before reset_input_buffer() for half-duplex RS-485
        calls = transport.serial.method_calls
        flush_idx = next(i for i, c in enumerate(calls) if c[0] == "flush")
        reset_idx = next(i for i, c in enumerate(calls) if c[0] == "reset_input_buffer")
        assert flush_idx < reset_idx, "flush() must be called before reset_input_buffer()"

    @pytest.mark.asyncio
    async def test_write_frame_no_transport(self):
        """write_frame returns False when not connected."""
        protocol = GM3Protocol()

        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        result = await protocol.write_frame(frame)

        assert result is False

    def test_reset_buffer(self):
        """reset_buffer clears rx buffer and drains queue."""
        protocol, _ = self._make_protocol()

        # Add data to buffer and queue
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        protocol.data_received(frame.to_bytes())
        protocol._rx_buffer.extend(b"leftover data")

        assert not protocol._frame_queue.empty()

        protocol.reset_buffer()

        assert len(protocol._rx_buffer) == 0
        assert protocol._frame_queue.empty()

    @pytest.mark.asyncio
    async def test_queue_full_drops_oldest(self):
        """When queue is full, oldest frame is dropped to make room."""
        protocol, _ = self._make_protocol()

        # Fill queue to capacity
        frame = Frame(destination=1, command=Command.GET_PARAMS, data=b"")
        frame_bytes = frame.to_bytes()
        for _ in range(64):
            protocol.data_received(frame_bytes)

        assert protocol._frame_queue.full()

        # One more should succeed (dropping oldest)
        new_frame = Frame(destination=2, command=Command.GET_PARAMS_RESPONSE, data=b"\x01")
        protocol.data_received(new_frame.to_bytes())

        # Queue is still full, and the newest frame is there
        assert protocol._frame_queue.full()
        assert protocol.stats["frames_read"] == 65


# ============================================================================
# TestGM3SerialTransport
# ============================================================================


class TestGM3SerialTransport:
    """Tests for GM3SerialTransport."""

    @pytest.mark.asyncio
    async def test_init(self):
        """Test transport initialization."""
        transport = GM3SerialTransport("/dev/ttyUSB0", baudrate=9600)

        assert transport.port == "/dev/ttyUSB0"
        assert transport.baudrate == 9600
        assert not transport.connected

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection via serial_asyncio."""
        mock_transport = MagicMock()
        mock_protocol = MagicMock(spec=GM3Protocol)
        mock_protocol.connected = True

        with (
            patch("econext_gateway.serial.connection.serial.Serial") as mock_serial_class,
            patch("serial_asyncio.create_serial_connection", new_callable=AsyncMock) as mock_create,
        ):
            mock_serial = MagicMock()
            mock_serial_class.return_value = mock_serial
            mock_create.return_value = (mock_transport, mock_protocol)

            transport = GM3SerialTransport("/dev/ttyUSB0")
            result = await transport.connect()

            assert result is True
            assert transport.connected is True
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure."""
        with (
            patch("econext_gateway.serial.connection.serial.Serial") as mock_serial_class,
            patch("serial_asyncio.create_serial_connection", new_callable=AsyncMock) as mock_create,
        ):
            mock_serial = MagicMock()
            mock_serial_class.return_value = mock_serial
            mock_create.side_effect = OSError("Port not found")

            transport = GM3SerialTransport("/dev/ttyUSB0")
            result = await transport.connect()

            assert result is False
            assert transport.connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection closes the transport."""
        mock_transport = MagicMock()
        mock_protocol = MagicMock(spec=GM3Protocol)
        mock_protocol.connected = True

        with (
            patch("econext_gateway.serial.connection.serial.Serial"),
            patch("serial_asyncio.create_serial_connection", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = (mock_transport, mock_protocol)

            transport = GM3SerialTransport("/dev/ttyUSB0")
            await transport.connect()
            assert transport.connected is True

            await transport.disconnect()

            mock_transport.close.assert_called_once()
            assert transport.connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        mock_transport = MagicMock()
        mock_protocol = MagicMock(spec=GM3Protocol)
        mock_protocol.connected = True

        with (
            patch("econext_gateway.serial.connection.serial.Serial"),
            patch("serial_asyncio.create_serial_connection", new_callable=AsyncMock) as mock_create,
        ):
            mock_create.return_value = (mock_transport, mock_protocol)

            async with GM3SerialTransport("/dev/ttyUSB0") as transport:
                assert transport.connected is True

            mock_transport.close.assert_called_once()
