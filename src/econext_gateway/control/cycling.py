"""Compressor cycling monitor.

Tracks compressor on/off transitions by reading HPStatusComprStat from
the parameter cache after each poll cycle. Computes cycling metrics for
API exposure and Home Assistant dashboards.
"""

import logging
import time
from dataclasses import dataclass

from econext_gateway.core.cache import ParameterCache

logger = logging.getLogger(__name__)

# Parameter indices
COMPR_STAT_INDEX = 1363  # HPStatusComprStat (0=off, 1=on)
MIN_WORK_TIME_INDEX = 498
MIN_BREAK_TIME_INDEX = 499
COUNTER_MIN_WORK_INDEX = 504  # counterMinWork
COUNTER_MIN_BREAK_INDEX = 505  # counterMinBreak
TEMP_OUTLET_INDEX = 75
TEMP_RETURN_INDEX = 74
TEMP_WEATHER_INDEX = 68
PRESET_TEMP_INDEX = 1351  # HPStatusPresetTemp

SHORT_CYCLE_THRESHOLD = 300  # 5 minutes in seconds
MAX_HISTORY = 200  # max events to keep (prune to 100 on API response)
WINDOW_24H = 86400  # 24 hours in seconds


@dataclass
class CycleEvent:
    """A single compressor state transition."""

    timestamp: float  # time.monotonic()
    wall_time: float  # time.time() for API display
    turned_on: bool  # True = OFF->ON, False = ON->OFF
    duration: float  # how long the previous state lasted (seconds)


class CompressorMonitor:
    """Monitors compressor cycling via cache reads after each poll."""

    def __init__(self, cache: ParameterCache) -> None:
        self._cache = cache
        self._compressor_on: bool | None = None  # None = unknown initial state
        self._state_since: float | None = None  # monotonic time of last transition
        self._events: list[CycleEvent] = []
        self._last_run_duration: float | None = None

    async def update(self) -> None:
        """Called after each poll cycle to check compressor state."""
        param = await self._cache.get(COMPR_STAT_INDEX)
        if param is None:
            return

        now = time.monotonic()
        is_on = bool(param.value)

        if self._compressor_on is None:
            # First observation: record initial state, no transition
            self._compressor_on = is_on
            self._state_since = now
            logger.info("Compressor initial state: %s", "ON" if is_on else "OFF")
            return

        if is_on == self._compressor_on:
            return  # no change

        # State transition detected
        duration = now - self._state_since if self._state_since is not None else 0.0

        if not is_on:
            # ON -> OFF: record run duration
            self._last_run_duration = duration

        event = CycleEvent(
            timestamp=now,
            wall_time=time.time(),
            turned_on=is_on,
            duration=duration,
        )
        self._events.append(event)
        self._compressor_on = is_on
        self._state_since = now

        state_str = "ON" if is_on else "OFF"
        logger.info(
            "Compressor %s (previous state lasted %.0fs)", state_str, duration
        )

        self._prune_old_events(now)

    def _prune_old_events(self, now: float) -> None:
        """Remove events older than 24h window."""
        cutoff = now - WINDOW_24H
        while self._events and self._events[0].timestamp < cutoff:
            self._events.pop(0)
        # Hard cap to prevent unbounded growth
        if len(self._events) > MAX_HISTORY:
            self._events = self._events[-MAX_HISTORY:]

    @property
    def compressor_on(self) -> bool | None:
        return self._compressor_on

    @property
    def current_state_seconds(self) -> float:
        """How long the compressor has been in its current state."""
        if self._state_since is None:
            return 0.0
        return time.monotonic() - self._state_since

    @property
    def last_run_duration(self) -> float | None:
        """Duration of the last completed run (ON period), or None if no run completed yet."""
        return self._last_run_duration

    @property
    def events(self) -> list[CycleEvent]:
        return list(self._events)

    def starts_in_window(self, window_seconds: float) -> int:
        """Count compressor starts (OFF->ON transitions) within a time window."""
        cutoff = time.monotonic() - window_seconds
        return sum(
            1 for e in self._events if e.turned_on and e.timestamp >= cutoff
        )

    def run_durations_in_window(self, window_seconds: float) -> list[float]:
        """Get all completed run durations (ON->OFF transitions) within a window."""
        cutoff = time.monotonic() - window_seconds
        return [
            e.duration
            for e in self._events
            if not e.turned_on and e.timestamp >= cutoff
        ]

    def short_cycles_in_window(self, window_seconds: float) -> int:
        """Count runs shorter than SHORT_CYCLE_THRESHOLD in a window."""
        return sum(
            1 for d in self.run_durations_in_window(window_seconds)
            if d < SHORT_CYCLE_THRESHOLD
        )

    async def get_metrics(self) -> dict:
        """Build metrics dict for API response."""
        now = time.monotonic()
        self._prune_old_events(now)

        starts_1h = self.starts_in_window(3600)
        starts_24h = self.starts_in_window(WINDOW_24H)
        runs_1h = self.run_durations_in_window(3600)
        avg_run_1h = sum(runs_1h) / len(runs_1h) if runs_1h else None
        short_cycles_1h = sum(1 for d in runs_1h if d < SHORT_CYCLE_THRESHOLD)

        # Read timer parameters from cache (read-only enrichment)
        min_work = await self._cache.get(MIN_WORK_TIME_INDEX)
        min_break = await self._cache.get(MIN_BREAK_TIME_INDEX)
        counter_work = await self._cache.get(COUNTER_MIN_WORK_INDEX)
        counter_break = await self._cache.get(COUNTER_MIN_BREAK_INDEX)

        # Read temperature context
        temp_outlet = await self._cache.get(TEMP_OUTLET_INDEX)
        temp_return = await self._cache.get(TEMP_RETURN_INDEX)
        temp_weather = await self._cache.get(TEMP_WEATHER_INDEX)
        preset_temp = await self._cache.get(PRESET_TEMP_INDEX)

        return {
            "compressor_on": self._compressor_on,
            "current_state_seconds": round(self.current_state_seconds, 1),
            "last_run_seconds": round(self._last_run_duration, 1) if self._last_run_duration is not None else None,
            "starts_last_hour": starts_1h,
            "starts_last_24h": starts_24h,
            "avg_run_seconds_1h": round(avg_run_1h, 1) if avg_run_1h is not None else None,
            "short_cycle_count_1h": short_cycles_1h,
            "min_work_time": min_work.value if min_work else None,
            "min_break_time": min_break.value if min_break else None,
            "counter_min_work": counter_work.value if counter_work else None,
            "counter_min_break": counter_break.value if counter_break else None,
            "temp_outlet": temp_outlet.value if temp_outlet else None,
            "temp_return": temp_return.value if temp_return else None,
            "temp_weather": temp_weather.value if temp_weather else None,
            "preset_temp": preset_temp.value if preset_temp else None,
        }
