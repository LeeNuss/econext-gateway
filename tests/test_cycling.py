"""Unit tests for CompressorMonitor."""

import asyncio

import pytest

from econext_gateway.control.cycling import (
    COMPR_STAT_INDEX,
    CompressorMonitor,
)
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter


def _make_param(index: int, value) -> Parameter:
    return Parameter(
        index=index, name=f"Param{index}", value=value,
        type=2, unit=0, writable=False,
    )


@pytest.fixture
def cache():
    return ParameterCache()


@pytest.fixture
def monitor(cache):
    return CompressorMonitor(cache)


class TestInitialState:
    """Test initial state detection."""

    def test_initial_state_is_none(self, monitor):
        assert monitor.compressor_on is None

    def test_detect_initial_on(self, cache, monitor):
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())
        assert monitor.compressor_on is True

    def test_detect_initial_off(self, cache, monitor):
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())
        assert monitor.compressor_on is False

    def test_no_param_in_cache(self, monitor):
        asyncio.run(monitor.update())
        assert monitor.compressor_on is None


class TestTransitions:
    """Test compressor state transitions."""

    def test_off_to_on(self, cache, monitor):
        # Start OFF
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())
        assert monitor.compressor_on is False

        # Transition to ON
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())
        assert monitor.compressor_on is True
        assert len(monitor.events) == 1
        assert monitor.events[0].turned_on is True

    def test_on_to_off_records_run_duration(self, cache, monitor):
        # Start ON
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())

        # Transition to OFF
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        assert monitor.compressor_on is False
        assert len(monitor.events) == 1
        assert monitor.events[0].turned_on is False
        assert monitor.last_run_duration is not None
        assert monitor.last_run_duration >= 0

    def test_no_transition_on_same_state(self, cache, monitor):
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())
        asyncio.run(monitor.update())
        asyncio.run(monitor.update())
        assert len(monitor.events) == 0

    def test_full_cycle(self, cache, monitor):
        # OFF -> ON -> OFF
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        assert len(monitor.events) == 2
        assert monitor.events[0].turned_on is True
        assert monitor.events[1].turned_on is False


class TestMetrics:
    """Test metrics computation."""

    def test_starts_in_window(self, cache, monitor):
        # OFF -> ON -> OFF -> ON (2 starts)
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())

        assert monitor.starts_in_window(3600) == 2

    def test_short_cycle_detection(self, cache, monitor):
        # Quick OFF -> ON -> OFF cycle (duration near 0 = short cycle)
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())

        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())

        # ON->OFF event duration is near-zero, which is < SHORT_CYCLE_THRESHOLD
        assert monitor.short_cycles_in_window(3600) == 1

    def test_current_state_seconds(self, cache, monitor):
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 1)))
        asyncio.run(monitor.update())
        assert monitor.current_state_seconds >= 0

    def test_get_metrics_returns_dict(self, cache, monitor):
        asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, 0)))
        asyncio.run(monitor.update())
        metrics = asyncio.run(monitor.get_metrics())

        assert isinstance(metrics, dict)
        assert metrics["compressor_on"] is False
        assert "starts_last_hour" in metrics
        assert "starts_last_24h" in metrics
        assert "short_cycle_count_1h" in metrics


class TestPruning:
    """Test event pruning."""

    def test_max_history_cap(self, cache, monitor):
        # Generate lots of events
        for i in range(250):
            val = i % 2
            asyncio.run(cache.set(_make_param(COMPR_STAT_INDEX, val)))
            asyncio.run(monitor.update())

        # Should be capped
        assert len(monitor.events) <= 200
