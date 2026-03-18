"""Virtual thermostat state holder.

Stores the latest temperature submitted by Home Assistant and tracks
staleness so the bus emulator can report a safe fallback when updates stop.
"""

import logging
import time

logger = logging.getLogger(__name__)


class VirtualThermostat:
    """In-memory temperature state with staleness detection."""

    def __init__(self, max_age: float = 300.0, stale_fallback: float = 0.0) -> None:
        self._temperature: float | None = None
        self._updated_at: float | None = None
        self._max_age = max_age
        self._stale_fallback = stale_fallback

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

        Returns the submitted temperature if fresh, or the stale_fallback
        value if no update has been received within max_age seconds.
        A low fallback (e.g. 0.0) causes the controller to increase heating,
        which is the safer default for cold climates.
        """
        if self.is_stale:
            return self._stale_fallback
        assert self._temperature is not None
        return self._temperature

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

        return prev_age
