"""Tests for virtual thermostat: state holder, emulator, and API."""

import struct
import time

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter
from econext_gateway.core.virtual_thermostat import VirtualThermostat
from econext_gateway.protocol.codec import decode_value
from econext_gateway.protocol.constants import (
    PANEL_ADDRESS,
    Command,
    DataType,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.thermostat.emulator import (
    THERMOSTAT_IDENTITY,
    ThermostatEmulator,
    build_params_response,
    build_struct_with_range_response,
)
from econext_gateway.thermostat.params import ThermostatParam

THERMOSTAT_ADDR = 165


# ---------------------------------------------------------------------------
# VirtualThermostat unit tests
# ---------------------------------------------------------------------------


class TestVirtualThermostat:
    def test_initial_state(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        assert vt.temperature is None
        assert vt.updated_at is None
        assert vt.age_seconds is None
        assert vt.is_stale is True
        assert vt.effective_temperature == 0.0

    def test_update_temperature(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        prev_age = vt.update(21.5)
        assert prev_age is None  # First update
        assert vt.temperature == 21.5
        assert vt.is_stale is False
        assert vt.effective_temperature == 21.5
        assert vt.age_seconds is not None
        assert vt.age_seconds < 1.0

    def test_subsequent_update_returns_age(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        vt.update(20.0)
        prev_age = vt.update(21.0)
        assert prev_age is not None
        assert prev_age < 1.0

    def test_staleness_detection(self):
        vt = VirtualThermostat(max_age=0.1, stale_fallback=5.0)
        vt.update(22.0)
        assert vt.is_stale is False
        assert vt.effective_temperature == 22.0

        # Wait for staleness - keeps last value, doesn't fall back to 0
        time.sleep(0.15)
        assert vt.is_stale is True
        assert vt.effective_temperature == 22.0  # Keeps last known value

    def test_temperature_rounding(self):
        vt = VirtualThermostat()
        vt.update(21.12345)
        assert vt.temperature == 21.12

    def test_custom_stale_fallback(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=15.0)
        # Never updated = stale
        assert vt.effective_temperature == 15.0


# ---------------------------------------------------------------------------
# Response builder tests
# ---------------------------------------------------------------------------


class TestResponseBuilders:
    def test_build_struct_with_range_response(self):
        params = [
            ThermostatParam(
                index=0,
                name="RoomTemp",
                type_code=DataType.FLOAT,
                unit_string="'C",
                writable=False,
                min_value=0,
                max_value=50,
            ),
        ]
        data = build_struct_with_range_response(params, first_index=0)

        # Parse header
        assert data[0] == 1  # paramsNo
        assert struct.unpack("<H", data[1:3])[0] == 0  # firstIndex

        # Parse name
        null_pos = data.index(b"\x00", 3)
        name = data[3:null_pos].decode("utf-8")
        assert name == "RoomTemp"

        # Parse unit
        next_null = data.index(b"\x00", null_pos + 1)
        unit = data[null_pos + 1 : next_null].decode("utf-8")
        assert unit == "'C"

        # Parse type byte
        type_byte = data[next_null + 1]
        assert type_byte & 0x0F == DataType.FLOAT
        assert not (type_byte & 0x20)  # Not writable

    def test_build_struct_writable_param(self):
        params = [
            ThermostatParam(
                index=5,
                name="Setpoint",
                type_code=DataType.FLOAT,
                unit_string="'C",
                writable=True,
                min_value=10,
                max_value=30,
            ),
        ]
        data = build_struct_with_range_response(params, first_index=5)
        # Find the type byte (after two null-terminated strings)
        null1 = data.index(b"\x00", 3)
        null2 = data.index(b"\x00", null1 + 1)
        type_byte = data[null2 + 1]
        assert type_byte & 0x20  # Writable flag set

    def test_build_params_response(self):
        param = ThermostatParam(index=0, name="RoomTemp", type_code=DataType.FLOAT, unit_string="'C")
        values = [(param, 21.5)]
        data = build_params_response(values, first_index=0)

        # Header: [count][start_LE]
        assert data[0] == 1  # paramsNo
        assert struct.unpack("<H", data[1:3])[0] == 0  # firstIndex
        # Status byte before value
        assert data[3] == 0x00  # STATUS_DEFAULT for IntrSens (index 0, temperature)

        # Decode the float value
        value_bytes = data[4:8]
        decoded = decode_value(value_bytes, DataType.FLOAT)
        assert decoded == 21.5

    def test_build_params_response_multiple(self):
        p1 = ThermostatParam(index=0, name="T", type_code=DataType.FLOAT)
        p2 = ThermostatParam(index=1, name="H", type_code=DataType.UINT8)
        values = [(p1, 20.0), (p2, 55)]
        data = build_params_response(values, first_index=0)

        assert data[0] == 2  # 2 params
        # Format: [count(1)][start(2)] [status(1)][float(4)] [status(1)][uint8(1)]
        # offset 3: status byte for param 0
        # offset 4-7: float value
        float_val = decode_value(data[4:8], DataType.FLOAT)
        assert float_val == 20.0
        # offset 8: status byte for param 1
        uint8_val = decode_value(data[9:10], DataType.UINT8)
        assert uint8_val == 55


# ---------------------------------------------------------------------------
# ThermostatEmulator tests
# ---------------------------------------------------------------------------


class TestThermostatEmulator:
    @pytest.fixture
    def vt(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        vt.update(21.3)
        return vt

    @pytest.fixture
    def emulator(self, vt):
        return ThermostatEmulator(address=THERMOSTAT_ADDR, virtual_thermostat=vt)

    @pytest.mark.asyncio
    async def test_handle_identify(self, emulator):
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.IDENTIFY,
            data=b"",
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert len(written_frames) == 1
        resp = written_frames[0]
        assert resp.command == Command.IDENTIFY_RESPONSE
        assert resp.destination == PANEL_ADDRESS
        assert resp.source == THERMOSTAT_ADDR
        assert resp.data == THERMOSTAT_IDENTITY

    @pytest.mark.asyncio
    async def test_handle_get_struct(self, emulator):
        """Panel requests parameter structure."""
        request_data = struct.pack("<BH", 100, 0)  # count=100, start=0
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS_STRUCT_WITH_RANGE,
            data=request_data,
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert len(written_frames) == 1
        resp = written_frames[0]
        assert resp.command == Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE
        # First batch should contain 14 params (matching real ecoSTER batching)
        assert resp.data[0] == 14

    @pytest.mark.asyncio
    async def test_handle_get_struct_no_data(self, emulator):
        """Panel requests struct for indices beyond our params -> NO_DATA."""
        request_data = struct.pack("<BH", 100, 9999)  # start way beyond our params
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS_STRUCT_WITH_RANGE,
            data=request_data,
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert written_frames[0].command == Command.NO_DATA

    @pytest.mark.asyncio
    async def test_handle_get_params(self, emulator, vt):
        """Panel reads parameter values -- should include temperature."""
        request_data = struct.pack("<BH", 100, 0)  # count=100, start=0
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS,
            data=request_data,
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        resp = written_frames[0]
        assert resp.command == Command.GET_PARAMS_RESPONSE

        # Decode the temperature from the response
        data = resp.data
        params_no = data[0]
        assert params_no >= 1
        # Value starts at offset 4 (header + separator)
        temp = struct.unpack("<f", data[4:8])[0]
        assert round(temp, 2) == 21.3

    @pytest.mark.asyncio
    async def test_handle_get_params_stale(self, emulator, vt):
        """When temperature is stale, should report fallback."""
        # Use a very short max_age
        vt._max_age = 0.0
        time.sleep(0.01)  # Ensure staleness

        request_data = struct.pack("<BH", 100, 0)
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS,
            data=request_data,
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        await emulator.handle_frame(frame, fake_write)
        data = written_frames[0].data
        temp = struct.unpack("<f", data[4:8])[0]
        assert round(temp, 2) == 21.3  # Keeps last value even when stale

    @pytest.mark.asyncio
    async def test_handle_modify_param(self, emulator):
        """Panel writes config to thermostat -- just ACK."""
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.MODIFY_PARAM,
            data=b"\x00" * 19,  # Arbitrary MODIFY_PARAM payload
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert written_frames[0].command == Command.MODIFY_PARAM_RESPONSE
        assert written_frames[0].data == b"\x00"

    @pytest.mark.asyncio
    async def test_ignores_wrong_address(self, emulator):
        frame = Frame(
            destination=999,
            command=Command.IDENTIFY,
            data=b"",
            source=PANEL_ADDRESS,
        )

        async def fake_write(f, flush_after=False):
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert not handled


# ---------------------------------------------------------------------------
# Schedule served from the controller's Circuit 2 schedule
# ---------------------------------------------------------------------------


class TestThermostatScheduleFromCache:
    """The thermostat's schedule params (9-22) mirror the controller's Circuit 2
    schedule (297-310), so the panel does not sync our (otherwise zero) schedule
    back over Circuit 2. Mapping is 1:1 by position: param i -> 297 + (i - 9),
    with odd indices (A slots) UINT32 and even indices (B slots) UINT16.

    The controller stores a circuit schedule in a different packing than a
    thermostat reports it (verified against a real ecoSTER bus capture):
        AM slot (UINT32): thermostat = controller | 0xFF000000
        PM slot (UINT16): thermostat = controller >> 8
    The emulator applies this transform; these tests assert it.
    """

    # Realistic controller storage (top byte 0 for AM; 24-bit for PM).
    AM_VALUE = 16760832  # 0x00FFC600
    PM_VALUE = 1032447  # 0x000FC0FF -- would overflow UINT16 if served raw

    @pytest.fixture
    def vt(self):
        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        vt.update(21.0)
        return vt

    async def _request_schedule(self, emulator):
        """Send GET_PARAMS for the schedule range (params 9-22) and return the payload."""
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS,
            data=struct.pack("<BH", 14, 9),  # count=14, start=9
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, **kwargs):
            written_frames.append(f)
            return True

        await emulator.handle_frame(frame, fake_write)
        resp = written_frames[0]
        assert resp.command == Command.GET_PARAMS_RESPONSE
        return resp.data

    def _decode_schedule(self, data):
        """Decode the 14 schedule values from a GET_PARAMS response payload."""
        assert data[0] == 14
        assert struct.unpack("<H", data[1:3])[0] == 9
        values = {}
        offset = 3
        for i in range(14):
            param_index = 9 + i
            offset += 1  # status byte
            if param_index % 2 == 1:  # 9, 11, ... = "A" slots = UINT32
                values[param_index] = decode_value(data[offset : offset + 4], DataType.UINT32)
                offset += 4
            else:  # 10, 12, ... = "B" slots = UINT16
                values[param_index] = decode_value(data[offset : offset + 2], DataType.UINT16)
                offset += 2
        return values

    _DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

    async def _populate_circuit(self, cache, *, circuit, addr, base_index):
        """Set up Circuit{circuit} assigned to `addr` with a 14-slot schedule."""
        await cache.set(
            Parameter(
                index=200 + circuit, name=f"Circuit{circuit}ThermostatAddress",
                value=addr, type=DataType.UINT32, unit=0, writable=False,
            )
        )
        for i in range(14):
            day = self._DAYS[i // 2]
            slot = "AM" if i % 2 == 0 else "PM"
            await cache.set(
                Parameter(
                    index=base_index + i, name=f"Circuit{circuit}{day}{slot}",
                    value=self.AM_VALUE if i % 2 == 0 else self.PM_VALUE,
                    type=DataType.UINT32, unit=0, writable=True,
                )
            )

    @pytest.mark.asyncio
    async def test_schedule_served_from_cache(self, vt):
        cache = ParameterCache()
        # Virtual thermostat (addr 165) governs Circuit 2; schedule base at 297.
        await self._populate_circuit(cache, circuit=2, addr=THERMOSTAT_ADDR, base_index=297)
        emulator = ThermostatEmulator(address=THERMOSTAT_ADDR, virtual_thermostat=vt, cache=cache)

        values = self._decode_schedule(await self._request_schedule(emulator))

        # param 9 <-> 297 (AM), param 10 <-> 298 (PM), ... param 22 <-> 310 (PM)
        # Emulator applies the controller->thermostat transform.
        for param_index in range(9, 23):
            if param_index % 2 == 1:  # AM slot (UINT32)
                expected = self.AM_VALUE | 0xFF000000
            else:  # PM slot (UINT16)
                expected = (self.PM_VALUE >> 8) & 0xFFFF
            assert values[param_index] == expected, f"param {param_index}"

    async def _request_schedule_response(self, emulator):
        """Send a schedule-range GET_PARAMS and return the raw response Frame."""
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS,
            data=struct.pack("<BH", 14, 9),  # count=14, start=9
            source=PANEL_ADDRESS,
        )
        written = []

        async def fake_write(f, **kwargs):
            written.append(f)
            return True

        await emulator.handle_frame(frame, fake_write)
        return written[0]

    @pytest.mark.asyncio
    async def test_schedule_served_from_assigned_circuit_not_hardcoded(self, vt):
        # Virtual thermostat governs Circuit 1 (base 247), not Circuit 2 — the base
        # index must be resolved from the assignment, not hardcoded to 297.
        cache = ParameterCache()
        await self._populate_circuit(cache, circuit=1, addr=THERMOSTAT_ADDR, base_index=247)
        emulator = ThermostatEmulator(address=THERMOSTAT_ADDR, virtual_thermostat=vt, cache=cache)

        values = self._decode_schedule(await self._request_schedule(emulator))

        for param_index in range(9, 23):
            if param_index % 2 == 1:
                expected = self.AM_VALUE | 0xFF000000
            else:
                expected = (self.PM_VALUE >> 8) & 0xFFFF
            assert values[param_index] == expected, f"param {param_index}"

    @pytest.mark.asyncio
    async def test_schedule_deferred_without_cache(self, vt):
        # No cache -> schedule never becomes ready -> we must NOT serve a (zero)
        # schedule (that would let the panel wipe Circuit 2). Respond NO_DATA.
        emulator = ThermostatEmulator(address=THERMOSTAT_ADDR, virtual_thermostat=vt)

        resp = await self._request_schedule_response(emulator)

        assert resp.command == Command.NO_DATA

    @pytest.mark.asyncio
    async def test_schedule_deferred_on_cache_miss(self, vt):
        # Cache present but Circuit 2 schedule not polled yet -> defer (NO_DATA),
        # do not serve zeros.
        emulator = ThermostatEmulator(
            address=THERMOSTAT_ADDR, virtual_thermostat=vt, cache=ParameterCache()
        )

        resp = await self._request_schedule_response(emulator)

        assert resp.command == Command.NO_DATA

    @pytest.mark.asyncio
    async def test_full_poll_serves_temp_but_truncates_schedule_when_not_ready(self, vt):
        # Before the schedule is retrieved, a full-table poll (start=0) still reports
        # temperature/presets but truncates at the schedule range (no schedule served).
        emulator = ThermostatEmulator(
            address=THERMOSTAT_ADDR, virtual_thermostat=vt, cache=ParameterCache()
        )
        frame = Frame(
            destination=THERMOSTAT_ADDR,
            command=Command.GET_PARAMS,
            data=struct.pack("<BH", 35, 0),  # count=35, start=0 (full table)
            source=PANEL_ADDRESS,
        )
        written = []

        async def fake_write(f, **kwargs):
            written.append(f)
            return True

        await emulator.handle_frame(frame, fake_write)
        resp = written[0]
        assert resp.command == Command.GET_PARAMS_RESPONSE
        # Response covers params 0..8 only (count=9), schedule (9+) truncated.
        assert resp.data[0] == 9
        assert struct.unpack("<H", resp.data[1:3])[0] == 0


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class _FakeHandler:
    """Minimal handler stub for API tests."""

    thermostat_pairing_state = "unpaired"
    thermostat_address = None


class TestThermostatApi:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        from econext_gateway.main import app

        vt = VirtualThermostat(max_age=300.0, stale_fallback=19.0)
        app_state.virtual_thermostat = vt
        app_state.settings = None
        app_state.handler = _FakeHandler()
        app_state.cache = None
        self.client = TestClient(app, raise_server_exceptions=False)
        yield

    def test_submit_temperature(self):
        resp = self.client.post("/api/thermostat/temperature", json={"temperature": 22.5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["temperature"] == 22.5
        assert data["previous_age_seconds"] is None  # First update

    def test_submit_temperature_subsequent(self):
        self.client.post("/api/thermostat/temperature", json={"temperature": 20.0})
        resp = self.client.post("/api/thermostat/temperature", json={"temperature": 21.0})
        data = resp.json()
        assert data["previous_age_seconds"] is not None
        assert data["previous_age_seconds"] < 5.0

    def test_get_status_initial(self):
        resp = self.client.get("/api/thermostat/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["temperature"] is None
        assert data["is_stale"] is True
        assert data["effective_temperature"] == 19.0  # stale fallback
        assert data["pairing_state"] == "unpaired"
        assert data["bus_address"] is None

    def test_get_status_after_update(self):
        self.client.post("/api/thermostat/temperature", json={"temperature": 21.5})
        resp = self.client.get("/api/thermostat/status")
        data = resp.json()
        assert data["temperature"] == 21.5
        assert data["is_stale"] is False
        assert data["effective_temperature"] == 21.5
        assert data["pairing_state"] == "unpaired"

    def test_submit_missing_temperature(self):
        resp = self.client.post("/api/thermostat/temperature", json={})
        assert resp.status_code == 422  # Validation error
