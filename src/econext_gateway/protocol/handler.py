"""Protocol handler for GM3 serial communication.

Orchestrates serial communication, request/response correlation,
parameter reading/writing, and cache management.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time as _time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from econext_gateway.thermostat.emulator import ThermostatEmulator

from econext_gateway.core.cache import ParameterCache
from econext_gateway.core.models import Alarm, Parameter
from econext_gateway.protocol.codec import decode_value, encode_value
from econext_gateway.protocol.constants import (
    ALARM_REQUEST_PREFIX,
    CLAIMABLE_ADDRESS_RANGE,
    CONTROLLER_ADDRESS,
    DEVICE_TABLE_FUNC,
    GET_TOKEN_FUNC,
    GIVE_BACK_TOKEN_DATA,
    IDENTIFY_RESPONSE_DATA,
    PAIRING_ASSIGN_FUNC,
    PAIRING_BEACON_FUNC,
    PANEL_ADDRESS,
    POLL_INTERVAL,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    THERMOSTAT_CLAIMABLE_ADDRESS_RANGE,
    TOKEN_TIMEOUT,
    TYPE_SIZES,
    Command,
    DataType,
)
from econext_gateway.protocol.dispatcher import FrameDispatcher
from econext_gateway.protocol.frames import Frame
from econext_gateway.serial.connection import GM3SerialTransport

logger = logging.getLogger(__name__)

# Human-readable command names for bus sniff logging
_CMD_NAMES: dict[int, str] = {
    0x00: "GET_SETTINGS",
    0x80: "GET_SETTINGS_RESP",
    0x01: "GET_PARAMS_STRUCT",
    0x81: "GET_PARAMS_STRUCT_RESP",
    0x02: "GET_PARAMS_STRUCT_RANGE",
    0x82: "GET_PARAMS_STRUCT_RANGE_RESP",
    0x09: "IDENTIFY",
    0x89: "IDENTIFY_ANS",
    0x29: "MODIFY_PARAM",
    0xA9: "MODIFY_PARAM_RESP",
    0x40: "GET_PARAMS",
    0xC0: "GET_PARAMS_RESP",
    0x68: "SERVICE",
    0xE8: "SERVICE_ANS",
    0x7E: "ERROR",
    0x7F: "NO_DATA",
}


def _cmd_name(cmd: int) -> str:
    return _CMD_NAMES.get(cmd, f"0x{cmd:02X}")


# Known real thermostat addresses on the bus (for debug logging)
_KNOWN_THERMOSTAT_ADDRS = frozenset({165, 166, 167})


def _log_thermostat_frame(
    frame: Frame,
    thermostat_addrs: frozenset[int],
    *,
    truncate_hex: bool = False,
) -> None:
    """Log thermostat-related bus traffic at DEBUG level.

    Args:
        frame: The bus frame to log.
        thermostat_addrs: Set of thermostat addresses (known + virtual).
        truncate_hex: If True, truncate hex dump (used during polling).
    """
    if frame.source not in thermostat_addrs and frame.destination not in thermostat_addrs:
        return

    extra = ""
    if frame.command == 0xC0 and frame.data and len(frame.data) >= 8:
        try:
            temp = struct.unpack("<f", frame.data[4:8])[0]
            extra = f" temp={temp:.1f}"
        except struct.error:
            pass

    hex_dump = ""
    if frame.command == 0xC0 and frame.data:
        if truncate_hex and frame.source in thermostat_addrs:
            hex_dump = f" hex={frame.data[:20].hex()}..."
        else:
            hex_dump = f" hex={frame.data.hex()}"
    elif frame.data:
        hex_dump = f" data={frame.data.hex()}"

    logger.debug(
        "THERMO src=%d dst=%d %s [%db]%s%s",
        frame.source,
        frame.destination,
        _cmd_name(frame.command),
        len(frame.data) if frame.data else 0,
        extra,
        hex_dump,
    )


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
        min_param_ref: int | None = None,
        max_param_ref: int | None = None,
    ):
        self.index = index
        self.name = name
        self.unit = unit
        self.type_code = type_code
        self.writable = writable
        self.min_value = min_value
        self.max_value = max_value
        # Dynamic min/max: index of another parameter whose value is the limit
        self.min_param_ref = min_param_ref
        self.max_param_ref = max_param_ref


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


@dataclass
class DeviceTableEntry:
    """A device in the panel's bus device table (from SERVICE 0x2001)."""

    address: int
    temperature: float


@dataclass
class BusDevice:
    """A device known to exist on the RS-485 bus."""

    address: int
    identity: str | None = None
    temperature: float | None = None
    source: str = ""
    last_seen: float = 0.0


@dataclass
class _PendingRequest:
    """An outbound request awaiting a matching response frame.

    Set by `send_and_receive` before writing, resolved by the frame
    dispatcher when a matching frame arrives. Only one request is
    in flight at a time; concurrent callers serialise via `_lock`.
    """

    destination: int  # expected response source (or 0xFFFF for broadcast)
    expected_cmd: int | None
    accept_cmds: set[int]
    validator: Callable[[Frame], bool] | None
    future: asyncio.Future


_KNOWN_ADDRESSES: dict[int, str] = {
    1: "controller",
    100: "panel",
}


def _parse_identity(data: bytes) -> str:
    """Parse null-separated identity bytes into a human-readable string."""
    return data.replace(b"\x00", b" ").strip().decode("ascii", errors="replace")


def parse_device_table(data: bytes) -> list[DeviceTableEntry]:
    """Parse SERVICE 0x2001 device table broadcast payload.

    Format: [func_lo][func_hi][0x00][0x00] then repeating 6-byte entries
    of [addr_lo][addr_hi][float32_LE] (device address + temperature).

    Args:
        data: SERVICE frame data (includes func code bytes).

    Returns:
        List of DeviceTableEntry with address and temperature.
    """
    if len(data) < 4:
        return []

    entries = []
    offset = 4  # skip func code + padding
    while offset + 6 <= len(data):
        addr = struct.unpack("<H", data[offset : offset + 2])[0]
        temp = struct.unpack("<f", data[offset + 2 : offset + 6])[0]
        entries.append(DeviceTableEntry(address=addr, temperature=round(temp, 2)))
        offset += 6

    return entries


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


