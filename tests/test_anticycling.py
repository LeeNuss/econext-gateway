"""Unit tests for apply_anticycling_defaults."""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from econext_gateway.control.anticycling import apply_anticycling_defaults
from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.config import Settings
from econext_gateway.core.models import Parameter


def _make_param(index: int, name: str, value, writable: bool = True) -> Parameter:
    return Parameter(
        index=index, name=name, value=value,
        type=2, unit=0, writable=writable,
    )


@pytest.fixture
def cache():
    return ParameterCache()


@pytest.fixture
def handler():
    mock = AsyncMock()
    mock.write_param = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def settings():
    with patch.dict(os.environ, {}, clear=True):
        return Settings()


class TestApplyDefaults:
    """Test apply_anticycling_defaults logic."""

    def test_writes_when_values_are_zero(self, cache, handler, settings):
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 0)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 0)))

        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, settings)
        )

        assert handler.write_param.call_count == 2
        handler.write_param.assert_any_call("minWorkTime", 10)
        handler.write_param.assert_any_call("minBreakTime", 10)

        assert results["minWorkTime"] == "set to 10"
        assert results["minBreakTime"] == "set to 10"

    def test_skips_nonzero_values(self, cache, handler, settings):
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 5)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 8)))

        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, settings)
        )

        handler.write_param.assert_not_called()
        assert "skipped" in results["minWorkTime"]
        assert "skipped" in results["minBreakTime"]

    def test_handles_missing_params(self, cache, handler, settings):
        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, settings)
        )

        handler.write_param.assert_not_called()
        assert results["minWorkTime"] == "not_found"
        assert results["minBreakTime"] == "not_found"

    def test_disabled_by_config(self, cache, handler):
        with patch.dict(os.environ, {"ECONEXT_ANTICYCLING_ENABLED": "false"}, clear=True):
            disabled_settings = Settings()

        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, disabled_settings)
        )

        handler.write_param.assert_not_called()
        assert results["status"] == "disabled"

    def test_partial_zero_values(self, cache, handler, settings):
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 0)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 15)))

        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, settings)
        )

        handler.write_param.assert_called_once_with("minWorkTime", 10)
        assert results["minWorkTime"] == "set to 10"
        assert "skipped" in results["minBreakTime"]

    def test_write_failure(self, cache, handler, settings):
        asyncio.run(cache.set(_make_param(498, "minWorkTime", 0)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 0)))

        handler.write_param = AsyncMock(return_value=False)

        results = asyncio.run(
            apply_anticycling_defaults(handler, cache, settings)
        )

        assert results["minWorkTime"] == "write_failed"

    def test_custom_config_values(self, cache, handler):
        with patch.dict(os.environ, {
            "ECONEXT_ANTICYCLING_MIN_WORK": "15",
            "ECONEXT_ANTICYCLING_MIN_BREAK": "20",
        }, clear=True):
            custom_settings = Settings()

        asyncio.run(cache.set(_make_param(498, "minWorkTime", 0)))
        asyncio.run(cache.set(_make_param(499, "minBreakTime", 0)))

        asyncio.run(
            apply_anticycling_defaults(handler, cache, custom_settings)
        )

        handler.write_param.assert_any_call("minWorkTime", 15)
        handler.write_param.assert_any_call("minBreakTime", 20)
