"""Unit tests for parameter cache."""

import asyncio

import pytest

from econet_gm3_gateway.core.cache import ParameterCache
from econet_gm3_gateway.core.models import Parameter


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
    async def test_set_and_get(self):
        """Test storing and retrieving a parameter."""
        cache = ParameterCache()
        param = make_param("Temperature", index=10, value=55)

        await cache.set(param)
        result = await cache.get("Temperature")

        assert result is not None
        assert result.name == "Temperature"
        assert result.index == 10
        assert result.value == 55

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Test getting a nonexistent parameter returns None."""
        cache = ParameterCache()

        result = await cache.get("NoSuchParam")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_index(self):
        """Test retrieving a parameter by index."""
        cache = ParameterCache()
        param = make_param("Pressure", index=42, value=100)

        await cache.set(param)
        result = await cache.get_by_index(42)

        assert result is not None
        assert result.name == "Pressure"

    @pytest.mark.asyncio
    async def test_get_by_index_nonexistent(self):
        """Test getting by nonexistent index returns None."""
        cache = ParameterCache()

        result = await cache.get_by_index(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_empty(self):
        """Test get_all on empty cache."""
        cache = ParameterCache()

        result = await cache.get_all()

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all(self):
        """Test get_all returns all parameters."""
        cache = ParameterCache()
        await cache.set(make_param("A", index=1, value=10))
        await cache.set(make_param("B", index=2, value=20))

        result = await cache.get_all()

        assert len(result) == 2
        assert "A" in result
        assert "B" in result

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(self):
        """Test get_all returns a copy, not the internal dict."""
        cache = ParameterCache()
        await cache.set(make_param("A", index=1))

        result = await cache.get_all()
        result["B"] = make_param("B", index=2)

        assert cache.count == 1

    @pytest.mark.asyncio
    async def test_set_updates_existing(self):
        """Test setting a parameter with same name updates it."""
        cache = ParameterCache()

        await cache.set(make_param("Temp", index=5, value=30))
        await cache.set(make_param("Temp", index=5, value=60))

        result = await cache.get("Temp")
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
        a = await cache.get("A")
        assert a is not None and a.value == 10

    @pytest.mark.asyncio
    async def test_set_many_empty(self):
        """Test set_many with empty list is a no-op."""
        cache = ParameterCache()

        await cache.set_many([])

        assert cache.count == 0
        assert cache.last_update is None

    @pytest.mark.asyncio
    async def test_remove_existing(self):
        """Test removing an existing parameter."""
        cache = ParameterCache()
        await cache.set(make_param("Temp", index=1))

        removed = await cache.remove("Temp")

        assert removed is True
        assert cache.count == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self):
        """Test removing a nonexistent parameter."""
        cache = ParameterCache()

        removed = await cache.remove("NoSuchParam")

        assert removed is False

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
    async def test_contains_true(self):
        """Test contains returns True for existing parameter."""
        cache = ParameterCache()
        await cache.set(make_param("Temp", index=1))

        assert await cache.contains("Temp") is True

    @pytest.mark.asyncio
    async def test_contains_false(self):
        """Test contains returns False for nonexistent parameter."""
        cache = ParameterCache()

        assert await cache.contains("NoSuch") is False

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
        await cache.remove("A")
        assert cache.count == 1

    @pytest.mark.asyncio
    async def test_get_names(self):
        """Test get_names returns all parameter names."""
        cache = ParameterCache()
        await cache.set(make_param("Alpha", index=1))
        await cache.set(make_param("Beta", index=2))

        names = await cache.get_names()

        assert set(names) == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_get_indices(self):
        """Test get_indices returns sorted indices."""
        cache = ParameterCache()
        await cache.set(make_param("C", index=30))
        await cache.set(make_param("A", index=10))
        await cache.set(make_param("B", index=20))

        indices = await cache.get_indices()

        assert indices == [10, 20, 30]

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
