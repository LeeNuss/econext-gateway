"""Integration tests: API -> handler -> mock serial.

Tests the full stack by replacing GM3SerialTransport with a fake that
operates at the Frame level. ProtocolHandler, ParameterCache, and the
FastAPI API all use real code.
"""

import asyncio
import struct

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter
from econext_gateway.protocol.codec import encode_value
from econext_gateway.protocol.constants import (
    GET_TOKEN_FUNC,
    IDENTIFY_CMD,
    PANEL_ADDRESS,
    SERVICE_CMD,
    SRC_ADDRESS,
    Command,
    DataType,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.protocol.handler import ParamStructEntry, ProtocolHandler

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

    async def write_frame(self, frame: Frame, flush_after: bool = False) -> bool:
        self._writes.append(frame)
        return True

    def reset_buffer(self) -> None:
        # No-op in tests: pre-queued response frames must survive the
        # reset_buffer() call that send_and_receive() issues after every write.
        pass

    def queue_frame(self, source: int, command: int, data: bytes = b"") -> None:
        """Queue a response frame addressed to SRC_ADDRESS (131)."""
        frame = Frame(destination=SRC_ADDRESS, command=command, data=data)
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
