"""Tests for virtual thermostat: state holder, emulator, and API."""

import asyncio
import struct
import time

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.virtual_thermostat import VirtualThermostat
from econext_gateway.protocol.codec import decode_value
from econext_gateway.protocol.constants import (
    IDENTIFY_ANS_CMD,
    IDENTIFY_CMD,
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
from econext_gateway.thermostat.params import THERMOSTAT_PARAMS, ThermostatParam

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

        # Wait for staleness
        time.sleep(0.15)
        assert vt.is_stale is True
        assert vt.effective_temperature == 5.0  # Falls back

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
                unit_code=1,
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
        assert unit == "C"

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
                unit_code=1,
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
        param = ThermostatParam(
            index=0, name="RoomTemp", type_code=DataType.FLOAT, unit_code=1
        )
        values = [(param, 21.5)]
        data = build_params_response(values, first_index=0)

        # Header
        assert data[0] == 1  # paramsNo
        assert struct.unpack("<H", data[1:3])[0] == 0  # firstIndex
        # Separator after header
        assert data[3] == 0xC2

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
        # After header (3) + separator (1) = offset 4
        # Float: 4 bytes + separator (1) = 5 bytes
        # uint8: 1 byte + separator (1)
        float_val = decode_value(data[4:8], DataType.FLOAT)
        assert float_val == 20.0
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
            command=IDENTIFY_CMD,
            data=b"",
            source=PANEL_ADDRESS,
        )
        written_frames = []

        async def fake_write(f, flush_after=False):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert len(written_frames) == 1
        resp = written_frames[0]
        assert resp.command == IDENTIFY_ANS_CMD
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

        async def fake_write(f, flush_after=False):
            written_frames.append(f)
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert handled
        assert len(written_frames) == 1
        resp = written_frames[0]
        assert resp.command == Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE
        # Should contain at least the header
        assert resp.data[0] == len(THERMOSTAT_PARAMS)

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

        async def fake_write(f, flush_after=False):
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

        async def fake_write(f, flush_after=False):
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

        async def fake_write(f, flush_after=False):
            written_frames.append(f)
            return True

        await emulator.handle_frame(frame, fake_write)
        data = written_frames[0].data
        temp = struct.unpack("<f", data[4:8])[0]
        assert round(temp, 2) == 0.0  # stale_fallback

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

        async def fake_write(f, flush_after=False):
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
            command=IDENTIFY_CMD,
            data=b"",
            source=PANEL_ADDRESS,
        )

        async def fake_write(f, flush_after=False):
            return True

        handled = await emulator.handle_frame(frame, fake_write)
        assert not handled


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestThermostatApi:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        from econext_gateway.main import app

        vt = VirtualThermostat(max_age=300.0, stale_fallback=0.0)
        app_state.virtual_thermostat = vt
        # Minimal app state for API tests
        app_state.settings = None
        app_state.handler = None
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
        assert data["effective_temperature"] == 0.0

    def test_get_status_after_update(self):
        self.client.post("/api/thermostat/temperature", json={"temperature": 21.5})
        resp = self.client.get("/api/thermostat/status")
        data = resp.json()
        assert data["temperature"] == 21.5
        assert data["is_stale"] is False
        assert data["effective_temperature"] == 21.5

    def test_submit_missing_temperature(self):
        resp = self.client.post("/api/thermostat/temperature", json={})
        assert resp.status_code == 422  # Validation error
