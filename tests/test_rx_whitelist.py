"""Serial RX whitelist must never hide the frames a device needs to register."""

from econext_gateway.main import rx_whitelist
from econext_gateway.protocol.constants import (
    CLAIMABLE_ADDRESS_RANGE,
    THERMOSTAT_CLAIMABLE_ADDRESS_RANGE,
)


def test_both_paired_keeps_only_our_addresses():
    assert rx_whitelist(114, 165, True) == {114, 165}


def test_gateway_unpaired_lets_scanning_probes_through():
    # Re-pairing the gateway with a paired thermostat: regression for the
    # whitelist {165} that filtered every IDENTIFY probe to 105-130.
    keep = rx_whitelist(None, 165, True)
    assert 165 in keep
    assert set(CLAIMABLE_ADDRESS_RANGE) <= keep
    assert 131 not in keep


def test_thermostat_enabled_but_unpaired_lets_its_range_through():
    keep = rx_whitelist(114, None, True)
    assert 114 in keep
    assert set(THERMOSTAT_CLAIMABLE_ADDRESS_RANGE) <= keep


def test_thermostat_disabled_is_not_added():
    assert rx_whitelist(114, None, False) == {114}


def test_fresh_install_filters_to_claimable_ranges():
    keep = rx_whitelist(None, None, True)
    assert keep == set(CLAIMABLE_ADDRESS_RANGE) | set(THERMOSTAT_CLAIMABLE_ADDRESS_RANGE)
