"""Unit tests for data models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from econet_gm3_gateway.core.models import (
    ErrorResponse,
    HealthResponse,
    Parameter,
    ParameterCollection,
    ParameterSetRequest,
    ParameterSetResponse,
    ParametersResponse,
)


class TestParameter:
    """Tests for Parameter model."""

    def test_parameter_valid(self):
        """Test creating a valid parameter."""
        param = Parameter(
            index=103,
            name="HDWTSetPoint",
            value=45,
            type=2,
            unit=1,
            writable=True,
            min_value=20.0,
            max_value=80.0,
        )

        assert param.index == 103
        assert param.name == "HDWTSetPoint"
        assert param.value == 45
        assert param.type == 2
        assert param.unit == 1
        assert param.writable is True
        assert param.min_value == 20.0
        assert param.max_value == 80.0

    def test_parameter_minimal(self):
        """Test parameter with minimal required fields."""
        param = Parameter(
            index=0,
            name="TestParam",
            value=100,
            type=1,
            unit=0,
            writable=False,
        )

        assert param.index == 0
        assert param.name == "TestParam"
        assert param.min_value is None
        assert param.max_value is None

    def test_parameter_negative_index(self):
        """Test parameter with negative index fails validation."""
        with pytest.raises(ValidationError):
            Parameter(
                index=-1,
                name="Test",
                value=0,
                type=1,
                unit=0,
                writable=False,
            )

    def test_parameter_empty_name(self):
        """Test parameter with empty name fails validation."""
        with pytest.raises(ValidationError):
            Parameter(
                index=0,
                name="",
                value=0,
                type=1,
                unit=0,
                writable=False,
            )

    def test_parameter_whitespace_name(self):
        """Test parameter with whitespace-only name fails validation."""
        with pytest.raises(ValidationError):
            Parameter(
                index=0,
                name="   ",
                value=0,
                type=1,
                unit=0,
                writable=False,
            )

    def test_parameter_invalid_range_cleared(self):
        """Test parameter with max < min clears the range."""
        param = Parameter(
            index=0,
            name="Test",
            value=50,
            type=1,
            unit=0,
            writable=True,
            min_value=80.0,
            max_value=20.0,
        )
        assert param.min_value is None
        assert param.max_value is None

    def test_parameter_different_value_types(self):
        """Test parameter accepts different value types."""
        # Integer
        param_int = Parameter(index=0, name="Int", value=42, type=2, unit=0, writable=False)
        assert param_int.value == 42

        # Float
        param_float = Parameter(index=1, name="Float", value=22.5, type=7, unit=1, writable=False)
        assert param_float.value == 22.5

        # Boolean
        param_bool = Parameter(index=2, name="Bool", value=True, type=10, unit=0, writable=False)
        assert param_bool.value is True

        # String
        param_str = Parameter(index=3, name="String", value="test", type=12, unit=0, writable=False)
        assert param_str.value == "test"


class TestParameterCollection:
    """Tests for ParameterCollection model."""

    def test_collection_empty(self):
        """Test creating an empty collection."""
        collection = ParameterCollection()

        assert isinstance(collection.timestamp, datetime)
        assert len(collection.parameters) == 0

    def test_collection_with_parameters(self):
        """Test creating collection with parameters."""
        param1 = Parameter(index=0, name="Param1", value=10, type=1, unit=0, writable=False)
        param2 = Parameter(index=1, name="Param2", value=20, type=1, unit=0, writable=False)

        collection = ParameterCollection(parameters={"Param1": param1, "Param2": param2})

        assert len(collection.parameters) == 2
        assert "Param1" in collection.parameters
        assert "Param2" in collection.parameters

    def test_collection_get_parameter(self):
        """Test getting parameter from collection."""
        param = Parameter(index=0, name="Test", value=10, type=1, unit=0, writable=False)
        collection = ParameterCollection(parameters={"Test": param})

        result = collection.get_parameter("Test")
        assert result is not None
        assert result.name == "Test"
        assert result.value == 10

    def test_collection_get_nonexistent(self):
        """Test getting nonexistent parameter returns None."""
        collection = ParameterCollection()
        result = collection.get_parameter("DoesNotExist")
        assert result is None

    def test_collection_set_parameter(self):
        """Test adding parameter to collection."""
        collection = ParameterCollection()
        param = Parameter(index=0, name="New", value=42, type=1, unit=0, writable=False)

        collection.set_parameter(param)

        assert len(collection.parameters) == 1
        assert "New" in collection.parameters
        assert collection.parameters["New"].value == 42

    def test_collection_update_parameter(self):
        """Test updating existing parameter in collection."""
        param1 = Parameter(index=0, name="Test", value=10, type=1, unit=0, writable=True)
        collection = ParameterCollection(parameters={"Test": param1})

        param2 = Parameter(index=0, name="Test", value=20, type=1, unit=0, writable=True)
        collection.set_parameter(param2)

        assert len(collection.parameters) == 1
        assert collection.parameters["Test"].value == 20

    def test_collection_remove_parameter(self):
        """Test removing parameter from collection."""
        param = Parameter(index=0, name="Test", value=10, type=1, unit=0, writable=False)
        collection = ParameterCollection(parameters={"Test": param})

        result = collection.remove_parameter("Test")

        assert result is True
        assert len(collection.parameters) == 0
        assert "Test" not in collection.parameters

    def test_collection_remove_nonexistent(self):
        """Test removing nonexistent parameter returns False."""
        collection = ParameterCollection()
        result = collection.remove_parameter("DoesNotExist")
        assert result is False


class TestParametersResponse:
    """Tests for ParametersResponse model."""

    def test_parameters_response_valid(self):
        """Test creating valid parameters response."""
        timestamp = datetime(2026, 1, 13, 10, 30, 0)
        params = {
            "HDWTSetPoint": {
                "index": 103,
                "value": 45,
                "type": 2,
                "unit": 1,
                "writable": True,
                "min": 20.0,
                "max": 80.0,
            }
        }

        response = ParametersResponse(timestamp=timestamp, parameters=params)

        assert response.timestamp == timestamp
        assert len(response.parameters) == 1
        assert "HDWTSetPoint" in response.parameters

    def test_parameters_response_empty(self):
        """Test parameters response with no parameters."""
        response = ParametersResponse(timestamp=datetime.now(), parameters={})
        assert len(response.parameters) == 0


class TestParameterSetRequest:
    """Tests for ParameterSetRequest model."""

    def test_set_request_integer(self):
        """Test parameter set request with integer value."""
        request = ParameterSetRequest(value=50)
        assert request.value == 50

    def test_set_request_float(self):
        """Test parameter set request with float value."""
        request = ParameterSetRequest(value=22.5)
        assert request.value == 22.5

    def test_set_request_bool(self):
        """Test parameter set request with boolean value."""
        request = ParameterSetRequest(value=True)
        assert request.value is True

    def test_set_request_string(self):
        """Test parameter set request with string value."""
        request = ParameterSetRequest(value="test")
        assert request.value == "test"


class TestParameterSetResponse:
    """Tests for ParameterSetResponse model."""

    def test_set_response_valid(self):
        """Test creating valid parameter set response."""
        response = ParameterSetResponse(
            name="HDWTSetPoint",
            old_value=45,
            new_value=50,
        )

        assert response.success is True
        assert response.name == "HDWTSetPoint"
        assert response.old_value == 45
        assert response.new_value == 50
        assert isinstance(response.timestamp, datetime)


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_error_response_minimal(self):
        """Test error response with minimal fields."""
        response = ErrorResponse(error="Test error")

        assert response.success is False
        assert response.error == "Test error"
        assert response.detail is None
        assert isinstance(response.timestamp, datetime)

    def test_error_response_with_detail(self):
        """Test error response with detail."""
        response = ErrorResponse(
            error="Parameter not found",
            detail="Parameter 'InvalidParam' does not exist",
        )

        assert response.success is False
        assert response.error == "Parameter not found"
        assert response.detail == "Parameter 'InvalidParam' does not exist"


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_health_response_healthy(self):
        """Test healthy status response."""
        response = HealthResponse(
            status="healthy",
            controller_connected=True,
            parameters_count=1786,
            last_update=datetime(2026, 1, 13, 10, 30, 0),
        )

        assert response.status == "healthy"
        assert response.controller_connected is True
        assert response.parameters_count == 1786
        assert response.last_update is not None

    def test_health_response_unhealthy(self):
        """Test unhealthy status response."""
        response = HealthResponse(
            status="unhealthy",
            controller_connected=False,
            parameters_count=0,
            last_update=None,
        )

        assert response.status == "unhealthy"
        assert response.controller_connected is False
        assert response.parameters_count == 0
        assert response.last_update is None

    def test_health_response_negative_count(self):
        """Test health response with negative count fails validation."""
        with pytest.raises(ValidationError):
            HealthResponse(
                status="healthy",
                controller_connected=True,
                parameters_count=-1,
            )
