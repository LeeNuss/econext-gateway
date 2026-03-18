"""Thermostat parameter table definition.

Defines the parameters that a virtual thermostat exposes to the panel.
The panel reads these via GET_PARAMS_STRUCT_WITH_RANGE (0x02) and
GET_PARAMS (0x40) commands.

TODO: This is a placeholder table. Once the protocol capture (Step 0)
provides the real thermostat parameter names, types, and indices, this
table should be updated to match exactly what a real ecoSTER thermostat
reports. The temperature index is the critical one -- the panel reads
it to get the room temperature.
"""

from econext_gateway.protocol.constants import DataType

# Reverse mapping: unit code -> wire string (inverse of handler.UNIT_STRING_MAP)
UNIT_CODE_TO_STRING = {
    0: "",
    1: "C",
    2: "s",
    3: "min",
    4: "h",
    5: "d",
    6: "%",
    7: "kW",
    8: "kWh",
}


class ThermostatParam:
    """Definition of a single thermostat parameter."""

    __slots__ = ("index", "name", "unit_code", "type_code", "writable", "min_value", "max_value")

    def __init__(
        self,
        index: int,
        name: str,
        type_code: int,
        unit_code: int = 0,
        writable: bool = False,
        min_value: int = 0,
        max_value: int = 0,
    ):
        self.index = index
        self.name = name
        self.type_code = type_code
        self.unit_code = unit_code
        self.writable = writable
        self.min_value = min_value
        self.max_value = max_value

    @property
    def unit_string(self) -> str:
        return UNIT_CODE_TO_STRING.get(self.unit_code, "")


# Index of the room temperature parameter within the thermostat.
# TODO: Update after protocol capture reveals the real index.
TEMPERATURE_PARAM_INDEX = 0

# Placeholder parameter table.
# After protocol capture, replace with the real thermostat parameters.
# The panel expects to discover these via GET_PARAMS_STRUCT_WITH_RANGE.
THERMOSTAT_PARAMS: list[ThermostatParam] = [
    ThermostatParam(
        index=0,
        name="RoomTemperature",
        type_code=DataType.FLOAT,
        unit_code=1,  # Celsius
        writable=False,
        min_value=0,
        max_value=50,
    ),
]
