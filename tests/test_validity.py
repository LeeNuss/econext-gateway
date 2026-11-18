"""Unit tests for poll validity and data readiness."""

import logging

import pytest

from econext_gateway.core.validity import (
    DEFAULT_GRACE,
    DEFAULT_SENTINELS,
    PollValidity,
    default_stale_after,
)

GOOD = {"resetCounter": 58, "TempCWU": 40.0, "HoldingRegister_6061": 50, "HoldingRegister_6271": 60, "Other": 1}
ZEROS = {"resetCounter": 59, "TempCWU": 0.0, "HoldingRegister_6061": 0, "HoldingRegister_6271": 0, "Other": 1}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(**kwargs) -> tuple[PollValidity, Clock]:
    clock = Clock()
    kwargs.setdefault("sentinels", DEFAULT_SENTINELS)
    kwargs.setdefault("stale_after", 30.0)
    return PollValidity(clock=clock, **kwargs), clock


class TestStart:
    def test_not_ready_before_the_first_poll(self):
        v, _ = make()
        assert v.ready is False
        assert v.reason == "starting"
        assert v.reset_counter is None
        assert v.last_valid_at is None

    def test_first_poll_is_valid_without_a_baseline(self):
        v, _ = make()
        assert v.judge(GOOD) is None
        assert v.ready is True
        assert v.reason == "ok"
        assert v.reset_counter == 58
        assert v.last_valid_at is not None

    def test_poll_without_a_watched_parameter_is_valid(self):
        """A controller that has neither the counter nor a sentinel is not locked out."""
        v, _ = make()
        assert v.judge({}) is None
        assert v.ready is True
        assert v.reset_counter is None


class TestController:
    def test_poll_the_controller_did_not_answer_is_not_valid(self):
        """Nothing read at all, or only the panel answered."""
        v, _ = make()
        v.judge(GOOD)
        assert v.judge({}, controller=False) == "controller did not answer"
        assert v.ready is False

    def test_it_does_not_refresh_the_last_valid_poll(self):
        v, clock = make(stale_after=30.0)
        v.judge(GOOD)
        clock.now += 20
        v.judge({}, controller=False)
        clock.now += 20
        assert v.reason == "controller did not answer; no valid poll for 40 s"

    def test_it_is_not_also_reported_as_an_unread_counter(self):
        v, _ = make()
        assert v.judge({}, controller=False, counter_unread=True) == "controller did not answer"


