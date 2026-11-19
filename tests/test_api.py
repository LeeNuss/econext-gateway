"""Unit tests for API endpoints."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter
from econext_gateway.core.validity import Readiness
from econext_gateway.main import app
from econext_gateway.protocol.handler import ProtocolHandler
from econext_gateway.serial.connection import GM3SerialTransport

READY = Readiness(
    ready=True,
    reason="ok",
    reset_counter=58,
    last_valid_poll=datetime(2026, 1, 13, 10, 30, 0),
    polls_complete=6,
    polls_incomplete=1,
    polls_discarded=0,
)
NOT_READY = replace(READY, ready=False, reason="controller reset (counter 58 to 59)", polls_discarded=1)


@pytest.fixture
def mock_app_state():
    """Set up mock app state for testing."""
    # Save original state (set by lifespan)
    orig_conn = app_state.connection
    orig_cache = app_state.cache
    orig_handler = app_state.handler

    conn = MagicMock(spec=GM3SerialTransport)
    conn.connected = True

    cache = ParameterCache()

    handler = MagicMock(spec=ProtocolHandler)
    handler.connected = True
    handler.params_ready = True
    handler.readiness.return_value = READY

    app_state.connection = conn
    app_state.cache = cache
    app_state.handler = handler

    yield {"connection": conn, "cache": cache, "handler": handler}

    # Restore original state for lifespan teardown
    app_state.connection = orig_conn
    app_state.cache = orig_cache
    app_state.handler = orig_handler


@pytest.fixture
def client():
    """Create test client without lifespan (we manage state manually)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestRootEndpoint:
    """Tests for GET / endpoint."""

    def test_root(self, client, mock_app_state):
        """Test root endpoint returns app info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "ecoNEXT Gateway"
        assert "version" in data
        assert data["status"] == "running"


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_not_initialized(self, client):
        """Test health when app is not initialized."""
        handler, cache = app_state.handler, app_state.cache
        app_state.handler = None
        app_state.cache = None
        try:
            response = client.get("/health")
        finally:
            # the lifespan of the client fixture still has to stop its handler
            app_state.handler, app_state.cache = handler, cache

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["controller_connected"] is False
        assert data["data_ready"] is False
        assert data["reset_counter"] is None
        assert data["last_valid_poll"] is None

    def test_health_connected_with_params(self, client, mock_app_state):
        """Test health when connected with cached params."""
        import asyncio

        asyncio.run(
            mock_app_state["cache"].set(Parameter(index=0, name="Test", value=42, type=2, unit=0, writable=True))
        )

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["controller_connected"] is True
        assert data["parameters_count"] == 1

    def test_health_connected_no_params(self, client, mock_app_state):
        """Test health when connected but the first poll has not finished."""
        mock_app_state["handler"].params_ready = False
        mock_app_state["handler"].readiness.return_value = replace(READY, ready=False, reason="starting")

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["parameters_ready"] is False
        assert data["data_ready"] is False

    def test_health_disconnected(self, client, mock_app_state):
        """Test health when disconnected: the data is not ready either, although the last poll was valid."""
        mock_app_state["handler"].connected = False
        mock_app_state["handler"].readiness.return_value = replace(READY, ready=False, reason="not connected")

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["controller_connected"] is False
        assert data["data_ready"] is False
        assert data["ready_reason"] == "not connected"

    def test_health_reports_data_readiness_and_poll_counts(self, client, mock_app_state):
        response = client.get("/health")

        data = response.json()
        assert data["status"] == "healthy"
        assert data["data_ready"] is True
        assert data["ready_reason"] == "ok"
        assert data["reset_counter"] == 58
        assert data["last_valid_poll"] == "2026-01-13T10:30:00"
        assert (data["polls_complete"], data["polls_incomplete"], data["polls_discarded"]) == (6, 1, 0)

    def test_health_degraded_when_the_data_is_not_ready(self, client, mock_app_state):
        """Connected and past the first poll, but the last poll was discarded."""
        mock_app_state["handler"].readiness.return_value = NOT_READY

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["parameters_ready"] is True
        assert data["data_ready"] is False
        assert data["ready_reason"] == "controller reset (counter 58 to 59)"
        assert data["polls_discarded"] == 1


class TestGetParameters:
    """Tests for GET /api/parameters endpoint."""

    def test_get_parameters_while_loading(self, client, mock_app_state):
        """A half-filled cache is never served as the parameter set."""
        mock_app_state["handler"].params_ready = False

        response = client.get("/api/parameters")

        assert response.status_code == 503
        assert response.json()["detail"] == "Parameters still loading"

    def test_get_parameters_empty(self, client, mock_app_state):
        """Test getting parameters when cache is empty."""
        response = client.get("/api/parameters")

        assert response.status_code == 200
        data = response.json()
        assert data["parameters"] == {}

    def test_get_parameters_with_data(self, client, mock_app_state):
        """Test getting parameters with cached data."""
        import asyncio

        cache = mock_app_state["cache"]
        asyncio.run(
            cache.set(
                Parameter(
                    index=0,
                    name="Temperature",
                    value=55,
                    type=2,
                    unit=1,
                    writable=True,
                    min_value=20.0,
                    max_value=80.0,
                )
            )
        )
        asyncio.run(
            cache.set(
                Parameter(
                    index=1,
                    name="Pressure",
                    value=2.5,
                    type=7,
                    unit=6,
                    writable=False,
                )
            )
        )

        response = client.get("/api/parameters")

        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert len(data["parameters"]) == 2

        temp = data["parameters"]["0"]
        assert temp["index"] == 0
        assert temp["name"] == "Temperature"
        assert temp["value"] == 55
        assert temp["type"] == 2
        assert temp["unit"] == 1
        assert temp["writable"] is True
        assert temp["min"] == 20.0
        assert temp["max"] == 80.0

        pressure = data["parameters"]["1"]
        assert pressure["name"] == "Pressure"
        assert pressure["value"] == 2.5
        assert pressure["writable"] is False

    def test_get_parameters_reports_readiness(self, client, mock_app_state):
        response = client.get("/api/parameters")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["ready_reason"] == "ok"
        # diagnostics are on /health; the counter is the parameter resetCounter
        assert set(data) == {"timestamp", "ready", "ready_reason", "parameters"}

    def test_get_parameters_not_ready_still_serves_the_last_valid_values(self, client, mock_app_state):
        """Not ready is a flag in the reply, not an error: the cache holds the last valid poll."""
        import asyncio

        asyncio.run(
            mock_app_state["cache"].set(Parameter(index=61, name="TempCWU", value=40.0, type=7, unit=1, writable=False))
        )
        mock_app_state["handler"].readiness.return_value = NOT_READY

        response = client.get("/api/parameters")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False
        assert data["ready_reason"] == "controller reset (counter 58 to 59)"
        assert data["parameters"]["61"]["value"] == 40.0

    def test_get_parameters_disconnected(self, client, mock_app_state):
        """Test getting parameters when controller is disconnected."""
        mock_app_state["handler"].connected = False

        response = client.get("/api/parameters")

        assert response.status_code == 503


class TestSetParameter:
    """Tests for POST /api/parameters/{name} endpoint."""

    def test_set_parameter_success(self, client, mock_app_state):
        """Test successful parameter write."""
        import asyncio

        cache = mock_app_state["cache"]
        asyncio.run(
            cache.set(
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
        )

        mock_app_state["handler"].write_param = AsyncMock(return_value=True)

        response = client.post(
            "/api/parameters/SetPoint",
            json={"value": 65},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["name"] == "SetPoint"
        assert data["old_value"] == 50
        assert data["new_value"] == 65

    def test_set_parameter_accepted_while_the_data_is_not_ready(self, client, mock_app_state):
        """A write is not refused while not ready: a stop set by hand during a
        controller restart must still be taken."""
        import asyncio

        asyncio.run(
            mock_app_state["cache"].set(
                Parameter(index=119, name="HDWusermode", value=1, type=4, unit=0, writable=True)
            )
        )
        mock_app_state["handler"].readiness.return_value = NOT_READY
        mock_app_state["handler"].write_param = AsyncMock(return_value=True)

        response = client.post("/api/parameters/HDWusermode", json={"value": 0})

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_app_state["handler"].write_param.assert_awaited_once_with("HDWusermode", 0)

    def test_set_parameter_not_found(self, client, mock_app_state):
        """Test setting nonexistent parameter."""
        response = client.post(
            "/api/parameters/NonExistent",
            json={"value": 42},
        )

        assert response.status_code == 404

    def test_set_parameter_validation_error(self, client, mock_app_state):
        """Test setting parameter with invalid value."""
        import asyncio

        cache = mock_app_state["cache"]
        asyncio.run(
            cache.set(
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
        )

        mock_app_state["handler"].write_param = AsyncMock(
            side_effect=ValueError("Value 100 above maximum 80.0 for Temp")
        )

        response = client.post(
            "/api/parameters/Temp",
            json={"value": 100},
        )

        assert response.status_code == 400

    def test_set_parameter_write_failure(self, client, mock_app_state):
        """Test parameter write not acknowledged."""
        import asyncio

        cache = mock_app_state["cache"]
        asyncio.run(
            cache.set(
                Parameter(
                    index=0,
                    name="Temp",
                    value=50,
                    type=2,
                    unit=1,
                    writable=True,
                )
            )
        )

        mock_app_state["handler"].write_param = AsyncMock(return_value=False)

        response = client.post(
            "/api/parameters/Temp",
            json={"value": 60},
        )

        assert response.status_code == 503

    def test_set_parameter_disconnected(self, client, mock_app_state):
        """Test setting parameter when disconnected."""
        mock_app_state["handler"].connected = False

        response = client.post(
            "/api/parameters/Temp",
            json={"value": 60},
        )

        assert response.status_code == 503

    def test_set_parameter_missing_value(self, client, mock_app_state):
        """Test setting parameter without value field."""
        response = client.post(
            "/api/parameters/Temp",
            json={},
        )

        assert response.status_code == 422


class TestSetParameters:
    """Tests for POST /api/parameters (batch write)."""

    @staticmethod
    def _seed(cache, names):
        import asyncio

        for i, name in enumerate(names):
            asyncio.run(
                cache.set(
                    Parameter(index=i, name=name, value=i, type=2, unit=0, writable=True)
                )
            )

    def test_set_parameters_success(self, client, mock_app_state):
        self._seed(mock_app_state["cache"], ["A", "B"])
        mock_app_state["handler"].write_params = AsyncMock(return_value={"A": True, "B": True})

        response = client.post("/api/parameters", json={"values": {"A": 10, "B": 20}})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["A"] == {"success": True, "old_value": 0, "new_value": 10}
        assert data["results"]["B"] == {"success": True, "old_value": 1, "new_value": 20}
        mock_app_state["handler"].write_params.assert_awaited_once_with({"A": 10, "B": 20})

    def test_set_parameters_by_index(self, client, mock_app_state):
        """A digit key addresses the parameter by index."""
        self._seed(mock_app_state["cache"], ["A", "B"])
        mock_app_state["handler"].write_params = AsyncMock(return_value={"1": True})

        response = client.post("/api/parameters", json={"values": {"1": 20}})

        assert response.status_code == 200
        assert response.json()["results"]["1"] == {"success": True, "old_value": 1, "new_value": 20}
        mock_app_state["handler"].write_params.assert_awaited_once_with({"1": 20})

    def test_set_parameters_partial_failure(self, client, mock_app_state):
        self._seed(mock_app_state["cache"], ["A", "B"])
        mock_app_state["handler"].write_params = AsyncMock(return_value={"A": True, "B": False})

        response = client.post("/api/parameters", json={"values": {"A": 10, "B": 20}})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["results"]["B"]["success"] is False

    def test_set_parameters_unknown_name_writes_nothing(self, client, mock_app_state):
        self._seed(mock_app_state["cache"], ["A"])
        mock_app_state["handler"].write_params = AsyncMock()

        response = client.post("/api/parameters", json={"values": {"A": 10, "Nope": 1}})

        assert response.status_code == 404
        mock_app_state["handler"].write_params.assert_not_awaited()

    def test_set_parameters_validation_error(self, client, mock_app_state):
        self._seed(mock_app_state["cache"], ["A"])
        mock_app_state["handler"].write_params = AsyncMock(
            side_effect=ValueError("Value 5000 above maximum 1000.0 for A")
        )

        response = client.post("/api/parameters", json={"values": {"A": 5000}})

        assert response.status_code == 400

    def test_set_parameters_empty(self, client, mock_app_state):
        response = client.post("/api/parameters", json={"values": {}})

        assert response.status_code == 422

    def test_set_parameters_too_many(self, client, mock_app_state):
        response = client.post(
            "/api/parameters", json={"values": {f"P{i}": i for i in range(65)}}
        )

        assert response.status_code == 422

    def test_set_parameters_disconnected(self, client, mock_app_state):
        mock_app_state["handler"].connected = False

        response = client.post("/api/parameters", json={"values": {"A": 1}})

        assert response.status_code == 503
