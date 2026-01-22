"""Unit tests for protocol handler."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from econet_gm3_gateway.core.cache import ParameterCache
from econet_gm3_gateway.core.models import Parameter
from econet_gm3_gateway.protocol.constants import Command, DataType
from econet_gm3_gateway.protocol.frames import Frame
from econet_gm3_gateway.protocol.handler import (
    ParamStructEntry,
    ProtocolHandler,
    build_get_params_request,
    build_modify_param_request,
    build_struct_request,
    parse_get_params_request,
    parse_get_params_response,
    parse_struct_response,
)
from econet_gm3_gateway.serial.connection import SerialConnection

# ============================================================================
# Test Parse Functions
# ============================================================================


class TestParseGetParamsRequest:
    """Tests for parse_get_params_request."""

    def test_basic_request(self):
        """Test parsing a basic request."""
        # count=10, start_index=0
        data = struct.pack("<BH", 10, 0)
        count, start = parse_get_params_request(data)

        assert count == 10
        assert start == 0

    def test_nonzero_start(self):
        """Test parsing with non-zero start index."""
        data = struct.pack("<BH", 50, 100)
        count, start = parse_get_params_request(data)

        assert count == 50
        assert start == 100

    def test_max_values(self):
        """Test parsing with large values."""
        data = struct.pack("<BH", 255, 65535)
        count, start = parse_get_params_request(data)

        assert count == 255
        assert start == 65535

    def test_too_short(self):
        """Test parsing with insufficient data."""
        with pytest.raises(ValueError, match="too short"):
            parse_get_params_request(b"\x00\x00")


class TestParseGetParamsResponse:
    """Tests for parse_get_params_response."""

    def test_single_int16_param(self):
        """Test parsing single INT16 parameter value."""
        structs = {0: ParamStructEntry(index=0, name="Temp", unit=1, type_code=DataType.INT16, writable=True)}

        # paramsNo=1, firstIndex=0, value=45 (int16 LE)
        data = struct.pack("<BH", 1, 0) + struct.pack("<h", 45)

        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (0, 45)

    def test_multiple_params(self):
        """Test parsing multiple parameter values."""
        structs = {
            10: ParamStructEntry(index=10, name="A", unit=0, type_code=DataType.INT16, writable=True),
            11: ParamStructEntry(index=11, name="B", unit=0, type_code=DataType.UINT8, writable=True),
            12: ParamStructEntry(index=12, name="C", unit=0, type_code=DataType.FLOAT, writable=False),
        }

        data = struct.pack("<BH", 3, 10)
        data += struct.pack("<h", -100)  # A: int16
        data += struct.pack("<B", 200)  # B: uint8
        data += struct.pack("<f", 3.14)  # C: float

        results = parse_get_params_response(data, structs)

        assert len(results) == 3
        assert results[0] == (10, -100)
        assert results[1] == (11, 200)
        assert results[2][0] == 12
        assert abs(results[2][1] - 3.14) < 0.01

    def test_bool_param(self):
        """Test parsing BOOL parameter."""
        structs = {0: ParamStructEntry(index=0, name="Flag", unit=0, type_code=DataType.BOOL, writable=True)}

        data = struct.pack("<BH", 1, 0) + struct.pack("<B", 1)
        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (0, True)

    def test_unknown_index_stops(self):
        """Test parsing stops at unknown parameter index."""
        structs = {
            0: ParamStructEntry(index=0, name="A", unit=0, type_code=DataType.INT16, writable=True),
            # Index 1 is missing from structs
        }

        data = struct.pack("<BH", 2, 0)
        data += struct.pack("<h", 42)  # A
        data += struct.pack("<h", 99)  # Unknown - should stop

        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (0, 42)

    def test_too_short_response(self):
        """Test parsing too-short response."""
        with pytest.raises(ValueError, match="too short"):
            parse_get_params_response(b"\x01\x00", {})

    def test_empty_params(self):
        """Test parsing with zero params."""
        data = struct.pack("<BH", 0, 0)
        results = parse_get_params_response(data, {})
        assert results == []

    def test_uint32_param(self):
        """Test parsing UINT32 parameter."""
        structs = {5: ParamStructEntry(index=5, name="Counter", unit=0, type_code=DataType.UINT32, writable=False)}

        data = struct.pack("<BH", 1, 5) + struct.pack("<I", 1000000)
        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (5, 1000000)


class TestParseStructResponse:
    """Tests for parse_struct_response."""

    def test_single_param(self):
        """Test parsing single parameter structure."""
        # Build response: paramsNo=1, firstIndex=0, name, unit, type, extra, range
        data = struct.pack("<BH", 1, 0)
        data += b"Temperature\x00"  # name
        data += b"C\x00"  # unit
        data += struct.pack("<BB", 0x22, 0x00)  # type=INT16|writable, extra=0
        data += struct.pack("<hh", 10, 80)  # min=10, max=80

        entries = parse_struct_response(data)

        assert len(entries) == 1
        assert entries[0].index == 0
        assert entries[0].name == "Temperature"
        assert entries[0].unit == 1  # CELSIUS
        assert entries[0].type_code == 2  # INT16
        assert entries[0].writable is True
        assert entries[0].min_value == 10.0
        assert entries[0].max_value == 80.0

    def test_multiple_params(self):
        """Test parsing multiple parameter structures."""
        data = struct.pack("<BH", 2, 5)

        # Param 1
        data += b"Pressure\x00"
        data += b"%\x00"
        data += struct.pack("<BB", 0x05, 0x00)  # type=UINT16, not writable
        data += struct.pack("<HH", 0, 100)  # min=0, max=100

        # Param 2
        data += b"OnOff\x00"
        data += b"\x00"  # no unit
        data += struct.pack("<BB", 0x2A, 0x00)  # type=BOOL|writable
        data += struct.pack("<hh", 0, 1)  # min=0, max=1

        entries = parse_struct_response(data)

        assert len(entries) == 2

        assert entries[0].index == 5
        assert entries[0].name == "Pressure"
        assert entries[0].unit == 6  # PERCENT
        assert entries[0].type_code == 5  # UINT16
        assert entries[0].writable is False

        assert entries[1].index == 6
        assert entries[1].name == "OnOff"
        assert entries[1].type_code == 10  # BOOL
        assert entries[1].writable is True

    def test_no_range_flags(self):
        """Test parsing with range flags indicating no min/max."""
        data = struct.pack("<BH", 1, 0)
        data += b"NoRange\x00"
        data += b"\x00"
        data += struct.pack("<BB", 0x02, 0xC0)  # extra=0xC0: no min, no max
        data += struct.pack("<hh", 0, 0)  # ignored

        entries = parse_struct_response(data)

        assert len(entries) == 1
        assert entries[0].min_value is None
        assert entries[0].max_value is None

    def test_too_short(self):
        """Test with too-short data."""
        with pytest.raises(ValueError, match="too short"):
            parse_struct_response(b"\x01\x00")


# ============================================================================
# Test Build Functions
# ============================================================================


class TestBuildFunctions:
    """Tests for request building functions."""

    def test_build_get_params_request(self):
        """Test building GET_PARAMS request."""
        data = build_get_params_request(start_index=100, count=50)

        assert len(data) == 3
        assert data[0] == 50  # count
        assert struct.unpack("<H", data[1:3])[0] == 100  # start_index

    def test_build_struct_request(self):
        """Test building struct request."""
        data = build_struct_request(start_index=0, count=25)

        assert len(data) == 3
        assert data[0] == 25
        assert struct.unpack("<H", data[1:3])[0] == 0

    def test_build_modify_param_int16(self):
        """Test building MODIFY_PARAM request for INT16."""
        data = build_modify_param_request(index=42, value=65, type_code=DataType.INT16)

        assert len(data) == 4  # 2 (index) + 2 (int16)
        assert struct.unpack("<H", data[0:2])[0] == 42
        assert struct.unpack("<h", data[2:4])[0] == 65

    def test_build_modify_param_float(self):
        """Test building MODIFY_PARAM request for FLOAT."""
        data = build_modify_param_request(index=10, value=3.14, type_code=DataType.FLOAT)

        assert len(data) == 6  # 2 (index) + 4 (float)
        assert struct.unpack("<H", data[0:2])[0] == 10
        assert abs(struct.unpack("<f", data[2:6])[0] - 3.14) < 0.01

    def test_build_modify_param_bool(self):
        """Test building MODIFY_PARAM request for BOOL."""
        data = build_modify_param_request(index=5, value=True, type_code=DataType.BOOL)

        assert len(data) == 3  # 2 (index) + 1 (bool)
        assert struct.unpack("<H", data[0:2])[0] == 5
        assert data[2] == 1


# ============================================================================
# Test ProtocolHandler
# ============================================================================


class TestProtocolHandler:
    """Tests for ProtocolHandler class."""

    DEST_ADDR = 1  # Default controller address

    def _make_handler(self) -> tuple[ProtocolHandler, MagicMock, ParameterCache]:
        """Create handler with mocked connection."""
        conn = MagicMock(spec=SerialConnection)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.5,
        )
        return handler, conn, cache

    def _response_frame(self, command: int, data: bytes = b"") -> Frame:
        """Create a mock response frame from the controller."""
        frame = Frame(destination=131, command=command, data=data)
        frame.source = self.DEST_ADDR  # Response comes FROM the controller
        return frame

    @pytest.mark.asyncio
    async def test_init(self):
        """Test handler initialization."""
        handler, conn, cache = self._make_handler()

        assert handler.connected is True
        assert handler.param_count == 0
        assert handler.running is False

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping the handler."""
        handler, conn, cache = self._make_handler()
        conn.connected = False  # Prevent actual polling

        await handler.start()
        assert handler.running is True

        await handler.stop()
        assert handler.running is False

    @pytest.mark.asyncio
    async def test_send_and_receive_success(self):
        """Test successful send and receive."""
        handler, conn, cache = self._make_handler()

        # Mock writer and reader
        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, b"\x01\x00\x00\x2d\x00")
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is not None
        assert result.command == Command.GET_PARAMS_RESPONSE

    @pytest.mark.asyncio
    async def test_send_and_receive_write_failure(self):
        """Test send failure."""
        handler, conn, cache = self._make_handler()

        handler._writer.write_frame = AsyncMock(return_value=False)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_send_and_receive_timeout(self):
        """Test receive timeout."""
        handler, conn, cache = self._make_handler()

        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=None)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_send_and_receive_wrong_command(self):
        """Test receiving wrong response command."""
        handler, conn, cache = self._make_handler()

        wrong_response = self._response_frame(Command.GET_SETTINGS_RESPONSE)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=wrong_response)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_param_structs(self):
        """Test fetching parameter structures."""
        handler, conn, cache = self._make_handler()

        # Build mock response data
        response_data = struct.pack("<BH", 1, 0)
        response_data += b"TestParam\x00"
        response_data += b"C\x00"
        response_data += struct.pack("<BB", 0x22, 0x00)  # INT16, writable
        response_data += struct.pack("<hh", 0, 100)

        response_frame = self._response_frame(Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, response_data)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        entries = await handler.fetch_param_structs(0, 50)

        assert len(entries) == 1
        assert entries[0].name == "TestParam"
        assert entries[0].type_code == DataType.INT16
        assert handler.param_count == 1

    @pytest.mark.asyncio
    async def test_fetch_param_values(self):
        """Test fetching parameter values."""
        handler, conn, cache = self._make_handler()

        # Pre-populate structs
        handler._param_structs = {
            0: ParamStructEntry(index=0, name="Temp", unit=1, type_code=DataType.INT16, writable=True),
            1: ParamStructEntry(index=1, name="Pressure", unit=6, type_code=DataType.UINT8, writable=False),
        }

        response_data = struct.pack("<BH", 2, 0)
        response_data += struct.pack("<h", 55)  # Temp = 55
        response_data += struct.pack("<B", 80)  # Pressure = 80

        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        results = await handler.fetch_param_values(0, 2)

        assert len(results) == 2
        assert results[0] == (0, 55)
        assert results[1] == (1, 80)

    @pytest.mark.asyncio
    async def test_read_params_updates_cache(self):
        """Test that read_params updates the cache."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="Temp",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_value=10.0,
                max_value=90.0,
            ),
        }

        response_data = struct.pack("<BH", 1, 0) + struct.pack("<h", 65)
        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        params = await handler.read_params(0, 1)

        assert len(params) == 1
        assert params[0].name == "Temp"
        assert params[0].value == 65

        # Verify cache was updated
        cached = await cache.get("Temp")
        assert cached is not None
        assert cached.value == 65
        assert cached.min_value == 10.0
        assert cached.max_value == 90.0

    @pytest.mark.asyncio
    async def test_write_param_success(self):
        """Test successful parameter write."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="SetPoint",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            ),
        }
        await cache.set(
            Parameter(
                index=0,
                name="SetPoint",
                value=50,
                type=2,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        response_frame = self._response_frame(Command.MODIFY_PARAM_RESPONSE)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        result = await handler.write_param("SetPoint", 65)

        assert result is True

        # Verify cache was updated
        cached = await cache.get("SetPoint")
        assert cached is not None
        assert cached.value == 65

    @pytest.mark.asyncio
    async def test_write_param_not_found(self):
        """Test writing nonexistent parameter raises error."""
        handler, conn, cache = self._make_handler()

        with pytest.raises(ValueError, match="not found"):
            await handler.write_param("NonExistent", 42)

    @pytest.mark.asyncio
    async def test_write_param_read_only(self):
        """Test writing read-only parameter raises error."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="ReadOnly",
                unit=0,
                type_code=DataType.INT16,
                writable=False,
            ),
        }
        await cache.set(
            Parameter(
                index=0,
                name="ReadOnly",
                value=42,
                type=2,
                unit=0,
                writable=False,
            )
        )

        with pytest.raises(ValueError, match="read-only"):
            await handler.write_param("ReadOnly", 99)

    @pytest.mark.asyncio
    async def test_write_param_below_min(self):
        """Test writing value below minimum raises error."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="Temp",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            ),
        }
        await cache.set(
            Parameter(
                index=0,
                name="Temp",
                value=50,
                type=2,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        with pytest.raises(ValueError, match="below minimum"):
            await handler.write_param("Temp", 10)

    @pytest.mark.asyncio
    async def test_write_param_above_max(self):
        """Test writing value above maximum raises error."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="Temp",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            ),
        }
        await cache.set(
            Parameter(
                index=0,
                name="Temp",
                value=50,
                type=2,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        with pytest.raises(ValueError, match="above maximum"):
            await handler.write_param("Temp", 100)

    @pytest.mark.asyncio
    async def test_write_param_timeout(self):
        """Test write with no response returns False."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(
                index=0,
                name="Temp",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
            ),
        }
        await cache.set(
            Parameter(
                index=0,
                name="Temp",
                value=50,
                type=2,
                unit=1,
                writable=True,
            )
        )

        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=None)

        result = await handler.write_param("Temp", 60)

        assert result is False

        # Cache should not be updated on failure
        cached = await cache.get("Temp")
        assert cached.value == 50

    @pytest.mark.asyncio
    async def test_discover_params(self):
        """Test parameter discovery."""
        handler, conn, cache = self._make_handler()

        # First call returns 2 params, second call returns empty (end of params)
        call_count = 0

        async def mock_fetch_structs(start_index, count):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                entries = [
                    ParamStructEntry(0, "A", 0, DataType.INT16, True),
                    ParamStructEntry(1, "B", 0, DataType.UINT8, False),
                ]
                for e in entries:
                    handler._param_structs[e.index] = e
                return entries
            return []

        handler.fetch_param_structs = mock_fetch_structs

        total = await handler.discover_params()

        assert total == 2
        assert handler.param_count == 2

    @pytest.mark.asyncio
    async def test_poll_all_params(self):
        """Test polling all known parameters."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(0, "A", 0, DataType.INT16, True),
            1: ParamStructEntry(1, "B", 0, DataType.UINT8, False),
        }

        response_data = struct.pack("<BH", 2, 0)
        response_data += struct.pack("<h", 42)
        response_data += struct.pack("<B", 99)

        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(return_value=response_frame)

        total = await handler.poll_all_params()

        assert total == 2
        assert cache.count == 2

    @pytest.mark.asyncio
    async def test_poll_all_no_structs(self):
        """Test polling when no param structs are known returns 0."""
        handler, conn, cache = self._make_handler()

        total = await handler.poll_all_params()
        assert total == 0

    @pytest.mark.asyncio
    async def test_send_no_expected_response(self):
        """Test send without expecting response (fire-and-forget)."""
        handler, conn, cache = self._make_handler()

        handler._writer.write_frame = AsyncMock(return_value=True)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=None,
        )

        assert result is None
        handler._writer.write_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_params_keeps_existing_on_failure(self):
        """Test that discover_params keeps existing structs when discovery returns nothing."""
        handler, conn, cache = self._make_handler()

        # Pre-populate with existing structures
        handler._param_structs = {
            0: ParamStructEntry(0, "Existing", 0, DataType.INT16, True),
        }

        # Mock fetch_param_structs to return nothing (simulating communication failure)
        handler.fetch_param_structs = AsyncMock(return_value=[])

        total = await handler.discover_params()

        # Should keep existing structures
        assert total == 1
        assert handler.param_count == 1
        assert 0 in handler._param_structs
        assert handler._param_structs[0].name == "Existing"

    @pytest.mark.asyncio
    async def test_poll_loop_waits_when_disconnected(self):
        """Test that poll loop skips polling when not connected."""
        handler, conn, cache = self._make_handler()
        conn.connected = False

        handler._param_structs = {
            0: ParamStructEntry(0, "Temp", 0, DataType.INT16, True),
        }

        poll_mock = AsyncMock()
        handler.poll_all_params = poll_mock
        handler._poll_interval = 0.01

        await handler.start()
        await asyncio.sleep(0.05)
        await handler.stop()

        # Should not have polled since disconnected
        poll_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_loop_rediscovers_on_reconnect(self):
        """Test that poll loop re-discovers params when connection is restored."""
        handler, conn, cache = self._make_handler()
        conn.connected = False
        handler._poll_interval = 0.01

        discover_mock = AsyncMock(return_value=2)
        handler.discover_params = discover_mock
        handler.poll_all_params = AsyncMock(return_value=2)

        await handler.start()
        await asyncio.sleep(0.03)

        # Simulate reconnection
        conn.connected = True
        await asyncio.sleep(0.05)
        await handler.stop()

        # Should have called discover_params after reconnection
        discover_mock.assert_called()

    @pytest.mark.asyncio
    async def test_poll_loop_handles_connection_error(self):
        """Test that poll loop handles ConnectionError gracefully."""
        handler, conn, cache = self._make_handler()
        handler._poll_interval = 0.01

        handler._param_structs = {
            0: ParamStructEntry(0, "Temp", 0, DataType.INT16, True),
        }

        call_count = 0

        async def failing_poll():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("Serial port disconnected")
            return 1

        handler.poll_all_params = failing_poll

        await handler.start()
        await asyncio.sleep(0.08)
        await handler.stop()

        # Should have retried after ConnectionError
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_poll_loop_handles_generic_exception(self):
        """Test that poll loop handles unexpected exceptions without crashing."""
        handler, conn, cache = self._make_handler()
        handler._poll_interval = 0.01

        handler._param_structs = {
            0: ParamStructEntry(0, "Temp", 0, DataType.INT16, True),
        }

        call_count = 0

        async def sometimes_failing_poll():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Unexpected error")
            return 1

        handler.poll_all_params = sometimes_failing_poll

        await handler.start()
        await asyncio.sleep(0.05)
        await handler.stop()

        # Should have continued after the error
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_send_and_receive_response_validator(self):
        """Test that response_validator filters frames."""
        handler, conn, cache = self._make_handler()

        # First frame passes src+cmd but fails validator, second passes all
        rejected_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, b"\x01\x64\x00")
        accepted_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, b"\x01\x00\x00\x2d\x00")

        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(side_effect=[rejected_frame, accepted_frame])

        def validator(frame: Frame) -> bool:
            first_index = struct.unpack("<H", frame.data[1:3])[0]
            return first_index == 0

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
            response_validator=validator,
        )

        assert result is not None
        assert result is accepted_frame
        assert handler._reader.read_frame.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_param_values_skips_wrong_first_index(self):
        """Test that fetch_param_values skips responses with mismatched firstIndex."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(index=0, name="Temp", unit=1, type_code=DataType.INT16, writable=True),
        }

        # First response has firstIndex=100 (from another device's request)
        wrong_response_data = struct.pack("<BH", 100, 100) + b"\x00" * 200
        wrong_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, wrong_response_data)

        # Second response has firstIndex=0 (our response)
        correct_response_data = struct.pack("<BH", 1, 0) + struct.pack("<h", 42)
        correct_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, correct_response_data)

        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(side_effect=[wrong_frame, correct_frame])

        results = await handler.fetch_param_values(0, 1)

        assert len(results) == 1
        assert results[0] == (0, 42)

    @pytest.mark.asyncio
    async def test_fetch_param_structs_skips_wrong_first_index(self):
        """Test that fetch_param_structs skips responses with mismatched firstIndex."""
        handler, conn, cache = self._make_handler()

        # First response has firstIndex=50 (not our request for index 0)
        wrong_data = struct.pack("<BH", 1, 50)
        wrong_data += b"WrongParam\x00C\x00"
        wrong_data += struct.pack("<BB", 0x22, 0x00)
        wrong_data += struct.pack("<hh", 0, 100)
        wrong_frame = self._response_frame(Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, wrong_data)

        # Second response has firstIndex=0 (our response)
        correct_data = struct.pack("<BH", 1, 0)
        correct_data += b"RightParam\x00C\x00"
        correct_data += struct.pack("<BB", 0x22, 0x00)
        correct_data += struct.pack("<hh", 0, 100)
        correct_frame = self._response_frame(Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, correct_data)

        handler._writer.write_frame = AsyncMock(return_value=True)
        handler._reader.read_frame = AsyncMock(side_effect=[wrong_frame, correct_frame])

        entries = await handler.fetch_param_structs(0, 50)

        assert len(entries) == 1
        assert entries[0].name == "RightParam"
        assert entries[0].index == 0
