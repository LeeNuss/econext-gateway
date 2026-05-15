"""Virtual thermostat state holder.

Stores the latest temperature submitted by Home Assistant and tracks
staleness so the bus emulator can report a safe fallback when updates stop.
Persists the last temperature to disk so it survives gateway restarts.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Callback signature: takes the staleness threshold and returns
# (temperature, source_label) for the freshest backup reading newer than
# `max_age` seconds, or None if nothing fresh is available.
BackupSource = Callable[[float], "tuple[float, str] | None"]


class VirtualThermostat:
    """In-memory temperature state with staleness detection and persistence."""

    def __init__(
        self,
        max_age: float = 300.0,
        stale_fallback: float = 0.0,
        persist_file: Path | None = None,
    ) -> None:
        self._temperature: float | None = None
        self._updated_at: float | None = None
        self._max_age = max_age
        self._stale_fallback = stale_fallback
        self._persist_file = persist_file
        self._last_persist_time: float = 0.0
        self._persist_interval: float = 120.0  # write to disk at most every 2 minutes
        self._backup_source: BackupSource | None = None
        self._last_effective_source: str = "none"

        # Load persisted temperature from last run
        if self._persist_file is not None:
            self._load_persisted()

    def set_backup_source(self, source: BackupSource | None) -> None:
        """Register a callback used when the primary HA push is stale.

        The callback returns (temperature, label) for the freshest backup
        reading newer than `max_age` seconds, or None.
        """
        self._backup_source = source

    @property
    def temperature(self) -> float | None:
        """Raw temperature value (None if never set)."""
        return self._temperature

    @property
    def updated_at(self) -> float | None:
        """Monotonic timestamp of last update."""
        return self._updated_at

    @property
    def max_age(self) -> float:
        """Staleness threshold in seconds."""
        return self._max_age

    @property
    def stale_fallback(self) -> float:
        """Temperature reported when no reading has ever been received."""
        return self._stale_fallback

    @property
    def age_seconds(self) -> float | None:
        """Seconds since last update, or None if never updated."""
        if self._updated_at is None:
            return None
        return time.monotonic() - self._updated_at

    @property
    def is_stale(self) -> bool:
        """True if temperature has never been set or is older than max_age."""
        if self._updated_at is None:
            return True
        return (time.monotonic() - self._updated_at) > self._max_age

    @property
    def effective_temperature(self) -> float:
        """Temperature to report on the bus.

        Resolution order:
          1. Fresh HA push (`temperature` exists and not stale).
          2. Backup-source callback if registered and returns a fresh value.
          3. Last known HA push, even if stale (avoid 0.0 spike).
          4. `stale_fallback` constant.

        Side effect: updates `_last_effective_source` so callers can ask
        which branch was taken via `effective_source`.
        """
        if self._temperature is not None and not self.is_stale:
            self._last_effective_source = "primary"
            return self._temperature

        if self._backup_source is not None:
            backup = self._backup_source(self._max_age)
            if backup is not None:
                temp, label = backup
                self._last_effective_source = f"backup:{label}"
                return temp

        if self._temperature is not None:
            self._last_effective_source = "stale_cache"
            return self._temperature

        self._last_effective_source = "fallback"
        return self._stale_fallback

    @property
    def effective_source(self) -> str:
        """Which source the most recent `effective_temperature` came from.

        One of: `"primary"`, `"backup:<label>"`, `"stale_cache"`,
        `"fallback"`, `"none"` (before first read).
        """
        return self._last_effective_source

    def update(self, temperature: float) -> float | None:
        """Submit a new temperature reading.

        Returns the age of the previous reading (seconds), or None if first update.
        """
        prev_age = self.age_seconds
        was_stale = self.is_stale

        self._temperature = round(temperature, 2)
        self._updated_at = time.monotonic()

        if was_stale and prev_age is not None:
            logger.info(
                "Virtual thermostat recovered from stale (was %.0fs old), new temp=%.2f",
                prev_age,
                self._temperature,
            )
        else:
            logger.debug("Virtual thermostat updated: %.2f", self._temperature)

        self._save_persisted()
        return prev_age

    def _load_persisted(self) -> None:
        """Load last temperature from disk. Marks it as fresh so the first
        bus poll gets a real temperature instead of the stale fallback (0.0).
        HA will refresh within 10s; if it doesn't, staleness kicks in after max_age."""
        try:
            text = self._persist_file.read_text().strip()
            temp = float(text)
            self._temperature = round(temp, 2)
            self._updated_at = time.monotonic()  # Treat as fresh until HA refreshes
            logger.info("Loaded persisted temperature: %.2f (fresh until max_age)", temp)
        except (FileNotFoundError, ValueError):
            pass

    def _save_persisted(self) -> None:
        """Save current temperature to disk (throttled to avoid SD card wear)."""
        if self._persist_file is None or self._temperature is None:
            return
        now = time.monotonic()
        if now - self._last_persist_time < self._persist_interval:
            return
        try:
            self._persist_file.parent.mkdir(parents=True, exist_ok=True)
            self._persist_file.write_text(str(self._temperature))
            self._last_persist_time = now
        except OSError:
            pass
