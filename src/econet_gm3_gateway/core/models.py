"""Data models for GM3 gateway."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Parameter(BaseModel):
    """Represents a single parameter from the controller."""

    index: int = Field(..., ge=0, description="Parameter index")
    name: str = Field(..., min_length=1, description="Parameter name")
    value: Any = Field(..., description="Current parameter value")
    type: int = Field(..., ge=1, description="Data type code")
    unit: int = Field(..., ge=0, description="Unit code")
    writable: bool = Field(..., description="Whether parameter can be modified")
    min_value: float | None = Field(None, description="Minimum allowed value")
    max_value: float | None = Field(None, description="Maximum allowed value")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure parameter name is not empty after stripping."""
        if not v.strip():
            raise ValueError("Parameter name cannot be empty")
        return v

    @field_validator("max_value")
    @classmethod
    def validate_range(cls, v: float | None, info) -> float | None:
        """Ensure max_value >= min_value if both are set."""
        if v is not None and info.data.get("min_value") is not None:
            if v < info.data["min_value"]:
                raise ValueError("max_value must be >= min_value")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "index": 103,
                "name": "ExampleParameter",
                "value": 45,
                "type": 2,
                "unit": 1,
                "writable": True,
                "min_value": 20.0,
                "max_value": 80.0,
            }
        }
    )


class ParameterCollection(BaseModel):
    """Collection of parameters with metadata."""

    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp of parameter snapshot")
    parameters: dict[str, Parameter] = Field(default_factory=dict, description="Parameters keyed by name")

    def get_parameter(self, name: str) -> Parameter | None:
        """Get parameter by name."""
        return self.parameters.get(name)

    def set_parameter(self, parameter: Parameter) -> None:
        """Add or update a parameter."""
        self.parameters[parameter.name] = parameter

    def remove_parameter(self, name: str) -> bool:
        """Remove parameter by name. Returns True if removed, False if not found."""
        if name in self.parameters:
            del self.parameters[name]
            return True
        return False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timestamp": "2026-01-13T10:30:00",
                "parameters": {
                    "HDWTSetPoint": {
                        "index": 103,
                        "name": "ExampleParameter",
                        "value": 45,
                        "type": 2,
                        "unit": 1,
                        "writable": True,
                        "min_value": 20.0,
                        "max_value": 80.0,
                    }
                },
            }
        }
    )


# ============================================================================
# API Request/Response Models
# ============================================================================


class ParametersResponse(BaseModel):
    """Response model for GET /api/parameters."""

    timestamp: datetime = Field(..., description="Timestamp of parameter snapshot")
    parameters: dict[str, dict[str, Any]] = Field(..., description="Parameters keyed by name")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "timestamp": "2026-01-13T10:30:00",
                "parameters": {
                    "HDWTSetPoint": {
                        "index": 103,
                        "value": 45,
                        "type": 2,
                        "unit": 1,
                        "writable": True,
                        "min": 20.0,
                        "max": 80.0,
                    }
                },
            }
        }
    )


class ParameterSetRequest(BaseModel):
    """Request model for POST /api/parameters/{name}."""

    value: Any = Field(..., description="New parameter value")

    model_config = ConfigDict(json_schema_extra={"example": {"value": 50}})


class ParameterSetResponse(BaseModel):
    """Response model for successful parameter set operation."""

    success: bool = Field(True, description="Operation success status")
    name: str = Field(..., description="Parameter name")
    old_value: Any = Field(..., description="Previous parameter value")
    new_value: Any = Field(..., description="New parameter value")
    timestamp: datetime = Field(default_factory=datetime.now, description="Operation timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "name": "HDWTSetPoint",
                "old_value": 45,
                "new_value": 50,
                "timestamp": "2026-01-13T10:30:00",
            }
        }
    )


class ErrorResponse(BaseModel):
    """Response model for errors."""

    success: bool = Field(False, description="Operation success status")
    error: str = Field(..., description="Error message")
    detail: str | None = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "error": "Parameter not found",
                "detail": "Parameter 'InvalidParam' does not exist",
                "timestamp": "2026-01-13T10:30:00",
            }
        }
    )


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Health status (healthy/degraded/unhealthy)")
    controller_connected: bool = Field(..., description="Whether controller is connected")
    parameters_count: int = Field(..., ge=0, description="Number of cached parameters")
    last_update: datetime | None = Field(None, description="Last successful update timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "controller_connected": True,
                "parameters_count": 1786,
                "last_update": "2026-01-13T10:30:00",
            }
        }
    )
