"""Thermostat parameter table definition.

Defines the 35 parameters that a virtual thermostat exposes to the panel,
matching the real ecoSTER 200 thermostat layout. Decoded from protocol
capture on 2026-03-18.

The panel reads the struct via GET_PARAMS_STRUCT_WITH_RANGE (0x02) and
values via GET_PARAMS (0x40). Writable params are set by the panel via
MODIFY_PARAM (0x29) -- the emulator stores and echoes them back.
Only param 0 (IntrSens) is injected from the HA temperature submission.
"""

from __future__ import annotations

import math
import struct
import time
from typing import Any

from econext_gateway.protocol.constants import DataType


class ThermostatParam:
    """Definition of a single thermostat parameter."""

    __slots__ = (
        "index", "name", "unit_string", "type_code",
        "writable", "min_value", "max_value", "default",
    )

    def __init__(
        self,
        index: int,
        name: str,
        type_code: int,
        unit_string: str = "",
        writable: bool = False,
        min_value: int = 0,
        max_value: int = 0,
        default: Any = None,
    ):
        self.index = index
        self.name = name
        self.type_code = type_code
        self.unit_string = unit_string
        self.writable = writable
        self.min_value = min_value
        self.max_value = max_value
        self.default = default


# Index of the room temperature parameter.
TEMPERATURE_PARAM_INDEX = 0

# Status bytes that precede each value in GET_PARAMS response.
# From GM3 spec: b0=measured, b7=discontinuity.
STATUS_DEFAULT = 0x00      # RO non-measured params, strings, counters
STATUS_MODIFIED = 0x01     # Writable settings that have been written by panel
STATUS_MEASURED = 0x81     # Measured values, schedules, monitors

# Full parameter table matching real ecoSTER 200 (35 params).
# Decoded from GET_PARAMS_STRUCT_WITH_RANGE capture 2026-03-18.
THERMOSTAT_PARAMS: list[ThermostatParam] = [
    # Param 0: room temperature - injected from HA
    ThermostatParam(0, "IntrSens", DataType.FLOAT, "'C"),
    # Param 1-2: mode and alarm mask - panel-written
    ThermostatParam(1, "WorkMode", DataType.UINT8, writable=True),
    ThermostatParam(2, "AlMsk", DataType.UINT32, writable=True),
    # Param 3: current setpoint - derived from schedule/mode
    ThermostatParam(3, "PresetNow", DataType.FLOAT, "'C"),
    # Param 4-6: temperature presets and hysteresis - panel-written
    ThermostatParam(4, "PrDay", DataType.FLOAT, "'C", writable=True, min_value=10, max_value=35),
    ThermostatParam(5, "PrNight", DataType.FLOAT, "'C", writable=True, min_value=10, max_value=35),
    ThermostatParam(6, "Hyst", DataType.FLOAT, "'C", writable=True, min_value=-4, max_value=4),
    # Param 7-8: monitor flags - panel-written
    ThermostatParam(7, "MonitA", DataType.UINT32, writable=True),
    ThermostatParam(8, "MonitB", DataType.UINT32, writable=True),
    # Param 9-22: weekly schedule (7 days x 2 slots) - panel-written
    ThermostatParam(9, "Schedule A Sun.", DataType.UINT32, writable=True),
    ThermostatParam(10, "S B Sun.", DataType.UINT16, writable=True),
    ThermostatParam(11, "S A Mon.", DataType.UINT32, writable=True),
    ThermostatParam(12, "S B Mon.", DataType.UINT16, writable=True),
    ThermostatParam(13, "S A Tue.", DataType.UINT32, writable=True),
    ThermostatParam(14, "S B Tue.", DataType.UINT16, writable=True),
    ThermostatParam(15, "S A Wed.", DataType.UINT32, writable=True),
    ThermostatParam(16, "S B Wed.", DataType.UINT16, writable=True),
    ThermostatParam(17, "S A Thu.", DataType.UINT32, writable=True),
    ThermostatParam(18, "S B Thu.", DataType.UINT16, writable=True),
    ThermostatParam(19, "S A Fri.", DataType.UINT32, writable=True),
    ThermostatParam(20, "S B Fri.", DataType.UINT16, writable=True),
    ThermostatParam(21, "S A Sat.", DataType.UINT32, writable=True),
    ThermostatParam(22, "S B Sat.", DataType.UINT16, writable=True),
    # Param 23: external sensor - not connected
    ThermostatParam(23, "ExtSens", DataType.FLOAT, "'C"),
    # Param 24-27: identity strings
    ThermostatParam(24, "FN", DataType.STRING, writable=True, max_value=11,
                    default="ecoNext_VIRT"),
    ThermostatParam(25, "HV", DataType.STRING, max_value=7,
                    default="H0.0.1"),
    ThermostatParam(26, "SW", DataType.STRING, max_value=8,
                    default="S000.01"),
    ThermostatParam(27, "", DataType.STRING, max_value=21,
                    default="Mar 18 2026 00:00:00"),
    # Param 28-29: test
    ThermostatParam(28, "TestStart", DataType.UINT8, writable=True, max_value=1),
    ThermostatParam(29, "TestRes", DataType.UINT8),
    # Param 30-32: runtime and diagnostics
    ThermostatParam(30, "Run", DataType.UINT32, "s"),
    ThermostatParam(31, "RstCause", DataType.UINT8),
    ThermostatParam(32, "Rtc CV", DataType.UINT8),
    # Param 33-34: anti-freeze and correction - panel-written
    ThermostatParam(33, "Afrz", DataType.FLOAT, "'C", writable=True, min_value=5, max_value=30),
    ThermostatParam(34, "Corr", DataType.FLOAT, "'C", writable=True, min_value=-4, max_value=4),
]


def get_status_byte(param: ThermostatParam, was_written: bool) -> int:
    """Get the status byte for a param in the GET_PARAMS response."""
    if param.index == TEMPERATURE_PARAM_INDEX:
        return STATUS_DEFAULT  # measured but we use 0x00 like real thermostat
    if was_written:
        return STATUS_MODIFIED
    if param.writable and param.type_code in (DataType.UINT32, DataType.UINT16):
        return STATUS_MEASURED  # schedule/monitor params
    return STATUS_DEFAULT


def get_default_value(param: ThermostatParam) -> Any:
    """Get the default value for a parameter that hasn't been written by the panel."""
    if param.default is not None:
        return param.default
    if param.index == 23:  # ExtSens - not connected
        return float("nan")
    if param.index == 30:  # Run - uptime in seconds
        return 0
    if param.type_code == DataType.FLOAT:
        return 0.0
    if param.type_code == DataType.STRING:
        return ""
    return 0
