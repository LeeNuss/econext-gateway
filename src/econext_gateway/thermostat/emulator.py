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
        + b"ecoSTER_41\x00"           # model (must match real for panel acceptance)
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

    async def _respond(self, dest: int, command: int, data: bytes, write_fn) -> bool:
        """Send a response frame with RS-485 turnaround delay."""
        await asyncio.sleep(0.02)  # 20ms RS-485 turnaround
        response = Frame(
            destination=dest,
            command=command,
            data=data,
            source=self.address,
        )
        success = await write_fn(response, flush_after=True)
        return success

    async def _handle_identify(self, frame: Frame, write_fn) -> bool:
        """Respond to IDENTIFY probe from panel."""
        await self._respond(
            frame.source, IDENTIFY_ANS_CMD, THERMOSTAT_IDENTITY, write_fn
        )
        logger.info("Thermostat: responded to IDENTIFY from %d", frame.source)
        return True

    async def _handle_get_struct(self, frame: Frame, write_fn) -> bool:
        """Respond to GET_PARAMS_STRUCT_WITH_RANGE request.

        Only serves the struct once after pairing. Subsequent re-discovery
        requests get NO_DATA because the panel resets the temperature to 0.0
        when it re-discovers the struct.
        """
        if len(frame.data) < 3:
            return False

        count = frame.data[0]
        start_index = struct.unpack("<H", frame.data[1:3])[0]

        # Block struct re-discovery after initial serve
        if self._struct_served and start_index == 0:
            await self._respond(
                frame.source, Command.NO_DATA, b"", write_fn
            )
            logger.info("Thermostat: blocking struct re-discovery (already served)")
            return True

        params_in_range = [
            p for p in THERMOSTAT_PARAMS if start_index <= p.index < start_index + count
        ]

        if not params_in_range:
            # End of struct - mark as fully served
            if self._struct_served is False and start_index > 0:
                self._struct_served = True
                logger.info("Thermostat: struct fully served, will block re-discovery")
            await self._respond(
                frame.source, Command.NO_DATA, b"", write_fn
            )
            logger.info(
                "Thermostat: NO_DATA for struct request start=%d count=%d",
                start_index,
                count,
            )
            return True

        data = build_struct_with_range_response(params_in_range, start_index)
        await self._respond(
            frame.source, Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, data, write_fn
        )
        logger.info(
            "Thermostat: sent struct response for %d params starting at %d",
            len(params_in_range),
            start_index,
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
            logger.info(
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

    async def _handle_modify_param(self, frame: Frame, write_fn) -> bool:
        """Handle MODIFY_PARAM from panel.

        The panel writes configuration to the thermostat (schedules, comfort
        temps, etc.). We ACK everything and store the raw data bytes so we
        can echo them back exactly in GET_PARAMS.
        """
        if frame.data and len(frame.data) >= 3:
            param_index = struct.unpack("<H", frame.data[0:2])[0]
            param = self._params.get(param_index)
            if param is not None:
                # Store the raw value bytes for exact echo-back
                value_bytes = frame.data[2:]
                self._written_values[param_index] = value_bytes
                logger.info(
                    "Thermostat: stored MODIFY_PARAM idx=%d (%d bytes)",
                    param_index,
                    len(value_bytes),
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

        # If we have raw bytes from MODIFY_PARAM, echo them exactly
        if was_written and isinstance(written_values[param.index], (bytes, bytearray)):
            buf.extend(written_values[param.index])
        else:
            encoded = encode_value(value, param.type_code)
            buf.extend(encoded)

    return bytes(buf)
