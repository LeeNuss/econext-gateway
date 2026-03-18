"""Main application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from econext_gateway import __version__
from econext_gateway.api.dependencies import app_state
from econext_gateway.api.routes import router as api_router
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.config import Settings, setup_logging
from econext_gateway.core.models import HealthResponse
from econext_gateway.core.virtual_thermostat import VirtualThermostat
from econext_gateway.protocol.handler import ProtocolHandler
from econext_gateway.serial.connection import GM3SerialTransport
from econext_gateway.thermostat.emulator import ThermostatEmulator

logger = logging.getLogger(__name__)


def _load_address(path: Path) -> int | None:
    """Load a bus address from a file (single integer)."""
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = app_state.settings or Settings()
    app_state.settings = settings

    setup_logging(settings.log_level)
    logger.info(f"Starting ecoNEXT Gateway v{__version__}")

    # Initialize components
    persist_file = Path(settings.state_dir) / "thermostat_temperature" if settings.thermostat_enabled else None
    app_state.virtual_thermostat = VirtualThermostat(
        max_age=settings.thermostat_max_age,
        stale_fallback=settings.thermostat_stale_fallback,
        persist_file=persist_file,
    )
    if settings.thermostat_enabled:
        logger.info("Virtual thermostat enabled (max_age=%.0fs)", settings.thermostat_max_age)

    # Create thermostat emulator if enabled (address=0 triggers auto-registration)
    thermostat_emulator = None
    if settings.thermostat_enabled:
        thermostat_addr = _load_address(settings.thermostat_address_file)
        thermostat_emulator = ThermostatEmulator(
            address=thermostat_addr or 0,
            virtual_thermostat=app_state.virtual_thermostat,
        )
        if thermostat_addr is not None:
            logger.info("Thermostat emulator active at address %d", thermostat_addr)
        else:
            logger.info("Thermostat emulator created, will auto-register during pairing")

    app_state.cache = ParameterCache()
    app_state.connection = GM3SerialTransport(
        port=settings.serial_port,
        baudrate=settings.serial_baud,
    )
    app_state.handler = ProtocolHandler(
        connection=app_state.connection,
        cache=app_state.cache,
        destination=settings.destination_address,
        poll_interval=settings.poll_interval,
        request_timeout=settings.request_timeout,
        params_per_request=settings.params_per_request,
        token_required=settings.token_required,
        paired_address_file=settings.paired_address_file,
        thermostat_emulator=thermostat_emulator,
        thermostat_address_file=settings.thermostat_address_file if settings.thermostat_enabled else None,
    )

    # Connect and start polling
    connected = await app_state.connection.connect()
    if connected:
        logger.info(f"Connected to {settings.serial_port}")
    else:
        logger.warning(f"Failed to connect to {settings.serial_port}, will retry in background")

    # Start reconnect loop (handles connection drops and initial failures)
    await app_state.connection.start_reconnect_loop()

    # Always start handler - poll loop waits for connection
    await app_state.handler.start()

    yield

    # Shutdown
    logger.info("Shutting down...")
    if app_state.handler is not None:
        await app_state.handler.stop()
    if app_state.connection is not None:
        await app_state.connection.stop_reconnect_loop()
        if app_state.connection.connected:
            await app_state.connection.disconnect()


app = FastAPI(
    title="ecoNEXT Gateway",
    description="Local REST API gateway for heat pump controllers",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "ecoNEXT Gateway",
        "version": __version__,
        "status": "running",
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    handler = app_state.handler
    cache = app_state.cache

    if handler is None or cache is None:
        return HealthResponse(
            status="unhealthy",
            controller_connected=False,
            parameters_count=0,
            last_update=None,
        )

    connected = handler.connected
    status = "healthy" if connected and cache.count > 0 else ("degraded" if connected else "unhealthy")

    return HealthResponse(
        status=status,
        controller_connected=connected,
        parameters_count=cache.count,
        last_update=cache.last_update,
    )


def main():
    """Run the application (for CLI entry point)."""
    import uvicorn

    settings = Settings()
    setup_logging(settings.log_level)
    app_state.settings = settings

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
