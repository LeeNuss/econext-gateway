"""FastAPI dependency injection for shared application state."""

from typing import Optional

from ..core.cache import ParameterCache
from ..core.config import Settings
from ..protocol.handler import ProtocolHandler
from ..serial.connection import SerialConnection


class AppState:
    """Holds shared application state instances.

    Created during app startup and accessed via FastAPI dependencies.
    """

    def __init__(self) -> None:
        self.settings: Optional[Settings] = None
        self.connection: Optional[SerialConnection] = None
        self.cache: Optional[ParameterCache] = None
        self.handler: Optional[ProtocolHandler] = None


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