class TestResetCounter:
    def test_recorded_event(self):
        """Counter 58, then 59 with zeros, then silence, then real values with 59."""
        v, clock = make()
        assert v.judge(GOOD) is None

        clock.now += 10
        assert v.judge(ZEROS) == (
            "controller reset (counter 58 to 59); TempCWU, HoldingRegister_6061, HoldingRegister_6271 read 0"
        )
        assert v.ready is False
        assert v.reset_counter == 58  # of the last valid poll, the one the cache still holds

        clock.now += 70  # the panel grants no token: no poll at all
        assert v.ready is False

        assert v.judge({**GOOD, "resetCounter": 59}) is None
        assert v.ready is True
        assert v.reason == "ok"
        assert v.reset_counter == 59

    def test_counter_change_with_sane_values_costs_one_poll(self):
        v, _ = make()
        v.judge(GOOD)
        assert v.judge({**GOOD, "resetCounter": 59}) == "controller reset (counter 58 to 59)"
        assert v.ready is False
        assert v.judge({**GOOD, "resetCounter": 59}) is None
        assert v.ready is True

    def test_poll_without_the_counter_keeps_the_baseline(self):
        v, _ = make()
        v.judge(GOOD)
        without = {k: x for k, x in GOOD.items() if k != "resetCounter"}
        assert v.judge(without) is None
        assert v.reset_counter == 58
        assert v.judge({**GOOD, "resetCounter": 59}) == "controller reset (counter 58 to 59)"

    def test_counter_name_is_configurable(self):
        v, _ = make(reset_counter_param="boots")
        v.judge({"boots": 1, "resetCounter": 58})
        assert v.judge({"boots": 1, "resetCounter": 59}) is None
        assert v.judge({"boots": 2, "resetCounter": 59}) == "controller reset (counter 1 to 2)"

    def test_counter_is_reported_as_a_whole_number_or_not_at_all(self):
        v, _ = make(reset_counter_param="c")
        v.judge({"c": 7.0})
        assert v.reset_counter == 7 and isinstance(v.reset_counter, int)
        v2, _ = make(reset_counter_param="c")
        v2.judge({"c": "v1.2"})
        assert v2.reset_counter is None
        assert v2.judge({"c": "v1.3"}) == "controller reset (counter v1.2 to v1.3)"

    def test_no_counter_configured(self):
        v, _ = make(reset_counter_param="")
        v.judge(GOOD)
        assert v.judge({**GOOD, "resetCounter": 59}) is None
        assert v.reset_counter is None
        assert v.counter_param == ""
        assert v.watched == frozenset(DEFAULT_SENTINELS)

    def test_counter_the_controller_has_but_that_was_not_read(self):
        """Without the reading after the last batch nobody can say the poll saw no reset."""
        v, _ = make()
        v.judge(GOOD)
        without = {k: x for k, x in GOOD.items() if k != "resetCounter"}
        assert v.judge(without, counter_unread=True) == "reset counter not read"
        assert v.ready is False
        assert v.reset_counter == 58
        # the baseline is kept: the reset is still seen in the next poll
        assert v.judge({**GOOD, "resetCounter": 59}) == "controller reset (counter 58 to 59)"

    def test_counter_that_stays_unread_is_given_up_after_the_grace(self, caplog):
        """A batch that never answers must not freeze the cache for good."""
        caplog.set_level(logging.WARNING, logger="econext_gateway.core.validity")
        v, clock = make(grace=60.0)
        v.judge(GOOD)
        without = {k: x for k, x in GOOD.items() if k != "resetCounter"}
        assert v.judge(without, counter_unread=True) == "reset counter not read"
        clock.now += 59
        assert v.judge(without, counter_unread=True) == "reset counter not read"
        clock.now += 1
        assert v.judge(without, counter_unread=True) is None
        assert v.judge(without, counter_unread=True) is None
        assert len([r for r in caplog.records if "Reset counter not read for 60 s" in r.getMessage()]) == 1

        # it reads again: required again, and the reset it shows is still seen
        assert v.judge({**GOOD, "resetCounter": 59}) == "controller reset (counter 58 to 59)"
        assert v.judge(without, counter_unread=True) == "reset counter not read"

    def test_the_counter_is_one_of_the_watched_names(self):
        v, _ = make()
        assert v.watched == frozenset({"resetCounter", *DEFAULT_SENTINELS})


class TestSentinels:
    def test_zero_with_the_counter_unchanged(self):
        v, _ = make()
        v.judge(GOOD)
        assert v.judge({**GOOD, "TempCWU": 0.0}) == "TempCWU reads 0"
        assert v.ready is False
        assert v.reason == "TempCWU reads 0"
        assert v.judge(GOOD) is None
        assert v.ready is True

    def test_sentinel_never_seen_non_zero_does_not_block(self):
        """A site where one of these is always 0 must never be locked out."""
        v, _ = make()
        always_zero = {**GOOD, "HoldingRegister_6061": 0}
        assert v.judge(always_zero) is None
        assert v.judge(always_zero) is None
        assert v.ready is True
        assert v.armed == {"TempCWU", "HoldingRegister_6271"}

    def test_sentinel_absent_from_the_poll_is_not_judged(self):
        v, _ = make()
        v.judge(GOOD)
        without = {k: x for k, x in GOOD.items() if k != "TempCWU"}
        assert v.judge(without) is None
        assert v.ready is True

    def test_invalid_poll_arms_nothing(self):
        v, _ = make()
        v.judge({"resetCounter": 58, "TempCWU": 40.0})
        # counter change: discarded, so 6061 is not armed by this poll
        v.judge({"resetCounter": 59, "TempCWU": 40.0, "HoldingRegister_6061": 50})
        assert v.armed == {"TempCWU"}

    def test_empty_list_disables_sentinels(self):
        v, _ = make(sentinels=())
        v.judge(GOOD)
        assert v.judge({**GOOD, "TempCWU": 0.0}) is None

    def test_non_numeric_and_bool_values_are_not_judged(self):
        v, _ = make(sentinels=("Flag", "Text"))
        assert v.judge({"Flag": True, "Text": "abc"}) is None
        assert v.judge({"Flag": False, "Text": ""}) is None
        assert v.armed == set()


