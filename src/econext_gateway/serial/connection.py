"""Serial transport layer using serial_asyncio and GM3Protocol."""

import asyncio
import logging

import serial
from serial import SerialException

from econext_gateway.serial.protocol import GM3Protocol

logger = logging.getLogger(__name__)


class GM3SerialTransport:
    """Manages the serial connection lifecycle and reconnection.

    Uses ``serial_asyncio.create_serial_connection()`` to wire an
    event-loop-driven :class:`GM3Protocol` to the physical port.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        reconnect_delay: float = 5.0,
    ):
        self.port = port
        self.baudrate = baudrate
        self.reconnect_delay = reconnect_delay

        self._protocol: GM3Protocol | None = None
        self._transport: asyncio.Transport | None = None
        self._reconnect_task: asyncio.Task | None = None

    @property
    def protocol(self) -> GM3Protocol:
        """Return the current protocol instance.

        Raises RuntimeError if not connected.
        """
        if self._protocol is None:
            raise RuntimeError("Not connected")
        return self._protocol

    @property
    def connected(self) -> bool:
        return self._protocol is not None and self._protocol.connected

    # -- baud toggle (unchanged from original) --------------------------------

    def _baud_toggle_reset(self) -> None:
        """Perform baud rate toggle to reset RS-485 transceiver.

        The original ecoNET300 webserver does this sequence at startup:
        1. Open at 9600 baud
        2. Close
        3. Open at target baud rate
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

    # -- connect / disconnect -------------------------------------------------

    async def connect(self) -> bool:
        if self.connected:
            logger.debug("Already connected to %s", self.port)
            return True

        try:
            self._baud_toggle_reset()

            logger.info("Connecting to serial port %s at %d baud", self.port, self.baudrate)

            import serial_asyncio

            loop = asyncio.get_running_loop()
            transport, protocol = await serial_asyncio.create_serial_connection(
                loop,
                GM3Protocol,
                self.port,
                baudrate=self.baudrate,
            )
            self._transport = transport
            self._protocol = protocol

            logger.info("Successfully connected to %s", self.port)
            return True

        except (OSError, SerialException) as e:
            logger.error("Failed to connect to %s: %s", self.port, e)
            self._transport = None
            self._protocol = None
            return False

    async def disconnect(self) -> None:
        if self._transport is not None:
            logger.info("Disconnecting from %s", self.port)
            try:
                self._transport.close()
            except Exception as e:
                logger.error("Error closing serial transport: %s", e)
            self._transport = None
            self._protocol = None
            logger.info("Disconnected from %s", self.port)

    async def reconnect(self) -> bool:
        await self.disconnect()
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()

    # -- reconnect loop -------------------------------------------------------

    async def start_reconnect_loop(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            logger.warning("Reconnect loop already running")
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop_reconnect_loop(self) -> None:
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

    async def _reconnect_loop(self) -> None:
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

    # -- context manager ------------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
