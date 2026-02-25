"""Anti-cycling defaults: write protective timer parameters at startup.

Called once after the first successful poll cycle. Checks if minWorkTime
and minBreakTime are at zero (disabled) and writes configured defaults
if so. Respects manual overrides by skipping non-zero values.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from econext_gateway.core.cache import ParameterCache
    from econext_gateway.core.config import Settings
    from econext_gateway.protocol.handler import ProtocolHandler

logger = logging.getLogger(__name__)

# Parameter name -> (index, settings attribute, description)
ANTICYCLING_PARAMS = {
    "minWorkTime": (498, "anticycling_min_work", "minimum work time"),
    "minBreakTime": (499, "anticycling_min_break", "minimum break time"),
}


async def apply_anticycling_defaults(
    handler: ProtocolHandler,
    cache: ParameterCache,
    settings: Settings,
) -> dict[str, str]:
    """Write anti-cycling timer defaults if currently disabled.

    Returns a dict of parameter name -> result string for logging.
    """
    if not settings.anticycling_enabled:
        logger.info("Anti-cycling defaults disabled by config")
        return {"status": "disabled"}

    results: dict[str, str] = {}

    for name, (index, settings_attr, description) in ANTICYCLING_PARAMS.items():
        param = await cache.get(index)
        if param is None:
            logger.warning("Parameter %s (index %d) not in cache, skipping", name, index)
            results[name] = "not_found"
            continue

        current = param.value
        target = getattr(settings, settings_attr)

        if current != 0:
            logger.info(
                "%s = %s (non-zero), skipping (respecting manual override)",
                name, current,
            )
            results[name] = f"skipped (current={current})"
            continue

        try:
            success = await handler.write_param(name, target)
        except (ValueError, Exception) as e:
            logger.error("Failed to write %s: %s", name, e)
            results[name] = f"error: {e}"
            continue

        if success:
            logger.info("Set %s = %s (was %s) -- %s", name, target, current, description)
            results[name] = f"set to {target}"
        else:
            logger.warning("Write %s = %s not acknowledged by controller", name, target)
            results[name] = "write_failed"

    return results
