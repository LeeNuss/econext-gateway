"""Thread-safe parameter cache for GM3 gateway."""

import asyncio
from datetime import datetime

from econext_gateway.core.models import Parameter


class ParameterCache:
    """Thread-safe in-memory cache for controller parameters.

    Provides async-safe access to cached parameters using asyncio.Lock().
    Parameters are stored by index (as string) for unique keying since
    multiple parameters can share the same name across address spaces.
    """

    def __init__(self) -> None:
        """Initialize empty parameter cache."""
        self._lock = asyncio.Lock()
        self._parameters: dict[str, Parameter] = {}  # keyed by str(index)
        self._last_update: datetime | None = None

    async def get(self, index: int) -> Parameter | None:
        """Get parameter by index."""
        async with self._lock:
            return self._parameters.get(str(index))

    async def get_by_name(self, name: str) -> Parameter | None:
        """Get parameter by name.

        Some names exist more than once (PS and HV in both the regulator and
        the panel space, Circuit2BaseTemp at 311 and 785). The lowest index
        wins, so the regulator copy is picked regardless of cache order.
        Use ``resolve`` with the index to reach any other copy.
        """
        async with self._lock:
            matches = [p for p in self._parameters.values() if p.name == name]
            return min(matches, key=lambda p: p.index) if matches else None

    async def resolve(self, key: str) -> Parameter | None:
        """Get parameter by index (all digits, e.g. "10013") or by name."""
        if key.isdigit():
            return await self.get(int(key))
        return await self.get_by_name(key)

    async def get_all(self) -> dict[str, Parameter]:
        """Get all cached parameters keyed by index (as string)."""
        async with self._lock:
            return dict(self._parameters)

    async def set(self, param: Parameter) -> None:
        """Store or update a parameter."""
        async with self._lock:
            self._parameters[str(param.index)] = param
            self._last_update = datetime.now()

    async def set_many(self, params: list[Parameter]) -> None:
        """Store or update multiple parameters."""
        if not params:
            return

        async with self._lock:
            for param in params:
                self._parameters[str(param.index)] = param
            self._last_update = datetime.now()

    async def clear(self) -> None:
        """Remove all cached parameters."""
        async with self._lock:
            self._parameters.clear()
            self._last_update = None

    @property
    def last_update(self) -> datetime | None:
        """Get timestamp of last cache update."""
        return self._last_update

    @property
    def count(self) -> int:
        """Get number of cached parameters."""
        return len(self._parameters)
