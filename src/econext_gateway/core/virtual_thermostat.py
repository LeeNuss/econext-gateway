"""Virtual thermostat state holder.

Stores the latest temperature submitted by Home Assistant and tracks
staleness so the bus emulator can report a safe fallback when updates stop.
Persists the last temperature to disk so it survives gateway restarts.
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


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

        # Load persisted temperature from last run
        if self._persist_file is not None:
            self._load_persisted()

    @property
    def temperature(self) -> float | None:
        """Raw temperature value (None if never set)."""
        return self._temperature

    @property
    def updated_at(self) -> float | None:
        """Monotonic timestamp of last update."""
        return self._updated_at

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

        Returns the last known temperature, even if stale. This prevents
        the heat pump from seeing 0.0 and running at maximum if HA stops
        sending updates. The is_stale flag is still tracked for monitoring.
        """
        if self._temperature is not None:
            return self._temperature
        return self._stale_fallback

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
            # Don't set _updated_at - value is stale until HA refreshes
            logger.info("Loaded persisted temperature: %.2f (stale until HA updates)", temp)
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
