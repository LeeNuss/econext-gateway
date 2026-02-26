"""Shared test fixtures."""

from pathlib import Path

import pytest

# Address used by all tests (must not be in RESERVED_ADDRESSES)
TEST_BUS_ADDRESS = 200


@pytest.fixture
def paired_address_file(tmp_path: Path) -> Path:
    """Create a temporary paired address file for tests."""
    f = tmp_path / "paired_address"
    f.write_text(str(TEST_BUS_ADDRESS))
    return f
