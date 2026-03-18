"""API route handlers."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from econext_gateway.api.dependencies import get_cache, get_handler, get_virtual_thermostat
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import (
    AlarmsResponse,
    ErrorResponse,
    ParameterSetRequest,
    ParameterSetResponse,
    ParametersResponse,
    ThermostatStatusResponse,
    ThermostatSubmitRequest,
    ThermostatSubmitResponse,
)
from econext_gateway.core.virtual_thermostat import VirtualThermostat
from econext_gateway.protocol.handler import ProtocolHandler

router = APIRouter(prefix="/api")


@router.get("/parameters", response_model=ParametersResponse)
async def get_parameters(
    cache: ParameterCache = Depends(get_cache),
    handler: ProtocolHandler = Depends(get_handler),
):
    """Get all cached parameter values."""
    if not handler.connected:
        raise HTTPException(status_code=503, detail="Controller not connected")

    params = await cache.get_all()

    parameters_dict = {}
    for index_str, param in params.items():
        parameters_dict[index_str] = {
            "index": param.index,
            "name": param.name,
            "value": param.value,
            "type": param.type,
            "unit": param.unit,
            "writable": param.writable,
            "min": param.min_value,
            "max": param.max_value,
        }

    return ParametersResponse(
        timestamp=cache.last_update or datetime.now(),
        parameters=parameters_dict,
    )


@router.post(
    "/parameters/{name}",
    response_model=ParameterSetResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def set_parameter(
    name: str,
    request: ParameterSetRequest,
    cache: ParameterCache = Depends(get_cache),
    handler: ProtocolHandler = Depends(get_handler),
):
    """Set a parameter value."""
    if not handler.connected:
        raise HTTPException(status_code=503, detail="Controller not connected")

    param = await cache.get_by_name(name)
    if param is None:
        raise HTTPException(status_code=404, detail=f"Parameter not found: {name}")

    old_value = param.value

    try:
        success = await handler.write_param(name, request.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not success:
        raise HTTPException(status_code=503, detail="Controller did not acknowledge write")

    return ParameterSetResponse(
        success=True,
        name=name,
        old_value=old_value,
        new_value=request.value,
    )


@router.get("/alarms", response_model=AlarmsResponse)
async def get_alarms(
    handler: ProtocolHandler = Depends(get_handler),
):
    """Get alarm history from the controller."""
    if not handler.connected:
        raise HTTPException(status_code=503, detail="Controller not connected")

    return AlarmsResponse(alarms=handler.alarms)


@router.post(
    "/thermostat/temperature",
    response_model=ThermostatSubmitResponse,
    responses={503: {"model": ErrorResponse}},
)
async def submit_thermostat_temperature(
    request: ThermostatSubmitRequest,
    thermostat: VirtualThermostat = Depends(get_virtual_thermostat),
):
    """Submit a room temperature reading from Home Assistant."""
    previous_age = thermostat.update(request.temperature)
    return ThermostatSubmitResponse(
        success=True,
        temperature=thermostat.temperature,
        previous_age_seconds=round(previous_age, 1) if previous_age is not None else None,
    )


@router.get("/thermostat/status", response_model=ThermostatStatusResponse)
async def get_thermostat_status(
    thermostat: VirtualThermostat = Depends(get_virtual_thermostat),
):
    """Get virtual thermostat status."""
    age = thermostat.age_seconds
    return ThermostatStatusResponse(
        enabled=True,
        temperature=thermostat.temperature,
        effective_temperature=thermostat.effective_temperature,
        is_stale=thermostat.is_stale,
        age_seconds=round(age, 1) if age is not None else None,
        max_age_seconds=thermostat._max_age,
        stale_fallback=thermostat._stale_fallback,
    )
