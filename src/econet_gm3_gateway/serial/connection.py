"""Serial port connection management."""

import asyncio
import logging

import serial_asyncio
from serial import SerialException

logger = logging.getLogger(__name__)


class SerialConnection:
    """Manages serial port connection with automatic reconnection."""

    def __init__(
        self,
        port: str,
        baudrate: int = 19200,
        timeout: float = 1.0,
        reconnect_delay: float = 5.0,
    ):
        """
        Initialize serial connection manager.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0')
            baudrate: Communication speed (default: 19200)
            timeout: Read/write timeout in seconds
            reconnect_delay: Delay between reconnection attempts in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._reconnect_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Check if currently connected."""
        return self._connected and self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> bool:
        """
        Open serial port connection.

        Returns:
            True if connection successful, False otherwise
        """
        async with self._lock:
            if self.connected:
                logger.debug("Already connected to %s", self.port)
                return True

            try:
                logger.info("Connecting to serial port %s at %d baud", self.port, self.baudrate)

                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                )

                self._connected = True
                logger.info("Successfully connected to %s", self.port)
                return True

            except (OSError, SerialException) as e:
                logger.error("Failed to connect to %s: %s", self.port, e)
                self._connected = False
                return False

    async def disconnect(self) -> None:
        """Close serial port connection."""
        async with self._lock:
            if not self._connected:
                return

            logger.info("Disconnecting from %s", self.port)

            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception as e:
                    logger.error("Error closing writer: %s", e)

            self._reader = None
            self._writer = None
            self._connected = False
            logger.info("Disconnected from %s", self.port)

    async def reconnect(self) -> bool:
        """
        Reconnect to serial port.

        Returns:
            True if reconnection successful, False otherwise
        """
        await self.disconnect()
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()

    async def start_reconnect_loop(self) -> None:
        """
        Start automatic reconnection loop.

        Continuously attempts to reconnect if connection is lost.
        """
        if self._reconnect_task and not self._reconnect_task.done():
            logger.warning("Reconnect loop already running")
            return

        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop_reconnect_loop(self) -> None:
        """Stop automatic reconnection loop."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

    async def _reconnect_loop(self) -> None:
        """Internal reconnection loop."""
        while True:
            try:
                if not self.connected:
                    logger.info("Connection lost, attempting to reconnect...")
                    success = await self.reconnect()
                    if success:
                        logger.info("Reconnection successful")
                    else:
                        logger.warning("Reconnection failed, will retry in %ss", self.reconnect_delay)

                await asyncio.sleep(self.reconnect_delay)

            except asyncio.CancelledError:
                logger.info("Reconnect loop cancelled")
                break
            except Exception as e:
                logger.error("Error in reconnect loop: %s", e)
                await asyncio.sleep(self.reconnect_delay)

    async def read(self, n: int = -1) -> bytes:
        """
        Read from serial port.

        Args:
            n: Number of bytes to read (-1 for all available)

        Returns:
            Bytes read from serial port

        Raises:
            ConnectionError: If not connected
            asyncio.TimeoutError: If read times out
        """
        if not self.connected or not self._reader:
            raise ConnectionError("Not connected to serial port")

        try:
            if n == -1:
                data = await asyncio.wait_for(self._reader.read(8192), timeout=self.timeout)
            else:
                data = await asyncio.wait_for(self._reader.readexactly(n), timeout=self.timeout)
            return data

        except asyncio.IncompleteReadError as e:
            logger.error("Incomplete read: got %d bytes, expected %d", len(e.partial), n)
            raise
        except TimeoutError:
            logger.debug("Read timeout after %ss", self.timeout)
            raise
        except Exception as e:
            logger.error("Read error: %s", e)
            self._connected = False
            raise

    async def write(self, data: bytes) -> None:
        """
        Write to serial port.

        Args:
            data: Bytes to write

        Raises:
            ConnectionError: If not connected
        """
        if not self.connected or not self._writer:
            raise ConnectionError("Not connected to serial port")

        try:
            self._writer.write(data)
            await self._writer.drain()

        except Exception as e:
            logger.error("Write error: %s", e)
            self._connected = False
            raise

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
