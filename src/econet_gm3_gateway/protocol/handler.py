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
    GET_TOKEN_FUNC,
    GIVE_BACK_TOKEN_DATA,
    IDENTIFY_ANS_CMD,
    IDENTIFY_CMD,
    IDENTIFY_RESPONSE_DATA,
    PANEL_ADDRESS,
    POLL_INTERVAL,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    SERVICE_CMD,
    SRC_ADDRESS,
    TOKEN_TIMEOUT,
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


def parse_struct_response_no_range(data: bytes) -> list[ParamStructEntry]:
    """Parse a GET_PARAMS_STRUCT_RESPONSE payload (WITHOUT range data).

    Used for panel parameters (command 0x01/0x81). Format differs from
    WITH_RANGE: instead of (type_byte, extra_byte, 4-byte range), it has
    (exponent_byte, type_byte) with no range data.

    Args:
        data: Response payload bytes.

    Returns:
        List of ParamStructEntry instances (min/max always None).
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

        # Read exponent and type bytes (WITHOUT_RANGE format)
        if offset + 2 > len(data):
            break
        _exp, type_byte = struct.unpack("<bB", data[offset : offset + 2])
        offset += 2

        type_code = type_byte & 0x0F
        writable = bool(type_byte & 0x20)

        # No range data in WITHOUT_RANGE format

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
        token_timeout: float = TOKEN_TIMEOUT,
        token_required: bool = True,
    ):
        """Initialize protocol handler.

        Args:
            connection: Serial connection to use.
            cache: Parameter cache to update.
            destination: Controller address to communicate with.
            poll_interval: Seconds between poll cycles.
            request_timeout: Timeout for individual requests.
            params_per_request: Number of params per GET_PARAMS request.
            token_timeout: Seconds to wait for token before fallback.
            token_required: If True, wait indefinitely for token (like original).
                If False, use token_timeout as maximum wait time.
        """
        self._connection = connection
        self._cache = cache
        self._destination = destination
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout
        self._params_per_request = params_per_request
        self._token_timeout = token_timeout
        self._token_required = token_required

        self._reader = FrameReader(connection)
        self._writer = FrameWriter(connection)

        self._param_structs: dict[int, ParamStructEntry] = {}
        self._total_params: int = 0
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self._has_token = False

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

    async def _handle_panel_frame(self, frame: Frame) -> None:
        """Handle frames from the master panel (device 100).

        Responds to IDENTIFY_DEV probes (registering on the bus) and
        detects SERVICE/GET_TOKEN grants (exclusive bus access).

        Args:
            frame: Frame from the panel addressed to us.
        """
        if frame.command == IDENTIFY_CMD:
            # Panel is asking "who are you?" - respond with device identity
            # 20ms delay for RS-485 bus turnaround (matches original webserver)
            await asyncio.sleep(0.02)
            response = Frame(
                destination=PANEL_ADDRESS,
                command=IDENTIFY_ANS_CMD,
                data=IDENTIFY_RESPONSE_DATA,
            )
            # flush_after=True ensures proper RS-485 handling:
            # 1. Clears RX buffer (flushInput) to discard any garbage during turnaround
            # 2. Waits for TX buffer to empty (flush) to ensure data is fully transmitted
            # This matches the original webserver's clearFrameBuffer() + flush() sequence
            await self._writer.write_frame(response, flush_after=True)
            logger.info("Responded to IDENTIFY from panel")

        elif frame.command == SERVICE_CMD:
            # Log all SERVICE frames for debugging
            func_code = 0
            if len(frame.data) >= 2:
                func_code = struct.unpack("<H", frame.data[0:2])[0]
            logger.info(
                "SERVICE frame: dest=%d, func=0x%04X, data=%s", frame.destination, func_code, frame.data.hex() if frame.data else "empty"
            )
            # Check if this is a token grant (GET_TOKEN function code)
            if func_code == GET_TOKEN_FUNC:
                self._has_token = True
                logger.info("Token received from master panel")

    async def _return_token(self) -> None:
        """Return token to master panel after completing bus operations."""
        token_frame = Frame(
            destination=PANEL_ADDRESS,
            command=SERVICE_CMD,
            data=GIVE_BACK_TOKEN_DATA,
        )
        await self._writer.write_frame(token_frame)
        self._has_token = False
        logger.info("Token returned to master panel")

    async def _wait_for_token(self) -> None:
        """Wait for bus token from the master panel.

        Listens passively on the bus, responds to IDENTIFY probes,
        and waits for the panel to grant us the token (SERVICE frame
        with GET_TOKEN function code). This matches the original
        webserver's checkIfMultimaster() + passive listen behavior.

        When token_required=True, waits indefinitely (like the original
        webserver which never sends without the token). When False,
        falls back after token_timeout seconds.
        """
        if not self._token_required and self._token_timeout <= 0:
            return

        if self._token_required:
            logger.debug("Waiting for token from panel (indefinite, token_required=True)...")
        else:
            logger.debug("Waiting for token from panel (%.0fs timeout)...", self._token_timeout)

        loop = asyncio.get_event_loop()
        deadline = None if self._token_required else loop.time() + self._token_timeout

        while True:
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    logger.debug("Token wait timed out after %.0fs, proceeding without token", self._token_timeout)
                    return
                read_timeout = min(remaining, 0.5)
            else:
                read_timeout = 0.5

            frame = await self._reader.read_frame(timeout=read_timeout)

            if frame is None:
                continue

            # Log ALL bus traffic for debugging (before filtering)
            logger.debug(
                "Bus: src=%d dst=%d cmd=0x%02X len=%d",
                frame.source,
                frame.destination,
                frame.command,
                len(frame.data) if frame.data else 0,
            )

            # Special logging for SERVICE frames to us
            if frame.command == SERVICE_CMD and frame.destination == SRC_ADDRESS:
                func_code = struct.unpack("<H", frame.data[0:2])[0] if len(frame.data) >= 2 else 0
                logger.info("SERVICE to US (131): func=0x%04X", func_code)

            # Only process frames addressed to us or broadcast
            if frame.destination != SRC_ADDRESS and frame.destination != 0xFFFF:
                continue

            # Handle panel frames (IDENTIFY and token grant)
            if frame.source == PANEL_ADDRESS:
                await self._handle_panel_frame(frame)
                if self._has_token:
                    logger.info("Token received, proceeding immediately")
                    return

    async def send_and_receive(
        self,
        command: int,
        data: bytes = b"",
        expected_response: int | None = None,
        also_accept_commands: list[int] | None = None,
        response_validator: Callable[[Frame], bool] | None = None,
        destination: int | None = None,
    ) -> Frame | None:
        """Send a frame and wait for response.

        Matches the original firmware's send-one/read-one pattern:
        sends a request, then reads frames with a short timeout (0.2s).
        If the bus goes quiet (no frame within 0.2s), the response
        isn't coming and we return None for the caller to retry.

        Args:
            command: Command code to send.
            data: Request payload.
            expected_response: Expected response command code.
            also_accept_commands: Additional command codes to accept as
                terminal responses (e.g., NO_DATA, ERROR). These bypass
                the response_validator.
            response_validator: Optional callable to validate response data.
                If provided and returns False, the frame is skipped.
                Only applied to expected_response frames, not also_accept.
            destination: Override destination address (default: self._destination).

        Returns:
            Response frame, or None on timeout.
        """
        dest = destination if destination is not None else self._destination
        request = Frame(destination=dest, command=command, data=data)

        success = await self._writer.write_frame(request, timeout=self._request_timeout)
        if not success:
            logger.warning(f"Failed to send command 0x{command:02X}")
            return None

        # Don't clear buffer between requests - the frame validation
        # (command + first_index check) handles filtering stale frames.
        # Clearing the buffer here can discard late-arriving responses.

        if expected_response is None:
            return None

        accept_set = set(also_accept_commands) if also_accept_commands else set()

        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._request_timeout
        skipped = 0
        consecutive_silence = 0

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break

            # 0.2s per-read timeout matching original PORT_TIMEOUT
            read_timeout = min(remaining, 0.2)
            response = await self._reader.read_frame(timeout=read_timeout)

            if response is None:
                consecutive_silence += 1
                if consecutive_silence >= 3:
                    # 0.6s of silence - response isn't coming
                    break
                continue

            # Any frame received resets the silence counter
            consecutive_silence = 0

            # Skip frames not addressed to us
            if response.destination != SRC_ADDRESS and response.destination != 0xFFFF:
                skipped += 1
                continue

            # Handle panel protocol frames (IDENTIFY and SERVICE for token)
            # Only intercept these specific commands; let data responses
            # (e.g., 0x81 struct response) through when querying the panel
            if response.source == PANEL_ADDRESS and response.command in (IDENTIFY_CMD, SERVICE_CMD):
                await self._handle_panel_frame(response)
                skipped += 1
                continue

            # Skip frames not from expected source
            if response.source != dest and dest != 0xFFFF:
                skipped += 1
                continue

            # Accept also_accept_commands immediately (terminal responses
            # like NO_DATA/ERROR that don't need validation)
            if response.command in accept_set:
                return response

            # Skip wrong response commands
            if response.command != expected_response:
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

            return response

        if skipped > 0:
            logger.debug(f"No matching response for 0x{command:02X} (skipped {skipped} frames)")
        return None

    async def _send_get_settings(self) -> None:
        """Send GET_SETTINGS as first request after receiving token.

        The original firmware sends this to address 0xFFFF (broadcast)
        as the first request after getting the token, which initializes
        the connection with the controller.
        """
        response = await self.send_and_receive(
            Command.GET_SETTINGS,
            data=b"",
            expected_response=Command.GET_SETTINGS_RESPONSE,
            destination=0xFFFF,
        )
        if response:
            logger.debug("GET_SETTINGS response received (%d bytes)", len(response.data))
        else:
            logger.debug("GET_SETTINGS got no response (non-critical)")

    # Sentinel returned by fetch_param_structs when controller says "no more data"
    _NO_MORE_DATA: list[ParamStructEntry] = []

    async def fetch_param_structs(
        self,
        start_index: int = 0,
        count: int = 50,
        destination: int | None = None,
        with_range: bool = True,
    ) -> tuple[list[ParamStructEntry], bool]:
        """Fetch parameter structure/metadata from controller.

        Args:
            start_index: Starting parameter index (wire index, not stored index).
            count: Number of parameters to request.
            destination: Override destination address.
            with_range: If True, use GET_PARAMS_STRUCT_WITH_RANGE (0x02) which
                returns min/max range data. If False, use GET_PARAMS_STRUCT (0x01)
                which has exponent+type but no range. Panel params use False.

        Returns:
            Tuple of (entries, end_of_range). end_of_range is True when the
            controller explicitly signals no more data (NO_DATA frame 0x7F).
        """
        data = build_struct_request(start_index, count)

        if with_range:
            send_cmd = Command.GET_PARAMS_STRUCT_WITH_RANGE
            expect_cmd = Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE
        else:
            send_cmd = Command.GET_PARAMS_STRUCT
            expect_cmd = Command.GET_PARAMS_STRUCT_RESPONSE

        def validate_first_index(frame: Frame) -> bool:
            if len(frame.data) < 3:
                return False
            first_index = struct.unpack("<H", frame.data[1:3])[0]
            return first_index == start_index

        response = await self.send_and_receive(
            send_cmd,
            data,
            expected_response=expect_cmd,
            also_accept_commands=[Command.NO_DATA, Command.ERROR],
            response_validator=validate_first_index,
            destination=destination,
        )

        if response is None:
            return [], False

        # Controller explicitly says "no more data at this index"
        if response.command == Command.NO_DATA:
            logger.debug("Controller returned NO_DATA for index %d", start_index)
            return [], True

        # Controller returned an error (e.g., doesn't support with-range)
        if response.command == Command.ERROR:
            logger.debug("Controller returned ERROR for index %d", start_index)
            return [], True

        if with_range:
            entries = parse_struct_response(response.data)
        else:
            entries = parse_struct_response_no_range(response.data)

        for entry in entries:
            self._param_structs[entry.index] = entry

        logger.debug(f"Fetched {len(entries)} param structs starting at index {start_index}")
        return entries, False

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

        async with self._lock:
            try:
                response = await self.send_and_receive(
                    Command.MODIFY_PARAM,
                    data,
                    expected_response=Command.MODIFY_PARAM_RESPONSE,
                )
            finally:
                if self._has_token:
                    await self._return_token()

        if response is not None:
            updated_param = param.model_copy(update={"value": value})
            await self._cache.set(updated_param)
            logger.info(f"Parameter {name} set to {value}")
            return True

        logger.warning(f"Failed to write parameter {name}")
        return False

    async def _discover_batch(
        self,
        wire_index: int,
        store_offset: int,
        destination: int | None,
        with_range: bool,
        structs: dict[int, ParamStructEntry],
    ) -> tuple[int, bool, bool]:
        """Try to fetch one batch of parameter structs.

        Args:
            wire_index: Starting wire index for this batch.
            store_offset: Offset added to wire index for storage.
            destination: Destination address override.
            with_range: Whether to use WITH_RANGE or WITHOUT_RANGE.
            structs: Dict to add discovered entries to (mutated in place).

        Returns:
            Tuple of (next_wire_index, range_done, token_expired).
            - next_wire_index: Where to continue from.
            - range_done: True if controller sent NO_DATA (range exhausted).
            - token_expired: True if request timed out (likely token expired).
        """
        batch_size = 100  # Match original's maxNumStructDPParams

        # Try up to 2 times - first failure might be transient
        # (bus noise, controller busy after panel communication)
        for attempt in range(2):
            entries, end_of_range = await self.fetch_param_structs(
                wire_index, batch_size, destination=destination, with_range=with_range,
            )
            if entries or end_of_range:
                break

        if end_of_range:
            return wire_index, True, False

        if not entries:
            return wire_index, False, True  # Token likely expired

        for entry in entries:
            stored_index = entry.index + store_offset
            entry.index = stored_index
            structs[stored_index] = entry

        # Next batch starts after last received param (wire index)
        next_index = entries[-1].index - store_offset + 1
        return next_index, False, False

    async def discover_params(self) -> int:
        """Discover all parameters across multiple token grants.

        The bus token has a limited time (~2s). Each token grant allows
        a few batches of struct requests. Discovery resumes from where
        it left off on each new token grant.

        Discovers two address spaces:
        1. Regulator params: dest=regulator, WITH_RANGE (0x02), stored at 0+
        2. Panel params: dest=panel (100), WITHOUT_RANGE (0x01), stored at 10000+

        Returns:
            Total number of parameters discovered.
        """
        async with self._lock:
            new_structs: dict[int, ParamStructEntry] = {}

            # Discovery state for each address space
            spaces = [
                {
                    "label": "regulator",
                    "wire_index": 0,
                    "store_offset": 0,
                    "destination": None,
                    "with_range": True,
                    "done": False,
                },
                {
                    "label": "panel",
                    "wire_index": 0,
                    "store_offset": 10000,
                    "destination": PANEL_ADDRESS,
                    "with_range": False,
                    "done": False,
                },
            ]

            max_token_grants = 100  # Safety limit
            grants_used = 0

            while any(not s["done"] for s in spaces) and grants_used < max_token_grants:
                # Get a token from the panel
                try:
                    await self._wait_for_token()
                except Exception:
                    logger.error("Failed to get token during discovery")
                    break

                grants_used += 1
                batches_this_grant = 0

                try:
                    # Clear reader buffer to discard any stale partial
                    # frames from the panel's previous communication
                    self._reader.reset_buffer()

                    # Use this token grant to discover as many batches as possible
                    for space in spaces:
                        if space["done"]:
                            continue

                        # Send batches until token expires or range ends
                        while True:
                            prev_count = len(new_structs)
                            next_idx, range_done, token_expired = await self._discover_batch(
                                wire_index=space["wire_index"],
                                store_offset=space["store_offset"],
                                destination=space["destination"],
                                with_range=space["with_range"],
                                structs=new_structs,
                            )

                            space["wire_index"] = next_idx
                            if len(new_structs) > prev_count:
                                batches_this_grant += 1

                            if range_done:
                                space["done"] = True
                                reg_count = sum(1 for k in new_structs if k < 10000)
                                panel_count = sum(1 for k in new_structs if k >= 10000)
                                logger.info(
                                    "Finished %s discovery (%d params so far: %d reg, %d panel)",
                                    space["label"], len(new_structs), reg_count, panel_count,
                                )
                                break

                            if token_expired:
                                logger.debug(
                                    "Token expired during %s discovery at index %d",
                                    space["label"], space["wire_index"],
                                )
                                break

                    # Log progress per token grant
                    if batches_this_grant > 0 or grants_used % 5 == 0:
                        reg_count = sum(1 for k in new_structs if k < 10000)
                        panel_count = sum(1 for k in new_structs if k >= 10000)
                        logger.info(
                            "Grant %d: %d total params so far (%d reg, %d panel)",
                            grants_used, len(new_structs), reg_count, panel_count,
                        )
                finally:
                    if self._has_token:
                        await self._return_token()

            if new_structs:
                self._param_structs = new_structs
                self._total_params = len(self._param_structs)
                reg_count = sum(1 for k in new_structs if k < 10000)
                panel_count = sum(1 for k in new_structs if k >= 10000)
                logger.info(
                    "Discovery complete: %d parameters (%d regulator, %d panel) in %d token grants",
                    self._total_params, reg_count, panel_count, grants_used,
                )
            else:
                logger.warning("Parameter discovery returned no results, keeping existing structures")

            return len(self._param_structs)

    async def poll_all_params(self) -> int:
        """Poll all known parameters and update cache.

        Waits for token from panel before sending requests.

        Returns:
            Number of parameters successfully read.
        """
        if not self._param_structs:
            return 0

        async with self._lock:
            try:
                await self._wait_for_token()

                indices = sorted(self._param_structs.keys())
                total_read = 0

                current_pos = 0
                while current_pos < len(indices):
                    start_index = indices[current_pos]

                    batch_end = min(current_pos + self._params_per_request, len(indices))
                    count = indices[batch_end - 1] - start_index + 1

                    values = None
                    for _ in range(RETRY_ATTEMPTS):
                        values = await self.fetch_param_values(start_index, count)
                        if values:
                            break

                    if not values:
                        current_pos = batch_end
                        continue

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

                    last_returned_index = values[-1][0]
                    new_pos = current_pos
                    while new_pos < len(indices) and indices[new_pos] <= last_returned_index:
                        new_pos += 1

                    current_pos = max(new_pos, current_pos + 1)

                return total_read
            finally:
                if self._has_token:
                    await self._return_token()

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
