"""Unit tests for parameter cache."""

import asyncio

import pytest

from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Parameter


def make_param(name: str = "TestParam", index: int = 0, value: int = 42) -> Parameter:
    """Create a test parameter."""
    return Parameter(index=index, name=name, value=value, type=2, unit=1, writable=True)


class TestParameterCache:
    """Tests for ParameterCache class."""

    @pytest.mark.asyncio
    async def test_init_empty(self):
        """Test cache starts empty."""
        cache = ParameterCache()

        assert cache.count == 0
        assert cache.last_update is None

    @pytest.mark.asyncio
    async def test_set_and_get_by_index(self):
        """Test storing and retrieving a parameter by index."""
        cache = ParameterCache()
        param = make_param("Temperature", index=10, value=55)

        await cache.set(param)
        result = await cache.get(10)

        assert result is not None
        assert result.name == "Temperature"
        assert result.index == 10
        assert result.value == 55

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Test getting a nonexistent parameter returns None."""
        cache = ParameterCache()

        result = await cache.get(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name(self):
        """Test retrieving a parameter by name."""
        cache = ParameterCache()
        param = make_param("Pressure", index=42, value=100)

        await cache.set(param)
        result = await cache.get_by_name("Pressure")

        assert result is not None
        assert result.index == 42
        assert result.name == "Pressure"

    @pytest.mark.asyncio
    async def test_get_by_name_nonexistent(self):
        """Test getting by nonexistent name returns None."""
        cache = ParameterCache()

        result = await cache.get_by_name("NoSuchParam")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_empty(self):
        """Test get_all on empty cache."""
        cache = ParameterCache()

        result = await cache.get_all()

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all(self):
        """Test get_all returns all parameters keyed by index string."""
        cache = ParameterCache()
        await cache.set(make_param("A", index=1, value=10))
        await cache.set(make_param("B", index=2, value=20))

        result = await cache.get_all()

        assert len(result) == 2
        assert "1" in result
        assert "2" in result

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(self):
        """Test get_all returns a copy, not the internal dict."""
        cache = ParameterCache()
        await cache.set(make_param("A", index=1))

        result = await cache.get_all()
        result["99"] = make_param("B", index=99)

        assert cache.count == 1

    @pytest.mark.asyncio
    async def test_set_updates_existing(self):
        """Test setting a parameter with same index updates it."""
        cache = ParameterCache()

        await cache.set(make_param("Temp", index=5, value=30))
        await cache.set(make_param("Temp", index=5, value=60))

        result = await cache.get(5)
        assert result is not None
        assert result.value == 60
        assert cache.count == 1

    @pytest.mark.asyncio
    async def test_set_many(self):
        """Test storing multiple parameters at once."""
        cache = ParameterCache()
        params = [
            make_param("A", index=1, value=10),
            make_param("B", index=2, value=20),
            make_param("C", index=3, value=30),
        ]

        await cache.set_many(params)

        assert cache.count == 3
        a = await cache.get(1)
        assert a is not None and a.value == 10

    @pytest.mark.asyncio
    async def test_set_many_empty(self):
        """Test set_many with empty list is a no-op."""
        cache = ParameterCache()

        await cache.set_many([])

        assert cache.count == 0
        assert cache.last_update is None

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing the cache."""
        cache = ParameterCache()
        await cache.set(make_param("A", index=1))
        await cache.set(make_param("B", index=2))

        await cache.clear()

        assert cache.count == 0
        assert cache.last_update is None

    @pytest.mark.asyncio
    async def test_last_update_set_on_set(self):
        """Test last_update is set when a parameter is stored."""
        cache = ParameterCache()
        assert cache.last_update is None

        await cache.set(make_param("A", index=1))

        assert cache.last_update is not None

    @pytest.mark.asyncio
    async def test_last_update_set_on_set_many(self):
        """Test last_update is set when set_many is called."""
        cache = ParameterCache()

        await cache.set_many([make_param("A", index=1)])

        assert cache.last_update is not None

    @pytest.mark.asyncio
    async def test_count(self):
        """Test count property."""
        cache = ParameterCache()

        assert cache.count == 0
        await cache.set(make_param("A", index=1))
        assert cache.count == 1
        await cache.set(make_param("B", index=2))
        assert cache.count == 2

    @pytest.mark.asyncio
    async def test_duplicate_names_different_indices(self):
        """Test that params with same name but different indices are stored separately."""
        cache = ParameterCache()
        await cache.set(make_param("PS", index=0, value=100))
        await cache.set(make_param("PS", index=10010, value=200))

        assert cache.count == 2

        reg = await cache.get(0)
        panel = await cache.get(10010)
        assert reg is not None and reg.value == 100
        assert panel is not None and panel.value == 200

        # get_by_name returns first match
        by_name = await cache.get_by_name("PS")
        assert by_name is not None

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test cache is safe under concurrent access."""
        cache = ParameterCache()
        errors = []

        async def writer(start: int):
            try:
                for i in range(50):
                    await cache.set(make_param(f"P{start + i}", index=start + i, value=i))
            except Exception as e:
                errors.append(e)

        async def reader():
            try:
                for _ in range(50):
                    await cache.get_all()
                    await asyncio.sleep(0)
            except Exception as e:
                errors.append(e)

        await asyncio.gather(
            writer(0),
            writer(100),
            writer(200),
            reader(),
            reader(),
        )

        assert not errors
        assert cache.count == 150