def parse_get_params_response(
    data: bytes,
    param_structs: dict[int, ParamStructEntry],
    store_offset: int = 0,
) -> list[tuple[int, Any]]:
    """Parse a GET_PARAMS_RESPONSE payload.

    Response format:
    - data[0]: paramsNo (number of parameters)
    - data[1:3]: firstParamIndex (LE uint16)
    - data[3]: separator byte (skipped)
    - data[4:]: parameter values, each followed by a 1-byte separator

    Args:
        data: Response payload bytes.
        param_structs: Known parameter structure indexed by param index.
        store_offset: Offset added to wire index for param_structs lookup
            (0 for regulator, 10000 for panel).

    Returns:
        List of (stored_index, decoded_value) tuples.

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
        param_index = first_index + i + store_offset

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
        min_param_ref = None
        max_param_ref = None

        if offset + 4 > len(data):
            break

        # Min value
        if extra_byte & 0x10:
            # Dynamic min: value is a parameter index reference, not a literal
            min_param_ref = struct.unpack("<H", data[offset : offset + 2])[0]
        elif not (extra_byte & 0x40):
            # Literal min value
            if type_code in (DataType.UINT8, DataType.UINT16, DataType.UINT32):
                min_value = float(struct.unpack("<H", data[offset : offset + 2])[0])
            else:
                min_value = float(struct.unpack("<h", data[offset : offset + 2])[0])

        # Max value
        if extra_byte & 0x20:
            # Dynamic max: value is a parameter index reference, not a literal
            max_param_ref = struct.unpack("<H", data[offset + 2 : offset + 4])[0]
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
                min_param_ref=min_param_ref,
                max_param_ref=max_param_ref,
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

    Format: [AUTH_HEADER][MODE][INDEX_LO][INDEX_HI][VALUE_BYTES]
    Auth header: "USER-000\\x004096\\x00" (14 bytes) - service authorization
    Mode byte: 0x01
    Matches original webserver's getAnswerForModifyParam().

    Args:
        index: Parameter index to modify.
        value: New value.
        type_code: Data type code for encoding.

    Returns:
        Request payload bytes.
    """
    # Authorization header (matches original: USER-000\x004096\x00)
    auth = b"\x55\x53\x45\x52\x2d\x30\x30\x30\x00\x34\x30\x39\x36\x00"
    # Mode byte 0x01 + parameter index (LE 16-bit) + encoded value
    return auth + b"\x01" + struct.pack("<H", index) + encode_value(value, type_code)


