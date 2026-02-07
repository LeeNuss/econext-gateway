"""Unit tests for API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from econext_gateway.api.dependencies import app_state
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter
from econext_gateway.main import app
from econext_gateway.protocol.handler import ProtocolHandler
from econext_gateway.serial.connection import SerialConnection


@pytest.fixture
def mock_app_state():
    """Set up mock app state for testing."""
    # Save original state (set by lifespan)
    orig_conn = app_state.connection
    orig_cache = app_state.cache
    orig_handler = app_state.handler

    conn = MagicMock(spec=SerialConnection)
    conn.connected = True

    cache = ParameterCache()

    handler = MagicMock(spec=ProtocolHandler)
    handler.connected = True

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
        app_state.handler = None
        app_state.cache = None

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["controller_connected"] is False

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
        """Test health when connected but no params yet."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_health_disconnected(self, client, mock_app_state):
        """Test health when disconnected."""
        mock_app_state["handler"].connected = False

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["controller_connected"] is False


class TestGetParameters:
    """Tests for GET /api/parameters endpoint."""

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
