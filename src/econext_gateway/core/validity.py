"""Poll validity and data readiness.

A controller that restarts answers the first poll after its reset with
zeros in values that are never zero in operation, and its reset counter
moves in that same poll. A poll like that must not reach the cache: every
client would read the zeros as measurements.

``PollValidity`` judges each completed poll before it is committed:

- Controller. A poll in which the controller answered nothing is
  discarded, also when the panel did answer: panel values say nothing
  about the controller.
- Reset counter. The counter is read again after the last batch and that
  reading is the one judged, so a reset that falls in the middle of a poll
  is seen in that poll. A poll whose counter differs from the previous
  poll's is discarded (the reset fell in it or just before it), and so is
  a poll in which the controller has the counter but it could not be
  read. The next poll with the same counter can be valid again. There is
  no baseline on the first poll.
- Sentinels. Parameters that never read 0 in operation. A sentinel is
  armed once it has read non-zero in a valid poll since the gateway
  started; an armed sentinel reading exactly 0 discards the poll. A site
  where one of them is always 0 is therefore never locked out, and a
  sentinel missing from a poll is not judged.

No rule discards polls for the same cause for longer than ``grace``
seconds, or the cache would stay frozen for as long as the cause lasts. A
zero that lasts that long is a value, not a restart (a limit set to 0, a
unit that is switched off): the sentinel is disarmed until it reads
non-zero again. A counter that cannot be read for that long is no longer
asked for until it reads again.

Completeness is not part of validity: a poll with a failed batch is
committed and only counted.

The data is ready when the last poll was valid and the last valid poll is
no older than ``stale_after`` seconds, which covers a controller that
stops answering altogether.
"""

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RESET_COUNTER_PARAM = "resetCounter"
# Cylinder temperature and the circulation pump's speed limits.
DEFAULT_SENTINELS: tuple[str, ...] = ("TempCWU", "HoldingRegister_6061", "HoldingRegister_6271")
# How long a rule may discard polls for the same cause (a sentinel reading 0,
# a reset counter that cannot be read) before that is taken as the normal
# state. A restarting controller was seen to report zeros for about 90 seconds.
DEFAULT_GRACE = 300.0
# What a poll cycle takes besides the wait between two polls: the bus token,
# the poll itself and, every few cycles, the alarm read. None of it gets
# shorter with the poll interval.
STALE_MARGIN = 15.0
SUMMARY_INTERVAL = 3600.0


def default_stale_after(poll_interval: float) -> float:
    """Three poll intervals plus the part of a cycle that is not waiting."""
    return 3 * poll_interval + STALE_MARGIN


def parse_names(text: str) -> tuple[str, ...]:
    """Split a comma separated list of parameter names; blanks are dropped."""
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_zero(value: Any) -> bool:
    return _is_number(value) and value == 0


def _fmt(value: Any) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


@dataclass(frozen=True)
class Readiness:
    """Snapshot of the data readiness, for the API."""

    ready: bool
    reason: str
    reset_counter: int | None
    last_valid_poll: datetime | None
    polls_complete: int
    polls_incomplete: int
    polls_discarded: int