class ProtocolHandler:
    """Orchestrates GM3 serial protocol communication.

    Handles request/response correlation, parameter reading/writing,
    and background polling with cache management.
    """

    def __init__(
        self,
        connection: GM3SerialTransport,
        cache: ParameterCache,
        destination: int = CONTROLLER_ADDRESS,
        poll_interval: float = POLL_INTERVAL,
        request_timeout: float = REQUEST_TIMEOUT,
        params_per_request: int = 50,
        token_timeout: float = TOKEN_TIMEOUT,
        token_required: bool = True,
        paired_address_file: Path | None = None,
        thermostat_emulator: ThermostatEmulator | None = None,
        thermostat_address_file: Path | None = None,
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
            paired_address_file: Path to persist panel-assigned bus address.
                On first boot the gateway claims a free address via the
                panel's IDENTIFY scan and persists it here.  Delete the
                file and restart to re-pair at a new address.
            thermostat_emulator: Optional thermostat emulator for virtual
                thermostat support. When set, the handler will delegate
                frames addressed to the thermostat address to the emulator.
            thermostat_address_file: Path to persist thermostat bus address.
                When the thermostat has address=0 it will auto-register
                via IDENTIFY during pairing and persist the address here.
        """
        self._connection = connection
        self._cache = cache
        self._destination = destination
        self._poll_interval = poll_interval
        self._request_timeout = request_timeout
        self._params_per_request = params_per_request
        self._token_timeout = token_timeout
        self._token_required = token_required
        self._paired_address_file = paired_address_file

        # Load persisted address from previous auto-registration
        paired_addr = self._load_paired_address()
        if paired_addr is not None:
            logger.info("Loaded paired address %d from %s", paired_addr, paired_address_file)
            self._source_address = paired_addr
            self._registration_state = "paired"
        else:
            self._source_address = 0  # Placeholder; set during auto-registration
            self._registration_state = "unpaired"
            logger.info("No paired address found, will auto-register at next free address")

        self._tentative_since: float | None = None

        self._param_structs: dict[int, ParamStructEntry] = {}
        self._total_params: int = 0
        self._alarms: list[Alarm] = []
        self._device_table: list[DeviceTableEntry] = []
        self._device_registry: dict[int, BusDevice] = {}
        if self._registration_state == "paired":
            self._device_registry[self._source_address] = BusDevice(
                address=self._source_address,
                identity=_parse_identity(IDENTIFY_RESPONSE_DATA),
                source="self",
            )
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self._lock_holder: str | None = None
        self._has_token = False
        self._thermostat = thermostat_emulator
        self._thermostat_address_file = thermostat_address_file

        # Dispatcher + listener state (Phase 2 refactor).
        # The dispatcher runs a background task that consumes the protocol
        # frame queue and routes each frame through subscribers. Previously
        # `_wait_for_token` and `send_and_receive` both pulled from the queue
        # while holding `_lock`, which serialised the entire poll cycle
        # (including multi-second token waits) against HA API calls.
        self._dispatcher: FrameDispatcher | None = None
        self._watchdog_task: asyncio.Task | None = None
        # Set when the panel grants us the bus token (SERVICE/GET_TOKEN).
        # Cleared when we return the token. `_wait_for_token` waits on this.
        self._token_event = asyncio.Event()
        # Outbound request awaiting a matching response frame. The dispatcher
        # resolves the future when a matching frame arrives.
        self._pending_request: _PendingRequest | None = None
        # Small buffer for response-shaped frames that arrived slightly
        # before `send_and_receive` set the pending slot. Size-capped so
        # it can't grow unbounded in production.
        self._unmatched_response_buffer: list[Frame] = []
        self._unmatched_buffer_max = 8
        # Last time any frame was seen on the bus — for bus-silence watchdog.
        self._last_frame_time: float = 0.0
        # Pairing-mode state (was local to `_wait_for_token` in the pre-refactor
        # loop; now instance state so subscribers can see it).
        self._pairing_mode_active: bool = False
        self._device_table_seen: bool = len(self._device_table) > 0

        # Thermostat registration state (None = thermostat not enabled)
        if self._thermostat is not None and self._thermostat.address != 0:
            self._thermostat_reg_state: str | None = "paired"
        elif self._thermostat is not None:
            self._thermostat_reg_state = "unpaired"
        else:
            self._thermostat_reg_state = None
        self._thermostat_tentative_since: float | None = None

    @asynccontextmanager
    async def _traced_lock(self, name: str):
        """Acquire self._lock with diagnostic logging of wait + hold times.

        Logs LOCK_WAIT at INFO when waiters are blocked > 200ms (contention
        worth knowing about), and LOCK_HELD at INFO when a critical section
        takes > 1s (unusual — pre-refactor baseline was 15–22s). Shorter
        waits and holds go to DEBUG so steady-state operation stays quiet.
        """
        wait_start = _time.monotonic()
        prior_holder = self._lock_holder
        await self._lock.acquire()
        wait_ms = (_time.monotonic() - wait_start) * 1000
        if wait_ms > 200.0:
            logger.info(
                "LOCK_WAIT name=%s waited=%.0fms holder_was=%s",
                name,
                wait_ms,
                prior_holder,
            )
        elif wait_ms > 5.0:
            logger.debug(
                "LOCK_WAIT name=%s waited=%.0fms holder_was=%s",
                name,
                wait_ms,
                prior_holder,
            )
        self._lock_holder = name
        held_start = _time.monotonic()
        try:
            yield
        finally:
            held_ms = (_time.monotonic() - held_start) * 1000
            if held_ms > 1000.0:
                logger.info("LOCK_HELD name=%s held=%.0fms", name, held_ms)
            else:
                logger.debug("LOCK_HELD name=%s held=%.0fms", name, held_ms)
            self._lock_holder = None
            self._lock.release()

    def _load_paired_address(self) -> int | None:
        """Load persisted paired address from file."""
        if self._paired_address_file is None:
            return None
        try:
            text = self._paired_address_file.read_text().strip()
            return int(text)
        except (FileNotFoundError, ValueError):
            return None

    def _save_paired_address(self, address: int) -> None:
        """Persist the panel-assigned address to file."""
        if self._paired_address_file is None:
            return
        try:
            self._paired_address_file.parent.mkdir(parents=True, exist_ok=True)
            self._paired_address_file.write_text(str(address))
            logger.info("Saved paired address %d to %s", address, self._paired_address_file)
        except OSError as e:
            logger.warning("Failed to save paired address: %s", e)

    # Temporary source address for thermostat pairing SERVICE_ANS response.
    # Real ecoSTER uses 164; we use a different address to avoid collision.
    THERMOSTAT_PAIRING_ADDRESS = 163

    async def _thermostat_respond_to_beacon(self, beacon_frame: Frame) -> None:
        """Respond to a 0x2004 pairing beacon with SERVICE_ANS.

        The real thermostat sends SERVICE_ANS (0xE8) from a temporary address
        to the panel with a 67-byte identity payload. The panel then assigns
        a final address via SERVICE 0x2005.
        """
        from econext_gateway.thermostat.emulator import THERMOSTAT_PAIRING_IDENTITY

        data = THERMOSTAT_PAIRING_IDENTITY
        await asyncio.sleep(0.02)  # RS-485 turnaround
        response = Frame(
            destination=PANEL_ADDRESS,
            command=Command.SERVICE_RESPONSE,
            data=data,
            source=self.THERMOSTAT_PAIRING_ADDRESS,
        )
        await self._connection.protocol.write_frame(response, flush_after=True, clear_echo=False)
        logger.info(
            "Thermostat: sent SERVICE_ANS to panel from addr %d (%d bytes)",
            self.THERMOSTAT_PAIRING_ADDRESS,
            len(data),
        )

    def request_thermostat_pairing(self) -> bool:
        """Request thermostat pairing. Called from the API.

        Resets current pairing (deletes address file, clears emulator address)
        and sets state to 'pairing_requested' so the handler will respond to
        the next 0x2004 pairing beacon. Allows re-pairing at a new address.

        Returns:
            True if pairing was requested, False if not applicable.
        """
        if self._thermostat is None:
            return False

        # Always allow - reset any current state
        if self._thermostat_reg_state == "paired":
            logger.info(
                "Resetting thermostat pairing (was at address %d)",
                self._thermostat.address,
            )
        elif self._thermostat_reg_state not in ("unpaired", None):
            logger.info(
                "Resetting thermostat pairing state (was %s)",
                self._thermostat_reg_state,
            )
        self._thermostat.address = 0
        # Keep _written_values - panel config and temperature survive re-pairing
        if self._thermostat_address_file is not None:
            try:
                self._thermostat_address_file.unlink(missing_ok=True)
            except OSError:
                pass

        self._thermostat_reg_state = "pairing_requested"
        self._thermostat_tentative_since = asyncio.get_running_loop().time()
        logger.info("Thermostat pairing requested via API, waiting for 0x2004 beacon")
        return True

    def _save_thermostat_address(self, address: int) -> None:
        """Persist the thermostat bus address to file."""
        if self._thermostat_address_file is None:
            return
        try:
            self._thermostat_address_file.parent.mkdir(parents=True, exist_ok=True)
            self._thermostat_address_file.write_text(str(address))
            logger.info("Saved thermostat address %d to %s", address, self._thermostat_address_file)
        except OSError as e:
            logger.warning("Failed to save thermostat address: %s", e)

    def _process_device_table(self, data: bytes, now: float) -> list[DeviceTableEntry]:
        """Parse a device table broadcast and update registry.

        Shared by _handle_panel_frame (during polling) and _wait_for_token
        (during registration/pairing). Updates _device_table, _device_registry,
        and confirms thermostat registration if address appears.

        Returns:
            Parsed device table entries.
        """
        entries = parse_device_table(data)
        self._device_table = entries
        for e in entries:
            dev = self._device_registry.setdefault(
                e.address,
                BusDevice(address=e.address, source="device_table"),
            )
            dev.temperature = e.temperature
            dev.last_seen = now

        # Log all known bus devices
        parts = []
        for d in sorted(self._device_registry.values(), key=lambda d: d.address):
            label = d.identity or _KNOWN_ADDRESSES.get(d.address, "Unknown")
            if d.temperature is not None:
                parts.append(f"{d.address}({label} {d.temperature:.1f}C)")
            else:
                parts.append(f"{d.address}({label})")
        logger.info("Bus devices (%d): %s", len(self._device_registry), ", ".join(parts))

        # Thermostat registration: confirm when address appears in device table
        if (
            self._thermostat_reg_state == "tentative"
            and self._thermostat is not None
            and self._thermostat.address in {e.address for e in entries}
        ):
            self._thermostat_reg_state = "paired"
            self._save_thermostat_address(self._thermostat.address)
            logger.info(
                "Thermostat address %d confirmed in device table, persisted",
                self._thermostat.address,
            )

        return entries

    @property
    def _thermostat_log_addrs(self) -> frozenset[int]:
        """Thermostat addresses for debug logging (known + virtual)."""
        if self._thermostat is not None and self._thermostat.address != 0:
            return _KNOWN_THERMOSTAT_ADDRS | {self._thermostat.address}
        return _KNOWN_THERMOSTAT_ADDRS

    async def _resolve_min_max(self, entry: ParamStructEntry) -> tuple[float | None, float | None]:
        """Resolve min/max values, following parameter index references.

        When a parameter's min/max is a reference to another parameter's index,
        look up that parameter's current value in the cache to get the actual limit.
        """
        min_val = entry.min_value
        max_val = entry.max_value

        if entry.min_param_ref is not None:
            ref = self._param_structs.get(entry.min_param_ref)
            if ref is not None:
                cached = await self._cache.get(ref.index)
                if cached is not None:
                    min_val = float(cached.value)

        if entry.max_param_ref is not None:
            ref = self._param_structs.get(entry.max_param_ref)
            if ref is not None:
                cached = await self._cache.get(ref.index)
                if cached is not None:
                    max_val = float(cached.value)

        return min_val, max_val

    @property
    def connected(self) -> bool:
        """Whether the serial connection is active."""
        return self._connection.connected

    @property
    def param_count(self) -> int:
        """Number of known parameter structures."""
        return len(self._param_structs)

    @property
    def alarms(self) -> list[Alarm]:
        """Get cached alarm history."""
        return list(self._alarms)

    @property
    def running(self) -> bool:
        """Whether background polling is active."""
        return self._running

    @property
    def thermostat_pairing_state(self) -> str | None:
        """Current thermostat pairing state, or None if thermostat not enabled."""
        return self._thermostat_reg_state

    @property
    def thermostat_address(self) -> int | None:
        """Bus address of the virtual thermostat, or None if not paired/enabled."""
        if self._thermostat is not None and self._thermostat.address != 0:
            return self._thermostat.address
        return None

    async def start(self) -> None:
        """Start background polling + frame dispatcher + bus watchdog."""
        if self._running:
            return

        self._running = True
        self._last_frame_time = asyncio.get_running_loop().time()

        # Dispatcher owns the frame-queue read loop; it routes each frame
        # through subscribers (currently a single `_route_inbound` handler).
        self._dispatcher = FrameDispatcher(self._connection)
        self._dispatcher.subscribe(self._route_inbound)
        await self._dispatcher.start()

        self._watchdog_task = asyncio.create_task(
            self._bus_silence_watchdog(), name="BusSilenceWatchdog"
        )
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Protocol handler started")

    async def stop(self) -> None:
        """Stop background polling + frame dispatcher + bus watchdog."""
        self._running = False

        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        if self._dispatcher is not None:
            await self._dispatcher.stop()
            self._dispatcher = None

        logger.info("Protocol handler stopped")

    async def _handle_panel_frame(self, frame: Frame) -> None:
        """Handle frames from the master panel (device 100).

        Responds to IDENTIFY_DEV probes (registering on the bus) and
        detects SERVICE/GET_TOKEN grants (exclusive bus access).

        Args:
            frame: Frame from the panel addressed to us.
        """
        if frame.command == Command.IDENTIFY:
            # Panel is asking "who are you?" - respond with device identity
            response = Frame(
                destination=PANEL_ADDRESS,
                command=Command.IDENTIFY_RESPONSE,
                data=IDENTIFY_RESPONSE_DATA,
                source=self._source_address,
            )
            # No flush: fire-and-forget write avoids blocking the event loop
            # (~7ms tcdrain) which delays time-critical thermostat responses.
            # The OS/USB driver drains TX asynchronously. clear_echo=False
            # preserves RX buffer on the half-duplex bus.
            await self._connection.protocol.write_frame(response, flush_after=False)
            logger.info("Responded to IDENTIFY from panel")

        elif frame.command == Command.SERVICE:
            func_code = 0
            if len(frame.data) >= 2:
                func_code = struct.unpack("<H", frame.data[0:2])[0]

            if func_code == GET_TOKEN_FUNC:
                self._has_token = True
                self._token_event.set()
                logger.info("Token received from master panel")
            elif func_code == DEVICE_TABLE_FUNC:
                self._process_device_table(frame.data, asyncio.get_running_loop().time())
            else:
                logger.debug(
                    "SERVICE frame: dest=%d, func=0x%04X, data=%s",
                    frame.destination,
                    func_code,
                    frame.data.hex() if frame.data else "empty",
                )

    async def _return_token(self) -> None:
        """Return token to master panel after completing bus operations."""
        # 20ms RS-485 bus turnaround delay before transmitting
        await asyncio.sleep(0.02)
        token_frame = Frame(
            destination=PANEL_ADDRESS,
            command=Command.SERVICE,
            data=GIVE_BACK_TOKEN_DATA,
            source=self._source_address,
        )
        await self._connection.protocol.write_frame(token_frame)
        self._has_token = False
        self._token_event.clear()
        logger.info("Token returned to master panel")

    async def _wait_for_token(self) -> None:
        """Wait for bus token from the master panel.

        Event-based: the frame dispatcher sets `_token_event` when a
        SERVICE/GET_TOKEN from the panel arrives. This replaces the
        pre-refactor inline frame-reading loop so the lock covering
        the wait does not also cover a multi-second panel cycle.

        When `token_required=True`, waits indefinitely (matches original
        webserver behaviour). When False, falls back after
        `token_timeout` seconds.
        """
        if not self._token_required and self._token_timeout <= 0:
            return
        if self._has_token:
            return

        if self._token_required:
            logger.debug("Waiting for token from panel (indefinite)...")
        else:
            logger.debug(
                "Waiting for token from panel (%.0fs timeout)...", self._token_timeout
            )

        token_wait_start = _time.monotonic()
        last_noprog_log = token_wait_start

        while not self._has_token:
            now_mono = _time.monotonic()
            if self._token_required:
                wait_slice = 5.0
            else:
                remaining = self._token_timeout - (now_mono - token_wait_start)
                if remaining <= 0:
                    logger.info(
                        "TOKEN timeout waited=%.1fs proceeding without token",
                        now_mono - token_wait_start,
                    )
                    return
                wait_slice = min(remaining, 5.0)

            try:
                await asyncio.wait_for(self._token_event.wait(), timeout=wait_slice)
                break
            except asyncio.TimeoutError:
                now_mono = _time.monotonic()
                if now_mono - last_noprog_log >= 5.0:
                    logger.info(
                        "TOKEN waited=%.1fs no_grant_yet lock_holder=%s",
                        now_mono - token_wait_start,
                        self._lock_holder,
                    )
                    last_noprog_log = now_mono

        logger.debug(
            "TOKEN granted waited=%.1fs", _time.monotonic() - token_wait_start
        )

    def _try_match_pending(self, frame: Frame) -> bool:
        """If this frame is the response our `send_and_receive` is waiting
        on, resolve the future and return True. Otherwise return False.
        """
        pending = self._pending_request
        if pending is None or pending.future.done():
            return False

        if frame.destination != self._source_address and frame.destination != 0xFFFF:
            return False

        # Panel IDENTIFY / SERVICE belong to the panel subscriber unless we
        # explicitly sent a request to the panel (e.g. alarm SERVICE query).
        if frame.source == PANEL_ADDRESS and frame.command in (
            Command.IDENTIFY,
            Command.SERVICE,
        ):
            return False

        if frame.source != pending.destination and pending.destination != 0xFFFF:
            return False

        if frame.command in pending.accept_cmds:
            pending.future.set_result(frame)
            return True

        if frame.command != pending.expected_cmd:
            return False

        if pending.validator is not None and not pending.validator(frame):
            return False

        pending.future.set_result(frame)
        return True

    async def _route_inbound(self, frame: Frame) -> bool:
        """Dispatcher subscriber: route a single inbound frame.

        Contains the frame-handling logic extracted from the
        pre-refactor `_wait_for_token` loop. Preserves the exact
        decision order (response match, sniff, pairing, auto-reg,
        thermostat, panel) so behaviour is unchanged, only the
        execution context (background task instead of held lock).
        """
        loop = asyncio.get_running_loop()
        self._last_frame_time = loop.time()

        if self._try_match_pending(frame):
            return True

        cmd_name = _cmd_name(frame.command)
        logger.debug(
            "BUS  src=%-5d dst=%-5d %s  [%db]",
            frame.source,
            frame.destination,
            cmd_name,
            len(frame.data) if frame.data else 0,
        )
        _log_thermostat_frame(frame, self._thermostat_log_addrs)

        if (
            frame.command == Command.IDENTIFY_RESPONSE
            and frame.destination == PANEL_ADDRESS
        ):
            identity_str = _parse_identity(frame.data) if frame.data else ""
            logger.debug(
                "IDENTIFY_ANS from %d -> panel: identity=%r",
                frame.source,
                identity_str,
            )
            dev = self._device_registry.setdefault(
                frame.source,
                BusDevice(address=frame.source, source="identify"),
            )
            dev.identity = identity_str
            dev.last_seen = loop.time()

        if frame.command == Command.SERVICE and len(frame.data) >= 2:
            func_code = struct.unpack("<H", frame.data[0:2])[0]
            target_note = (
                " (TO US)" if frame.destination == self._source_address else ""
            )
            logger.debug(
                "SERVICE src=%d dst=%d func=0x%04X%s",
                frame.source,
                frame.destination,
                func_code,
                target_note,
            )

        if (
            frame.source == PANEL_ADDRESS
            and frame.command == Command.SERVICE
            and len(frame.data) >= 2
        ):
            func_code = struct.unpack("<H", frame.data[0:2])[0]
            if func_code == DEVICE_TABLE_FUNC:
                self._process_device_table(frame.data, loop.time())
                self._device_table_seen = True
            if func_code == PAIRING_BEACON_FUNC and not self._pairing_mode_active:
                self._pairing_mode_active = True
                logger.info("Pairing mode detected (SERVICE 0x2004 beacon)")

        if (
            frame.command == Command.SERVICE_RESPONSE
            and frame.destination == PANEL_ADDRESS
        ):
            logger.debug(
                "THERMO_CAPTURE SERVICE_ANS src=%d dst=%d len=%d data=%s",
                frame.source,
                frame.destination,
                len(frame.data) if frame.data else 0,
                frame.data.hex() if frame.data else "",
            )

        # Thermostat pairing: 0x2004 beacon response
        if (
            self._thermostat_reg_state == "pairing_requested"
            and self._pairing_mode_active
            and self._thermostat is not None
            and frame.source == PANEL_ADDRESS
            and frame.command == Command.SERVICE
            and len(frame.data) >= 2
            and struct.unpack("<H", frame.data[0:2])[0] == PAIRING_BEACON_FUNC
        ):
            self._thermostat_reg_state = "beacon_responded"
            self._thermostat_tentative_since = loop.time()
            logger.info("Thermostat: responding to pairing beacon with SERVICE_ANS")
            await self._thermostat_respond_to_beacon(frame)
            return True

        # Thermostat pairing: 0x2005 address assignment
        if (
            self._thermostat_reg_state == "beacon_responded"
            and self._thermostat is not None
            and frame.source == PANEL_ADDRESS
            and frame.command == Command.SERVICE
            and len(frame.data) >= 6
            and struct.unpack("<H", frame.data[0:2])[0] == PAIRING_ASSIGN_FUNC
        ):
            assigned_addr = struct.unpack("<H", frame.data[4:6])[0]
            logger.info(
                "Thermostat: panel assigned address %d (from SERVICE 0x2005)",
                assigned_addr,
            )
            self._thermostat.address = assigned_addr
            self._thermostat_reg_state = "paired"
            self._save_thermostat_address(assigned_addr)
            await asyncio.sleep(0.02)
            ack = Frame(
                destination=PANEL_ADDRESS,
                command=Command.SERVICE_RESPONSE,
                data=frame.data,
                source=assigned_addr,
            )
            await self._connection.protocol.write_frame(
                ack, flush_after=True, clear_echo=False
            )
            from econext_gateway.thermostat.emulator import THERMOSTAT_IDENTITY

            self._device_registry[assigned_addr] = BusDevice(
                address=assigned_addr,
                identity=_parse_identity(THERMOSTAT_IDENTITY),
                source="thermostat_pairing",
                last_seen=loop.time(),
            )
            logger.info(
                "Thermostat: ACK'd address assignment, now paired at %d",
                assigned_addr,
            )
            return True

        if frame.source == PANEL_ADDRESS and frame.command == Command.IDENTIFY:
            logger.debug("Panel IDENTIFY probe to %d", frame.destination)

        # Gateway auto-registration
        occupied = {e.address for e in self._device_table}
        if (
            self._registration_state == "unpaired"
            and self._device_table_seen
            and frame.source == PANEL_ADDRESS
            and frame.command == Command.IDENTIFY
            and frame.destination != self._source_address
            and frame.destination in CLAIMABLE_ADDRESS_RANGE
            and frame.destination not in occupied
        ):
            target = frame.destination
            logger.info(
                "Scanning IDENTIFY to %d detected, claiming tentatively", target
            )
            self._source_address = target
            self._registration_state = "tentative"
            self._tentative_since = loop.time()
            await self._handle_panel_frame(frame)
            return True

        # Thermostat auto-registration (pairing-mode only)
        if (
            self._thermostat_reg_state == "unpaired"
            and self._pairing_mode_active
            and self._device_table_seen
            and frame.source == PANEL_ADDRESS
            and frame.command == Command.IDENTIFY
            and frame.destination in THERMOSTAT_CLAIMABLE_ADDRESS_RANGE
            and frame.destination not in occupied
            and frame.destination != self._source_address
            and self._thermostat is not None
        ):
            target = frame.destination
            logger.info(
                "Thermostat: IDENTIFY to %d detected, claiming tentatively", target
            )
            self._thermostat.address = target
            self._thermostat_reg_state = "tentative"
            self._thermostat_tentative_since = loop.time()
            await self._thermostat.handle_frame(
                frame, self._connection.protocol.write_frame
            )
            return True

        # Gateway tentative timeout
        if (
            self._registration_state == "tentative"
            and self._tentative_since is not None
            and loop.time() - self._tentative_since > 20.0
        ):
            logger.warning(
                "Tentative address %d timed out (no token in 20s), reverting",
                self._source_address,
            )
            self._source_address = 0
            self._registration_state = "unpaired"
            self._tentative_since = None

        # Thermostat pairing timeout
        if (
            self._thermostat_reg_state
            in ("pairing_requested", "tentative", "beacon_responded")
            and self._thermostat_tentative_since is not None
            and loop.time() - self._thermostat_tentative_since > 60.0
        ):
            logger.warning(
                "Thermostat pairing timed out (state=%s, 60s elapsed), reverting",
                self._thermostat_reg_state,
            )
            if self._thermostat is not None:
                self._thermostat.address = 0
            self._thermostat_reg_state = "unpaired"
            self._thermostat_tentative_since = None

        # Thermostat frames (dst = thermostat address, src = panel)
        if (
            self._thermostat is not None
            and frame.destination == self._thermostat.address
            and frame.source == PANEL_ADDRESS
        ):
            proto = self._connection.protocol
            qsize = proto._frame_queue.qsize()
            # Only log at INFO when there is backlog or lock contention; the
            # common steady-state case (qsize=0, no holder) is DEBUG.
            if qsize > 0 or self._lock_holder is not None:
                logger.debug(
                    "THERMO_WAIT src=%d dst=%d cmd=0x%02X len=%d qsize=%d holder=%s",
                    frame.source,
                    frame.destination,
                    frame.command,
                    len(frame.data) if frame.data else 0,
                    qsize,
                    self._lock_holder,
                )
            if qsize > 10:
                queued = list(proto._frame_queue._queue)  # type: ignore[attr-defined]
                summary: dict[str, int] = {}
                for f in queued:
                    if f is None:
                        continue
                    key = f"src={f.source},dst={f.destination},cmd=0x{f.command:02X}"
                    summary[key] = summary.get(key, 0) + 1
                logger.info("THERMO_QUEUE_DUMP qsize=%d summary=%s", qsize, summary)
            await self._thermostat.handle_frame(
                frame, self._connection.protocol.write_frame
            )
            return True

        # Frames not addressed to us (bus sniff already done above).
        if frame.destination != self._source_address and frame.destination != 0xFFFF:
            return False

        # Panel IDENTIFY / SERVICE to us (token grants, device table to us).
        if frame.source == PANEL_ADDRESS and frame.command in (
            Command.IDENTIFY,
            Command.SERVICE,
        ):
            if frame.command == Command.IDENTIFY and self._thermostat is not None:
                asyncio.create_task(self._handle_panel_frame(frame))
                return True
            await self._handle_panel_frame(frame)
            if self._has_token and self._registration_state == "tentative":
                self._registration_state = "paired"
                self._save_paired_address(self._source_address)
                self._device_registry[self._source_address] = BusDevice(
                    address=self._source_address,
                    identity=_parse_identity(IDENTIFY_RESPONSE_DATA),
                    source="self",
                    last_seen=loop.time(),
                )
                logger.info(
                    "Address %d validated by token grant, persisted",
                    self._source_address,
                )
            return True

        # Nothing claimed it. If it's addressed to us and looks like a
        # response (not a panel IDENTIFY/SERVICE, already handled above),
        # buffer it so a `send_and_receive` starting shortly can still
        # pick it up — covers the race where a response arrives between
        # two back-to-back requests.
        self._unmatched_response_buffer.append(frame)
        if len(self._unmatched_response_buffer) > self._unmatched_buffer_max:
            self._unmatched_response_buffer.pop(0)
        return False

    async def _bus_silence_watchdog(self) -> None:
        """Reconnect the serial port if no frames arrive for a while.

        Previously lived inside `_wait_for_token`. Now a standalone task
        so it runs regardless of whether anyone is waiting for a token.
        """
        bus_silence_limit = 30.0
        check_interval = 5.0
        while self._running:
            await asyncio.sleep(check_interval)
            if self._last_frame_time == 0.0:
                continue
            now = asyncio.get_running_loop().time()
            silence = now - self._last_frame_time
            if silence >= bus_silence_limit:
                logger.warning(
                    "Bus silent for %.0fs, reconnecting serial port", silence
                )
                try:
                    await self._connection.reconnect()
                except Exception as e:  # noqa: BLE001
                    logger.error("Reconnect failed: %s", e)
                self._last_frame_time = now

    async def send_and_receive(
        self,
        command: int,
        data: bytes = b"",
        expected_response: int | None = None,
        also_accept_commands: list[int] | None = None,
        response_validator: Callable[[Frame], bool] | None = None,
        destination: int | None = None,
    ) -> Frame | None:
        """Send a frame and wait for a matching response.

        Post-refactor: registers a `_PendingRequest` that the frame
        dispatcher resolves when a matching response arrives. The old
        inline polling loop is gone; only one request is in flight at
        a time, serialised via `_lock` as before.

        Args:
            command: Command code to send.
            data: Request payload.
            expected_response: Expected response command code.
            also_accept_commands: Additional command codes to accept as
                terminal responses (e.g., NO_DATA, ERROR). These bypass
                the response_validator.
            response_validator: Optional callable to validate response data.
            destination: Override destination address (default: self._destination).

        Returns:
            Response frame, or None on timeout.
        """
        dest = destination if destination is not None else self._destination
        request = Frame(
            destination=dest, command=command, data=data, source=self._source_address
        )

        accept_set = set(also_accept_commands) if also_accept_commands else set()

        pending = _PendingRequest(
            destination=dest,
            expected_cmd=expected_response,
            accept_cmds=accept_set,
            validator=response_validator,
            future=asyncio.get_running_loop().create_future(),
        )
        # Cancel any prior unresolved pending (shouldn't happen — lock serialises).
        if (
            self._pending_request is not None
            and not self._pending_request.future.done()
        ):
            self._pending_request.future.cancel()
        self._pending_request = pending

        # Check if a buffered response-shape frame already matches this
        # pending request. Matched frames are removed; unmatched ones stay
        # for a future request (still size-capped).
        remaining: list[Frame] = []
        matched_one = False
        for buf_frame in self._unmatched_response_buffer:
            if not matched_one and self._try_match_pending(buf_frame):
                matched_one = True
            else:
                remaining.append(buf_frame)
        self._unmatched_response_buffer = remaining

        try:
            # 20ms RS-485 bus turnaround delay
            await asyncio.sleep(0.02)

            success = await self._connection.protocol.write_frame(
                request, flush_after=True
            )
            if not success:
                logger.warning(f"Failed to send command 0x{command:02X}")
                return None

            if expected_response is None:
                return None

            # Same 2s patience as the pre-refactor loop (10 * 0.2s).
            try:
                return await asyncio.wait_for(pending.future, timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug(
                    f"No matching response for 0x{command:02X} within 2.0s"
                )
                return None
        finally:
            if self._pending_request is pending:
                self._pending_request = None

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

    async def fetch_param_values(
        self,
        start_index: int,
        count: int,
        destination: int | None = None,
        store_offset: int = 0,
    ) -> list[tuple[int, Any]]:
        """Fetch parameter values from controller.

        Args:
            start_index: Starting wire index.
            count: Number of parameters to read.
            destination: Override destination address (for panel params).
            store_offset: Offset for mapping wire index to stored index
                (0 for regulator, 10000 for panel).

        Returns:
            List of (stored_index, value) tuples.
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
            destination=destination,
        )

        if response is None:
            return []

        results = parse_get_params_response(response.data, self._param_structs, store_offset)
        logger.debug(f"Fetched {len(results)} param values starting at wire index {start_index}")
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

            min_val, max_val = await self._resolve_min_max(entry)
            param = Parameter(
                index=index,
                name=entry.name,
                value=value,
                type=entry.type_code,
                unit=entry.unit,
                writable=entry.writable,
                min_value=min_val,
                max_value=max_val,
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
        param = await self._cache.get_by_name(name)
        if param is None:
            raise ValueError(f"Parameter not found: {name}")

        entry = self._param_structs.get(param.index)
        if entry is None:
            raise ValueError(f"No structure info for parameter: {name}")

        if not entry.writable:
            raise ValueError(f"Parameter is read-only: {name}")

        min_val, max_val = await self._resolve_min_max(entry)

        if min_val is not None and float(value) < min_val:
            raise ValueError(f"Value {value} below minimum {min_val} for {name}")

        if max_val is not None and float(value) > max_val:
            raise ValueError(f"Value {value} above maximum {max_val} for {name}")

        data = build_modify_param_request(param.index, value, entry.type_code)

        async with self._traced_lock(f"api:write_param:{name}"):
            try:
                # Must hold the bus token to transmit on the RS-485 bus
                await self._wait_for_token()
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
            logger.info("Parameter %s set to %s", name, value)
            return True

        logger.warning("Failed to write parameter %s", name)
        return False

    @staticmethod
    def _decode_alarm_date(data: bytes) -> datetime | None:
        """Decode a 7-byte alarm date from the controller.

        Format: year(LE16), month, day, hour, minute, second.
        All 0xFF bytes means no date (null/end marker).

        Returns:
            datetime if valid, None for null/invalid dates.
        """
        if len(data) < 7:
            return None
        if all(b == 0xFF for b in data[:7]):
            return None
        try:
            year = struct.unpack("<h", data[0:2])[0]
            month, day, hour, minute, second = data[2], data[3], data[4], data[5], data[6]
            if year < 1 or month < 1 or month > 12 or day < 1 or day > 31:
                return None
            return datetime(year=year, month=month, day=day, hour=hour, minute=minute, second=second)
        except (ValueError, OverflowError):
            return None

    async def read_alarms(self) -> list[Alarm]:
        """Read alarm history from the controller.

        Sequentially reads alarms by index using SERVICE frames to the panel.
        Stops when a null date is returned (no more alarms at that index).

        Returns:
            List of Alarm objects sorted by from_date (newest first).
        """
        alarms: list[Alarm] = []

        async with self._traced_lock("api:read_alarms"):
            try:
                await self._wait_for_token()

                alarm_index = 0
                while True:
                    data = ALARM_REQUEST_PREFIX + bytes([alarm_index & 0xFF])
                    response = await self.send_and_receive(
                        Command.SERVICE,
                        data,
                        expected_response=Command.SERVICE_RESPONSE,
                        destination=PANEL_ADDRESS,
                    )

                    if response is None or len(response.data) < 15:
                        logger.debug("No alarm response at index %d, stopping", alarm_index)
                        break

                    code = response.data[0]
                    from_date = self._decode_alarm_date(response.data[1:8])

                    if from_date is None:
                        logger.debug("Null alarm at index %d, end of list", alarm_index)
                        break

                    to_date = self._decode_alarm_date(response.data[8:15])

                    alarm = Alarm(
                        index=alarm_index,
                        code=code,
                        from_date=from_date,
                        to_date=to_date,
                    )
                    alarms.append(alarm)
                    logger.debug(
                        "Alarm #%d: code=%d, from=%s, to=%s",
                        alarm_index,
                        code,
                        from_date,
                        to_date,
                    )
                    alarm_index += 1

            finally:
                if self._has_token:
                    await self._return_token()

        alarms.sort(key=lambda a: a.from_date, reverse=True)
        self._alarms = alarms
        logger.info("Read %d alarms from controller", len(alarms))
        return alarms

    async def _discover_address_space(
        self,
        label: str,
        store_offset: int,
        destination: int | None,
        with_range: bool,
        structs: dict[int, ParamStructEntry],
    ) -> bool:
        """Discover all parameters in one address space.

        Sends struct requests one at a time in a tight loop until NO_DATA.
        Retries failed requests up to RETRY_ATTEMPTS times.

        Args:
            label: Human-readable name for logging ("regulator" or "panel").
            store_offset: Offset added to wire index for storage (0 or 10000).
            destination: Destination address (None for default, PANEL_ADDRESS for panel).
            with_range: If True, use WITH_RANGE command; False for WITHOUT_RANGE.
            structs: Dict to add discovered entries to (mutated in place).

        Returns:
            True if all params discovered, False if failed.
        """
        wire_index = 0
        batch_size = 100  # maxNumStructDPParams (matches original)
        max_retries = 10  # generous retries - token doesn't expire
        resend_counter = 0
        batches = 0

        while True:
            entries, end_of_range = await self.fetch_param_structs(
                wire_index,
                batch_size,
                destination=destination,
                with_range=with_range,
            )

            if end_of_range:
                logger.info(
                    "Finished %s discovery (NO_DATA at wire index %d, %d batches)",
                    label,
                    wire_index,
                    batches,
                )
                return True

            if not entries:
                resend_counter += 1
                if resend_counter > max_retries:
                    logger.error(
                        "Too many failures for %s at index %d after %d retries",
                        label,
                        wire_index,
                        max_retries,
                    )
                    return False
                logger.warning(
                    "No response for %s index %d, retrying (%d/%d)",
                    label,
                    wire_index,
                    resend_counter,
                    max_retries,
                )
                continue

            resend_counter = 0
            batches += 1

            for entry in entries:
                stored_index = entry.index + store_offset
                entry.index = stored_index
                structs[stored_index] = entry

            # Advance to next batch
            last_wire = entries[-1].index - store_offset
            wire_index = last_wire + 1

        return True

    async def discover_params(self) -> int:
        """Discover all parameters in a single token grant.

        The token does NOT expire on a timer - it lasts until we
        explicitly return it. Discovery proceeds sequentially:
        first all regulator params, then all panel params.

        Address spaces:
        1. Regulator params: dest=regulator, WITH_RANGE (0x02), stored at 0+
        2. Panel params: dest=panel (100), WITHOUT_RANGE (0x01), stored at 10000+

        Returns:
            Total number of parameters discovered.
        """

        async with self._traced_lock("poll:discover_params"):
            new_structs: dict[int, ParamStructEntry] = {}

            # Wait for token from panel
            try:
                await self._wait_for_token()
            except Exception:
                logger.error("Failed to get token during discovery")
                return len(self._param_structs)

            start_time = _time.monotonic()

            try:
                # Clear reader buffer (fresh start after panel communication)
                self._connection.protocol.reset_buffer()

                # Discover regulator params first (WITH_RANGE to default dest)
                await self._discover_address_space(
                    "regulator",
                    store_offset=0,
                    destination=None,
                    with_range=True,
                    structs=new_structs,
                )

                reg_elapsed = _time.monotonic() - start_time
                reg_count = sum(1 for k in new_structs if k < 10000)
                logger.info("Regulator: %d params in %.1fs", reg_count, reg_elapsed)

                # Then discover panel params (WITHOUT_RANGE to panel address)
                await self._discover_address_space(
                    "panel",
                    store_offset=10000,
                    destination=PANEL_ADDRESS,
                    with_range=False,
                    structs=new_structs,
                )

            finally:
                if self._has_token:
                    await self._return_token()

            elapsed = _time.monotonic() - start_time

            if new_structs:
                self._param_structs = new_structs
                self._total_params = len(self._param_structs)
                reg_count = sum(1 for k in new_structs if k < 10000)
                panel_count = sum(1 for k in new_structs if k >= 10000)
                logger.info(
                    "Discovery complete: %d parameters (%d regulator, %d panel) in %.1fs",
                    self._total_params,
                    reg_count,
                    panel_count,
                    elapsed,
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

        async with self._traced_lock("poll:poll_all_params"):
            try:
                await self._wait_for_token()

                indices = sorted(self._param_structs.keys())
                total_read = 0

                current_pos = 0
                while current_pos < len(indices):
                    start_index = indices[current_pos]

                    # Find batch end, but don't cross address space boundaries
                    # (regulator 0-9999 vs panel 10000+) or exceed 255 count
                    batch_end = current_pos + 1
                    while batch_end < min(current_pos + self._params_per_request, len(indices)):
                        if indices[batch_end] - start_index >= 255:
                            break
                        if (start_index < 10000) != (indices[batch_end] < 10000):
                            break
                        batch_end += 1
                    count = indices[batch_end - 1] - start_index + 1

                    # Panel params (10000+) use wire index and panel destination
                    is_panel = start_index >= 10000
                    dest = PANEL_ADDRESS if is_panel else None
                    wire_index = start_index - 10000 if is_panel else start_index
                    offset = 10000 if is_panel else 0

                    values = None
                    for _ in range(RETRY_ATTEMPTS):
                        values = await self.fetch_param_values(
                            wire_index,
                            count,
                            destination=dest,
                            store_offset=offset,
                        )
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
                        min_val, max_val = await self._resolve_min_max(entry)
                        param = Parameter(
                            index=index,
                            name=entry.name,
                            value=value,
                            type=entry.type_code,
                            unit=entry.unit,
                            writable=entry.writable,
                            min_value=min_val,
                            max_value=max_val,
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
        poll_count = 0
        alarm_poll_interval = 5  # Read alarms every N poll cycles

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
                    await self.read_alarms()

                # Discover params on first poll if needed
                if not self._param_structs:
                    await self.discover_params()
                    await self.read_alarms()

                await self.poll_all_params()
                poll_count += 1

                if poll_count % alarm_poll_interval == 0:
                    await self.read_alarms()

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