class TestSentinelGrace:
    """A zero that lasts is a value (a limit set to 0, a unit switched off), not a restart."""

    PUMP_ZERO = {**GOOD, "HoldingRegister_6061": 0}

    def test_zero_blocks_until_the_grace_is_over_then_the_sentinel_is_disarmed(self, caplog):
        caplog.set_level(logging.WARNING, logger="econext_gateway.core.validity")
        v, clock = make()
        v.judge(GOOD)
        assert v.judge(self.PUMP_ZERO) == "HoldingRegister_6061 reads 0"
        clock.now += DEFAULT_GRACE - 1
        assert v.judge(self.PUMP_ZERO) == "HoldingRegister_6061 reads 0"
        clock.now += 1
        assert v.judge(self.PUMP_ZERO) is None  # committed: the cache is not frozen for good
        assert v.ready is True
        assert v.armed == {"TempCWU", "HoldingRegister_6271"}
        assert v.judge(self.PUMP_ZERO) is None
        hits = [r for r in caplog.records if "HoldingRegister_6061 has read 0 for 300 s" in r.getMessage()]
        assert len(hits) == 1

    def test_disarmed_sentinel_is_armed_again_by_a_non_zero_reading(self):
        v, clock = make(grace=60.0)
        v.judge(GOOD)
        v.judge(self.PUMP_ZERO)
        clock.now += 60
        assert v.judge(self.PUMP_ZERO) is None
        assert v.judge(GOOD) is None
        assert "HoldingRegister_6061" in v.armed
        assert v.judge(self.PUMP_ZERO) == "HoldingRegister_6061 reads 0"

    def test_a_non_zero_reading_starts_the_grace_again(self):
        v, clock = make(grace=60.0)
        v.judge(GOOD)
        v.judge(self.PUMP_ZERO)
        clock.now += 50
        v.judge(GOOD)
        clock.now += 50
        assert v.judge(self.PUMP_ZERO) == "HoldingRegister_6061 reads 0"

    def test_the_grace_runs_on_while_the_sentinel_is_missing_from_a_poll(self):
        v, clock = make(grace=60.0)
        v.judge(GOOD)
        v.judge(self.PUMP_ZERO)
        clock.now += 30
        without = {k: x for k, x in GOOD.items() if k != "HoldingRegister_6061"}
        assert v.judge(without) is None
        clock.now += 30
        assert v.judge(self.PUMP_ZERO) is None

    def test_the_restart_zeros_are_inside_the_grace(self):
        """The recorded restart reported zeros for about 90 seconds."""
        v, clock = make()
        v.judge(GOOD)
        for _ in range(9):
            clock.now += 10
            assert v.judge({**ZEROS, "resetCounter": 58}) is not None
        assert v.armed == set(DEFAULT_SENTINELS)


