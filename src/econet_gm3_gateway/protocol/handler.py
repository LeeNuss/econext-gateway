"""Protocol handler for GM3 serial communication.

Orchestrates serial communication, request/response correlation,
parameter reading/writing, and cache management.
"""

import asyncio
import logging
import struct
from collections.abc import Callable
from typing import Any

from econet_gm3_gateway.core.cache import ParameterCache
from econet_gm3_gateway.core.models import Parameter
from econet_gm3_gateway.protocol.codec import decode_value, encode_value
from econet_gm3_gateway.protocol.constants import (
    DEST_ADDRESSES,
    POLL_INTERVAL,
    REQUEST_TIMEOUT,
    TYPE_SIZES,
    Command,
    DataType,
)
from econet_gm3_gateway.protocol.frames import Frame
from econet_gm3_gateway.serial.connection import SerialConnection
from econet_gm3_gateway.serial.reader import FrameReader
from econet_gm3_gateway.serial.writer import FrameWriter

logger = logging.getLogger(__name__)


class ParamStructEntry:
    """Metadata for a single parameter from struct response."""

    def __init__(
        self,
        index: int,
        name: str,
        unit: int,
        type_code: int,
        writable: bool,
        min_value: float | None = None,
        max_value: float | None = None,
    ):
        self.index = index
        self.name = name
        self.unit = unit
        self.type_code = type_code
        self.writable = writable
        self.min_value = min_value
        self.max_value = max_value


# Unit string to code mapping
UNIT_STRING_MAP = {
    "": 0,
    "C": 1,
    "s": 2,
    "min": 3,
    "h": 4,
    "d": 5,
    "%": 6,
    "kW": 7,
    "kWh": 8,
}


def parse_get_params_request(data: bytes) -> tuple[int, int]:
    """Parse a GET_PARAMS request payload.

    Args:
        data: Request payload bytes.

    Returns:
        Tuple of (count, start_index).

    Raises:
        ValueError: If data is too short.
    """
    if len(data) < 3:
        raise ValueError(f"GET_PARAMS request too short: {len(data)} bytes")

    count = data[0]
    start_index = struct.unpack("<H", data[1:3])[0]
    return count, start_index


def parse_get_params_response(data: bytes, param_structs: dict[int, ParamStructEntry]) -> list[tuple[int, Any]]:
    """Parse a GET_PARAMS_RESPONSE payload.

    Response format:
    - data[0]: paramsNo (number of parameters)
    - data[1:3]: firstParamIndex (LE uint16)
    - data[3]: separator byte (skipped)
    - data[4:]: parameter values, each followed by a 1-byte separator

    Args:
        data: Response payload bytes.
        param_structs: Known parameter structure indexed by param index.

    Returns:
        List of (index, decoded_value) tuples.

    Raises:
        ValueError: If response is malformed.
    """
    if len(data) < 3:
        raise ValueError(f"GET_PARAMS_RESPONSE too short: {len(data)} bytes")

    params_no = data[0]
    first_index = struct.unpack("<H", data[1:3])[0]

    results = []
    offset = 4  # Skip header (3 bytes) + first separator byte

    for i in range(params_no):
        param_index = first_index + i

        if param_index not in param_structs:
            break

        entry = param_structs[param_index]
        type_code = entry.type_code

        if type_code == DataType.STRING:
            # Find null terminator for string
            null_pos = data.find(b"\x00", offset)
            if null_pos == -1:
                break
            value_bytes = data[offset : null_pos + 1]
            value_len = len(value_bytes)
        else:
            value_len = TYPE_SIZES.get(type_code, 0)
            if value_len == 0:
                break
            if offset + value_len > len(data):
                break
            value_bytes = data[offset : offset + value_len]

        try:
            decoded = decode_value(value_bytes, type_code)
            results.append((param_index, decoded))
        except (ValueError, struct.error) as e:
            logger.warning(f"Failed to decode param {param_index}: {e}")
            break

        offset += value_len + 1  # +1 to skip separator byte after value

    return results