class PollValidity:
    """Judges completed polls and tracks whether the served data can be trusted."""

    def __init__(
        self,
        reset_counter_param: str = DEFAULT_RESET_COUNTER_PARAM,
        sentinels: Iterable[str] = DEFAULT_SENTINELS,
        stale_after: float = 30.0,
        grace: float = DEFAULT_GRACE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize.

        Args:
            reset_counter_param: Name of the controller's reset counter;
                empty disables the counter rule.
            sentinels: Names of parameters that never read 0 in operation.
            stale_after: Seconds without a valid poll after which the data
                is no longer ready. Must be positive.
            grace: Seconds a sentinel may read 0, or the reset counter may
                stay unread, before polls are no longer discarded for it.
            clock: Monotonic clock, replaceable in tests.
        """
        if stale_after <= 0:
            raise ValueError(f"stale_after must be positive, got {stale_after}")
        self._counter_param = reset_counter_param
        self._sentinels = tuple(sentinels)
        self._stale_after = stale_after
        self._grace = grace
        self._clock = clock

        self._seen_counter: Any = None  # of the previous poll that read one, valid or not
        self._valid_counter: Any = None  # of the last valid poll that read one
        self._armed: set[str] = set()
        self._zero_since: dict[str, float] = {}  # when an armed sentinel first read 0
        self._counter_unread_since: float | None = None
        self._counter_given_up = False  # unread for longer than the grace
        self._polls = 0  # polls since start, discarded and failed ones included
        self._last_valid: bool | None = None  # verdict on the last poll
        self._last_reason = ""
        self._last_valid_mono: float | None = None
        self.last_valid_at: datetime | None = None

        self.polls_complete = 0
        self.polls_incomplete = 0
        self.polls_discarded = 0
        self._hour = [0, 0, 0]  # complete, incomplete, discarded since the last summary
        self._hour_started = clock()
        self._reported: bool | None = None  # readiness last returned by transition()

    @property
    def counter_param(self) -> str:
        """Name of the reset counter; empty when the counter rule is off."""
        return self._counter_param

    @property
    def watched(self) -> frozenset[str]:
        """Names of the parameters a poll is judged by: the counter and the sentinels."""
        names = set(self._sentinels)
        if self._counter_param:
            names.add(self._counter_param)
        return frozenset(names)

    # ------------------------------------------------------------------ judging
    def judge(
        self,
        values: Mapping[str, Any],
        complete: bool = True,
        *,
        controller: bool = True,
        counter_unread: bool = False,
    ) -> str | None:
        """Judge a completed poll.

        Args:
            values: Parameter name to the value read in this poll. Only the
                reset counter and the sentinels are looked at; the counter
                is the reading taken after the last batch.
            complete: False when a batch of the poll failed.
            controller: False when the controller answered nothing.
            counter_unread: True when the controller has the reset counter
                but it could not be read after the last batch.

        Returns:
            None when the poll is valid and may be committed, otherwise the
            reason it is discarded.
        """
        self._polls += 1
        now = self._clock()
        reasons: list[str] = []

        counter = values.get(self._counter_param) if self._counter_param else None
        if counter is not None:
            self._counter_unread_since = None
            self._counter_given_up = False
        if not controller:
            reasons.append("controller did not answer")
        elif counter is not None:
            if self._seen_counter is not None and counter != self._seen_counter:
                reasons.append(f"controller reset (counter {_fmt(self._seen_counter)} to {_fmt(counter)})")
            self._seen_counter = counter
        elif counter_unread and self._counter_still_required(now):
            reasons.append("reset counter not read")

        zeros = self._blocking_zeros(values, now)
        if zeros:
            reasons.append(f"{', '.join(zeros)} {'reads' if len(zeros) == 1 else 'read'} 0")

        if reasons:
            return self._discard("; ".join(reasons))

        for name in self._sentinels:
            value = values.get(name)
            if _is_number(value) and value != 0:
                self._armed.add(name)
        if counter is not None:
            self._valid_counter = counter
        self._last_valid = True
        self._last_reason = ""
        self._last_valid_mono = now
        self.last_valid_at = datetime.now()
        if complete:
            self.polls_complete += 1
            self._hour[0] += 1
        else:
            self.polls_incomplete += 1
            self._hour[1] += 1
        return None

    def fail(self, reason: str) -> None:
        """Record a poll that ended before it could be judged.

        Nothing of it is committed, so it counts as discarded and the data
        is not ready until a later poll is valid.
        """
        self._polls += 1
        self._discard(reason)

    def _discard(self, reason: str) -> str:
        self._last_valid = False
        self._last_reason = reason
        self.polls_discarded += 1
        self._hour[2] += 1
        return reason

    def _counter_still_required(self, now: float) -> bool:
        """False once the reset counter has been unread for longer than the grace."""
        if self._counter_unread_since is None:
            self._counter_unread_since = now
        unread_for = now - self._counter_unread_since
        if unread_for < self._grace:
            return True
        if not self._counter_given_up:
            self._counter_given_up = True
            logger.warning(
                "Reset counter not read for %.0f s: polls are judged without it until it reads again", unread_for
            )
        return False

    def _blocking_zeros(self, values: Mapping[str, Any], now: float) -> list[str]:
        """Armed sentinels that read 0 in this poll and have not done so for long."""
        zeros: list[str] = []
        for name in self._sentinels:
            if name not in values:
                continue
            if not _is_zero(values[name]):
                self._zero_since.pop(name, None)
                continue
            if name not in self._armed:
                continue
            since = self._zero_since.setdefault(name, now)
            if now - since >= self._grace:
                self._armed.discard(name)
                del self._zero_since[name]
                logger.warning(
                    "%s has read 0 for %.0f s: taken as its value from now on, not as a controller restart",
                    name,
                    now - since,
                )
                continue
            zeros.append(name)
        return zeros

    # ---------------------------------------------------------------- readiness
    def _evaluate(self) -> tuple[bool, str]:
        """(ready, reason) from one reading of the clock."""
        if self._last_valid is None:
            return False, "starting"
        age = None if self._last_valid_mono is None else self._clock() - self._last_valid_mono
        stale = f"no valid poll for {age:.0f} s" if age is not None and age > self._stale_after else ""
        if self._last_valid is False:
            return False, f"{self._last_reason}; {stale}" if stale else self._last_reason
        if stale:
            return False, stale
        return True, "ok"

    @property
    def ready(self) -> bool:
        """The last poll was valid and the last valid poll is recent enough."""
        return self._evaluate()[0]

    @property
    def reason(self) -> str:
        """Why the data is not ready, or "ok"."""
        return self._evaluate()[1]

    @property
    def reset_counter(self) -> int | None:
        """Reset counter of the last valid poll, the one the cache holds.

        None when no valid poll has read it, or when the configured
        parameter does not hold a whole number.
        """
        value = self._valid_counter
        if _is_number(value) and float(value).is_integer():
            return int(value)
        return None

    @property
    def armed(self) -> set[str]:
        """Sentinels that have read non-zero in a valid poll."""
        return set(self._armed)

    def snapshot(self) -> Readiness:
        """Readiness and counts in one consistent reading."""
        ready, reason = self._evaluate()
        return Readiness(
            ready=ready,
            reason=reason,
            reset_counter=self.reset_counter,
            last_valid_poll=self.last_valid_at,
            polls_complete=self.polls_complete,
            polls_incomplete=self.polls_incomplete,
            polls_discarded=self.polls_discarded,
        )

    # ------------------------------------------------------------------ logging
    def transition(self) -> tuple[bool, str] | None:
        """(ready, reason) once per change of the readiness, otherwise None.

        The first ready state after start is not reported.
        """
        now_ready, reason = self._evaluate()
        if self._reported is None:
            if now_ready:
                self._reported = True
                return None
            if self._polls == 0:
                return None  # still starting
            self._reported = False
            return False, reason
        if now_ready == self._reported:
            return None
        self._reported = now_ready
        return now_ready, reason

    def hourly_summary(self) -> str | None:
        """One line of poll counts per hour, otherwise None."""
        now = self._clock()
        if now - self._hour_started < SUMMARY_INTERVAL:
            return None
        complete, incomplete, discarded = self._hour
        self._hour = [0, 0, 0]
        self._hour_started = now
        return f"Polls in the last hour: {complete} complete, {incomplete} incomplete, {discarded} discarded"
