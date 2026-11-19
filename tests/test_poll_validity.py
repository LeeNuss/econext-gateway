"""Polls are committed to the cache only when valid (handler level)."""

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.validity import DEFAULT_GRACE
from econext_gateway.protocol.constants import RETRY_ATTEMPTS, Command, DataType
from econext_gateway.protocol.frames import Frame
from econext_gateway.protocol.handler import STARTUP_POLLS, ParamStructEntry, ProtocolHandler, _BatchRequest
from econext_gateway.serial.connection import GM3SerialTransport
from econext_gateway.serial.protocol import GM3Protocol

COUNTER, CYLINDER, SETPOINT, PUMP_MIN, PUMP_MAX = 14, 61, 103, 1440, 1441
# Not in STRUCTS: a measurement in a batch of its own, and a panel parameter.
FLOW, PANEL = 2000, 10005
FLOW_STRUCT = ParamStructEntry(FLOW, "FlowTemp", 1, DataType.FLOAT, False)
PANEL_STRUCT = ParamStructEntry(PANEL, "PanelBrightness", 0, DataType.UINT8, True)

STRUCTS = {
    COUNTER: ParamStructEntry(COUNTER, "resetCounter", 0, DataType.UINT16, False),
    CYLINDER: ParamStructEntry(CYLINDER, "TempCWU", 1, DataType.FLOAT, False),
    SETPOINT: ParamStructEntry(SETPOINT, "HDWTSetPoint", 1, DataType.UINT8, True),
    PUMP_MIN: ParamStructEntry(PUMP_MIN, "HoldingRegister_6061", 6, DataType.UINT16, True),
    PUMP_MAX: ParamStructEntry(PUMP_MAX, "HoldingRegister_6271", 6, DataType.UINT16, True),
}

# The recorded sequence: a normal poll, then the poll in which the controller
# restarted (counter moved, zeros in values that are never zero, a setting
# that kept its value), then real values again.
BEFORE = {COUNTER: 58, CYLINDER: 40.0, SETPOINT: 46, PUMP_MIN: 50, PUMP_MAX: 60}
RESET = {COUNTER: 59, CYLINDER: 0.0, SETPOINT: 46, PUMP_MIN: 0, PUMP_MAX: 0}
AFTER = {COUNTER: 59, CYLINDER: 39.9, SETPOINT: 46, PUMP_MIN: 50, PUMP_MAX: 60}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(paired_address_file):
    """Handler with a mocked connection, the five parameters and a test clock."""
    conn = MagicMock(spec=GM3SerialTransport)
    conn.connected = True
    conn.protocol = MagicMock(spec=GM3Protocol)
    conn.protocol.write_frame = AsyncMock(return_value=True)
    conn.protocol.reset_buffer = MagicMock()
    cache = ParameterCache()
    handler = ProtocolHandler(
        connection=conn,
        cache=cache,
        poll_interval=10.0,
        request_timeout=0.5,
        token_timeout=0,
        token_required=False,
        paired_address_file=paired_address_file,
    )
    handler._param_structs = dict(STRUCTS)
    clock = Clock()
    handler._validity._clock = clock
    handler._validity._hour_started = clock.now
    return handler, cache, clock


