"""Frame dispatcher for GM3 bus.

Single consumer of GM3Protocol's frame queue. Routes each inbound frame
through an ordered chain of subscribers. The first subscriber to return
True claims the frame.

This decouples frame receipt from the handler's critical section.
Previously `_wait_for_token()` and `send_and_receive()` both pulled from
the queue while holding `ProtocolHandler._lock`, which meant the lock
covered the full duration of a panel-granted token wait (up to minutes
of real time). API calls queued behind the poll loop for the whole
wait. With the dispatcher running its own task, `_wait_for_token()`
becomes a fast `asyncio.Event` wait and the lock only needs to cover
actual bus transactions.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from econext_gateway.protocol.frames import Frame

logger = logging.getLogger(__name__)

Subscriber = Callable[[Frame], Awaitable[bool]]


class FrameDispatcher:
    """Consumes the protocol frame queue and routes frames to subscribers.

    Subscribers are called in registration order; the first to return
    True claims the frame. Unhandled frames are logged at debug level.
    """

    def __init__(self, connection) -> None:
        """Args:
            connection: GM3SerialTransport. Accessed via its `.protocol`
                property each loop iteration so reconnects are transparent
                to the dispatcher.
        """
        self._connection = connection
        self._subscribers: list[Subscriber] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        try:
            self._subscribers.remove(subscriber)
        except ValueError:
            pass

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="FrameDispatcher")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while self._running:
                # Access protocol fresh each iteration so reconnect just works.
                try:
                    protocol = self._connection.protocol
                except RuntimeError:
                    # Not connected yet; wait a bit and retry.
                    await asyncio.sleep(0.5)
                    continue
                try:
                    frame = await protocol.receive_frame(timeout=1.0)
                except RuntimeError:
                    await asyncio.sleep(0.5)
                    continue
                if frame is None:
                    # Ensure we yield to the event loop even if a misbehaving
                    # implementation returns None without awaiting (e.g. mocks).
                    await asyncio.sleep(0)
                    continue
                await self._dispatch(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("FrameDispatcher crashed; frames will no longer be routed")
            self._running = False

    async def _dispatch(self, frame: Frame) -> None:
        for sub in list(self._subscribers):
            try:
                handled = await sub(frame)
            except Exception:
                logger.exception("Subscriber raised while handling frame")
                continue
            if handled:
                return
        logger.debug(
            "Unhandled frame: src=%d dst=%d cmd=0x%02X",
            frame.source,
            frame.destination,
            frame.command,
        )