def parse_struct_response(data: bytes) -> list[ParamStructEntry]:
    """Parse a GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE payload.

    Response format:
    - data[0]: paramsNo (number of parameters)
    - data[1:3]: firstParamIndex (LE uint16)
    - For each parameter:
      - null-terminated name string
      - null-terminated unit string
      - type byte (low 4 bits = type, bit 5 = writable)
      - extra byte (range flags)
      - 4 bytes range data (min/max as int16)

    Args:
        data: Response payload bytes.

    Returns:
        List of ParamStructEntry instances.
    """
    if len(data) < 3:
        raise ValueError(f"Struct response too short: {len(data)} bytes")

    params_no = data[0]
    first_index = struct.unpack("<H", data[1:3])[0]

    entries = []
    offset = 3

    for i in range(params_no):
        if offset >= len(data):
            break

        # Read name (null-terminated)
        null_pos = data.find(b"\x00", offset)
        if null_pos == -1:
            break
        name = data[offset:null_pos].decode("utf-8", errors="replace")
        offset = null_pos + 1

        # Read unit string (null-terminated)
        null_pos = data.find(b"\x00", offset)
        if null_pos == -1:
            break
        unit_str = data[offset:null_pos].decode("utf-8", errors="replace")
        offset = null_pos + 1

        # Read type and extra bytes
        if offset + 2 > len(data):
            break
        type_byte = data[offset]
        extra_byte = data[offset + 1]
        offset += 2

        type_code = type_byte & 0x0F
        writable = bool(type_byte & 0x20)

        # Parse range (4 bytes)
        min_value = None
        max_value = None

        if offset + 4 > len(data):
            break

        # Min value
        if extra_byte & 0x10:
            # Original min value (unsigned)
            min_value = float(struct.unpack("<H", data[offset : offset + 2])[0])
        elif not (extra_byte & 0x40):
            # Regular min value
            if type_code in (DataType.UINT8, DataType.UINT16, DataType.UINT32):
                min_value = float(struct.unpack("<H", data[offset : offset + 2])[0])
            else:
                min_value = float(struct.unpack("<h", data[offset : offset + 2])[0])

        # Max value
        if extra_byte & 0x20:
            max_value = float(struct.unpack("<H", data[offset + 2 : offset + 4])[0])
        elif not (extra_byte & 0x80):
            if type_code in (DataType.UINT8, DataType.UINT16, DataType.UINT32):
                max_value = float(struct.unpack("<H", data[offset + 2 : offset + 4])[0])
            else:
                max_value = float(struct.unpack("<h", data[offset + 2 : offset + 4])[0])

        offset += 4

        # Map unit string to code
        unit_code = UNIT_STRING_MAP.get(unit_str, 0)

        # Sanitize name: replace spaces
        name = name.replace(" ", "_").strip()

        param_index = first_index + i
        entries.append(
            ParamStructEntry(
                index=param_index,
                name=name,
                unit=unit_code,
                type_code=type_code,
                writable=writable,
                min_value=min_value,
                max_value=max_value,
            )
        )

    return entries


def build_get_params_request(start_index: int, count: int) -> bytes:
    """Build GET_PARAMS request payload.

    Args:
        start_index: Starting parameter index.
        count: Number of parameters to read.

    Returns:
        Request payload bytes.
    """
    return struct.pack("<BH", count, start_index)


def build_struct_request(start_index: int, count: int) -> bytes:
    """Build GET_PARAMS_STRUCT_WITH_RANGE request payload.

    Args:
        start_index: Starting parameter index.
        count: Number of parameters to request.

    Returns:
        Request payload bytes.
    """
    return struct.pack("<BH", count, start_index)


def build_modify_param_request(index: int, value: Any, type_code: int) -> bytes:
    """Build MODIFY_PARAM request payload.

    Args:
        index: Parameter index to modify.
        value: New value.
        type_code: Data type code for encoding.

    Returns:
        Request payload bytes.
    """
    index_bytes = struct.pack("<H", index)
    value_bytes = encode_value(value, type_code)
    return index_bytes + value_bytes


