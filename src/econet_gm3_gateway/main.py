"""Main application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from econet_gm3_gateway import __version__
from econet_gm3_gateway.api.dependencies import app_state
from econet_gm3_gateway.api.routes import router as api_router
from econet_gm3_gateway.core.cache import ParameterCache
from econet_gm3_gateway.core.config import Settings, setup_logging
from econet_gm3_gateway.core.models import HealthResponse
from econet_gm3_gateway.protocol.handler import ProtocolHandler
from econet_gm3_gateway.serial.connection import SerialConnection

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    settings = app_state.settings or Settings()
    app_state.settings = settings

    setup_logging(settings.log_level)
    logger.info(f"Starting econet GM3 Gateway v{__version__}")

    # Initialize components
    app_state.cache = ParameterCache()
    app_state.connection = SerialConnection(
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
    )

    # Connect and start polling
    connected = await app_state.connection.connect()
    if connected:
        logger.info(f"Connected to {settings.serial_port}")
        await app_state.handler.start()
    else:
        logger.warning(f"Failed to connect to {settings.serial_port}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if app_state.handler is not None:
        await app_state.handler.stop()
    if app_state.connection is not None and app_state.connection.connected:
        await app_state.connection.disconnect()


app = FastAPI(
    title="econet GM3 Gateway",
    description="Local REST API gateway for GM3 protocol heat pump controllers",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "econet GM3 Gateway",
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
