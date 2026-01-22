"""Async frame writer for GM3 protocol."""

import asyncio
import logging

from ..protocol.frames import Frame
from .connection import SerialConnection

logger = logging.getLogger(__name__)


class FrameWriter:
    """Async writer for GM3 protocol frames with retry logic."""

    def __init__(
        self,
        connection: SerialConnection,
        max_retries: int = 3,
        retry_delay: float = 0.1,
    ):
        """
        Initialize frame writer.

        Args:
            connection: Serial connection to write to
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.connection = connection
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._lock = asyncio.Lock()
        self._stats = {
            "frames_written": 0,
            "frames_failed": 0,
            "bytes_written": 0,
            "retries": 0,
        }

    @property
    def stats(self) -> dict:
        """Get writer statistics."""
        return self._stats.copy()

    async def write_frame(self, frame: Frame, timeout: float | None = None) -> bool:
        """
        Write a frame to the serial connection with retry logic.

        Args:
            frame: Frame to write
            timeout: Write timeout in seconds (None for no timeout)

        Returns:
            True if write successful, False otherwise

        Raises:
            ConnectionError: If connection is lost
        """
        async with self._lock:
            frame_bytes = frame.to_bytes()

            for attempt in range(1, self.max_retries + 1):
                try:
                    if timeout:
                        await asyncio.wait_for(self.connection.write(frame_bytes), timeout=timeout)
                    else:
                        await self.connection.write(frame_bytes)

                    self._stats["frames_written"] += 1
                    self._stats["bytes_written"] += len(frame_bytes)

                    if attempt > 1:
                        self._stats["retries"] += attempt - 1
                        logger.info("Frame write succeeded on attempt %d", attempt)

                    logger.debug("Frame written: %s", frame)
                    return True

                except TimeoutError:
                    logger.warning("Frame write timeout on attempt %d/%d", attempt, self.max_retries)
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay)
                    else:
                        self._stats["frames_failed"] += 1
                        return False

                except ConnectionError as e:
                    logger.error("Connection error during write: %s", e)
                    self._stats["frames_failed"] += 1
                    raise

                except Exception as e:
                    logger.error("Unexpected error during write: %s", e)
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay)
                    else:
                        self._stats["frames_failed"] += 1
                        return False

            return False

    async def write_frames(self, frames: list[Frame], timeout: float | None = None) -> int:
        """
        Write multiple frames sequentially.

        Args:
            frames: List of frames to write
            timeout: Write timeout per frame in seconds

        Returns:
            Number of frames successfully written

        Raises:
            ConnectionError: If connection is lost
        """
        written = 0
        for frame in frames:
            if await self.write_frame(frame, timeout):
                written += 1
            else:
                logger.warning("Failed to write frame %d/%d", written + 1, len(frames))
                break

        return written

    def reset_stats(self) -> None:
        """Reset writer statistics."""
        self._stats = {
            "frames_written": 0,
            "frames_failed": 0,
            "bytes_written": 0,
            "retries": 0,
        }
