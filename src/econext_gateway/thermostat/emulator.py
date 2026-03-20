"""Thermostat emulator for the GM3 bus.

Responds to panel queries at a dedicated bus address, serving the
temperature value submitted by Home Assistant via the API. The panel
treats this as a real thermostat and propagates the temperature to
the controller and device table broadcasts.

All 35 parameters match the real ecoSTER 200 layout. The emulator
stores panel-written config (schedules, presets, etc.) and echoes it
back. Only param 0 (IntrSens) is injected from the HA temperature.
"""

import asyncio
import logging
import struct
from typing import Any

from econext_gateway.core.virtual_thermostat import VirtualThermostat
from econext_gateway.protocol.codec import encode_value
from econext_gateway.protocol.constants import (
    IDENTIFY_ANS_CMD,
    IDENTIFY_CMD,
    Command,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.thermostat.params import (
    SCHEDULE_PARAM_RANGE,
    TEMPERATURE_PARAM_INDEX,
    THERMOSTAT_PARAMS,
    ThermostatParam,
    get_default_value,
    get_status_byte,
)

# Re-export for handler.py imports
__all__ = ["ThermostatEmulator", "THERMOSTAT_IDENTITY", "THERMOSTAT_PAIRING_IDENTITY"]

logger = logging.getLogger(__name__)


def _build_pairing_identity() -> bytes:
    """Build SERVICE_ANS payload from params defaults.

    Format: manufacturer\\0model\\0serial\\0class\\0sub\\0version\\0
    Assembled from the same defaults used in the parameter table.
    """
    fn = get_default_value(THERMOSTAT_PARAMS[24])   # FN (serial)
    hv = get_default_value(THERMOSTAT_PARAMS[25])   # HV
    sw = get_default_value(THERMOSTAT_PARAMS[26])   # SW
    version = f"{hv}_{sw}_D6AFC__"
    return (
        b"PLUM Sp. z o.o.\x00"
        + b"ecoSTER_40\x00"           # model (same as real - panel caches struct for this model)
        + fn.encode() + b"\x00"       # serial number (different from real)
        + b"03\x00"                   # device class (same as real ecoSTER)
        + b"00\x00"                   # sub-class
        + version.encode() + b"\x00"
    )


THERMOSTAT_PAIRING_IDENTITY = _build_pairing_identity()

# IDENTIFY_ANS uses the same 67-byte payload as pairing SERVICE_ANS
# (confirmed from real ecoSTER capture: cmd=0x89 response is 67 bytes, identical)
THERMOSTAT_IDENTITY = THERMOSTAT_PAIRING_IDENTITY


class ThermostatEmulator:
    """Emulates a thermostat device on the GM3 bus.

    Handles frames addressed to the thermostat address and responds
    to panel queries (IDENTIFY, GET_PARAMS_STRUCT, GET_PARAMS, MODIFY_PARAM).
    """

    def __init__(self, address: int, virtual_thermostat: VirtualThermostat) -> None:
        self.address = address
        self._vt = virtual_thermostat
        self._params = {p.index: p for p in THERMOSTAT_PARAMS}
        # Values the panel has written to us via MODIFY_PARAM
        self._written_values: dict[int, Any] = {}
        # Only serve struct once after pairing. Re-discovery resets panel temp to 0.
        self._struct_served = False
        # Uptime counter for param 30 (Run) - matches real thermostat behaviour
        import time as _time
        self._start_time = _time.monotonic()

    def _get_param_value(self, param: ThermostatParam) -> Any:
        """Get the current value for a parameter.

        For the temperature parameter, returns the HA-submitted value.
        For other parameters, returns whatever the panel last wrote,
        or a sensible default.
        """
        if param.index == TEMPERATURE_PARAM_INDEX:
            return self._vt.effective_temperature

        # PresetNow (param 3) mirrors the HA temperature as current setpoint
        if param.index == 3:
            return self._vt.effective_temperature

        # Run (param 30): uptime counter in seconds, like real thermostat
        if param.index == 30:
            import time as _time
            return int(_time.monotonic() - self._start_time)

        # Schedules (params 9-22): always return zeros like real thermostat
        if param.index in SCHEDULE_PARAM_RANGE:
            return 0

        if param.index in self._written_values:
            return self._written_values[param.index]

        return get_default_value(param)

    async def handle_frame(self, frame: Frame, write_fn) -> bool:
        """Handle a frame addressed to the thermostat.

        Args:
            frame: Incoming frame from the bus.
            write_fn: Async callable to write a response frame.
                Signature: write_fn(frame: Frame, flush_after: bool) -> bool

        Returns:
            True if the frame was handled, False if not our address.
        """
        if frame.destination != self.address:
            return False

        if frame.command == IDENTIFY_CMD:
            return await self._handle_identify(frame, write_fn)
        elif frame.command == Command.GET_PARAMS_STRUCT_WITH_RANGE:
            return await self._handle_get_struct(frame, write_fn)
        elif frame.command == Command.GET_PARAMS:
            return await self._handle_get_params(frame, write_fn)
        elif frame.command == Command.MODIFY_PARAM:
            return await self._handle_modify_param(frame, write_fn)
        else:
            logger.info(
                "Thermostat: unhandled cmd=0x%02X from %d",
                frame.command,
                frame.source,
            )
            return False

    # Baud rate for wire transmission time calculation.
    BAUD_RATE = 115200
    # Frame overhead: start(1) + len(1) + start(1) + dst(2) + src(2) + cmd(1) + crc(1) + end(1) = 10
    FRAME_OVERHEAD = 10

    async def _respond(self, dest: int, command: int, data: bytes, write_fn) -> bool:
        """Send a response frame.

        After writing, waits for the actual wire transmission time.
        USB-to-serial converters buffer data internally: tcdrain/flush()
        returns when the kernel buffer reaches the USB device, NOT when
        the bytes are physically on the RS-485 wire.  Without this wait,
        we return to reading frames before our response has been transmitted,
        and the panel's next request arrives before we've finished responding
        to the current one.
        """
        import time as _time
        t0 = _time.monotonic()

        response = Frame(
            destination=dest,
            command=command,
            data=data,
            source=self.address,
        )

        if data:
            logger.debug(
                "Thermostat: responding cmd=0x%02X %db hex=%s",
                command, len(data), data.hex(),
            )

        # flush_after=True drains TX to wire; clear_echo=False preserves RX
        # buffer so the panel's next frame isn't destroyed on half-duplex bus.
        success = await write_fn(response, flush_after=True, clear_echo=False)
        write_ms = (_time.monotonic() - t0) * 1000

        # Wait for the USB converter to physically transmit the bytes.
        # 8N1 = 10 bits per byte.  Add a small margin for USB scheduling.
        frame_bytes = len(data) + self.FRAME_OVERHEAD
        wire_time = frame_bytes * 10 / self.BAUD_RATE
        await asyncio.sleep(wire_time + 0.002)  # +2ms USB margin

        total_ms = (_time.monotonic() - t0) * 1000
        logger.debug(
            "Thermostat: write=%.1fms total=%.1fms (wire=%.1fms) %db success=%s",
            write_ms, total_ms, wire_time * 1000, len(data), success,
        )
        return success

    async def _handle_identify(self, frame: Frame, write_fn) -> bool:
        """Respond to IDENTIFY probe from panel."""
        await self._respond(
            frame.source, IDENTIFY_ANS_CMD, THERMOSTAT_IDENTITY, write_fn
        )
        logger.debug("Thermostat: responded to IDENTIFY from %d", frame.source)
        return True

    # Max struct response size in bytes (excluding frame overhead).
    # Real ecoSTER batches at ~230-234 bytes. Using 240 as limit produces
    # identical batching: 14 params (230b), 16 params (234b), 5 params (73b).
    MAX_STRUCT_RESPONSE_BYTES = 240

    async def _handle_get_struct(self, frame: Frame, write_fn) -> bool:
        """Respond to GET_PARAMS_STRUCT_WITH_RANGE request.

        Batches the response to match the real ecoSTER thermostat's behavior.
        The panel expects multiple batched responses, not all params at once.
        """
        if len(frame.data) < 3:
            return False

        count = frame.data[0]
        start_index = struct.unpack("<H", frame.data[1:3])[0]

        params_in_range = [
            p for p in THERMOSTAT_PARAMS if start_index <= p.index < start_index + count
        ]

        if not params_in_range:
            await self._respond(
                frame.source, Command.NO_DATA, b"", write_fn
            )
            logger.debug(
                "Thermostat: NO_DATA for struct request start=%d count=%d",
                start_index,
                count,
            )
            return True

        # Limit batch size to match real thermostat response sizes.
        # Calculate how many params fit within MAX_STRUCT_RESPONSE_BYTES.
        batch = []
        batch_size = 3  # header: count(1) + start_index(2)
        for p in params_in_range:
            # Each param: name\0 + unit\0 + type_byte + extra_byte + min(2) + max(2)
            param_size = len(p.name) + len(p.unit_string) + 8
            if batch_size + param_size > self.MAX_STRUCT_RESPONSE_BYTES and batch:
                break
            batch.append(p)
            batch_size += param_size

        data = build_struct_with_range_response(batch, start_index)
        await self._respond(
            frame.source, Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, data, write_fn
        )
        logger.debug(
            "Thermostat: sent struct response for %d params starting at %d (%d bytes)",
            len(batch),
            start_index,
            len(data),
        )
        return True

    async def _handle_get_params(self, frame: Frame, write_fn) -> bool:
        """Respond to GET_PARAMS request.

        The panel sends this to read current parameter values.
        Response uses status-byte format: [count][start_LE] then [status][value] per param.
        """
        if len(frame.data) < 3:
            return False

        count = frame.data[0]
        start_index = struct.unpack("<H", frame.data[1:3])[0]

        params_in_range = [
            p for p in THERMOSTAT_PARAMS if start_index <= p.index < start_index + count
        ]

        if not params_in_range:
            await self._respond(
                frame.source, Command.NO_DATA, b"", write_fn
            )
            logger.debug(
                "Thermostat: NO_DATA for params request start=%d count=%d",
                start_index,
                count,
            )
            return True

        values = [(p, self._get_param_value(p)) for p in params_in_range]
        data = build_params_response(values, start_index, self._written_values)
        await self._respond(
            frame.source, Command.GET_PARAMS_RESPONSE, data, write_fn
        )
        logger.info(
            "Thermostat: sent %d param values (temp=%.2f) starting at %d",
            len(params_in_range),
            self._vt.effective_temperature,
            start_index,
        )
        return True

    @staticmethod
    def _skip_auth_prefix(data: bytes) -> bytes:
        """Skip the auth prefix in MODIFY_PARAM data.

        Panel sends: USER-001\\04096\\0<payload>
        Two null-terminated strings followed by the actual param data.
        """
        try:
            first_null = data.index(0)
            second_null = data.index(0, first_null + 1)
            return data[second_null + 1:]
        except ValueError:
            return data  # No auth prefix, use as-is

    async def _handle_modify_param(self, frame: Frame, write_fn) -> bool:
        """Handle MODIFY_PARAM from panel.

        The panel writes configuration to the thermostat (schedules, comfort
        temps, etc.). Data format: auth prefix + count(1) + param_index(2) + value_bytes.
        We store the raw value bytes so we can echo them back exactly in GET_PARAMS.
        """
        if frame.data and len(frame.data) >= 3:
            # Skip auth prefix (e.g., "USER-001\04096\0")
            payload = self._skip_auth_prefix(frame.data)
            logger.debug(
                "Thermostat: MODIFY_PARAM raw=%db payload=%db hex=%s",
                len(frame.data),
                len(payload),
                payload.hex() if payload else "",
            )
            if len(payload) >= 3:
                count = payload[0]
                param_index = struct.unpack("<H", payload[1:3])[0]
                value_bytes = payload[3:]
                param = self._params.get(param_index)
                if param is not None:
                    self._written_values[param_index] = value_bytes
                    logger.info(
                        "Thermostat: stored MODIFY_PARAM idx=%d (%s, %d bytes): %s",
                        param_index,
                        param.name,
                        len(value_bytes),
                        value_bytes.hex(),
                    )
                else:
                    logger.warning(
                        "Thermostat: MODIFY_PARAM unknown param idx=%d",
                        param_index,
                    )

        await self._respond(
            frame.source, Command.MODIFY_PARAM_RESPONSE, b"\x00", write_fn
        )
        return True


def build_struct_with_range_response(
    params: list[ThermostatParam], first_index: int
) -> bytes:
    """Build GET_PARAMS_STRUCT_WITH_RANGE response payload.

    Wire format:
        [paramsNo][firstIndex_L][firstIndex_H]
        For each param:
            [name_string...][0x00]     (null-terminated)
            [unit_string...][0x00]     (null-terminated)
            [type_byte][extra_byte]    (type: low 4 bits = code, bit 5 = writable)
            [min_L][min_H][max_L][max_H]  (literal range as int16)
    """
    buf = bytearray()
    buf.append(len(params))
    buf.extend(struct.pack("<H", first_index))

    for p in params:
        buf.extend(p.name.encode("utf-8"))
        buf.append(0x00)

        buf.extend(p.unit_string.encode("utf-8"))
        buf.append(0x00)

        type_byte = p.type_code & 0x0F
        if p.writable:
            type_byte |= 0x20
        buf.append(type_byte)

        buf.append(0x00)  # extra byte

        buf.extend(struct.pack("<h", int(p.min_value)))
        buf.extend(struct.pack("<h", int(p.max_value)))

    return bytes(buf)


def build_params_response(
    param_values: list[tuple[ThermostatParam, Any]],
    first_index: int,
    written_values: dict[int, Any] | None = None,
) -> bytes:
    """Build GET_PARAMS response payload.

    Wire format (matching real ecoSTER):
        [paramsNo][firstIndex_L][firstIndex_H]
        For each param: [status_byte][value_bytes]

    Status byte precedes each value (not a trailing separator).
    """
    if written_values is None:
        written_values = {}

    buf = bytearray()
    buf.append(len(param_values))
    buf.extend(struct.pack("<H", first_index))

    for param, value in param_values:
        was_written = param.index in written_values
        status = get_status_byte(param, was_written)
        buf.append(status)

        # Echo raw MODIFY_PARAM bytes, but not for schedules (real
        # thermostat always returns zeros for schedules regardless)
        if (
            was_written
            and param.index not in SCHEDULE_PARAM_RANGE
            and isinstance(written_values[param.index], (bytes, bytearray))
        ):
            buf.extend(written_values[param.index])
        else:
            encoded = encode_value(value, param.type_code)
            buf.extend(encoded)

    return bytes(buf)