def feed(handler: ProtocolHandler, values: dict[int, Any], fail: frozenset[int] = frozenset()) -> None:
    """Answer the handler's batch requests from ``values``; batches starting at an index in ``fail`` time out."""

    async def fake(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
        first = start_index + store_offset
        if first in fail:
            return []
        return [(i, values[i]) for i in sorted(values) if first <= i < first + count]

    handler.fetch_param_values = fake


def second_reading(handler: ProtocolHandler, counter: Any) -> None:
    """Make the reading of the reset counter after the last batch return ``counter``, or fail when it is None."""
    handler._read_again = AsyncMock(return_value=(counter is not None, counter))


async def cached(cache: ParameterCache) -> dict[int, Any]:
    return {p.index: p.value for p in (await cache.get_all()).values()}


class TestRecordedEvent:
    @pytest.mark.asyncio
    async def test_reset_poll_is_discarded_and_the_next_valid_poll_recovers(self, rig):
        handler, cache, clock = rig

        feed(handler, BEFORE)
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True
        assert handler.readiness().reason == "ok"
        assert await cached(cache) == BEFORE

        # the poll in which the controller restarted
        clock.now += 10
        feed(handler, RESET)
        assert await handler.poll_all_params() == 0
        assert handler.readiness().ready is False
        assert handler.readiness().reason.startswith("controller reset (counter 58 to 59)")
        assert "TempCWU" in handler.readiness().reason
        assert await cached(cache) == BEFORE  # nobody reads the zeros
        assert handler.readiness().reset_counter == 58

        # 70 s without a bus token: no poll at all
        clock.now += 70
        assert handler.readiness().ready is False
        assert "no valid poll for 80 s" in handler.readiness().reason
        assert await cached(cache) == BEFORE

        # first poll after the controller is back
        feed(handler, AFTER)
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True
        assert handler.readiness().reason == "ok"
        assert await cached(cache) == AFTER
        state = handler.readiness()
        assert (state.reset_counter, state.polls_discarded) == (59, 1)

    @pytest.mark.asyncio
    async def test_silence_alone_makes_the_data_not_ready(self, rig):
        handler, cache, clock = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        clock.now += 45  # three poll intervals and the fixed part of a cycle
        assert handler.readiness().ready is True
        clock.now += 1
        assert handler.readiness().ready is False
        assert handler.readiness().reason == "no valid poll for 46 s"


class TestRules:
    @pytest.mark.asyncio
    async def test_zeros_with_the_counter_unchanged(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, {**BEFORE, CYLINDER: 0.0})
        assert await handler.poll_all_params() == 0
        assert handler.readiness().ready is False
        assert handler.readiness().reason == "TempCWU reads 0"
        assert await cached(cache) == BEFORE

    @pytest.mark.asyncio
    async def test_counter_change_with_sane_values_costs_one_poll(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, {**BEFORE, COUNTER: 59})
        assert await handler.poll_all_params() == 0
        assert handler.readiness().ready is False
        assert await cached(cache) == BEFORE
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True
        assert (await cached(cache))[COUNTER] == 59

    @pytest.mark.asyncio
    async def test_sentinel_that_was_never_non_zero_does_not_block(self, rig):
        handler, cache, _ = rig
        always_zero = {**BEFORE, PUMP_MIN: 0}
        feed(handler, always_zero)
        assert await handler.poll_all_params() == 5
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True
        assert (await cached(cache))[PUMP_MIN] == 0

    @pytest.mark.asyncio
    async def test_sentinels_and_counter_come_from_the_settings(self, paired_address_file):
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            token_timeout=0,
            token_required=False,
            paired_address_file=paired_address_file,
            reset_counter_param="",
            validity_sentinels=("HDWTSetPoint",),
            stale_after=5.0,
        )
        handler._param_structs = dict(STRUCTS)
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, RESET)  # counter rule off, the default sentinels are not sentinels here
        assert await handler.poll_all_params() == 5
        feed(handler, {**RESET, SETPOINT: 0})
        assert await handler.poll_all_params() == 0
        assert handler.readiness().reason == "HDWTSetPoint reads 0"

    @pytest.mark.asyncio
    async def test_stale_after_defaults_to_three_poll_intervals_and_a_margin(self, rig):
        handler, _, _ = rig
        assert handler._validity._stale_after == 45.0


class TestControllerSilent:
    @pytest.mark.asyncio
    async def test_poll_only_the_panel_answered_is_discarded(self, rig):
        """Panel values say nothing about the controller: they must not make the data ready."""
        handler, cache, clock = rig
        handler._param_structs[PANEL] = PANEL_STRUCT
        feed(handler, {**BEFORE, PANEL: 3})
        assert await handler.poll_all_params() == 6

        clock.now += 40
        feed(handler, {**BEFORE, PANEL: 4}, fail=frozenset({COUNTER, PUMP_MIN}))  # only the panel answers
        assert await handler.poll_all_params() == 0
        state = handler.readiness()
        assert (state.ready, state.reason) == (False, "controller did not answer")
        assert (await cached(cache))[PANEL] == 3

        clock.now += 10  # 50 s after the last valid poll: the panel's answer did not refresh it
        assert handler.readiness().reason == "controller did not answer; no valid poll for 50 s"

    @pytest.mark.asyncio
    async def test_panel_only_poll_does_not_open_the_startup_gate(self, rig):
        handler, cache, _ = rig
        handler._param_structs[PANEL] = PANEL_STRUCT
        feed(handler, {**BEFORE, PANEL: 3}, fail=frozenset({COUNTER, PUMP_MIN}))
        for _ in range(STARTUP_POLLS + 1):
            assert await handler.poll_all_params() == 0
        assert handler.params_ready is False
        assert cache.count == 0


