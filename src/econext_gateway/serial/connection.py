"""Serial port connection management using direct pyserial.

Note: serial_asyncio doesn't work reliably with CP210x USB-serial adapters.
It produces constant "device reports readiness to read but returned no data"
errors and misses most bus traffic. Using direct pyserial with run_in_executor()
instead.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import serial
from serial import SerialException

logger = logging.getLogger(__name__)


class SerialConnection:
    """Manages serial port connection with automatic reconnection.

    Uses direct pyserial with asyncio.run_in_executor() for async compatibility.
    This approach works reliably with CP210x USB-serial adapters, unlike serial_asyncio.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 0.2,  # Match original webserver's PORT_TIMEOUT
        reconnect_delay: float = 5.0,
    ):
        """
        Initialize serial connection manager.

        Args:
            port: Serial port path (e.g., '/dev/ttyUSB1')
            baudrate: Communication speed (default: 115200)
            timeout: Read/write timeout in seconds (default: 0.2 matches original)
            reconnect_delay: Delay between reconnection attempts in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay

        self._serial: serial.Serial | None = None
        self._connected = False
        self._reconnect_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="serial")

    @property
    def connected(self) -> bool:
        """Check if currently connected."""
        return self._connected and self._serial is not None and self._serial.is_open

    def _baud_toggle_reset(self) -> None:
        """Perform baud rate toggle to reset RS-485 transceiver.

        The original ecoNET300 webserver does this sequence at startup:
        1. Open at 9600 baud
        2. Close
        3. Open at target baud rate

        This may help synchronize with the panel or reset the RS-485 state.
        """
        try:
            logger.debug("Performing baud toggle reset on %s", self.port)
            temp_port = serial.Serial()
            temp_port.port = self.port
            temp_port.baudrate = 9600
            temp_port.timeout = 0.1
            temp_port.open()
            temp_port.close()
            logger.debug("Baud toggle reset completed")
        except (OSError, SerialException) as e:
            logger.warning("Baud toggle reset failed (non-fatal): %s", e)

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
                # Perform baud toggle reset (matches original webserver behavior)
                self._baud_toggle_reset()

                logger.info("Connecting to serial port %s at %d baud", self.port, self.baudrate)

                self._serial = serial.Serial()
                self._serial.port = self.port
                self._serial.baudrate = self.baudrate
                self._serial.timeout = self.timeout
                self._serial.open()

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

            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                except Exception as e:
                    logger.error("Error closing serial port: %s", e)

            self._serial = None
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

    def _blocking_read(self, n: int) -> bytes:
        """Blocking read for use with run_in_executor.

        Uses a two-stage approach for fast reads:
        1. Wait for first byte (blocks up to self.timeout = 0.2s)
        2. Read all remaining bytes already in the OS buffer

        This avoids the problem where serial.read(4096) always waits
        the full 0.2s timeout even after a complete 500-byte response,
        because it keeps blocking trying to read 4096 bytes.

        With this approach, a 500-byte response returns in ~50ms
        (controller processing time) instead of always hitting 200ms.
        """
        if not self._serial or not self._serial.is_open:
            raise ConnectionError("Not connected to serial port")
        try:
            # Stage 1: Wait for first byte (up to timeout)
            first = self._serial.read(1)
            if not first:
                return b""  # Timeout - no data available

            # Stage 2: Read all bytes already buffered in the OS
            available = self._serial.in_waiting
            if available > 0:
                rest = self._serial.read(available)
                return first + rest

            return first
        except (OSError, SerialException) as e:
            error_str = str(e)
            # "device reports readiness to read but returned no data" is transient
            if "reports readiness" in error_str or "multiple access" in error_str:
                return b""
            raise

    async def read(self, n: int = -1) -> bytes:
        """
        Read from serial port.

        Args:
            n: Number of bytes to read (-1 for available data up to 4096)

        Returns:
            Bytes read from serial port

        Raises:
            ConnectionError: If not connected
        """
        if not self.connected or not self._serial:
            raise ConnectionError("Not connected to serial port")

        try:
            read_size = 4096 if n == -1 else n
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(self._executor, self._blocking_read, read_size)
            return data

        except (OSError, SerialException) as e:
            error_str = str(e)
            if "reports readiness" in error_str or "multiple access" in error_str:
                logger.warning("Transient serial error (will retry): %s", e)
                return b""
            logger.error("Read error: %s", e)
            self._connected = False
            raise ConnectionError(str(e)) from e

    async def write(self, data: bytes, flush_after: bool = False) -> None:
        """
        Write to serial port.

        Args:
            data: Bytes to write
            flush_after: If True, flush input/output buffers after write

        Raises:
            ConnectionError: If not connected
        """
        if not self.connected or not self._serial:
            raise ConnectionError("Not connected to serial port")

        try:
            self._serial.write(data)

            if flush_after:
                self._flush_serial()

        except Exception as e:
            logger.error("Write error: %s", e)
            self._connected = False
            raise

    def _flush_serial(self) -> None:
        """Flush underlying serial port buffers (input and output).

        The original webserver does:
        1. self.port.flushInput()  - clear any garbage in RX buffer
        2. self.port.flush()       - wait for TX buffer to empty

        This ensures the response is fully transmitted before we
        start listening for the next frame.
        """
        try:
            if self._serial and self._serial.is_open:
                self._serial.reset_input_buffer()  # Clear RX buffer
                self._serial.flush()  # Wait for TX complete
                logger.debug("Serial port flushed (RX cleared, TX complete)")
        except Exception as e:
            logger.warning("Failed to flush serial port: %s", e)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
