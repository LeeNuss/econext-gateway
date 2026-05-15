"""API route handlers."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from econext_gateway.api.dependencies import get_cache, get_handler, get_virtual_thermostat
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import (
    AlarmsResponse,
    ClockSyncRequest,
    ClockSyncResponse,
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

_logger = logging.getLogger(__name__)

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


@router.post(
    "/clock/sync",
    response_model=ClockSyncResponse,
    responses={503: {"model": ErrorResponse}},
)
async def sync_clock(
    request: ClockSyncRequest,
    handler: ProtocolHandler = Depends(get_handler),
):
    """Broadcast a SERVICE 0x0023 clock-sync frame on the bus.

    Test endpoint: lets us probe whether the panel accepts an external
    time source. Pass `when` to broadcast a deliberately-wrong time;
    omit it to broadcast host current time.
    """
    if not handler.connected:
        raise HTTPException(status_code=503, detail="Controller not connected")
    target = request.when or datetime.now()
    await handler.broadcast_clock_sync(target)
    return ClockSyncResponse(success=True, broadcast=target)


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
    _logger.info(
        "Thermostat temp submitted: %.2f C (previous_age=%s s)",
        request.temperature,
        round(previous_age, 1) if previous_age is not None else None,
    )
    return ThermostatSubmitResponse(
        success=True,
        temperature=thermostat.temperature,
        previous_age_seconds=round(previous_age, 1) if previous_age is not None else None,
    )


@router.post(
    "/thermostat/pair",
    responses={503: {"model": ErrorResponse}},
)
async def request_thermostat_pairing(
    handler: ProtocolHandler = Depends(get_handler),
):
    """Request thermostat pairing. Put the panel in pairing mode first."""
    success = handler.request_thermostat_pairing()
    if not success:
        raise HTTPException(
            status_code=409,
            detail="Thermostat already paired or pairing not available",
        )
    return {"success": True, "message": "Pairing requested, put panel in pairing mode within 60s"}


@router.get("/thermostat/status", response_model=ThermostatStatusResponse)
async def get_thermostat_status(
    thermostat: VirtualThermostat = Depends(get_virtual_thermostat),
    handler: ProtocolHandler = Depends(get_handler),
):
    """Get virtual thermostat status including pairing state."""
    age = thermostat.age_seconds
    effective_temp = thermostat.effective_temperature  # also updates effective_source

    return ThermostatStatusResponse(
        enabled=True,
        temperature=thermostat.temperature,
        effective_temperature=effective_temp,
        is_stale=thermostat.is_stale,
        age_seconds=round(age, 1) if age is not None else None,
        max_age_seconds=thermostat.max_age,
        stale_fallback=thermostat.stale_fallback,
        pairing_state=handler.thermostat_pairing_state,
        bus_address=handler.thermostat_address,
        effective_source=thermostat.effective_source,
    )
