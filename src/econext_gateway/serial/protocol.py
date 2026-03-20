"""asyncio.Protocol implementation for GM3 serial framing."""

import asyncio
import logging

from econext_gateway.protocol.constants import BEGIN_FRAME, END_FRAME, FRAME_MIN_LEN
from econext_gateway.protocol.frames import Frame

logger = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 64


class GM3Protocol(asyncio.Protocol):
    """Event-driven GM3 frame parser and writer.

    Receives raw bytes via ``data_received()``, extracts complete frames,
    and places them on an asyncio.Queue for consumption by higher layers.
    Writing is serialised through an asyncio.Lock.
    """

    def __init__(self, keep_destinations: set[int] | None = None, panel_address: int = 100) -> None:
        self._transport: asyncio.Transport | None = None
        self._rx_buffer = bytearray()
        self._frame_queue: asyncio.Queue[Frame | None] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._write_lock = asyncio.Lock()
        self._connected_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        # Whitelist: only queue frames addressed to us. Panel broadcasts
        # (dst=65535, src=panel) are also kept for device table updates.
        self._keep_destinations = keep_destinations
        self._panel_address = panel_address
        self._stats = {
            "frames_read": 0,
            "frames_invalid": 0,
            "frames_filtered": 0,
            "bytes_read": 0,
            "frames_written": 0,
        }

    # -- asyncio.Protocol callbacks ------------------------------------------

    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        self._transport = transport
        self._connected_event.set()
        self._disconnected_event.clear()
        logger.debug("GM3Protocol: connection made")

    def connection_lost(self, exc: Exception | None) -> None:
        self._transport = None
        self._connected_event.clear()
        self._disconnected_event.set()
        # Push sentinel so any pending receive_frame() unblocks.
        try:
            self._frame_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        logger.debug("GM3Protocol: connection lost (exc=%s)", exc)

    def data_received(self, data: bytes) -> None:
        self._rx_buffer.extend(data)
        self._stats["bytes_read"] += len(data)
        while True:
            frame = self._extract_frame()
            if frame is None:
                break
            self._stats["frames_read"] += 1
            # Only keep frames addressed to us (or panel broadcasts).
            if self._keep_destinations is not None:
                dst = frame.destination
                if (dst not in self._keep_destinations
                        and not (dst == 65535 and frame.source == self._panel_address)):
                    self._stats["frames_filtered"] += 1
                    continue
            if self._frame_queue.full():
                # Drop oldest frame to make room.
                try:
                    self._frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                self._frame_queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    # -- frame extraction (from FrameReader._extract_frame_from_buffer) ------

    def _extract_frame(self) -> Frame | None:
        while len(self._rx_buffer) >= FRAME_MIN_LEN:
            begin_idx = self._rx_buffer.find(BEGIN_FRAME)
            if begin_idx == -1:
                if self._rx_buffer:
                    logger.debug("No BEGIN marker found, discarding %d bytes", len(self._rx_buffer))
                self._rx_buffer.clear()
                return None

            if begin_idx > 0:
                logger.debug("Discarding %d bytes before BEGIN marker", begin_idx)
                del self._rx_buffer[:begin_idx]

            if len(self._rx_buffer) < 3:
                return None

            length = self._rx_buffer[1] | (self._rx_buffer[2] << 8)
            frame_length = length + 6

            if frame_length > 1024:
                logger.debug("Invalid frame length %d, discarding BEGIN marker", frame_length)
                del self._rx_buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            if len(self._rx_buffer) < frame_length:
                return None

            frame_data = bytes(self._rx_buffer[:frame_length])

            if frame_data[-1] != END_FRAME:
                logger.debug("Invalid END marker 0x%02X, discarding BEGIN marker", frame_data[-1])
                del self._rx_buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            frame = Frame.from_bytes(frame_data)
            if frame is None:
                logger.warning("Frame parse failed (CRC or validation error): %s", frame_data.hex())
                del self._rx_buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            del self._rx_buffer[:frame_length]
            return frame

        return None

    # -- public API ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._transport is not None

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def receive_frame(self, timeout: float | None = None) -> Frame | None:
        """Wait for the next parsed frame.

        Returns ``None`` on timeout or when a disconnect sentinel is received.
        """
        try:
            frame = await asyncio.wait_for(self._frame_queue.get(), timeout=timeout)
            return frame
        except TimeoutError:
            return None

    async def write_frame(
        self, frame: Frame, flush_after: bool = False, clear_echo: bool = True,
    ) -> bool:
        """Serialise *frame* onto the transport.

        Args:
            flush_after: Wait for TX to drain to wire (tcdrain) and optionally
                clear the RX buffer.
            clear_echo: When flush_after is True, also clear the RX input
                buffer after flushing.  Set to False for thermostat responses
                where the panel sends its next request immediately after
                receiving our response -- reset_input_buffer() can race with
                that next request and destroy it.

        Returns True on success, False when the transport is unavailable.
        """
        async with self._write_lock:
            if self._transport is None:
                return False

            frame_bytes = frame.to_bytes()
            self._transport.write(frame_bytes)
            self._stats["frames_written"] += 1

            if flush_after:
                serial_obj = getattr(self._transport, "serial", None)
                if serial_obj is not None:
                    try:
                        # flush() -- block until TX buffer is drained to wire
                        serial_obj.flush()
                        if clear_echo:
                            # reset_input_buffer() -- discard echo/garbage
                            # that arrived during transmission
                            serial_obj.reset_input_buffer()
                    except Exception as e:
                        logger.warning("Failed to flush serial port: %s", e)

            logger.debug("Frame written: %s (hex: %s)", frame, frame_bytes.hex())
            return True

    def reset_buffer(self) -> None:
        """Clear the receive buffer and drain any queued frames."""
        self._rx_buffer.clear()
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
