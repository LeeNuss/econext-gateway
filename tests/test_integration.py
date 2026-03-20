"""Integration tests: API -> handler -> mock serial.

Tests the full stack by replacing GM3SerialTransport with a fake that
operates at the Frame level. ProtocolHandler, ParameterCache, and the
FastAPI API all use real code.
"""

import asyncio
import struct
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter
from econext_gateway.protocol.codec import encode_value
from econext_gateway.protocol.constants import (
    CLAIMABLE_ADDRESS_RANGE,
    DEVICE_TABLE_FUNC,
    GET_TOKEN_FUNC,
    IDENTIFY_CMD,
    PAIRING_BEACON_FUNC,
    PANEL_ADDRESS,
    SERVICE_CMD,
    THERMOSTAT_CLAIMABLE_ADDRESS_RANGE,
    Command,
    DataType,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.protocol.handler import ParamStructEntry, ProtocolHandler

# Must match conftest.TEST_BUS_ADDRESS
TEST_BUS_ADDRESS = 200

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_frame(source: int, dest: int, command: int, data: bytes = b"") -> bytes:
    """Build raw frame bytes with an arbitrary source address."""
    frame = Frame(destination=dest, command=command, data=data)
    frame.source = source
    return frame.to_bytes()


def build_struct_with_range(start_index: int, params: list[tuple]) -> bytes:
    """Build GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE payload.

    params: list of (name, unit_str, type_code, writable, min_val|None, max_val|None)
    """
    data = bytearray()
    data.append(len(params))
    data.extend(struct.pack("<H", start_index))

    for name, unit_str, type_code, writable, min_val, max_val in params:
        data.extend(name.encode() + b"\x00")
        data.extend(unit_str.encode() + b"\x00")

        type_byte = type_code
        if writable:
            type_byte |= 0x20
        data.append(type_byte)

        extra_byte = 0x00
        if min_val is None:
            extra_byte |= 0x40
        if max_val is None:
            extra_byte |= 0x80
        data.append(extra_byte)

        data.extend(struct.pack("<h", int(min_val) if min_val is not None else 0))
        data.extend(struct.pack("<h", int(max_val) if max_val is not None else 0))

    return bytes(data)


def build_struct_no_range(start_index: int, params: list[tuple]) -> bytes:
    """Build GET_PARAMS_STRUCT_RESPONSE payload (WITHOUT_RANGE, panel).

    params: list of (name, unit_str, type_code, writable)
    """
    data = bytearray()
    data.append(len(params))
    data.extend(struct.pack("<H", start_index))

    for name, unit_str, type_code, writable in params:
        data.extend(name.encode() + b"\x00")
        data.extend(unit_str.encode() + b"\x00")

        type_byte = type_code
        if writable:
            type_byte |= 0x20
        data.extend(struct.pack("<bB", 0, type_byte))  # exponent=0, type

    return bytes(data)


def build_params_response(start_index: int, values: list[tuple]) -> bytes:
    """Build GET_PARAMS_RESPONSE payload.

    values: list of (value, type_code)
    """
    data = bytearray()
    data.append(len(values))
    data.extend(struct.pack("<H", start_index))
    data.append(0x00)  # separator

    for value, type_code in values:
        data.extend(encode_value(value, type_code))
        data.append(0x00)  # separator

    return bytes(data)


# ---------------------------------------------------------------------------
# Fake serial transport operating at the Frame level
# ---------------------------------------------------------------------------


class FakeProtocol:
    """Mock GM3Protocol that operates at the Frame level.

    Frames are returned from receive_frame() in FIFO order. When the queue
    is exhausted, receive_frame() returns None (timeout).
    """

    def __init__(self):
        self._connected = True
        self._frame_queue: asyncio.Queue[Frame | None] = asyncio.Queue()
        self._writes: list[Frame] = []

    @property
    def connected(self) -> bool:
        return self._connected

    async def receive_frame(self, timeout: float | None = None) -> Frame | None:
        try:
            return await asyncio.wait_for(self._frame_queue.get(), timeout=timeout or 0.05)
        except TimeoutError:
            return None

    async def write_frame(self, frame: Frame, flush_after: bool = False, clear_echo: bool = True) -> bool:
        self._writes.append(frame)
        return True

    def reset_buffer(self) -> None:
        # No-op in tests: pre-queued response frames must survive the
        # reset_buffer() call that send_and_receive() issues after every write.
        pass

    def queue_frame(self, source: int, command: int, data: bytes = b"") -> None:
        """Queue a response frame addressed to the test bus address."""
        frame = Frame(destination=TEST_BUS_ADDRESS, command=command, data=data)
        frame.source = source
        self._frame_queue.put_nowait(frame)


class FakeTransport:
    """Minimal stand-in for GM3SerialTransport backed by a FakeProtocol."""

    def __init__(self, protocol: FakeProtocol | None = None):
        self._protocol = protocol or FakeProtocol()

    @property
    def protocol(self) -> FakeProtocol:
        return self._protocol

    @property
    def connected(self) -> bool:
        return self._protocol.connected


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_proto():
    return FakeProtocol()


@pytest.fixture
def fake_conn(fake_proto):
    return FakeTransport(fake_proto)


@pytest.fixture
def cache():
    return ParameterCache()


def _make_paired_file(address: int = TEST_BUS_ADDRESS) -> Path:
    """Create a temporary paired address file for tests."""
    d = Path(tempfile.mkdtemp())
    f = d / "paired_address"
    f.write_text(str(address))
    return f


def _make_device_table_frame(*addresses: int) -> Frame:
    """Build a SERVICE 0x2001 device table broadcast frame from the panel."""
    data = struct.pack("<H", DEVICE_TABLE_FUNC) + b"\x00\x00"
    for addr in addresses:
        data += struct.pack("<Hf", addr, 20.0)  # address + dummy temperature
    frame = Frame(destination=0xFFFF, command=SERVICE_CMD, data=data)
    frame.source = PANEL_ADDRESS
    return frame


def _make_empty_paired_file() -> Path:
    """Create a temporary directory for paired address file (file does not exist)."""
    d = Path(tempfile.mkdtemp())
    return d / "paired_address"


def make_handler(conn, cache, **kwargs):
    """Create a ProtocolHandler wired to a FakeTransport."""
    defaults = dict(
        connection=conn,
        cache=cache,
        destination=1,
        poll_interval=10.0,
        request_timeout=3.0,
        params_per_request=50,
        token_required=False,
        token_timeout=0,
        paired_address_file=_make_paired_file(),
    )
    defaults.update(kwargs)
    return ProtocolHandler(**defaults)


# ---------------------------------------------------------------------------
# Discovery integration
# ---------------------------------------------------------------------------


class TestDiscoveryIntegration:
    """Discovery flow: struct requests -> frame parsing -> param_structs."""

    @pytest.mark.asyncio
    async def test_discover_regulator_params(self, fake_conn, fake_proto, cache):
        """Struct response with 2 params is parsed and stored."""
        handler = make_handler(fake_conn, cache)

        struct_data = build_struct_with_range(
            0,
            [
                ("Temperature", "C", DataType.INT16, True, 20, 80),
                ("Pressure", "%", DataType.UINT8, False, None, None),
            ],
        )
        fake_proto.queue_frame(1, Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, struct_data)
        fake_proto.queue_frame(1, Command.NO_DATA)
        # Panel: no params
        fake_proto.queue_frame(PANEL_ADDRESS, Command.NO_DATA)

        total = await handler.discover_params()

        assert total == 2
        assert handler._param_structs[0].name == "Temperature"
        assert handler._param_structs[0].writable is True
        assert handler._param_structs[0].min_value == 20.0
        assert handler._param_structs[0].max_value == 80.0
        assert handler._param_structs[1].name == "Pressure"
        assert handler._param_structs[1].writable is False

    @pytest.mark.asyncio
    async def test_discover_both_address_spaces(self, fake_conn, fake_proto, cache):
        """Regulator (WITH_RANGE) + panel (WITHOUT_RANGE) params discovered."""
        handler = make_handler(fake_conn, cache)

        # Regulator: 2 params
        reg_data = build_struct_with_range(
            0,
            [
                ("RegTemp", "C", DataType.INT16, True, 0, 100),
                ("RegBool", "", DataType.BOOL, False, None, None),
            ],
        )
        fake_proto.queue_frame(1, Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, reg_data)
        fake_proto.queue_frame(1, Command.NO_DATA)

        # Panel: 1 param
        panel_data = build_struct_no_range(
            0,
            [
                ("PanelTemp", "C", DataType.INT16, True),
            ],
        )
        fake_proto.queue_frame(PANEL_ADDRESS, Command.GET_PARAMS_STRUCT_RESPONSE, panel_data)
        fake_proto.queue_frame(PANEL_ADDRESS, Command.NO_DATA)

        total = await handler.discover_params()

        assert total == 3
        # Regulator at offset 0
        assert handler._param_structs[0].name == "RegTemp"
        assert handler._param_structs[0].min_value == 0.0
        assert handler._param_structs[0].max_value == 100.0
        assert handler._param_structs[1].name == "RegBool"
        # Panel at offset 10000
        assert handler._param_structs[10000].name == "PanelTemp"
        assert handler._param_structs[10000].min_value is None

    @pytest.mark.asyncio
    async def test_discovery_preserves_existing_on_empty_result(self, fake_conn, fake_proto, cache):
        """If discovery returns nothing, existing structs are kept."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "Existing", 1, DataType.INT16, True),
        }

        # Both address spaces return NO_DATA immediately
        fake_proto.queue_frame(1, Command.NO_DATA)
        fake_proto.queue_frame(PANEL_ADDRESS, Command.NO_DATA)

        total = await handler.discover_params()

        assert total == 1
        assert handler._param_structs[0].name == "Existing"


# ---------------------------------------------------------------------------
# Polling integration
# ---------------------------------------------------------------------------


class TestPollIntegration:
    """Polling flow: GET_PARAMS -> frame parsing -> cache update."""

    @pytest.mark.asyncio
    async def test_poll_updates_cache(self, fake_conn, fake_proto, cache):
        """Polling reads values and stores them in the cache."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "Temperature", 1, DataType.INT16, True, 20.0, 80.0),
            1: ParamStructEntry(1, "Humidity", 6, DataType.UINT8, False),
        }

        resp_data = build_params_response(
            0,
            [
                (42, DataType.INT16),
                (75, DataType.UINT8),
            ],
        )
        fake_proto.queue_frame(1, Command.GET_PARAMS_RESPONSE, resp_data)

        count = await handler.poll_all_params()

        assert count == 2
        temp = await cache.get(0)
        assert temp is not None
        assert temp.value == 42
        assert temp.writable is True

        hum = await cache.get(1)
        assert hum is not None
        assert hum.value == 75
        assert hum.writable is False


