"""Thread-safe parameter cache for GM3 gateway."""

import asyncio
from datetime import datetime
from typing import Optional

from .models import Parameter


class ParameterCache:
    """Thread-safe in-memory cache for controller parameters.

    Provides async-safe access to cached parameters using asyncio.Lock().
    Parameters are stored by name for efficient lookup.
    """

    def __init__(self) -> None:
        """Initialize empty parameter cache."""
        self._lock = asyncio.Lock()
        self._parameters: dict[str, Parameter] = {}
        self._last_update: Optional[datetime] = None

    async def get(self, name: str) -> Optional[Parameter]:
        """Get parameter by name.

        Args:
            name: Parameter name to look up.

        Returns:
            Parameter if found, None otherwise.
        """
        async with self._lock:
            return self._parameters.get(name)

    async def get_by_index(self, index: int) -> Optional[Parameter]:
        """Get parameter by index.

        Args:
            index: Parameter index to look up.

        Returns:
            Parameter if found, None otherwise.
        """
        async with self._lock:
            for param in self._parameters.values():
                if param.index == index:
                    return param
            return None

    async def get_all(self) -> dict[str, Parameter]:
        """Get all cached parameters.

        Returns:
            Copy of parameter dictionary keyed by name.
        """
        async with self._lock:
            return dict(self._parameters)

    async def set(self, param: Parameter) -> None:
        """Store or update a parameter.

        Args:
            param: Parameter to store.
        """
        async with self._lock:
            self._parameters[param.name] = param
            self._last_update = datetime.now()

    async def set_many(self, params: list[Parameter]) -> None:
        """Store or update multiple parameters.

        Args:
            params: List of parameters to store.
        """
        if not params:
            return

        async with self._lock:
            for param in params:
                self._parameters[param.name] = param
            self._last_update = datetime.now()

    async def remove(self, name: str) -> bool:
        """Remove parameter by name.

        Args:
            name: Parameter name to remove.

        Returns:
            True if parameter was removed, False if not found.
        """
        async with self._lock:
            if name in self._parameters:
                del self._parameters[name]
                return True
            return False

    async def clear(self) -> None:
        """Remove all cached parameters."""
        async with self._lock:
            self._parameters.clear()
            self._last_update = None

    async def contains(self, name: str) -> bool:
        """Check if parameter exists in cache.

        Args:
            name: Parameter name to check.

        Returns:
            True if parameter exists, False otherwise.
        """
        async with self._lock:
            return name in self._parameters

    @property
    def last_update(self) -> Optional[datetime]:
        """Get timestamp of last cache update.

        Returns:
            Datetime of last update, None if never updated.
        """
        return self._last_update

    @property
    def count(self) -> int:
        """Get number of cached parameters.

        Returns:
            Number of parameters in cache.
        """
        return len(self._parameters)

    async def get_names(self) -> list[str]:
        """Get list of all parameter names.

        Returns:
            List of parameter names in cache.
        """
        async with self._lock:
            return list(self._parameters.keys())

    async def get_indices(self) -> list[int]:
        """Get list of all parameter indices.

        Returns:
            Sorted list of parameter indices in cache.
        """
        async with self._lock:
            return sorted(p.index for p in self._parameters.values())
