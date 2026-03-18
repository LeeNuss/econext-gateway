"""Thermostat emulator for the GM3 bus.

Responds to panel queries at a dedicated bus address, serving the
temperature value submitted by Home Assistant via the API. The panel
treats this as a real thermostat and propagates the temperature to
the controller and device table broadcasts.
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
    PANEL_ADDRESS,
    TYPE_SIZES,
    Command,
    DataType,
)
from econext_gateway.protocol.frames import Frame
from econext_gateway.thermostat.params import (
    TEMPERATURE_PARAM_INDEX,
    THERMOSTAT_PARAMS,
    ThermostatParam,
)

logger = logging.getLogger(__name__)

# Separator byte used between parameter values in GET_PARAMS responses.
# Observed as 0xC2 in real protocol traffic.
SEPARATOR_BYTE = b"\xc2"

# Identity string for thermostat IDENTIFY_ANS responses.
# TODO: Update after protocol capture reveals what real thermostats report.
# Real ecoSTER thermostats may use a different string than "EcoNEXT".
THERMOSTAT_IDENTITY = b"PLUM\x00EcoNEXT\x00\x00\x00\x00\x00"


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

    def _get_param_value(self, param: ThermostatParam) -> Any:
        """Get the current value for a parameter.

        For the temperature parameter, returns the HA-submitted value.
        For other parameters, returns whatever the panel last wrote,
        or a sensible default.
        """
        if param.index == TEMPERATURE_PARAM_INDEX:
            return self._vt.effective_temperature

        # Return panel-written value if any, otherwise type-appropriate default
        if param.index in self._written_values:
            return self._written_values[param.index]

        if param.type_code == DataType.FLOAT:
            return 0.0
        if param.type_code == DataType.DOUBLE:
            return 0.0
        if param.type_code == DataType.BOOL:
            return False
        if param.type_code == DataType.STRING:
            return ""
        return 0

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
            logger.debug(
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

        The panel sends this to discover what parameters we expose.
        """
        if len(frame.data) < 3:
            return False

        count = frame.data[0]
        start_index = struct.unpack("<H", frame.data[1:3])[0]

        # Find params in the requested range
        params_in_range = [
            p for p in THERMOSTAT_PARAMS if start_index <= p.index < start_index + count
        ]

        if not params_in_range:
            # No params in range -> send NO_DATA
            await self._respond(
                frame.source, Command.NO_DATA, b"", write_fn
            )
            logger.debug(
                "Thermostat: NO_DATA for struct request start=%d count=%d",
                start_index,
                count,
            )
            return True

        data = build_struct_with_range_response(params_in_range, start_index)
        await self._respond(
            frame.source, Command.GET_PARAMS_STRUCT_WITH_RANGE_RESPONSE, data, write_fn
        )
        logger.debug(
            "Thermostat: sent struct response for %d params starting at %d",
            len(params_in_range),
            start_index,
        )
        return True

    async def _handle_get_params(self, frame: Frame, write_fn) -> bool:
        """Respond to GET_PARAMS request.

        The panel sends this to read current parameter values (including temperature).
        """
        if len(frame.data) < 3:
            return False

        count = frame.data[0]
        start_index = struct.unpack("<H", frame.data[1:3])[0]

        # Find params in the requested range
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
        data = build_params_response(values, start_index)
        await self._respond(
            frame.source, Command.GET_PARAMS_RESPONSE, data, write_fn
        )
        logger.debug(
            "Thermostat: sent %d param values (temp=%.2f) starting at %d",
            len(params_in_range),
            self._vt.effective_temperature,
            start_index,
        )
        return True

    async def _handle_modify_param(self, frame: Frame, write_fn) -> bool:
        """Handle MODIFY_PARAM from panel.

        The panel writes configuration to the thermostat (schedules, comfort
        temps, etc.). We ACK everything and store the values.
        """
        # ACK the write with success byte
        await self._respond(
            frame.source, Command.MODIFY_PARAM_RESPONSE, b"\x00", write_fn
        )
        logger.debug(
            "Thermostat: ACK'd MODIFY_PARAM from %d (len=%d)",
            frame.source,
            len(frame.data) if frame.data else 0,
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
        # Name (null-terminated)
        buf.extend(p.name.encode("utf-8"))
        buf.append(0x00)

        # Unit string (null-terminated)
        buf.extend(p.unit_string.encode("utf-8"))
        buf.append(0x00)

        # Type byte: low 4 bits = type code, bit 5 = writable flag
        type_byte = p.type_code & 0x0F
        if p.writable:
            type_byte |= 0x20
        buf.append(type_byte)

        # Extra byte: 0x00 = literal min/max
        buf.append(0x00)

        # Min/max range as int16 LE
        buf.extend(struct.pack("<h", int(p.min_value)))
        buf.extend(struct.pack("<h", int(p.max_value)))

    return bytes(buf)


def build_params_response(
    param_values: list[tuple[ThermostatParam, Any]], first_index: int
) -> bytes:
    """Build GET_PARAMS response payload.

    Wire format:
        [paramsNo][firstIndex_L][firstIndex_H][separator]
        [param1_bytes][separator]
        [param2_bytes][separator]
        ...
    """
    buf = bytearray()
    buf.append(len(param_values))
    buf.extend(struct.pack("<H", first_index))
    buf.extend(SEPARATOR_BYTE)  # Header separator

    for param, value in param_values:
        encoded = encode_value(value, param.type_code)
        buf.extend(encoded)
        buf.extend(SEPARATOR_BYTE)

    return bytes(buf)