class ProtocolHandler:
    """Orchestrates GM3 serial protocol communication.

    Handles request/response correlation, parameter reading/writing,
    and background polling with cache management.
    """

    def __init__(
        self,
        connection: SerialConnection,
        cache: ParameterCache,
        destination: int = DEST_ADDRESSES[0],
        poll_interval: float = POLL_INTERVAL,
        request_timeout: float = REQUEST_TIMEOUT,
        params_per_request: int = 50,
    ):
        """Initialize protocol handler.

        Args:
            connection: Serial connection to use.
            cache: Parameter cache to update.
            destination: Controller address to communicate with.
            poll_interval: Seconds between poll cycles.
            request_timeout: Timeout for individual requests.
            params_per_request: Number of params per GET_PARAMS request.
        """
        self._connection = connection
        self._cache = cache
        self._destination = destination
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout
        self._params_per_request = params_per_request

        self._reader = FrameReader(connection)
        self._writer = FrameWriter(connection)

        self._param_structs: dict[int, ParamStructEntry] = {}
        self._total_params: int = 0
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Whether the serial connection is active."""
        return self._connection.connected

    @property
    def param_count(self) -> int:
        """Number of known parameter structures."""
        return len(self._param_structs)

    @property
    def running(self) -> bool:
        """Whether background polling is active."""
        return self._running

    async def start(self) -> None:
        """Start background polling task."""
        if self._running:
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Protocol handler started")

    async def stop(self) -> None:
        """Stop background polling task."""
        self._running = False

        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        logger.info("Protocol handler stopped")

    async def send_and_receive(
        self,
        command: int,
        data: bytes = b"",
        expected_response: int | None = None,
        response_validator: Callable[[Frame], bool] | None = None,
    ) -> Frame | None:
        """Send a frame and wait for response.

        Skips frames from unexpected sources, wrong commands, or that
        fail the response_validator (e.g., responses to other devices
        on the bus). Keeps reading frames until either a match is found,
        the bus goes silent (per-read timeout), or the total request
        timeout is exceeded.

        Args:
            command: Command code to send.
            data: Request payload.
            expected_response: Expected response command code.
            response_validator: Optional callable to validate response data.
                If provided and returns False, the frame is skipped.

        Returns:
            Response frame, or None on timeout.
        """
        async with self._lock:
            request = Frame(destination=self._destination, command=command, data=data)

            success = await self._writer.write_frame(request, timeout=self._request_timeout)
            if not success:
                logger.warning(f"Failed to send command 0x{command:02X}")
                return None

            if expected_response is None:
                return None

            loop = asyncio.get_event_loop()
            deadline = loop.time() + self._request_timeout
            skipped = 0

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break

                # Use shorter per-read timeout: wait up to 0.5s for next frame,
                # but never exceed the total deadline
                read_timeout = min(remaining, 0.5)
                response = await self._reader.read_frame(timeout=read_timeout)

                if response is None:
                    logger.warning(f"Timeout waiting for response to 0x{command:02X}")
                    return None

                # Skip frames not from our target device
                if response.source != self._destination:
                    logger.debug(
                        f"Skipping frame from src={response.source} "
                        f"(expected src={self._destination}), cmd=0x{response.command:02X}"
                    )
                    skipped += 1
                    continue

                # Skip responses to other devices' requests
                if response.command != expected_response:
                    logger.debug(
                        f"Skipping frame with cmd=0x{response.command:02X} "
                        f"(expected 0x{expected_response:02X})"
                    )
                    skipped += 1
                    continue

                # Validate response payload if validator provided
                if response_validator is not None and not response_validator(response):
                    logger.debug(
                        f"Response validator rejected frame cmd=0x{response.command:02X}, "
                        f"first bytes: {response.data[:6].hex() if response.data else 'empty'}"
                    )
                    skipped += 1
                    continue

                if skipped > 0:
                    logger.debug(f"Found matching response after skipping {skipped} frames")
                return response

            logger.warning(
                f"No matching response within {self._request_timeout}s for 0x{command:02X} "
                f"(skipped {skipped} frames)"
            )
            return None

    async def fetch_param_structs(self, start_index: int = 0, count: int = 50) -> list[ParamStructEntry]:
        """Fetch parameter structure/metadata from controller.

        Args:
            start_index: Starting parameter index.
            count: Number of parameters to request.

        Returns:
            List of parameter structure entries.
        """
        data = build_struct_request(start_index, count)

        def validate_first_index(frame: Frame) -> bool:
            if len(frame.data) < 3:
                return False
            first_index = struct.unpack("<H", frame.data[1:3])[0]
            return first_index == start_index

        response = await self.send_and_receive(
            Command.GET_PARAMS_STRUCT_WITH_RANGE,
            data,
            expected_response=Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE,
            response_validator=validate_first_index,
        )

        if response is None:
            return []

        entries = parse_struct_response(response.data)

        for entry in entries:
            self._param_structs[entry.index] = entry

        logger.debug(f"Fetched {len(entries)} param structs starting at index {start_index}")
        return entries

    async def fetch_param_values(self, start_index: int, count: int) -> list[tuple[int, Any]]:
        """Fetch parameter values from controller.

        Args:
            start_index: Starting parameter index.
            count: Number of parameters to read.

        Returns:
            List of (index, value) tuples.
        """
        data = build_get_params_request(start_index, count)

        def validate_first_index(frame: Frame) -> bool:
            if len(frame.data) < 3:
                return False
            first_index = struct.unpack("<H", frame.data[1:3])[0]
            return first_index == start_index

        response = await self.send_and_receive(
            Command.GET_PARAMS,
            data,
            expected_response=Command.GET_PARAMS_RESPONSE,
            response_validator=validate_first_index,
        )

        if response is None:
            return []

        results = parse_get_params_response(response.data, self._param_structs)
        logger.debug(f"Fetched {len(results)} param values starting at index {start_index}")
        return results

    async def read_params(self, start_index: int, count: int) -> list[Parameter]:
        """Read parameters and update cache.

        Fetches values from controller, creates Parameter objects,
        and updates the cache.

        Args:
            start_index: Starting parameter index.
            count: Number of parameters to read.

        Returns:
            List of Parameter objects with current values.
        """
        values = await self.fetch_param_values(start_index, count)
        parameters = []

        for index, value in values:
            entry = self._param_structs.get(index)
            if entry is None or not entry.name:
                continue

            param = Parameter(
                index=index,
                name=entry.name,
                value=value,
                type=entry.type_code,
                unit=entry.unit,
                writable=entry.writable,
                min_value=entry.min_value,
                max_value=entry.max_value,
            )
            parameters.append(param)

        if parameters:
            await self._cache.set_many(parameters)

        return parameters

    async def write_param(self, name: str, value: Any) -> bool:
        """Write a parameter value to the controller.

        Args:
            name: Parameter name to modify.
            value: New value to set.

        Returns:
            True if write was acknowledged, False otherwise.

        Raises:
            ValueError: If parameter not found or not writable.
        """
        param = await self._cache.get(name)
        if param is None:
            raise ValueError(f"Parameter not found: {name}")

        entry = self._param_structs.get(param.index)
        if entry is None:
            raise ValueError(f"No structure info for parameter: {name}")

        if not entry.writable:
            raise ValueError(f"Parameter is read-only: {name}")

        if entry.min_value is not None and float(value) < entry.min_value:
            raise ValueError(f"Value {value} below minimum {entry.min_value} for {name}")

        if entry.max_value is not None and float(value) > entry.max_value:
            raise ValueError(f"Value {value} above maximum {entry.max_value} for {name}")

        data = build_modify_param_request(param.index, value, entry.type_code)
        response = await self.send_and_receive(
            Command.MODIFY_PARAM,
            data,
            expected_response=Command.MODIFY_PARAM_RESPONSE,
        )

        if response is not None:
            # Update cache with new value
            updated_param = param.model_copy(update={"value": value})
            await self._cache.set(updated_param)
            logger.info(f"Parameter {name} set to {value}")
            return True

        logger.warning(f"Failed to write parameter {name}")
        return False

    async def discover_params(self, max_params: int = 2000) -> int:
        """Discover all parameters by fetching structures.

        Sends GET_PARAMS_STRUCT_WITH_RANGE requests until no more
        parameters are returned. Only replaces existing structures
        if discovery succeeds (at least one param found).

        Args:
            max_params: Maximum number of parameters to discover.

        Returns:
            Total number of parameters discovered.
        """
        new_structs: dict[int, ParamStructEntry] = {}
        index = 0
        batch_size = 255  # Protocol max (count is uint8), get all in fewest requests

        while index < max_params:
            entries = await self.fetch_param_structs(index, batch_size)
            if not entries:
                break
            for entry in entries:
                new_structs[entry.index] = entry
            index = entries[-1].index + 1

        if new_structs:
            self._param_structs = new_structs
            self._total_params = len(self._param_structs)
            logger.info(f"Discovered {self._total_params} parameters")
        else:
            logger.warning("Parameter discovery returned no results, keeping existing structures")

        return len(self._param_structs)

    async def poll_all_params(self) -> int:
        """Poll all known parameters and update cache.

        Reads parameters in batches, advancing based on the actual
        number of values returned by the controller (which may be
        less than requested).

        Returns:
            Number of parameters successfully read.
        """
        if not self._param_structs:
            return 0

        indices = sorted(self._param_structs.keys())
        total_read = 0

        current_pos = 0
        while current_pos < len(indices):
            start_index = indices[current_pos]

            # Request up to params_per_request indices
            batch_end = min(current_pos + self._params_per_request, len(indices))
            count = indices[batch_end - 1] - start_index + 1

            values = await self.fetch_param_values(start_index, count)

            if not values:
                # No response, skip to next batch
                current_pos = batch_end
                continue

            # Build Parameter objects and update cache
            parameters = []
            for index, value in values:
                entry = self._param_structs.get(index)
                if entry is None or not entry.name:
                    continue
                param = Parameter(
                    index=index,
                    name=entry.name,
                    value=value,
                    type=entry.type_code,
                    unit=entry.unit,
                    writable=entry.writable,
                    min_value=entry.min_value,
                    max_value=entry.max_value,
                )
                parameters.append(param)

            if parameters:
                await self._cache.set_many(parameters)
                total_read += len(parameters)

            # Advance past the last index actually returned by controller
            last_returned_index = values[-1][0]
            new_pos = current_pos
            while new_pos < len(indices) and indices[new_pos] <= last_returned_index:
                new_pos += 1

            # Always advance at least to batch_end to prevent infinite loops
            current_pos = max(new_pos, current_pos + 1)

        return total_read

    async def _poll_loop(self) -> None:
        """Background polling loop with reconnection support."""
        consecutive_errors = 0
        was_connected = self.connected

        while self._running:
            try:
                if not self.connected:
                    if was_connected:
                        logger.warning("Connection lost, waiting for reconnection...")
                        was_connected = False
                    await asyncio.sleep(self._poll_interval)
                    continue

                if not was_connected:
                    logger.info("Connection restored, re-discovering parameters...")
                    was_connected = True
                    await self.discover_params()

                # Discover params on first poll if needed
                if not self._param_structs:
                    await self.discover_params()

                await self.poll_all_params()
                consecutive_errors = 0

            except asyncio.CancelledError:
                raise
            except ConnectionError:
                consecutive_errors += 1
                if consecutive_errors <= 3:
                    logger.warning("Connection error during poll, will retry")
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 3:
                    logger.error(f"Poll error: {e}")

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise
