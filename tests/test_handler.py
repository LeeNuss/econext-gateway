"""Unit tests for protocol handler."""

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Alarm, Parameter
from econext_gateway.protocol.constants import (
    ALARM_REQUEST_PREFIX,
    PANEL_ADDRESS,
    SERVICE_ANS_CMD,
    SERVICE_CMD,
    Command,
    DataType,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.protocol.handler import (
    ParamStructEntry,
    ProtocolHandler,
    build_get_params_request,
    build_modify_param_request,
    build_struct_request,
    parse_get_params_request,
    parse_get_params_response,
    parse_struct_response,
)
from econext_gateway.serial.connection import GM3SerialTransport
from econext_gateway.serial.protocol import GM3Protocol

# Must match conftest.TEST_BUS_ADDRESS
TEST_BUS_ADDRESS = 200

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

        # paramsNo=1, firstIndex=0, separator, value=45 (int16 LE)
        data = struct.pack("<BH", 1, 0) + b"\xc2" + struct.pack("<h", 45)

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
        data += b"\xc2" + struct.pack("<h", -100)  # sep + A: int16
        data += b"\xc2" + struct.pack("<B", 200)  # sep + B: uint8
        data += b"\xc2" + struct.pack("<f", 3.14)  # sep + C: float

        results = parse_get_params_response(data, structs)

        assert len(results) == 3
        assert results[0] == (10, -100)
        assert results[1] == (11, 200)
        assert results[2][0] == 12
        assert abs(results[2][1] - 3.14) < 0.01

    def test_bool_param(self):
        """Test parsing BOOL parameter."""
        structs = {0: ParamStructEntry(index=0, name="Flag", unit=0, type_code=DataType.BOOL, writable=True)}

        data = struct.pack("<BH", 1, 0) + b"\xc2" + struct.pack("<B", 1)
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
        data += b"\xc2" + struct.pack("<h", 42)  # sep + A
        data += b"\xc2" + struct.pack("<h", 99)  # sep + Unknown - should stop

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

        data = struct.pack("<BH", 1, 5) + b"\xc2" + struct.pack("<I", 1000000)
        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (5, 1000000)

    def test_string_param(self):
        """Test parsing STRING parameter with null terminator."""
        structs = {0: ParamStructEntry(index=0, name="Version", unit=0, type_code=DataType.STRING, writable=False)}

        data = struct.pack("<BH", 1, 0) + b"\xc2" + b"S024.25\x00"
        results = parse_get_params_response(data, structs)

        assert len(results) == 1
        assert results[0] == (0, "S024.25")

    def test_mixed_string_and_numeric(self):
        """Test parsing mixed string and numeric params with separators."""
        structs = {
            0: ParamStructEntry(index=0, name="Name", unit=0, type_code=DataType.STRING, writable=False),
            1: ParamStructEntry(index=1, name="Code", unit=0, type_code=DataType.UINT8, writable=False),
            2: ParamStructEntry(index=2, name="Count", unit=0, type_code=DataType.UINT32, writable=False),
        }

        data = struct.pack("<BH", 3, 0)
        data += b"\xc2" + b"Hello\x00"  # sep + string
        data += b"\xc2" + struct.pack("<B", 42)  # sep + uint8
        data += b"\xc2" + struct.pack("<I", 99999)  # sep + uint32

        results = parse_get_params_response(data, structs)

        assert len(results) == 3
        assert results[0] == (0, "Hello")
        assert results[1] == (1, 42)
        assert results[2] == (2, 99999)


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

    def test_param_ref_min_max(self):
        """Test that parameter index references are stored separately from literal values."""
        data = struct.pack("<BH", 1, 103)
        data += b"HDWTSetPoint\x00"
        data += b"C\x00"
        # type=INT16|writable (0x22), extra=0x30 (bit4=min ref, bit5=max ref)
        data += struct.pack("<BB", 0x22, 0x30)
        data += struct.pack("<HH", 107, 108)  # param refs, not literal values

        entries = parse_struct_response(data)

        assert len(entries) == 1
        assert entries[0].index == 103
        assert entries[0].min_value is None
        assert entries[0].max_value is None
        assert entries[0].min_param_ref == 107
        assert entries[0].max_param_ref == 108

    def test_mixed_literal_and_ref(self):
        """Test literal min with referenced max."""
        data = struct.pack("<BH", 1, 107)
        data += b"HDWMinSetTemp\x00"
        data += b"C\x00"
        # type=INT16|writable (0x22), extra=0x20 (bit5=max ref, min is literal)
        data += struct.pack("<BB", 0x22, 0x20)
        data += struct.pack("<hH", 20, 108)  # min=20 literal, max=108 param ref

        entries = parse_struct_response(data)

        assert len(entries) == 1
        assert entries[0].min_value == 20.0
        assert entries[0].max_value is None
        assert entries[0].min_param_ref is None
        assert entries[0].max_param_ref == 108

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

        # 14 (auth) + 1 (mode) + 2 (index) + 2 (int16) = 19
        assert len(data) == 19
        assert data[:14] == b"\x55\x53\x45\x52\x2d\x30\x30\x30\x00\x34\x30\x39\x36\x00"
        assert data[14] == 0x01  # mode byte
        assert struct.unpack("<H", data[15:17])[0] == 42
        assert struct.unpack("<h", data[17:19])[0] == 65

    def test_build_modify_param_float(self):
        """Test building MODIFY_PARAM request for FLOAT."""
        data = build_modify_param_request(index=10, value=3.14, type_code=DataType.FLOAT)

        # 14 (auth) + 1 (mode) + 2 (index) + 4 (float) = 21
        assert len(data) == 21
        assert data[14] == 0x01
        assert struct.unpack("<H", data[15:17])[0] == 10
        assert abs(struct.unpack("<f", data[17:21])[0] - 3.14) < 0.01

    def test_build_modify_param_bool(self):
        """Test building MODIFY_PARAM request for BOOL."""
        data = build_modify_param_request(index=5, value=True, type_code=DataType.BOOL)

        # 14 (auth) + 1 (mode) + 2 (index) + 1 (bool) = 18
        assert len(data) == 18
        assert data[14] == 0x01
        assert struct.unpack("<H", data[15:17])[0] == 5
        assert data[17] == 1


# ============================================================================
# Test ProtocolHandler
# ============================================================================


class TestProtocolHandler:
    """Tests for ProtocolHandler class."""

    DEST_ADDR = 1  # Default controller address

    @pytest.fixture(autouse=True)
    def _paired_file(self, paired_address_file):
        self._paired_address_file = paired_address_file

    def _make_handler(self) -> tuple[ProtocolHandler, MagicMock, ParameterCache]:
        """Create handler with mocked connection."""
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        conn.protocol = MagicMock(spec=GM3Protocol)
        conn.protocol.write_frame = AsyncMock(return_value=True)
        conn.protocol.receive_frame = AsyncMock(return_value=None)
        conn.protocol.reset_buffer = MagicMock()
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.5,
            token_timeout=0,
            token_required=False,
            paired_address_file=self._paired_address_file,
        )
        return handler, conn, cache

    def _response_frame(self, command: int, data: bytes = b"") -> Frame:
        """Create a mock response frame from the controller."""
        frame = Frame(destination=TEST_BUS_ADDRESS, command=command, data=data)
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
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

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

        handler._connection.protocol.write_frame = AsyncMock(return_value=False)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_send_and_receive_timeout(self):
        """Test receive timeout when bus is silent."""
        handler, conn, cache = self._make_handler()
        handler._request_timeout = 0.05  # Short timeout for test speed

        async def simulated_read(*args, **kwargs):
            await asyncio.sleep(0.02)
            return None

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=simulated_read)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=Command.GET_PARAMS_RESPONSE,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_send_and_receive_wrong_command(self):
        """Test that wrong command frames are skipped until timeout."""
        handler, conn, cache = self._make_handler()
        handler._request_timeout = 0.05

        wrong_response = self._response_frame(Command.GET_SETTINGS_RESPONSE)
        call_count = 0

        async def read_wrong_then_silent(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return wrong_response
            await asyncio.sleep(0.02)
            return None

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=read_wrong_then_silent)

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
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

        entries, end_of_range = await handler.fetch_param_structs(0, 50)

        assert len(entries) == 1
        assert entries[0].name == "TestParam"
        assert entries[0].type_code == DataType.INT16
        assert end_of_range is False
        assert handler.param_count == 1

    @pytest.mark.asyncio
    async def test_fetch_param_structs_no_data(self):
        """Test that NO_DATA response signals end of range."""
        handler, conn, cache = self._make_handler()

        no_data_frame = self._response_frame(Command.NO_DATA, b"")
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=no_data_frame)

        entries, end_of_range = await handler.fetch_param_structs(500, 100)

        assert len(entries) == 0
        assert end_of_range is True

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
        response_data += b"\xc2" + struct.pack("<h", 55)  # sep + Temp = 55
        response_data += b"\xc2" + struct.pack("<B", 80)  # sep + Pressure = 80

        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

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

        response_data = struct.pack("<BH", 1, 0) + b"\xc2" + struct.pack("<h", 65)
        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

        params = await handler.read_params(0, 1)

        assert len(params) == 1
        assert params[0].name == "Temp"
        assert params[0].value == 65

        # Verify cache was updated (keyed by index)
        cached = await cache.get(0)
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
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

        result = await handler.write_param("SetPoint", 65)

        assert result is True

        # Verify cache was updated (keyed by index)
        cached = await cache.get(0)
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

        handler._request_timeout = 0.05

        async def simulated_read(*args, **kwargs):
            await asyncio.sleep(0.02)
            return None

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=simulated_read)

        result = await handler.write_param("Temp", 60)

        assert result is False

        # Cache should not be updated on failure
        cached = await cache.get(0)
        assert cached.value == 50

    @pytest.mark.asyncio
    async def test_write_param_acquires_and_returns_token(self):
        """Test that write_param waits for token and returns it after."""
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.5,
            token_timeout=5.0,
            token_required=True,
            paired_address_file=self._paired_address_file,
        )

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

        # Mock _wait_for_token to simulate receiving token
        async def mock_wait_for_token():
            handler._has_token = True

        handler._wait_for_token = mock_wait_for_token

        # Mock _return_token to track it was called
        return_token_called = False
        original_return = handler._return_token

        async def mock_return_token():
            nonlocal return_token_called
            return_token_called = True
            await original_return()

        handler._return_token = mock_return_token

        response_frame = self._response_frame(Command.MODIFY_PARAM_RESPONSE)
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

        result = await handler.write_param("SetPoint", 65)

        assert result is True
        assert return_token_called is True
        assert handler._has_token is False

    @pytest.mark.asyncio
    async def test_write_param_returns_token_on_failure(self):
        """Test that token is returned even when write fails."""
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.05,
            token_timeout=5.0,
            token_required=True,
            paired_address_file=self._paired_address_file,
        )

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

        async def mock_wait_for_token():
            handler._has_token = True

        handler._wait_for_token = mock_wait_for_token

        return_token_called = False

        async def mock_return_token():
            nonlocal return_token_called
            return_token_called = True
            handler._has_token = False

        handler._return_token = mock_return_token

        # Simulate no response (timeout)
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=None)

        result = await handler.write_param("Temp", 60)

        assert result is False
        assert return_token_called is True
        assert handler._has_token is False

    @pytest.mark.asyncio
    async def test_build_modify_param_auth_header(self):
        """Test that auth header matches original webserver format."""
        data = build_modify_param_request(index=0, value=1, type_code=DataType.BOOL)

        # Auth header is "USER-000\x004096\x00" in ASCII
        auth = data[:14]
        assert auth == b"USER-000\x004096\x00"

    @pytest.mark.asyncio
    async def test_resolve_min_max_with_param_refs(self):
        """Test that dynamic min/max refs are resolved from cached param values."""
        handler, conn, cache = self._make_handler()

        # Set up param structs: HDWTSetPoint refs HDWMinSetTemp and HDWMaxSetTemp
        handler._param_structs = {
            103: ParamStructEntry(
                index=103,
                name="HDWTSetPoint",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_param_ref=107,
                max_param_ref=108,
            ),
            107: ParamStructEntry(
                index=107,
                name="HDWMinSetTemp",
                unit=0,
                type_code=DataType.INT16,
                writable=True,
                min_value=20.0,
                max_value=65.0,
            ),
            108: ParamStructEntry(
                index=108,
                name="HDWMaxSetTemp",
                unit=0,
                type_code=DataType.INT16,
                writable=True,
                min_value=35.0,
                max_value=80.0,
            ),
        }

        # Cache the referenced params with their current values
        await cache.set(Parameter(index=107, name="HDWMinSetTemp", value=35, type=2, unit=0, writable=True))
        await cache.set(Parameter(index=108, name="HDWMaxSetTemp", value=65, type=2, unit=0, writable=True))

        entry = handler._param_structs[103]
        min_val, max_val = await handler._resolve_min_max(entry)

        assert min_val == 35.0
        assert max_val == 65.0

    @pytest.mark.asyncio
    async def test_resolve_min_max_ref_not_cached(self):
        """Test that unresolvable refs return None."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            103: ParamStructEntry(
                index=103,
                name="HDWTSetPoint",
                unit=1,
                type_code=DataType.INT16,
                writable=True,
                min_param_ref=107,
                max_param_ref=108,
            ),
            107: ParamStructEntry(
                index=107,
                name="HDWMinSetTemp",
                unit=0,
                type_code=DataType.INT16,
                writable=True,
            ),
        }
        # Referenced params not in cache yet
        min_val, max_val = await handler._resolve_min_max(handler._param_structs[103])

        assert min_val is None
        assert max_val is None

    @pytest.mark.asyncio
    async def test_resolve_min_max_literal_values(self):
        """Test that literal min/max values pass through unchanged."""
        handler, conn, cache = self._make_handler()

        entry = ParamStructEntry(
            index=0,
            name="Temp",
            unit=1,
            type_code=DataType.INT16,
            writable=True,
            min_value=10.0,
            max_value=80.0,
        )
        handler._param_structs = {0: entry}

        min_val, max_val = await handler._resolve_min_max(entry)

        assert min_val == 10.0
        assert max_val == 80.0

    @pytest.mark.asyncio
    async def test_discover_params(self):
        """Test parameter discovery with NO_DATA termination."""
        handler, conn, cache = self._make_handler()

        # First call returns 2 regulator params, second returns NO_DATA
        # Third call returns 1 panel param, fourth returns NO_DATA
        call_count = 0

        async def mock_fetch_structs(start_index, count, destination=None, with_range=True):
            nonlocal call_count
            call_count += 1
            if destination is None:
                # Regulator params
                if start_index == 0:
                    entries = [
                        ParamStructEntry(0, "A", 0, DataType.INT16, True),
                        ParamStructEntry(1, "B", 0, DataType.UINT8, False),
                    ]
                    for e in entries:
                        handler._param_structs[e.index] = e
                    return entries, False
                return [], True  # NO_DATA
            else:
                # Panel params (destination=PANEL_ADDRESS)
                if start_index == 0:
                    entries = [
                        ParamStructEntry(0, "PanelA", 0, DataType.INT16, True),
                    ]
                    for e in entries:
                        handler._param_structs[e.index] = e
                    return entries, False
                return [], True  # NO_DATA

        handler.fetch_param_structs = mock_fetch_structs
        handler._has_token = True

        total = await handler.discover_params()

        # 2 regulator + 1 panel = 3
        assert total == 3
        assert handler.param_count == 3

    @pytest.mark.asyncio
    async def test_poll_all_params(self):
        """Test polling all known parameters."""
        handler, conn, cache = self._make_handler()

        handler._param_structs = {
            0: ParamStructEntry(0, "A", 0, DataType.INT16, True),
            1: ParamStructEntry(1, "B", 0, DataType.UINT8, False),
        }

        response_data = struct.pack("<BH", 2, 0)
        response_data += b"\xc2" + struct.pack("<h", 42)
        response_data += b"\xc2" + struct.pack("<B", 99)

        response_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, response_data)
        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(return_value=response_frame)

        total = await handler.poll_all_params()

        assert total == 2
        assert cache.count == 2

    @pytest.mark.asyncio
    async def test_poll_all_params_partial_response(self):
        """Test polling handles controller returning fewer params than requested."""
        handler, conn, cache = self._make_handler()
        handler._params_per_request = 4  # Request all 4 at once

        handler._param_structs = {
            0: ParamStructEntry(0, "A", 0, DataType.INT16, True),
            1: ParamStructEntry(1, "B", 0, DataType.INT16, False),
            2: ParamStructEntry(2, "C", 0, DataType.INT16, True),
            3: ParamStructEntry(3, "D", 0, DataType.INT16, False),
        }

        # First response: controller only returns params 0-1 (partial)
        response1_data = struct.pack("<BH", 2, 0)
        response1_data += b"\xc2" + struct.pack("<h", 10)
        response1_data += b"\xc2" + struct.pack("<h", 20)
        response1 = self._response_frame(Command.GET_PARAMS_RESPONSE, response1_data)

        # Second response: controller returns params 2-3
        response2_data = struct.pack("<BH", 2, 2)
        response2_data += b"\xc2" + struct.pack("<h", 30)
        response2_data += b"\xc2" + struct.pack("<h", 40)
        response2 = self._response_frame(Command.GET_PARAMS_RESPONSE, response2_data)

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=[response1, response2])

        total = await handler.poll_all_params()

        assert total == 4
        assert cache.count == 4

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

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)

        result = await handler.send_and_receive(
            Command.GET_PARAMS,
            b"\x01\x00\x00",
            expected_response=None,
        )

        assert result is None
        handler._connection.protocol.write_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_params_keeps_existing_on_failure(self):
        """Test that discover_params keeps existing structs when discovery returns nothing."""
        handler, conn, cache = self._make_handler()

        # Pre-populate with existing structures
        handler._param_structs = {
            0: ParamStructEntry(0, "Existing", 0, DataType.INT16, True),
        }

        # Mock fetch_param_structs to return nothing (simulating communication failure)
        handler.fetch_param_structs = AsyncMock(return_value=([], False))

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
        handler.read_alarms = AsyncMock(return_value=[])

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
        handler.read_alarms = AsyncMock(return_value=[])

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
        handler.read_alarms = AsyncMock(return_value=[])

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

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=[rejected_frame, accepted_frame])

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
        assert handler._connection.protocol.receive_frame.call_count == 2

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
        correct_response_data = struct.pack("<BH", 1, 0) + b"\xc2" + struct.pack("<h", 42)
        correct_frame = self._response_frame(Command.GET_PARAMS_RESPONSE, correct_response_data)

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=[wrong_frame, correct_frame])

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

        handler._connection.protocol.write_frame = AsyncMock(return_value=True)
        handler._connection.protocol.receive_frame = AsyncMock(side_effect=[wrong_frame, correct_frame])

        entries, end_of_range = await handler.fetch_param_structs(0, 50)

        assert len(entries) == 1
        assert entries[0].name == "RightParam"
        assert entries[0].index == 0
        assert end_of_range is False


# ============================================================================
# Test _discover_address_space
# ============================================================================


class TestDiscoverAddressSpace:
    """Tests for _discover_address_space retry and store_offset logic."""

    DEST_ADDR = 1

    @pytest.fixture(autouse=True)
    def _paired_file(self, paired_address_file):
        self._paired_address_file = paired_address_file

    def _make_handler(self) -> tuple[ProtocolHandler, MagicMock, ParameterCache]:
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.5,
            token_timeout=0,
            token_required=False,
            paired_address_file=self._paired_address_file,
        )
        return handler, conn, cache

    @pytest.mark.asyncio
    async def test_store_offset_applied(self):
        """Test that store_offset is added to entry indices."""
        handler, conn, cache = self._make_handler()

        call_count = 0

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            nonlocal call_count
            call_count += 1
            if start_index == 0:
                return [
                    ParamStructEntry(0, "PanelA", 0, DataType.INT16, True),
                    ParamStructEntry(1, "PanelB", 0, DataType.UINT8, False),
                ], False
            return [], True  # NO_DATA

        handler.fetch_param_structs = mock_fetch
        structs: dict[int, ParamStructEntry] = {}

        result = await handler._discover_address_space(
            "panel",
            store_offset=10000,
            destination=PANEL_ADDRESS,
            with_range=False,
            structs=structs,
        )

        assert result is True
        assert 10000 in structs
        assert 10001 in structs
        assert structs[10000].name == "PanelA"
        assert structs[10001].name == "PanelB"
        # Wire indices 0, 1 should not be present
        assert 0 not in structs
        assert 1 not in structs

    @pytest.mark.asyncio
    async def test_retry_on_empty_entries(self):
        """Test that empty response triggers retry before giving up."""
        handler, conn, cache = self._make_handler()

        call_count = 0

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            nonlocal call_count
            call_count += 1
            # First call: empty (transient failure), second: real data
            if call_count == 1:
                return [], False
            if call_count == 2:
                return [ParamStructEntry(0, "A", 0, DataType.INT16, True)], False
            return [], True  # NO_DATA

        handler.fetch_param_structs = mock_fetch
        structs: dict[int, ParamStructEntry] = {}

        result = await handler._discover_address_space(
            "regulator",
            store_offset=0,
            destination=None,
            with_range=True,
            structs=structs,
        )

        assert result is True
        assert 0 in structs
        assert call_count == 3  # empty, success, NO_DATA

    @pytest.mark.asyncio
    async def test_too_many_retries_returns_false(self):
        """Test that exceeding RETRY_ATTEMPTS returns False."""
        handler, conn, cache = self._make_handler()

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            return [], False  # Always empty but not end-of-range

        handler.fetch_param_structs = mock_fetch
        structs: dict[int, ParamStructEntry] = {}

        result = await handler._discover_address_space(
            "regulator",
            store_offset=0,
            destination=None,
            with_range=True,
            structs=structs,
        )

        assert result is False
        assert len(structs) == 0

    @pytest.mark.asyncio
    async def test_resend_counter_resets_after_success(self):
        """Test that resend counter resets after a successful batch."""
        handler, conn, cache = self._make_handler()

        call_count = 0

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            nonlocal call_count
            call_count += 1
            if start_index == 0:
                # Two failures then success for first batch
                if call_count <= 2:
                    return [], False
                return [ParamStructEntry(0, "A", 0, DataType.INT16, True)], False
            if start_index == 1:
                # Two more failures then success for second batch
                if call_count <= 5:
                    return [], False
                return [ParamStructEntry(1, "B", 0, DataType.UINT8, False)], False
            return [], True  # NO_DATA

        handler.fetch_param_structs = mock_fetch
        structs: dict[int, ParamStructEntry] = {}

        result = await handler._discover_address_space(
            "regulator",
            store_offset=0,
            destination=None,
            with_range=True,
            structs=structs,
        )

        assert result is True
        assert 0 in structs
        assert 1 in structs


# ============================================================================
# Test discover_params address space integration
# ============================================================================


class TestDiscoverParamsAddressSpaces:
    """Tests for discover_params with_range and store_offset per address space."""

    @pytest.fixture(autouse=True)
    def _paired_file(self, paired_address_file):
        self._paired_address_file = paired_address_file

    def _make_handler(self) -> tuple[ProtocolHandler, MagicMock, ParameterCache]:
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        conn.protocol = MagicMock(spec=GM3Protocol)
        conn.protocol.write_frame = AsyncMock(return_value=True)
        conn.protocol.receive_frame = AsyncMock(return_value=None)
        conn.protocol.reset_buffer = MagicMock()
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            poll_interval=1.0,
            request_timeout=0.5,
            token_timeout=0,
            token_required=False,
            paired_address_file=self._paired_address_file,
        )
        return handler, conn, cache

    @pytest.mark.asyncio
    async def test_regulator_uses_with_range_true(self):
        """Test that regulator discovery uses with_range=True."""
        handler, conn, cache = self._make_handler()
        handler._has_token = True

        captured_calls = []

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            captured_calls.append(
                {
                    "start": start_index,
                    "dest": destination,
                    "with_range": with_range,
                }
            )
            if destination is None and start_index == 0:
                entries = [ParamStructEntry(0, "RegA", 0, DataType.INT16, True)]
                for e in entries:
                    handler._param_structs[e.index] = e
                return entries, False
            # NO_DATA for everything else
            return [], True

        handler.fetch_param_structs = mock_fetch

        await handler.discover_params()

        # First call should be regulator (destination=None, with_range=True)
        reg_calls = [c for c in captured_calls if c["dest"] is None]
        assert len(reg_calls) >= 1
        assert reg_calls[0]["with_range"] is True

    @pytest.mark.asyncio
    async def test_panel_uses_with_range_false_and_panel_dest(self):
        """Test that panel discovery uses with_range=False and destination=PANEL_ADDRESS."""
        handler, conn, cache = self._make_handler()
        handler._has_token = True

        captured_calls = []

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            captured_calls.append(
                {
                    "start": start_index,
                    "dest": destination,
                    "with_range": with_range,
                }
            )
            if destination is None and start_index == 0:
                entries = [ParamStructEntry(0, "RegA", 0, DataType.INT16, True)]
                for e in entries:
                    handler._param_structs[e.index] = e
                return entries, False
            if destination == PANEL_ADDRESS and start_index == 0:
                entries = [ParamStructEntry(0, "PanelA", 0, DataType.UINT8, False)]
                for e in entries:
                    handler._param_structs[e.index + 10000] = e
                return entries, False
            return [], True

        handler.fetch_param_structs = mock_fetch

        await handler.discover_params()

        panel_calls = [c for c in captured_calls if c["dest"] == PANEL_ADDRESS]
        assert len(panel_calls) >= 1
        assert panel_calls[0]["with_range"] is False

    @pytest.mark.asyncio
    async def test_panel_params_stored_at_10000_offset(self):
        """Test that panel params are stored with 10000 offset."""
        handler, conn, cache = self._make_handler()
        handler._has_token = True

        async def mock_fetch(start_index, count, destination=None, with_range=True):
            if destination is None:
                if start_index == 0:
                    entries = [ParamStructEntry(0, "RegA", 0, DataType.INT16, True)]
                    for e in entries:
                        handler._param_structs[e.index] = e
                    return entries, False
                return [], True
            else:
                if start_index == 0:
                    entries = [ParamStructEntry(0, "PanelX", 0, DataType.UINT8, False)]
                    for e in entries:
                        handler._param_structs[e.index] = e
                    return entries, False
                return [], True

        handler.fetch_param_structs = mock_fetch

        total = await handler.discover_params()

        assert total == 2
        # Regulator at index 0
        assert 0 in handler._param_structs
        assert handler._param_structs[0].name == "RegA"
        # Panel at index 10000
        assert 10000 in handler._param_structs
        assert handler._param_structs[10000].name == "PanelX"


# ============================================================================
# Alarm Tests
# ============================================================================


class TestDecodeAlarmDate:
    """Tests for _decode_alarm_date static method."""

    def test_valid_date(self):
        # 2025-06-15 14:30:45 -> year=2025 as LE16, month=6, day=15, hour=14, min=30, sec=45
        data = struct.pack("<h", 2025) + bytes([6, 15, 14, 30, 45])
        result = ProtocolHandler._decode_alarm_date(data)
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 45

    def test_null_date_all_ff(self):
        data = b"\xff\xff\xff\xff\xff\xff\xff"
        result = ProtocolHandler._decode_alarm_date(data)
        assert result is None

    def test_short_data(self):
        result = ProtocolHandler._decode_alarm_date(b"\x01\x02\x03")
        assert result is None

    def test_invalid_month(self):
        data = struct.pack("<h", 2025) + bytes([13, 15, 14, 30, 45])
        result = ProtocolHandler._decode_alarm_date(data)
        assert result is None

    def test_invalid_day(self):
        data = struct.pack("<h", 2025) + bytes([6, 0, 14, 30, 45])
        result = ProtocolHandler._decode_alarm_date(data)
        assert result is None

    def test_year_2000_offset(self):
        # Year stored as absolute LE16, not offset from 2000
        data = struct.pack("<h", 2000) + bytes([1, 1, 0, 0, 0])
        result = ProtocolHandler._decode_alarm_date(data)
        assert result is not None
        assert result.year == 2000


class TestReadAlarms:
    """Tests for read_alarms method."""

    @pytest.fixture
    def handler(self, paired_address_file):
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        h = ProtocolHandler(
            conn, cache, token_required=False, token_timeout=0,
            paired_address_file=paired_address_file,
        )
        return h

    @pytest.mark.asyncio
    async def test_read_two_alarms_then_end(self, handler):
        """Read 2 alarms, then null date ends the list."""
        # Alarm 0: code=42, from=2025-06-15 14:30:00, to=2025-06-15 15:00:00
        from_date_0 = struct.pack("<h", 2025) + bytes([6, 15, 14, 30, 0])
        to_date_0 = struct.pack("<h", 2025) + bytes([6, 15, 15, 0, 0])
        alarm_0_data = bytes([42]) + from_date_0 + to_date_0

        # Alarm 1: code=17, from=2026-01-10 08:00:00, to=None (active)
        from_date_1 = struct.pack("<h", 2026) + bytes([1, 10, 8, 0, 0])
        to_date_1 = b"\xff\xff\xff\xff\xff\xff\xff"
        alarm_1_data = bytes([17]) + from_date_1 + to_date_1

        # End marker: null from_date
        null_data = bytes([0]) + b"\xff\xff\xff\xff\xff\xff\xff" + b"\xff\xff\xff\xff\xff\xff\xff"

        call_count = 0

        async def mock_send(command, data, expected_response=None, destination=None, **kwargs):
            nonlocal call_count
            resp_data = [alarm_0_data, alarm_1_data, null_data][call_count]
            call_count += 1
            return Frame(destination=TEST_BUS_ADDRESS, command=SERVICE_ANS_CMD, data=resp_data)

        handler.send_and_receive = mock_send

        alarms = await handler.read_alarms()

        assert len(alarms) == 2
        assert call_count == 3
        # Sorted newest first
        assert alarms[0].code == 17  # 2026 is newer
        assert alarms[0].to_date is None  # active
        assert alarms[1].code == 42  # 2025

    @pytest.mark.asyncio
    async def test_read_alarms_empty(self, handler):
        """First alarm is null -> empty list."""
        null_data = bytes([0]) + b"\xff\xff\xff\xff\xff\xff\xff" + b"\xff\xff\xff\xff\xff\xff\xff"

        async def mock_send(command, data, expected_response=None, destination=None, **kwargs):
            frame = Frame(destination=TEST_BUS_ADDRESS, command=SERVICE_ANS_CMD, data=null_data)
            frame.source = PANEL_ADDRESS
            return frame

        handler.send_and_receive = mock_send

        alarms = await handler.read_alarms()
        assert len(alarms) == 0

    @pytest.mark.asyncio
    async def test_read_alarms_no_response(self, handler):
        """No response from controller -> empty list."""

        async def mock_send(command, data, expected_response=None, destination=None, **kwargs):
            return None

        handler.send_and_receive = mock_send

        alarms = await handler.read_alarms()
        assert len(alarms) == 0

    @pytest.mark.asyncio
    async def test_read_alarms_request_format(self, handler):
        """Verify the alarm request frame format."""
        sent_commands = []

        async def mock_send(command, data, expected_response=None, destination=None, **kwargs):
            sent_commands.append((command, data, destination))
            null_data = bytes([0]) + b"\xff\xff\xff\xff\xff\xff\xff" + b"\xff\xff\xff\xff\xff\xff\xff"
            frame = Frame(destination=TEST_BUS_ADDRESS, command=SERVICE_ANS_CMD, data=null_data)
            frame.source = PANEL_ADDRESS
            return frame

        handler.send_and_receive = mock_send

        await handler.read_alarms()

        assert len(sent_commands) == 1
        cmd, data, dest = sent_commands[0]
        assert cmd == SERVICE_CMD
        assert dest == PANEL_ADDRESS
        assert data == ALARM_REQUEST_PREFIX + bytes([0])  # index 0

    @pytest.mark.asyncio
    async def test_alarms_property_returns_copy(self, handler):
        """alarms property returns a copy of the internal list."""
        handler._alarms = [
            Alarm(index=0, code=1, from_date="2025-01-01T00:00:00", to_date=None),
        ]
        result = handler.alarms
        assert len(result) == 1
        result.clear()
        assert len(handler._alarms) == 1  # original unchanged
