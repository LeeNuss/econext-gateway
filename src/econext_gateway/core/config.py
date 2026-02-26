"""Application configuration using pydantic-settings."""

import logging
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden via environment variables
    prefixed with ECONEXT_ (e.g., ECONEXT_SERIAL_PORT).
    """

    serial_port: str = "/dev/econext"
    serial_baud: int = 115200
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    poll_interval: float = 10.0
    request_timeout: float = 1.5
    destination_address: int = 1
    params_per_request: int = 100
    token_required: bool = True
    coexistence_mode: bool = False
    state_dir: str = "/var/lib/econext-gateway"

    model_config = SettingsConfigDict(env_prefix="ECONEXT_")

    @property
    def paired_address_file(self) -> Path:
        """Path to the file storing the panel-assigned bus address."""
        return Path(self.state_dir) / "paired_address"


def setup_logging(level: str = "INFO") -> None:
    """Configure application logging.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