# ---------------------------------------------------------------------------
# Write integration
# ---------------------------------------------------------------------------


class TestWriteIntegration:
    """Write flow: MODIFY_PARAM -> response -> cache update."""

    @pytest.mark.asyncio
    async def test_write_param_success(self, fake_conn, fake_proto, cache):
        """Successful write returns True and updates cache."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "SetPoint", 1, DataType.INT16, True, 20.0, 80.0),
        }
        await cache.set(
            Parameter(
                index=0,
                name="SetPoint",
                value=50,
                type=DataType.INT16,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        fake_proto.queue_frame(1, Command.MODIFY_PARAM_RESPONSE, b"\x00\x00\x41\x00")

        result = await handler.write_param("SetPoint", 65)

        assert result is True
        updated = await cache.get(0)
        assert updated.value == 65

    @pytest.mark.asyncio
    async def test_write_read_only_raises(self, fake_conn, fake_proto, cache):
        """Writing a read-only param raises ValueError."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "ReadOnly", 1, DataType.INT16, False),
        }
        await cache.set(
            Parameter(
                index=0,
                name="ReadOnly",
                value=42,
                type=DataType.INT16,
                unit=1,
                writable=False,
            )
        )

        with pytest.raises(ValueError, match="read-only"):
            await handler.write_param("ReadOnly", 99)

    @pytest.mark.asyncio
    async def test_write_out_of_range_raises(self, fake_conn, fake_proto, cache):
        """Writing a value outside min/max raises ValueError."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "SetPoint", 1, DataType.INT16, True, 20.0, 80.0),
        }
        await cache.set(
            Parameter(
                index=0,
                name="SetPoint",
                value=50,
                type=DataType.INT16,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        with pytest.raises(ValueError, match="above maximum"):
            await handler.write_param("SetPoint", 100)

    @pytest.mark.asyncio
    async def test_write_no_ack_returns_false(self, fake_conn, fake_proto, cache):
        """Write that gets no response returns False."""
        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "SetPoint", 1, DataType.INT16, True, 20.0, 80.0),
        }
        await cache.set(
            Parameter(
                index=0,
                name="SetPoint",
                value=50,
                type=DataType.INT16,
                unit=1,
                writable=True,
                min_value=20.0,
                max_value=80.0,
            )
        )

        # No response queued -> send_and_receive times out
        result = await handler.write_param("SetPoint", 65)

        assert result is False
        # Cache should NOT be updated
        param = await cache.get(0)
        assert param.value == 50


# ---------------------------------------------------------------------------
# Token grant integration
# ---------------------------------------------------------------------------


class TestTokenIntegration:
    """Token handshake: IDENTIFY response -> SERVICE token grant."""

    @pytest.mark.asyncio
    async def test_token_grant_via_identify_service(self, fake_conn, fake_proto, cache):
        """Handler responds to IDENTIFY, receives token, discovers, returns token."""
        handler = make_handler(fake_conn, cache, token_required=True)

        # Panel probes us
        fake_proto.queue_frame(PANEL_ADDRESS, IDENTIFY_CMD)
        # Panel grants token
        token_data = struct.pack("<H", GET_TOKEN_FUNC) + b"\x00\x00"
        fake_proto.queue_frame(PANEL_ADDRESS, SERVICE_CMD, token_data)
        # Empty discovery (both spaces)
        fake_proto.queue_frame(1, Command.NO_DATA)
        fake_proto.queue_frame(PANEL_ADDRESS, Command.NO_DATA)

        await handler.discover_params()

        # Token was returned at the end
        assert handler._has_token is False
        # At least 3 writes: IDENTIFY_ANS, struct request(s), token return
        assert len(fake_proto._writes) >= 3


# ---------------------------------------------------------------------------
# API integration (full stack)
# ---------------------------------------------------------------------------


class TestApiIntegration:
    """FastAPI endpoints backed by real handler and cache.

    The TestClient runs the lifespan (which creates its own objects),
    so we overwrite app_state AFTER the client starts and restore
    BEFORE it exits so the teardown works on the original objects.
    """

    @staticmethod
    def _swap(conn, cache, handler):
        """Overwrite app_state; return originals for restore."""
        orig = (app_state.connection, app_state.cache, app_state.handler)
        app_state.connection = conn
        app_state.cache = cache
        app_state.handler = handler
        return orig

    @staticmethod
    def _restore(orig):
        app_state.connection, app_state.cache, app_state.handler = orig

    def test_get_parameters_returns_cached_data(self, fake_conn, cache):
        """GET /api/parameters returns params stored in cache by handler."""
        from econext_gateway.main import app

        handler = make_handler(fake_conn, cache)
        handler._param_structs = {
            0: ParamStructEntry(0, "Temperature", 1, DataType.INT16, True, 20.0, 80.0),
        }
        asyncio.run(
            cache.set(
                Parameter(
                    index=0,
                    name="Temperature",
                    value=42,
                    type=DataType.INT16,
                    unit=1,
                    writable=True,
                    min_value=20.0,
                    max_value=80.0,
                )
            )
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            orig = self._swap(fake_conn, cache, handler)
            try:
                response = client.get("/api/parameters")

                assert response.status_code == 200
                data = response.json()
                assert "0" in data["parameters"]
                temp = data["parameters"]["0"]
                assert temp["name"] == "Temperature"
                assert temp["value"] == 42
                assert temp["min"] == 20.0
                assert temp["max"] == 80.0
                assert temp["writable"] is True
            finally:
                self._restore(orig)

    def test_health_reflects_connection_state(self):
        """Health endpoint reflects handler connected / cache count."""
        from econext_gateway.main import app

        conn = FakeTransport()
        c = ParameterCache()
        handler = make_handler(conn, c)

        with TestClient(app, raise_server_exceptions=False) as client:
            orig = self._swap(conn, c, handler)
            try:
                # Connected, no params -> degraded
                resp = client.get("/health")
                assert resp.json()["status"] == "degraded"
                assert resp.json()["controller_connected"] is True

                # Add a param -> healthy
                asyncio.run(
                    c.set(
                        Parameter(
                            index=0,
                            name="T",
                            value=1,
                            type=2,
                            unit=0,
                            writable=False,
                        )
                    )
                )
                resp = client.get("/health")
                assert resp.json()["status"] == "healthy"

                # Disconnect -> unhealthy
                conn._protocol._connected = False
                resp = client.get("/health")
                assert resp.json()["status"] == "unhealthy"
                assert resp.json()["controller_connected"] is False
            finally:
                self._restore(orig)

    def test_post_parameter_not_found(self, fake_conn, cache):
        """POST to nonexistent parameter returns 404."""
        from econext_gateway.main import app

        handler = make_handler(fake_conn, cache)

        with TestClient(app, raise_server_exceptions=False) as client:
            orig = self._swap(fake_conn, cache, handler)
            try:
                resp = client.post("/api/parameters/NoSuch", json={"value": 42})
                assert resp.status_code == 404
            finally:
                self._restore(orig)

    def test_get_parameters_disconnected_503(self, fake_conn, fake_proto, cache):
        """GET /api/parameters returns 503 when controller is disconnected."""
        from econext_gateway.main import app

        fake_proto._connected = False
        handler = make_handler(fake_conn, cache)

        with TestClient(app, raise_server_exceptions=False) as client:
            orig = self._swap(fake_conn, cache, handler)
            try:
                resp = client.get("/api/parameters")
                assert resp.status_code == 503
            finally:
                self._restore(orig)


# ---------------------------------------------------------------------------
# Registration state machine
# ---------------------------------------------------------------------------


class TestRegistrationStateMachine:
    """Validated address claiming: unpaired -> tentative -> paired."""

    @pytest.mark.asyncio
    async def test_tentative_validated_on_token(self, fake_conn, fake_proto, cache):
        """Address is persisted only after token grant validates it."""
        paired_file = _make_empty_paired_file()
        handler = make_handler(
            fake_conn,
            cache,
            token_required=True,
            paired_address_file=paired_file,
        )

        assert handler._registration_state == "unpaired"
        assert handler._source_address == 0

        # Panel broadcasts device table (must arrive before IDENTIFY)
        fake_proto._frame_queue.put_nowait(_make_device_table_frame(100, 166))

        # Panel scans address 112 (in claimable range)
        identify_frame = Frame(destination=112, command=IDENTIFY_CMD, data=b"")
        identify_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(identify_frame)

        # Panel grants token to address 112
        token_data = struct.pack("<H", GET_TOKEN_FUNC) + b"\x00\x00"
        token_frame = Frame(destination=112, command=SERVICE_CMD, data=token_data)
        token_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(token_frame)

        await handler._wait_for_token()

        assert handler._registration_state == "paired"
        assert handler._source_address == 112
        assert handler._has_token is True
        # File should now be persisted
        assert paired_file.exists()
        assert paired_file.read_text().strip() == "112"

    @pytest.mark.asyncio
    async def test_tentative_timeout_reverts(self, fake_conn, fake_proto, cache):
        """Address reverts to unpaired if no token within timeout."""
        paired_file = _make_empty_paired_file()
        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            paired_address_file=paired_file,
        )

        assert handler._registration_state == "unpaired"

        # Panel broadcasts device table
        fake_proto._frame_queue.put_nowait(_make_device_table_frame(100, 166))

        # Panel scans address 119 (in claimable range) -- gateway claims tentatively
        identify_frame = Frame(destination=119, command=IDENTIFY_CMD, data=b"")
        identify_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(identify_frame)

        # First, let the handler process the IDENTIFY
        # We need token_required=False and short timeout so _wait_for_token exits
        await handler._wait_for_token()

        # Handler should have processed the IDENTIFY and claimed tentatively,
        # but since no token was granted and token_required=False with short timeout,
        # it exited _wait_for_token. The state depends on timing.
        # With token_required=False and timeout=0.1, it will exit quickly.
        # The address should NOT be persisted since no token was received.
        assert not paired_file.exists()

    @pytest.mark.asyncio
    async def test_reserved_addresses_skipped(self, fake_conn, fake_proto, cache):
        """IDENTIFY to reserved addresses is not claimed."""
        paired_file = _make_empty_paired_file()
        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            paired_address_file=paired_file,
        )

        # Panel scans address 100 (reserved panel address)
        identify_frame = Frame(destination=100, command=IDENTIFY_CMD, data=b"")
        identify_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(identify_frame)

        await handler._wait_for_token()

        assert handler._registration_state == "unpaired"
        assert handler._source_address == 0
        assert not paired_file.exists()

    @pytest.mark.asyncio
    async def test_131_outside_claimable_range(self, fake_conn, fake_proto, cache):
        """Address 131 (ecoNET300) is outside the claimable range."""
        assert 131 not in CLAIMABLE_ADDRESS_RANGE

    @pytest.mark.asyncio
    async def test_panel_adjacent_addresses_claimable(self, fake_conn, fake_proto, cache):
        """Addresses in the panel peripheral range (e.g. 112) are claimable."""
        assert 112 in CLAIMABLE_ADDRESS_RANGE
        assert 105 in CLAIMABLE_ADDRESS_RANGE

    @pytest.mark.asyncio
    async def test_out_of_range_address_ignored(self, fake_conn, fake_proto, cache):
        """IDENTIFY to address outside panel range (e.g. 32) is ignored."""
        assert 32 not in CLAIMABLE_ADDRESS_RANGE

        paired_file = _make_empty_paired_file()
        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            paired_address_file=paired_file,
        )

        identify_frame = Frame(destination=32, command=IDENTIFY_CMD, data=b"")
        identify_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(identify_frame)

        await handler._wait_for_token()

        assert handler._registration_state == "unpaired"
        assert handler._source_address == 0
        assert not paired_file.exists()

    @pytest.mark.asyncio
    async def test_high_address_out_of_range_ignored(self, fake_conn, fake_proto, cache):
        """IDENTIFY to address 193 (above panel range) is ignored."""
        assert 193 not in CLAIMABLE_ADDRESS_RANGE

        paired_file = _make_empty_paired_file()
        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            paired_address_file=paired_file,
        )

        identify_frame = Frame(destination=193, command=IDENTIFY_CMD, data=b"")
        identify_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(identify_frame)

        await handler._wait_for_token()

        assert handler._registration_state == "unpaired"
        assert handler._source_address == 0
        assert not paired_file.exists()


# ---------------------------------------------------------------------------
# Thermostat registration
# ---------------------------------------------------------------------------


def _make_pairing_beacon_frame() -> Frame:
    """Build a SERVICE 0x2004 pairing beacon broadcast from the panel."""
    data = struct.pack("<H", PAIRING_BEACON_FUNC) + b"\x00\x00"
    frame = Frame(destination=0xFFFF, command=SERVICE_CMD, data=data)
    frame.source = PANEL_ADDRESS
    return frame


def _make_empty_thermostat_file() -> Path:
    """Create a temporary directory for thermostat address file (file does not exist)."""
    d = Path(tempfile.mkdtemp())
    return d / "thermostat_address"


def _make_thermostat_emulator(address: int = 0):
    """Create a ThermostatEmulator with a VirtualThermostat for tests."""
    from econext_gateway.core.virtual_thermostat import VirtualThermostat
    from econext_gateway.thermostat.emulator import ThermostatEmulator

    vt = VirtualThermostat(max_age=300, stale_fallback=0.0)
    return ThermostatEmulator(address=address, virtual_thermostat=vt)


class TestThermostatRegistration:
    """Thermostat pairing via SERVICE_ANS response to 0x2004 beacons."""

    @pytest.mark.asyncio
    async def test_thermostat_responds_to_pairing_beacon(self, fake_conn, fake_proto, cache):
        """Thermostat sends SERVICE_ANS when pairing beacon is detected."""
        from econext_gateway.protocol.constants import SERVICE_ANS_CMD

        thermo_file = _make_empty_thermostat_file()
        emulator = _make_thermostat_emulator(address=0)

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            thermostat_emulator=emulator,
            thermostat_address_file=thermo_file,
        )

        assert handler._thermostat_reg_state == "unpaired"

        # Must explicitly request pairing via API
        assert handler.request_thermostat_pairing() is True
        assert handler._thermostat_reg_state == "pairing_requested"

        # Pairing beacon triggers SERVICE_ANS response
        fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())

        await handler._wait_for_token()

        assert handler._thermostat_reg_state == "beacon_responded"
        # Should have written a SERVICE_ANS frame to the panel
        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 1
        assert service_ans[0].destination == PANEL_ADDRESS

    @pytest.mark.asyncio
    async def test_thermostat_full_pairing_flow(self, fake_conn, fake_proto, cache):
        """Full pairing: beacon -> SERVICE_ANS -> 0x2005 address assignment -> paired."""
        from econext_gateway.protocol.constants import PAIRING_ASSIGN_FUNC, SERVICE_ANS_CMD

        thermo_file = _make_empty_thermostat_file()
        emulator = _make_thermostat_emulator(address=0)

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.5,
            thermostat_emulator=emulator,
            thermostat_address_file=thermo_file,
        )

        # 1. Request pairing via API, then beacon
        handler.request_thermostat_pairing()
        fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())

        # 2. Panel assigns address 165 via SERVICE 0x2005
        assign_data = struct.pack("<H", PAIRING_ASSIGN_FUNC) + b"\x00\x00" + struct.pack("<H", 165)
        assign_frame = Frame(destination=0xFFFF, command=SERVICE_CMD, data=assign_data)
        assign_frame.source = PANEL_ADDRESS
        fake_proto._frame_queue.put_nowait(assign_frame)

        await handler._wait_for_token()

        # Should be fully paired at address 165
        assert handler._thermostat_reg_state == "paired"
        assert emulator.address == 165
        assert thermo_file.exists()
        assert thermo_file.read_text().strip() == "165"

        # Should have written SERVICE_ANS twice: once for beacon, once for ACK
        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 2
        # ACK should be from the assigned address
        assert service_ans[1].source == 165

    @pytest.mark.asyncio
    async def test_thermostat_responds_only_once_to_beacons(self, fake_conn, fake_proto, cache):
        """Thermostat only responds to the first pairing beacon, not subsequent ones."""
        from econext_gateway.protocol.constants import SERVICE_ANS_CMD

        thermo_file = _make_empty_thermostat_file()
        emulator = _make_thermostat_emulator(address=0)

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            thermostat_emulator=emulator,
            thermostat_address_file=thermo_file,
        )

        # Request pairing, then multiple beacons (like real panel sends ~10/sec)
        handler.request_thermostat_pairing()
        for _ in range(5):
            fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())

        await handler._wait_for_token()

        # Should have sent exactly one SERVICE_ANS
        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 1

    @pytest.mark.asyncio
    async def test_thermostat_ignores_beacon_without_emulator(self, fake_conn, fake_proto, cache):
        """No SERVICE_ANS when thermostat emulator is not configured."""
        from econext_gateway.protocol.constants import SERVICE_ANS_CMD

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            # No thermostat emulator
        )

        fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())
        await handler._wait_for_token()

        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 0

    @pytest.mark.asyncio
    async def test_thermostat_already_paired_skips_beacon(self, fake_conn, fake_proto, cache):
        """When thermostat has a persisted address, it does not respond to beacons."""
        from econext_gateway.protocol.constants import SERVICE_ANS_CMD

        thermo_file = _make_empty_thermostat_file()
        emulator = _make_thermostat_emulator(address=167)  # Already has address

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            thermostat_emulator=emulator,
            thermostat_address_file=thermo_file,
        )

        assert handler._thermostat_reg_state == "paired"

        fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())
        await handler._wait_for_token()

        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 0

    @pytest.mark.asyncio
    async def test_thermostat_ignores_beacon_without_api_request(self, fake_conn, fake_proto, cache):
        """Thermostat does NOT respond to beacons unless pairing is requested via API."""
        from econext_gateway.protocol.constants import SERVICE_ANS_CMD

        thermo_file = _make_empty_thermostat_file()
        emulator = _make_thermostat_emulator(address=0)

        handler = make_handler(
            fake_conn,
            cache,
            token_required=False,
            token_timeout=0.1,
            thermostat_emulator=emulator,
            thermostat_address_file=thermo_file,
        )

        # Pairing beacon present but NO API request -- should be ignored
        fake_proto._frame_queue.put_nowait(_make_pairing_beacon_frame())

        await handler._wait_for_token()

        assert handler._thermostat_reg_state == "unpaired"
        service_ans = [w for w in fake_proto._writes if w.command == SERVICE_ANS_CMD]
        assert len(service_ans) == 0

    @pytest.mark.asyncio
    async def test_request_pairing_resets_when_paired(self, fake_conn, fake_proto, cache):
        """API allows re-pairing when thermostat is already paired."""
        emulator = _make_thermostat_emulator(address=167)
        handler = make_handler(
            fake_conn, cache, thermostat_emulator=emulator,
            thermostat_address_file=_make_empty_thermostat_file(),
        )
        assert handler._thermostat_reg_state == "paired"
        assert handler.request_thermostat_pairing() is True
        assert handler._thermostat_reg_state == "pairing_requested"
        assert emulator.address == 0  # Reset for re-pairing

    @pytest.mark.asyncio
    async def test_thermostat_address_range(self):
        """Thermostat address range covers known thermostat addresses."""
        assert 165 in THERMOSTAT_CLAIMABLE_ADDRESS_RANGE
        assert 166 in THERMOSTAT_CLAIMABLE_ADDRESS_RANGE
        # Gateway range should not overlap
        for addr in CLAIMABLE_ADDRESS_RANGE:
            assert addr not in THERMOSTAT_CLAIMABLE_ADDRESS_RANGE