class TestResetInTheMiddleOfAPoll:
    @pytest.mark.asyncio
    async def test_second_reading_of_the_counter_catches_it(self, rig):
        """The first batch read the counter and the cylinder before the reset, the
        sentinels after it were not read, and what came after the reset is 0."""
        handler, cache, _ = rig
        handler._param_structs[FLOW] = FLOW_STRUCT
        feed(handler, {**BEFORE, FLOW: 35.0})
        assert await handler.poll_all_params() == 6

        values = {**BEFORE, FLOW: 0.0}
        counter = iter([58, 59])  # as the first batch reads it, and after the last batch

        async def resetting(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
            if start_index == PUMP_MIN:
                return []
            reply = [(i, values[i]) for i in sorted(values) if start_index <= i < start_index + count]
            if start_index == COUNTER:
                reply[0] = (COUNTER, next(counter))
            return reply

        handler.fetch_param_values = resetting
        assert await handler.poll_all_params() == 0
        assert handler.readiness().reason == "controller reset (counter 58 to 59)"
        assert (await cached(cache))[FLOW] == 35.0  # the zero is not served

        # the poll after it is the first whole one since the reset, and it lands
        feed(handler, {**AFTER, FLOW: 34.5})
        assert await handler.poll_all_params() == 6
        assert handler.readiness().ready is True
        assert (await cached(cache))[FLOW] == 34.5

    @pytest.mark.asyncio
    async def test_second_reading_repeats_the_request_of_the_counter_batch(self, rig):
        """A request the controller is known to answer, not a new kind of request."""
        handler, _, _ = rig
        requests: list[tuple[int, int]] = []

        async def fake(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
            requests.append((start_index, count))
            return [(i, BEFORE[i]) for i in sorted(BEFORE) if start_index <= i < start_index + count]

        handler.fetch_param_values = fake
        assert await handler.poll_all_params() == 5
        first_batch = (COUNTER, SETPOINT - COUNTER + 1)
        assert requests == [first_batch, (PUMP_MIN, 2), first_batch]

    @pytest.mark.asyncio
    async def test_counter_that_cannot_be_read_again_discards_the_poll(self, rig):
        """A controller that stops answering at the end of a poll may be restarting."""
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()

        feed(handler, {**BEFORE, CYLINDER: 41.0})
        second_reading(handler, None)
        assert await handler.poll_all_params() == 0
        assert handler.readiness().reason == "reset counter not read"
        assert (await cached(cache))[CYLINDER] == 40.0

        second_reading(handler, 58)
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True

    @pytest.mark.asyncio
    async def test_second_reading_gives_up_after_the_retries(self, rig):
        handler, _, _ = rig
        feed(handler, BEFORE, fail=frozenset({COUNTER}))
        handler.fetch_param_values = AsyncMock(wraps=handler.fetch_param_values)
        request = _BatchRequest(COUNTER, SETPOINT - COUNTER + 1, None, 0)
        assert await handler._read_again(request, COUNTER) == (False, None)
        assert handler.fetch_param_values.await_count == RETRY_ATTEMPTS

    @pytest.mark.asyncio
    async def test_counter_batch_that_failed_is_made_up_for_by_the_second_reading(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()

        values = {**BEFORE, PUMP_MIN: 55}
        attempts = 0

        async def late(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
            nonlocal attempts
            if start_index == COUNTER:
                attempts += 1
                if attempts <= RETRY_ATTEMPTS:
                    return []  # every attempt of the first batch times out
            return [(i, values[i]) for i in sorted(values) if start_index <= i < start_index + count]

        handler.fetch_param_values = late
        assert await handler.poll_all_params() == 2
        assert handler.readiness().ready is True
        assert (await cached(cache))[PUMP_MIN] == 55

    @pytest.mark.asyncio
    async def test_controller_without_the_counter_is_polled_without_a_second_reading(self, rig):
        handler, _, _ = rig
        del handler._param_structs[COUNTER]
        requests: list[tuple[int, int]] = []
        values = {k: v for k, v in BEFORE.items() if k != COUNTER}

        async def fake(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
            requests.append((start_index, count))
            return [(i, values[i]) for i in sorted(values) if start_index <= i < start_index + count]

        handler.fetch_param_values = fake
        assert await handler.poll_all_params() == 4
        assert handler.readiness().ready is True
        assert requests == [(CYLINDER, SETPOINT - CYLINDER + 1), (PUMP_MIN, 2)]


class TestSentinelThatStaysZero:
    @pytest.mark.asyncio
    async def test_zero_that_lasts_is_committed_after_the_grace(self, rig):
        """A pump limit set to 0, or an outdoor unit that is off, must not freeze the cache for good."""
        handler, cache, clock = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()

        feed(handler, {**BEFORE, PUMP_MIN: 0, CYLINDER: 43.0})
        assert await handler.poll_all_params() == 0
        assert (await cached(cache))[CYLINDER] == 40.0

        clock.now += DEFAULT_GRACE
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True
        assert (await cached(cache))[CYLINDER] == 43.0
        assert (await cached(cache))[PUMP_MIN] == 0


class TestDuplicateNames:
    @pytest.mark.asyncio
    async def test_sentinel_is_judged_by_its_lowest_index_only(self, paired_address_file):
        """The copy at the higher index is another parameter: when the first copy
        was not read, the second must not be judged in its place."""
        first, second = 311, 785
        conn = MagicMock(spec=GM3SerialTransport)
        conn.connected = True
        cache = ParameterCache()
        handler = ProtocolHandler(
            connection=conn,
            cache=cache,
            token_timeout=0,
            token_required=False,
            paired_address_file=paired_address_file,
            reset_counter_param="",
            validity_sentinels=("Circuit2BaseTemp",),
        )
        handler._param_structs = {
            first: ParamStructEntry(first, "Circuit2BaseTemp", 0, DataType.UINT8, True),
            second: ParamStructEntry(second, "Circuit2BaseTemp", 0, DataType.UINT8, True),
        }
        feed(handler, {first: 30, second: 0})
        assert await handler.poll_all_params() == 2  # arms the sentinel from index 311

        feed(handler, {first: 30, second: 0}, fail=frozenset({first}))
        assert await handler.poll_all_params() == 1
        assert handler.readiness().ready is True


class TestStartupGate:
    @pytest.mark.asyncio
    async def test_incomplete_first_poll_is_stored_but_does_not_open_the_gate(self, rig):
        """Home Assistant builds its entities from the first reply: it must not get part of the set."""
        handler, cache, _ = rig
        feed(handler, BEFORE, fail=frozenset({PUMP_MIN}))  # the batch with both pump settings times out
        assert await handler.poll_all_params() == 3
        assert handler.params_ready is False
        state = handler.readiness()
        assert (state.ready, state.reason) == (False, "waiting for a complete poll")
        assert (state.polls_complete, state.polls_incomplete, state.polls_discarded) == (0, 1, 0)
        assert await cached(cache) == {COUNTER: 58, CYLINDER: 40.0, SETPOINT: 46}

        feed(handler, BEFORE)
        assert await handler.poll_all_params() == 5
        assert handler.params_ready is True
        assert handler.readiness().ready is True

    @pytest.mark.asyncio
    async def test_gate_opens_when_a_batch_keeps_failing(self, rig, caplog):
        """A batch that never answers must not keep the API closed for good."""
        handler, cache, _ = rig
        caplog.set_level(logging.WARNING, logger="econext_gateway.protocol.handler")
        feed(handler, BEFORE, fail=frozenset({PUMP_MIN}))
        for poll in range(1, STARTUP_POLLS + 1):
            assert await handler.poll_all_params() == 3
            assert handler.params_ready is (poll == STARTUP_POLLS)
        assert handler.readiness().ready is True
        hits = [r for r in caplog.records if "a batch keeps failing" in r.getMessage()]
        assert len(hits) == 1
        assert "3 parameters after 3 incomplete polls" in hits[0].getMessage()


class TestFailedPoll:
    @pytest.mark.asyncio
    async def test_exception_in_the_middle_of_a_poll(self, rig):
        """Nothing of the poll is committed, and it is not passed over in silence."""
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()

        async def port_drops(start_index: int, count: int, destination: int | None = None, store_offset: int = 0):
            if start_index == PUMP_MIN:
                raise ConnectionError("serial port gone")
            return [(CYLINDER, 41.0)]

        handler.fetch_param_values = port_drops
        with pytest.raises(ConnectionError):
            await handler.poll_all_params()

        state = handler.readiness()
        assert (state.ready, state.reason) == (False, "poll failed (ConnectionError)")
        assert state.polls_discarded == 1
        assert await cached(cache) == BEFORE

        feed(handler, {**BEFORE, CYLINDER: 41.0})
        assert await handler.poll_all_params() == 5
        assert handler.readiness().ready is True


class TestConnection:
    @pytest.mark.asyncio
    async def test_not_ready_while_the_connection_is_down(self, rig):
        """The last poll was fine, but nothing can be read any more."""
        handler, _, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        handler._connection.connected = False
        state = handler.readiness()
        assert (state.ready, state.reason) == (False, "not connected")
        assert state.reset_counter == 58


class TestIncompletePolls:
    @pytest.mark.asyncio
    async def test_failed_batch_is_committed_and_counted(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, {**BEFORE, CYLINDER: 41.0}, fail=frozenset({PUMP_MIN}))  # the pump settings batch times out
        assert await handler.poll_all_params() == 3
        assert handler.readiness().ready is True
        assert await cached(cache) == {**BEFORE, CYLINDER: 41.0}
        state = handler.readiness()
        assert (state.polls_complete, state.polls_incomplete, state.polls_discarded) == (1, 1, 0)

    @pytest.mark.asyncio
    async def test_sentinel_absent_from_the_poll_is_not_judged(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, {**BEFORE, CYLINDER: 41.0}, fail=frozenset({PUMP_MIN}))
        assert await handler.poll_all_params() == 3
        assert handler.readiness().ready is True
        assert (await cached(cache))[CYLINDER] == 41.0
        assert (await cached(cache))[PUMP_MIN] == 50  # kept from the last poll that read it

    @pytest.mark.asyncio
    async def test_empty_poll_writes_nothing_and_does_not_set_the_start_latch(self, rig):
        handler, cache, _ = rig
        feed(handler, BEFORE, fail=frozenset({COUNTER, PUMP_MIN}))
        assert await handler.poll_all_params() == 0
        assert handler.params_ready is False
        assert handler.readiness().ready is False
        assert handler.readiness().reason == "controller did not answer"
        assert cache.count == 0
        feed(handler, BEFORE)
        assert await handler.poll_all_params() == 5
        assert handler.params_ready is True
        assert handler.readiness().ready is True

    @pytest.mark.asyncio
    async def test_not_ready_before_the_first_poll(self, rig):
        handler, _, _ = rig
        assert handler.readiness().ready is False
        assert handler.readiness().reason == "starting"


class TestCommit:
    @pytest.mark.asyncio
    async def test_one_cache_write_per_valid_poll_and_none_for_a_discarded_one(self, rig):
        handler, cache, _ = rig
        cache.set_many = AsyncMock(wraps=cache.set_many)
        feed(handler, BEFORE)
        await handler.poll_all_params()
        assert cache.set_many.await_count == 1
        assert len(cache.set_many.await_args.args[0]) == 5
        feed(handler, RESET)
        await handler.poll_all_params()
        assert cache.set_many.await_count == 1

    @pytest.mark.asyncio
    async def test_limits_by_reference_resolve_within_the_first_poll(self, rig):
        """A limit that refers to another parameter is resolved from the poll being
        collected, as it was when every batch went to the cache at once."""
        handler, cache, _ = rig
        handler._param_structs[SETPOINT] = ParamStructEntry(
            SETPOINT, "HDWTSetPoint", 1, DataType.UINT8, True, max_param_ref=COUNTER
        )
        feed(handler, BEFORE)
        await handler.poll_all_params()
        param = await cache.get(SETPOINT)
        assert param.max_value == 58.0

    @pytest.mark.asyncio
    async def test_limits_without_a_reference_do_not_touch_the_cache(self, rig):
        handler, cache, _ = rig
        cache.get = AsyncMock(wraps=cache.get)
        entry = STRUCTS[SETPOINT]
        assert await handler._resolve_min_max(entry) == (entry.min_value, entry.max_value)
        cache.get.assert_not_awaited()


class TestWritesWhileNotReady:
    @pytest.mark.asyncio
    async def test_write_is_sent_and_its_ack_reaches_the_cache(self, rig):
        """Not ready does not refuse writes: a stop set by hand during a controller
        restart must still be taken, and so must the fix for a sentinel set to 0."""
        handler, cache, _ = rig
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, RESET)
        await handler.poll_all_params()
        assert handler.readiness().ready is False

        ack = Frame(destination=200, command=Command.MODIFY_PARAM_RESPONSE, data=b"")
        handler.send_and_receive = AsyncMock(return_value=ack)
        assert await handler.write_param("HoldingRegister_6061", 55) is True
        assert (await cached(cache))[PUMP_MIN] == 55
        assert handler.readiness().ready is False  # only a valid poll makes the data ready again


class TestLogging:
    @pytest.mark.asyncio
    async def test_one_warning_on_not_ready_and_one_info_on_recovery(self, rig, caplog):
        handler, _, _ = rig
        caplog.set_level(logging.INFO, logger="econext_gateway.protocol.handler")
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, RESET)
        await handler.poll_all_params()
        await handler.poll_all_params()  # a second discarded poll: no second warning
        handler._report_readiness()

        def lines(text: str) -> list[logging.LogRecord]:
            return [r for r in caplog.records if text in r.getMessage()]

        assert len(lines("Data not ready")) == 1
        assert lines("Data not ready")[0].levelno == logging.WARNING
        assert "controller reset (counter 58 to 59)" in lines("Data not ready")[0].getMessage()
        assert lines("Data ready again") == []

        feed(handler, AFTER)
        await handler.poll_all_params()
        await handler.poll_all_params()
        assert len(lines("Data ready again")) == 1
        assert lines("Data ready again")[0].levelno == logging.INFO

    @pytest.mark.asyncio
    async def test_stale_is_logged_without_a_poll(self, rig, caplog):
        handler, _, clock = rig
        caplog.set_level(logging.INFO, logger="econext_gateway.protocol.handler")
        feed(handler, BEFORE)
        await handler.poll_all_params()
        clock.now += 50
        handler._report_readiness()  # what the bus watchdog calls every few seconds
        handler._report_readiness()
        hits = [r for r in caplog.records if "Data not ready: no valid poll for 50 s" in r.getMessage()]
        assert len(hits) == 1

    @pytest.mark.asyncio
    async def test_poll_counts_once_per_hour(self, rig, caplog):
        handler, _, clock = rig
        caplog.set_level(logging.INFO, logger="econext_gateway.protocol.handler")
        feed(handler, BEFORE)
        await handler.poll_all_params()
        feed(handler, BEFORE, fail=frozenset({PUMP_MIN}))
        await handler.poll_all_params()
        feed(handler, RESET)
        await handler.poll_all_params()
        assert [r for r in caplog.records if "Polls in the last hour" in r.getMessage()] == []
        clock.now += 3600
        handler._report_readiness()
        hits = [r for r in caplog.records if "Polls in the last hour" in r.getMessage()]
        assert len(hits) == 1
        assert hits[0].getMessage() == "Polls in the last hour: 1 complete, 1 incomplete, 1 discarded"
