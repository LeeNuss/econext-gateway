"""Application configuration using pydantic-settings."""

import logging
import sys
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from econext_gateway.core.validity import DEFAULT_RESET_COUNTER_PARAM, DEFAULT_SENTINELS, parse_names


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
    state_dir: str = "/var/lib/econext-gateway"

    # Virtual thermostat emulation (set ECONEXT_THERMOSTAT_ENABLED=false to disable)
    thermostat_enabled: bool = True
    thermostat_max_age: float = 300.0
    thermostat_stale_fallback: float = 19.0

    # Panel RTC sync. Gateway broadcasts SERVICE 0x0023 to keep the panel
    # (and via its rebroadcast cycle, the controller) on host-clock time.
    # Daily anchor at clock_sync_hour:clock_sync_minute local; an additional
    # sync is triggered whenever a wall/monotonic skew is detected (DST or
    # NTP step).
    clock_sync_enabled: bool = True
    clock_sync_hour: int = 3
    clock_sync_minute: int = 30

    # Poll validity (core/validity.py). A poll taken while the controller
    # restarts is not written to the cache.
    # Name of the controller's reset counter; a poll in which it changes is
    # discarded. Empty disables the rule.
    reset_counter_param: str = DEFAULT_RESET_COUNTER_PARAM
    # Comma separated names of parameters that never read 0 in operation; a
    # poll in which one of them reads 0, after it has read non-zero, is
    # discarded. Empty disables the rule.
    validity_sentinels: str = ",".join(DEFAULT_SENTINELS)
    # Seconds without a valid poll after which the data is reported as not
    # ready. Unset or empty: three poll intervals plus 15 seconds.
    stale_after: float | None = Field(default=None, gt=0)

    model_config = SettingsConfigDict(env_prefix="ECONEXT_")

    @field_validator("stale_after", mode="before")
    @classmethod
    def _empty_stale_after_is_unset(cls, value: object) -> object:
        """An empty ECONEXT_STALE_AFTER means the default, it is not an error."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def validity_sentinel_names(self) -> tuple[str, ...]:
        """The sentinel parameter names as a tuple."""
        return parse_names(self.validity_sentinels)

    @property
    def paired_address_file(self) -> Path:
        """Path to the file storing the panel-assigned bus address."""
        return Path(self.state_dir) / "paired_address"

    @property
    def thermostat_address_file(self) -> Path:
        """Path to the file storing the thermostat's panel-assigned bus address."""
        return Path(self.state_dir) / "thermostat_address"


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
    # Home Assistant polls several endpoints every few seconds; one access
    # line per request is noise in the journal unless debugging.
    if numeric_level > logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
