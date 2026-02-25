"""API routes for compressor cycling monitoring and anti-cycling settings."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from econext_gateway.api.dependencies import get_cache, get_handler, get_monitor, get_settings
from econext_gateway.control.cycling import CompressorMonitor
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.config import Settings
from econext_gateway.core.models import (
    AntiCyclingSettingsRequest,
    AntiCyclingSettingsResponse,
    CycleEventResponse,
    CyclingMetricsResponse,
    ErrorResponse,
)
from econext_gateway.protocol.handler import ProtocolHandler

router = APIRouter(prefix="/api/cycling")


@router.get("/metrics", response_model=CyclingMetricsResponse)
async def get_cycling_metrics(
    monitor: CompressorMonitor = Depends(get_monitor),
):
    """Get current compressor cycling metrics."""
    metrics = await monitor.get_metrics()
    return CyclingMetricsResponse(**metrics)


@router.get("/history", response_model=list[CycleEventResponse])
async def get_cycling_history(
    monitor: CompressorMonitor = Depends(get_monitor),
):
    """Get recent compressor cycle events (last 24h, max 100)."""
    events = monitor.events
    # Return most recent 100
    recent = events[-100:] if len(events) > 100 else events
    return [
        CycleEventResponse(
            timestamp=datetime.fromtimestamp(e.wall_time, tz=UTC),
            turned_on=e.turned_on,
            duration=round(e.duration, 1),
        )
        for e in recent
    ]


@router.get("/settings", response_model=AntiCyclingSettingsResponse)
async def get_cycling_settings(
    cache: ParameterCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
):
    """Get current anti-cycling timer settings from controller."""
    min_work = await cache.get(498)
    min_break = await cache.get(499)
    compr_min = await cache.get(503)

    return AntiCyclingSettingsResponse(
        anticycling_enabled=settings.anticycling_enabled,
        min_work_time=min_work.value if min_work else None,
        min_break_time=min_break.value if min_break else None,
        compressor_min_times_sett=compr_min.value if compr_min else None,
    )


@router.post(
    "/settings",
    response_model=AntiCyclingSettingsResponse,
    responses={503: {"model": ErrorResponse}},
)
async def set_cycling_settings(
    request: AntiCyclingSettingsRequest,
    handler: ProtocolHandler = Depends(get_handler),
    cache: ParameterCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
):
    """Write new anti-cycling timer settings to controller."""
    if not handler.connected:
        raise HTTPException(status_code=503, detail="Controller not connected")

    if request.min_work_time is None and request.min_break_time is None:
        raise HTTPException(status_code=400, detail="At least one setting must be provided")

    if request.min_work_time is not None:
        try:
            success = await handler.write_param("minWorkTime", request.min_work_time)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if not success:
            raise HTTPException(status_code=503, detail="Controller did not acknowledge minWorkTime write")

    if request.min_break_time is not None:
        try:
            success = await handler.write_param("minBreakTime", request.min_break_time)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if not success:
            raise HTTPException(status_code=503, detail="Controller did not acknowledge minBreakTime write")

    # Return updated settings
    min_work = await cache.get(498)
    min_break = await cache.get(499)
    compr_min = await cache.get(503)

    return AntiCyclingSettingsResponse(
        anticycling_enabled=settings.anticycling_enabled,
        min_work_time=min_work.value if min_work else None,
        min_break_time=min_break.value if min_break else None,
        compressor_min_times_sett=compr_min.value if compr_min else None,
    )
