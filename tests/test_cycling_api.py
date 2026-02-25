"""Unit tests for cycling API endpoints."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.control.cycling import COMPR_STAT_INDEX, CompressorMonitor
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.config import Settings
from econext_gateway.core.models import Parameter
from econext_gateway.main import app
from econext_gateway.protocol.handler import ProtocolHandler
from econext_gateway.serial.connection import GM3SerialTransport


def _make_param(index: int, name: str, value, writable: bool = True) -> Parameter:
    return Parameter(
        index=index, name=name, value=value,
        type=2, unit=0, writable=writable,
    )


@pytest.fixture
def mock_cycling_state():
    """Set up mock app state with CompressorMonitor."""
    orig_conn = app_state.connection
    orig_cache = app_state.cache
    orig_handler = app_state.handler
    orig_monitor = app_state.monitor
    orig_settings = app_state.settings

    conn = MagicMock(spec=GM3SerialTransport)
    conn.connected = True

    cache = ParameterCache()
    settings = Settings()

    handler = MagicMock(spec=ProtocolHandler)
    handler.connected = True

    monitor = CompressorMonitor(cache)

    app_state.connection = conn
    app_state.cache = cache
    app_state.handler = handler
    app_state.monitor = monitor
    app_state.settings = settings

    yield {
        "connection": conn,
        "cache": cache,
        "handler": handler,
        "monitor": monitor,
        "settings": settings,
    }

    app_state.connection = orig_conn
    app_state.cache = orig_cache
    app_state.handler = orig_handler
    app_state.monitor = orig_monitor
    app_state.settings = orig_settings


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestGetMetrics:
    """Tests for GET /api/cycling/metrics."""

    def test_metrics_initial(self, client, mock_cycling_state):
        response = client.get("/api/cycling/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["compressor_on"] is None
        assert data["starts_last_hour"] == 0

    def test_metrics_with_data(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        monitor = mock_cycling_state["monitor"]

        # Set up compressor state in cache
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, "HPStatusComprStat", 1)))
        asyncio.run(monitor.update())

        response = client.get("/api/cycling/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["compressor_on"] is True
        assert data["current_state_seconds"] >= 0


class TestGetHistory:
    """Tests for GET /api/cycling/history."""

    def test_history_empty(self, client, mock_cycling_state):
        response = client.get("/api/cycling/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_history_with_events(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        monitor = mock_cycling_state["monitor"]

        # OFF -> ON -> OFF
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, "HPStatusComprStat", 0)))
        asyncio.run(monitor.update())
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, "HPStatusComprStat", 1)))
        asyncio.run(monitor.update())
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, "HPStatusComprStat", 0)))
        asyncio.run(monitor.update())

        response = client.get("/api/cycling/history")
        assert response.status_code == 200
        events = response.json()
        assert len(events) == 2
        assert events[0]["turned_on"] is True
        assert events[1]["turned_on"] is False


class TestGetSettings:
    """Tests for GET /api/cycling/settings."""

    def test_settings_no_params(self, client, mock_cycling_state):
        response = client.get("/api/cycling/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["anticycling_enabled"] is True
        assert data["min_work_time"] is None
        assert data["min_break_time"] is None

    def test_settings_with_params(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 10)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 10)))
        asyncio.run(cache.set(_make_param(503, "compressorMinTimesSett", 1)))

        response = client.get("/api/cycling/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["min_work_time"] == 10
        assert data["min_break_time"] == 10
        assert data["compressor_min_times_sett"] == 1


class TestPostSettings:
    """Tests for POST /api/cycling/settings."""

    def test_set_min_work_time(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 10)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 10)))
        asyncio.run(cache.set(_make_param(503, "compressorMinTimesSett", 1)))

        mock_cycling_state["handler"].write_param = AsyncMock(return_value=True)

        response = client.post(
            "/api/cycling/settings",
            json={"min_work_time": 15},
        )
        assert response.status_code == 200
        mock_cycling_state["handler"].write_param.assert_called_once_with("minWorkTime", 15)

    def test_set_both_timers(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 10)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 10)))
        asyncio.run(cache.set(_make_param(503, "compressorMinTimesSett", 1)))

        mock_cycling_state["handler"].write_param = AsyncMock(return_value=True)

        response = client.post(
            "/api/cycling/settings",
            json={"min_work_time": 15, "min_break_time": 20},
        )
        assert response.status_code == 200
        assert mock_cycling_state["handler"].write_param.call_count == 2

    def test_set_no_values(self, client, mock_cycling_state):
        response = client.post(
            "/api/cycling/settings",
            json={},
        )
        assert response.status_code == 400

    def test_set_disconnected(self, client, mock_cycling_state):
        mock_cycling_state["handler"].connected = False

        response = client.post(
            "/api/cycling/settings",
            json={"min_work_time": 15},
        )
        assert response.status_code == 503

    def test_write_failure(self, client, mock_cycling_state):
        cache = mock_cycling_state["cache"]
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 10)))

        mock_cycling_state["handler"].write_param = AsyncMock(return_value=False)

        response = client.post(
            "/api/cycling/settings",
            json={"min_work_time": 15},
        )
        assert response.status_code == 503
