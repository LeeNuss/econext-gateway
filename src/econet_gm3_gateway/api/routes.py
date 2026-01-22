"""API route handlers."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from econet_gm3_gateway.api.dependencies import get_cache, get_handler
from econet_gm3_gateway.core.cache import ParameterCache
from econet_gm3_gateway.core.models import (
    ErrorResponse,
    ParameterSetRequest,
    ParameterSetResponse,
    ParametersResponse,
)
from econet_gm3_gateway.protocol.handler import ProtocolHandler

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
    for name, param in params.items():
        parameters_dict[name] = {
            "index": param.index,
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

    param = await cache.get(name)
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
