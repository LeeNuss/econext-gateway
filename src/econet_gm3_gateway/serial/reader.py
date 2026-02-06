"""Async frame reader for GM3 protocol."""

import asyncio
import logging

from econet_gm3_gateway.protocol.constants import BEGIN_FRAME, END_FRAME, FRAME_MIN_LEN
from econet_gm3_gateway.protocol.frames import Frame
from econet_gm3_gateway.serial.connection import SerialConnection

logger = logging.getLogger(__name__)


class FrameReader:
    """Async reader for GM3 protocol frames."""

    def __init__(self, connection: SerialConnection, buffer_size: int = 4096):
        """
        Initialize frame reader.

        Args:
            connection: Serial connection to read from
            buffer_size: Size of read buffer
        """
        self.connection = connection
        self.buffer_size = buffer_size
        self._buffer = bytearray()
        self._stats = {
            "frames_read": 0,
            "frames_invalid": 0,
            "bytes_read": 0,
        }

    @property
    def stats(self) -> dict:
        """Get reader statistics."""
        return self._stats.copy()

    async def read_frame(self, timeout: float | None = None) -> Frame | None:
        """
        Read a complete frame from the serial connection.

        Searches for BEGIN marker, reads until END marker, validates and parses.

        Args:
            timeout: Read timeout in seconds (None for no timeout)

        Returns:
            Parsed Frame object, or None if timeout/error

        Raises:
            ConnectionError: If connection is lost
        """
        try:
            if timeout:
                return await asyncio.wait_for(self._read_frame_internal(), timeout=timeout)
            else:
                return await self._read_frame_internal()

        except TimeoutError:
            logger.debug("Frame read timeout after %ss", timeout)
            return None
        except ConnectionError:
            logger.error("Connection lost while reading frame")
            raise

    async def _read_frame_internal(self) -> Frame | None:
        """Internal frame reading implementation."""
        while True:
            # Try to extract frame from buffer
            frame = self._extract_frame_from_buffer()
            if frame:
                return frame

            # Need more data
            try:
                chunk = await self.connection.read(self.buffer_size)
                if not chunk:
                    logger.debug("No data received from connection")
                    await asyncio.sleep(0.01)
                    continue

                self._buffer.extend(chunk)
                self._stats["bytes_read"] += len(chunk)

            except ConnectionError:
                logger.error("Connection error while reading")
                raise

    def _extract_frame_from_buffer(self) -> Frame | None:
        """
        Try to extract a complete frame from buffer.

        Returns:
            Parsed Frame if found, None otherwise
        """
        while len(self._buffer) >= FRAME_MIN_LEN:
            # Find BEGIN marker
            begin_idx = self._buffer.find(BEGIN_FRAME)
            if begin_idx == -1:
                # No BEGIN marker, discard buffer
                if self._buffer:
                    logger.debug("No BEGIN marker found, discarding %d bytes", len(self._buffer))
                self._buffer.clear()
                return None

            # Discard data before BEGIN marker
            if begin_idx > 0:
                logger.debug("Discarding %d bytes before BEGIN marker", begin_idx)
                del self._buffer[:begin_idx]

            # Check if we have enough data for length field
            if len(self._buffer) < 3:
                return None

            # Extract length
            length = self._buffer[1] | (self._buffer[2] << 8)
            frame_length = length + 6  # Total frame size

            # Check if frame length is reasonable
            if frame_length > 1024:
                logger.warning("Invalid frame length %d, discarding BEGIN marker", frame_length)
                del self._buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            # Wait for complete frame
            if len(self._buffer) < frame_length:
                return None

            # Extract frame data
            frame_data = bytes(self._buffer[:frame_length])

            # Validate END marker
            if frame_data[-1] != END_FRAME:
                logger.warning(f"Invalid END marker {frame_data[-1]}, discarding BEGIN marker")
                del self._buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            # Try to parse frame
            frame = Frame.from_bytes(frame_data)
            if frame is None:
                logger.warning("Frame parse failed (CRC or validation error): %s", frame_data.hex())
                del self._buffer[0]
                self._stats["frames_invalid"] += 1
                continue

            # Log SERVICE frames to address 131 specially
            if frame.command == 0x68 and frame.destination == 131:
                logger.debug("SERVICE to 131: %s", frame_data.hex())

            # Success! Remove frame from buffer
            del self._buffer[:frame_length]
            self._stats["frames_read"] += 1
            # logger.debug("Frame read: %s", frame)
            return frame

    def reset_buffer(self) -> None:
        """Clear the read buffer."""
        self._buffer.clear()

    def reset_stats(self) -> None:
        """Reset reader statistics."""
        self._stats = {
            "frames_read": 0,
            "frames_invalid": 0,
            "bytes_read": 0,
        }
