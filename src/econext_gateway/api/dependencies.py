"""FastAPI dependency injection for shared application state."""

from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.config import Settings
from econext_gateway.protocol.handler import ProtocolHandler
from econext_gateway.serial.connection import GM3SerialTransport


class AppState:
    """Holds shared application state instances.

    Created during app startup and accessed via FastAPI dependencies.
    """

    def __init__(self) -> None:
        self.settings: Settings | None = None
        self.connection: GM3SerialTransport | None = None
        self.cache: ParameterCache | None = None
        self.handler: ProtocolHandler | None = None


# Global app state singleton
app_state = AppState()


def get_cache() -> ParameterCache:
    """Get the parameter cache instance."""
    assert app_state.cache is not None, "App not initialized"
    return app_state.cache


def get_handler() -> ProtocolHandler:
    """Get the protocol handler instance."""
    assert app_state.handler is not None, "App not initialized"
    return app_state.handler


def get_settings() -> Settings:
    """Get the settings instance."""
    assert app_state.settings is not None, "App not initialized"
    return app_state.settings