class TestStale:
    def test_not_ready_when_no_valid_poll_for_too_long(self):
        v, clock = make(stale_after=30.0)
        v.judge(GOOD)
        clock.now += 30.0
        assert v.ready is True
        clock.now += 4.0
        assert v.ready is False
        assert v.reason == "no valid poll for 34 s"
        v.judge(GOOD)
        assert v.ready is True

    def test_invalid_and_stale_reasons_are_both_given(self):
        v, clock = make(stale_after=30.0)
        v.judge(GOOD)
        v.judge({**GOOD, "TempCWU": 0.0})
        assert v.reason == "TempCWU reads 0"
        clock.now += 100.0
        assert v.reason == "TempCWU reads 0; no valid poll for 100 s"

    def test_invalid_first_poll_has_no_stale_part(self):
        v, clock = make(stale_after=30.0)
        v.judge({}, controller=False)
        clock.now += 100.0
        assert v.reason == "controller did not answer"

    def test_ready_and_reason_come_from_one_reading_of_the_clock(self):
        """A snapshot taken as the age crosses the limit must not say ready with a stale reason."""
        v, clock = make(stale_after=30.0)
        v.judge(GOOD)
        clock.now += 29.0

        def ticking() -> float:
            clock.now += 1.0  # every reading of the clock is a second later
            return clock.now

        v._clock = ticking
        first = v.snapshot()  # age 30: two readings would give ready with "no valid poll for 31 s"
        assert (first.ready, first.reason) == (True, "ok")
        second = v.snapshot()
        assert (second.ready, second.reason) == (False, "no valid poll for 31 s")
        assert v.transition() == (False, "no valid poll for 32 s")

    def test_stale_after_must_be_positive(self):
        with pytest.raises(ValueError, match="stale_after must be positive"):
            PollValidity(stale_after=0)

    def test_default_allows_for_the_fixed_part_of_a_cycle(self):
        """Token wait, the poll itself and the alarm read do not shrink with the interval."""
        assert default_stale_after(10.0) == 45.0
        assert default_stale_after(2.0) == 21.0


class TestCounts:
    def test_complete_incomplete_discarded(self):
        v, _ = make()
        v.judge(GOOD, complete=True)
        v.judge(GOOD, complete=False)
        v.judge({**GOOD, "TempCWU": 0.0}, complete=True)
        v.judge({}, complete=False, controller=False)
        assert (v.polls_complete, v.polls_incomplete, v.polls_discarded) == (1, 1, 2)

    def test_failed_poll_counts_as_discarded(self):
        v, _ = make()
        v.judge(GOOD)
        v.fail("poll failed (ConnectionError)")
        assert v.ready is False
        assert v.reason == "poll failed (ConnectionError)"
        assert (v.polls_complete, v.polls_incomplete, v.polls_discarded) == (1, 0, 1)
        assert v.judge(GOOD) is None
        assert v.ready is True

    def test_hourly_summary_once_per_hour(self):
        v, clock = make()
        v.judge(GOOD)
        assert v.hourly_summary() is None
        clock.now += 3600.0
        v.judge(GOOD, complete=False)
        line = v.hourly_summary()
        assert line == "Polls in the last hour: 1 complete, 1 incomplete, 0 discarded"
        assert v.hourly_summary() is None
        # totals keep counting, the hourly window starts again
        assert (v.polls_complete, v.polls_incomplete, v.polls_discarded) == (1, 1, 0)
        clock.now += 3600.0
        assert v.hourly_summary() == "Polls in the last hour: 0 complete, 0 incomplete, 0 discarded"


class TestTransitions:
    def test_one_message_per_change(self):
        v, clock = make(stale_after=30.0)
        assert v.transition() is None  # starting is not a change
        v.judge(GOOD)
        assert v.transition() is None  # first ready after start: nothing to report
        v.judge({**GOOD, "TempCWU": 0.0})
        assert v.transition() == (False, "TempCWU reads 0")
        v.judge({**GOOD, "TempCWU": 0.0})
        assert v.transition() is None
        v.judge(GOOD)
        assert v.transition() == (True, "ok")
        clock.now += 40.0
        assert v.transition() == (False, "no valid poll for 40 s")
        clock.now += 5.0
        assert v.transition() is None
