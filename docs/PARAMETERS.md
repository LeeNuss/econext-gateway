# API Parameters Reference

This document describes commonly used parameters for GM3 protocol heat pump controllers.

## Parameter Structure

Each parameter has these attributes:

- **Index**: Unique identifier (0-65535)
- **Name**: Human-readable name
- **Type**: Data type (`float`, `int`, `bool`, `string`)
- **Unit**: Display unit (°C, %, kW, etc.)
- **Writable**: Whether parameter can be modified
- **Min/Max**: Valid range (for writable numeric parameters)

## Temperature Parameters

### Current Temperatures (Read-Only)

| Name        | Index  | Type  | Unit | Description                    |
| ----------- | ------ | ----- | ---- | ------------------------------ |
| OutsideTemp | varies | float | °C   | Outdoor ambient temperature    |
| BOILER_TEMP | varies | float | °C   | Boiler/buffer tank temperature |
| ReturnTemp  | varies | float | °C   | Return water temperature       |
| SupplyTemp  | varies | float | °C   | Supply water temperature       |
| HDWTemp     | varies | float | °C   | Domestic hot water temperature |

### Temperature Setpoints (Writable)

| Name            | Index | Type | Unit | Min    | Max    | Description                     |
| --------------- | ----- | ---- | ---- | ------ | ------ | ------------------------------- |
| HDWTSetPoint    | 103   | int  | °C   | 35     | 65     | Hot water target temperature    |
| HDWTempKeepWarm | 109   | int  | °C   | varies | varies | Hot water keep warm temperature |
| HDWMinSetTemp   | 107   | int  | °C   | 20     | varies | Minimum hot water temperature   |
| HDWMaxSetTemp   | 108   | int  | °C   | varies | 75     | Maximum hot water temperature   |

## Operating Mode

| Name               | Index | Type | Values                  | Description                       |
| ------------------ | ----- | ---- | ----------------------- | --------------------------------- |
| HDWusermode        | 119   | int  | 0=Off, 1=On, 2=Schedule | Hot water mode                    |
| HDWStartOneLoading | 115   | int  | 0=Off, 1=On             | Start single hot water load cycle |

## Status Parameters (Read-Only)

| Name               | Index Range | Type | Unit | Description              |
| ------------------ | ----------- | ---- | ---- | ------------------------ |
| compressor_running | 200-300     | bool | -    | Compressor active status |
| circulation_pump   | 200-300     | bool | -    | Circulation pump status  |
| heating_active     | 200-300     | bool | -    | Heating circuit active   |
| dhw_loading        | 200-300     | bool | -    | Hot water tank loading   |
| defrost_active     | 200-300     | bool | -    | Defrost cycle active     |

## Energy Monitoring

| Name              | Index Range | Type  | Unit | Description                |
| ----------------- | ----------- | ----- | ---- | -------------------------- |
| power_consumption | 400-500     | float | kW   | Current power draw         |
| energy_total      | 400-500     | float | kWh  | Total energy consumed      |
| cop               | 400-500     | float | -    | Coefficient of performance |
| heating_energy    | 400-500     | float | kWh  | Heating energy produced    |

## System Configuration

| Name             | Index Range | Type  | Unit | Min   | Max | Description                      |
| ---------------- | ----------- | ----- | ---- | ----- | --- | -------------------------------- |
| hysteresis       | 300-400     | float | °C   | 0.5   | 5.0 | Temperature control hysteresis   |
| pump_delay       | 300-400     | int   | s    | 0     | 300 | Pump start delay                 |
| anti_freeze_temp | 300-400     | float | °C   | -10.0 | 5.0 | Anti-freeze protection threshold |

## Network Parameters (Read-Only)

These parameters provide network status information:

| Name         | Index | Type   | Description                 |
| ------------ | ----- | ------ | --------------------------- |
| wifi_status  | 376   | int    | WiFi connection status      |
| wifi_quality | 380   | int    | WiFi signal quality (0-100) |
| eth_status   | 387   | int    | Ethernet connection status  |
| wifi_ip      | 381   | string | WiFi IP address             |
| eth_ip       | 384   | string | Ethernet IP address         |

## System Information (Read-Only)

| Name             | Index Range | Type   | Description              |
| ---------------- | ----------- | ------ | ------------------------ |
| device_name      | 0-50        | string | Controller model name    |
| software_version | 0-50        | string | Firmware version         |
| uid              | 0-50        | int    | Unique device identifier |
| uptime           | 0-50        | int    | System uptime in seconds |

## Parameter Discovery

Not all parameters are available on all controllers. The actual parameter set depends on:

- Controller model (ecotronic100, ecotronic200, etc.)
- Firmware version
- Hardware configuration
- Installed modules/sensors

Use the `GET /api/parameters` endpoint to discover available parameters for your specific controller.

## Parameter Names

The API uses the exact parameter names from the controller protocol. Common parameters include:

| Parameter Name     | Description                    | Typical Index |
| ------------------ | ------------------------------ | ------------- |
| OutsideTemp        | Outdoor sensor temperature     | varies        |
| HDWTemp            | Domestic hot water temperature | varies        |
| HDWTSetPoint       | Hot water target temperature   | 103           |
| HDWusermode        | Hot water operating mode       | 119           |
| HDWStartOneLoading | Start hot water load cycle     | 115           |

Note: Parameter names are case-sensitive and match the controller's internal naming.

## Data Types

### Float
Decimal values with 1-2 decimal places. Used for temperatures, power, energy.

Example: `22.5`, `45.0`, `3.14`

### Integer
Whole numbers. Used for setpoints, modes, status codes.

Example: `45`, `0`, `100`

### Boolean
True/false values represented as:
- `true` / `false` in JSON
- `1` / `0` in protocol

### String
Text values. Used for names, versions, IP addresses.

Example: `"ecotronic100"`, `"1.2.3"`, `"192.168.1.100"`

## Units

Common unit codes:

| Code | Unit | Used For                     |
| ---- | ---- | ---------------------------- |
| 0    | -    | Dimensionless (mode, status) |
| 1    | °C   | Temperature                  |
| 2    | s    | Seconds                      |
| 3    | min  | Minutes                      |
| 4    | h    | Hours                        |
| 6    | %    | Percentage                   |
| 7    | kW   | Power                        |
| 8    | kWh  | Energy                       |

## Value Constraints

Writable parameters have constraints:

- **Type constraint**: Value must match parameter type
- **Range constraint**: Numeric values must be within min/max
- **Enum constraint**: Must be one of allowed values (for mode parameters)


# gm3-pomp Parameter Reference

## Info Field Encoding

The `info` field encodes the parameter type and editability:
- **Bits 0-3 (0x0F)**: Base type
- **Bit 5 (0x20)**: Editable flag (1 = editable, 0 = read-only)

| Info | Hex  | Base Type | Editable |
| ---- | ---- | --------- | -------- |
| 18   | 0x12 | int16     | No       |
| 19   | 0x13 | int32     | No       |
| 20   | 0x14 | uint8     | No       |
| 21   | 0x15 | uint16    | No       |
| 22   | 0x16 | uint32    | No       |
| 23   | 0x17 | float     | No       |
| 26   | 0x1a | bool      | No       |
| 28   | 0x1c | string    | No       |
| 49   | 0x31 | int8      | Yes      |
| 50   | 0x32 | int16     | Yes      |
| 51   | 0x33 | int32     | Yes      |
| 52   | 0x34 | uint8     | Yes      |
| 53   | 0x35 | uint16    | Yes      |
| 54   | 0x36 | uint32    | Yes      |
| 55   | 0x37 | float     | Yes      |
| 60   | 0x3c | string    | Yes      |

## Parameter List

### Editable Parameters

**Mechanism Legend:**
- **bitfield**: Multiple boolean flags packed into bits of an integer
- **enum**: Discrete values representing states/modes (e.g., 0=Off, 1=Eco, 2=Comfort, 3=Auto)
- **bool**: Boolean on/off (0 or 1)
- **schedule**: Time slot encoding for weekly schedules (AM/PM halves)
- **numeric**: Direct numeric value (temperature, time, percentage, etc.)
- **string**: Text value

| ID    | Name                                       | Type   | Min | Max   | Mechanism | Access     |
| ----- | ------------------------------------------ | ------ | --- | ----- | --------- | ---------- |
| 5     | FactorySetup                               | uint8  | 0   | 0     |           |            |
| 6     | RTCSet                                     | uint8  | 0   | 0     |           |            |
| 7     | FlashsaveParams                            | uint8  | 0   | 0     |           |            |
| 8     | FlasherasePArams                           | uint8  | 0   | 0     | bool      |            |
| 9     | FN                                         | string | 0   | 0     | string    |            |
| 16    | TesterModuleKey                            | uint32 | 0   | 0     |           |            |
| 19    | currentSchemat                             | uint16 | 0   | 0     |           | Persistent |
| 20    | prevSchemat                                | uint16 | 0   | 0     |           | Persistent |
| 41    | ADCA0_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 42    | ADCA1_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 43    | ADCA2_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 44    | ADCA3_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 45    | ADCA4_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 46    | ADCA5_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 47    | ADCA6_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 48    | ADCA7_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 49    | ADCB0_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 50    | ADCB1_CORRECT                              | float  | -5  | 5     | numeric   | Persistent |
| 60    | analogONOFF                                | uint16 | 0   | 0     |           |            |
| 69    | TempSettings                               | uint32 | 0   | 0     | bitfield  | Persistent |
| 84    | flapValveSettings                          | uint8  | 0   | 0     |           | Persistent |
| 98    | ZT_settings                                | uint32 | 0   | 0     |           | Persistent |
| 101   | HDWSETTINGS                                | uint32 | 0   | 0     |           | Persistent |
| 103   | HDWTSetPoint                               | uint8  | 35  | 65    | numeric   | Persistent |
| 104   | HDWTSetPointDownHist                       | uint8  | 5   | 18    | numeric   | Persistent |
| 105   | HDWMinmalHisteresis                        | uint8  | 1   | 0     | numeric   | Persistent |
| 107   | HDWMinSetTemp                              | uint8  | 20  | 0     |           | Persistent |
| 108   | HDWMaxSetTemp                              | uint8  | 0   | 75    | numeric   | Persistent |
| 109   | HDWTempKeepWarm                            | uint8  | 0   | 0     |           | Persistent |
| 112   | HDWMaxTempHist                             | uint8  | 0   | 10    | numeric   | Persistent |
| 113   | HDWLoadTime                                | uint8  | 0   | 50    | numeric   | Persistent |
| 115   | HDWStartOneLoading                         | uint8  | 0   | 0     | bool      |            |
| 117   | HDWSupplyHist                              | uint8  | 3   | 15    | numeric   |            |
| 118   | HDWHarmonogramSettings                     | uint32 | 0   | 0     | bitfield  | Persistent |
| 119   | HDWusermode                                | uint8  | 0   | 0     | enum      | Persistent |
| 120   | HDWSundayAM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 121   | HDWSundayPM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 122   | HDWMondayAM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 123   | HDWMondayPM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 124   | HDWTuesdayAM                               | uint32 | 0   | 0     | schedule  | Persistent |
| 125   | HDWTuesdayPM                               | uint32 | 0   | 0     | schedule  | Persistent |
| 126   | HDWWednesdayAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 127   | HDWWednesdayPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 128   | HDWThursdayAM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 129   | HDWThursdayPM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 130   | HDWFridayAM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 131   | HDWFridayPM                                | uint32 | 0   | 0     | schedule  | Persistent |
| 132   | HDWSaturdayAM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 133   | HDWSaturdayPM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 135   | HDWStartLegion                             | uint8  | 0   | 1     | bool      |            |
| 136   | HDWLegionSetPoint                          | uint8  | 60  | 80    | numeric   | Persistent |
| 137   | HDWLegionDay                               | uint8  | 0   | 6     | enum      | Persistent |
| 138   | HDWLegionHour                              | uint8  | 0   | 23    | numeric   | Persistent |
| 139   | HDWHeatSource                              | uint8  | 0   | 0     | enum      | Persistent |
| 143   | heatersSett                                | uint8  | 0   | 0     |           | Persistent |
| 144   | heatersPermTemp                            | int8   | 0   | 20    | numeric   | Persistent |
| 145   | heatersForceTemp                           | int8   | -10 | 0     |           | Persistent |
| 146   | heaterDhwDel                               | uint8  | 0   | 240   | numeric   | Persistent |
| 147   | heaterBuffDel                              | uint8  | 0   | 240   | numeric   | Persistent |
| 151   | AntifreezeSett                             | uint32 | 0   | 0     |           | Persistent |
| 153   | AntifreezeStartTemp                        | uint8  | 5   | 15    | numeric   | Persistent |
| 154   | AntifreezeEndTemp                          | uint8  | 0   | 30    | numeric   | Persistent |
| 155   | AntifreezeOutTemp                          | int8   | -5  | 10    | numeric   | Persistent |
| 156   | AntifreezePumpRuntime                      | uint8  | 1   | 10    | numeric   | Persistent |
| 157   | AntifreezePumpBreakTime                    | uint8  | 5   | 120   | numeric   | Persistent |
| 161   | WS1                                        | uint32 | 0   | 0     | bitfield  | Persistent |
| 162   | workState2                                 | uint32 | 0   | 0     | bitfield  | Persistent |
| 163   | workState3                                 | uint32 | 0   | 0     | bitfield  | Persistent |
| 164   | workState4                                 | uint32 | 0   | 0     | bitfield  | Persistent |
| 165   | TrybUruch                                  | uint8  | 0   | 0     |           |            |
| 166   | dhw_mode                                   | uint8  | 0   | 0     | enum      | Persistent |
| 167   | heatcoolsett                               | uint8  | 0   | 0     |           | Persistent |
| 172   | ManualControl                              | uint32 | 0   | 0     | bitfield  |            |
| 173   | set_pwm0                                   | uint8  | 0   | 0     |           |            |
| 174   | set_pwm1                                   | uint8  | 0   | 0     |           |            |
| 175   | DACdec0                                    | float  | 0   | 0     |           |            |
| 176   | DACdec1                                    | float  | 0   | 0     |           |            |
| 177   | DACbin0                                    | int16  | 0   | 0     |           |            |
| 178   | DACbin1                                    | int16  | 0   | 0     |           |            |
| 181   | BuforSETTINGS                              | uint32 | 0   | 0     |           | Persistent |
| 183   | BuforsetPoint                              | uint8  | 24  | 75    | numeric   | Persistent |
| 188   | BuforSetTempDownHist                       | uint8  | 0   | 0     | numeric   | Persistent |
| 190   | BuforTempStartHydraulic                    | uint8  | 21  | 50    | numeric   | Persistent |
| 191   | BuforTempStartHydraulicHist                | uint8  | 0   | 20    | numeric   | Persistent |
| 192   | BuforMaxTemp                               | uint8  | 0   | 90    | numeric   | Persistent |
| 193   | BuforMaxTempHist                           | uint8  | 0   | 10    | numeric   | Persistent |
| 194   | BuforLongLoadTime                          | uint8  | 0   | 50    | numeric   | Persistent |
| 196   | BuforScheduleReduction                     | int8   | -20 | 0     |           | Persistent |
| 197   | BuforHarmonogramSet                        | uint32 | 0   | 0     |           | Persistent |
| 199   | BuforSundayAM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 200   | BuforSundayPM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 201   | BuforMondayAM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 202   | BuforMondayPM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 203   | BuforTuesdayAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 204   | BuforTuesdayPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 205   | BuforWednesdayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 206   | BuforWednesdayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 207   | BuforThursdayAM                            | uint32 | 0   | 0     | schedule  | Persistent |
| 208   | BuforThursdayPM                            | uint32 | 0   | 0     | schedule  | Persistent |
| 209   | BuforFridayAM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 210   | BuforFridayPM                              | uint32 | 0   | 0     | schedule  | Persistent |
| 211   | BuforSaturdayAM                            | uint32 | 0   | 0     | schedule  | Persistent |
| 212   | BuforSaturdayPM                            | uint32 | 0   | 0     | schedule  | Persistent |
| 213   | Buforcoolingtemp                           | uint8  | 6   | 20    | numeric   | Persistent |
| 214   | Buforcoolinghist                           | uint8  | 0   | 0     |           | Persistent |
| 215   | BuforTempStartHydraulicCooling             | uint8  | 0   | 0     |           | Persistent |
| 216   | BuforTempStartHydraulicCoolingHist         | uint8  | 0   | 0     | numeric   | Persistent |
| 217   | BuforminSetPoint                           | uint8  | 20  | 0     | numeric   | Persistent |
| 218   | BuformaxSetPoint                           | uint8  | 0   | 75    | numeric   | Persistent |
| 221   | BuforTempKeepingWarm                       | uint8  | 0   | 0     |           |            |
| 231   | Circuit1Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 236   | Circuit1WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 238   | Circuit1ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 239   | Circuit1EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 240   | Circuit1DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 241   | Circuit1MinSetTempRad                      | uint8  | 24  | 0     |           | Persistent |
| 242   | Circuit1MaxSetTempRad                      | uint8  | 0   | 75    | numeric   | Persistent |
| 243   | Circuit1MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 244   | Circuit1MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 246   | Circuit1ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 247   | Circuit1SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 248   | Circuit1SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 249   | Circuit1MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 250   | Circuit1MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 251   | Circuit1TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 252   | Circuit1TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 253   | Circuit1WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 254   | Circuit1WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 255   | Circuit1ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 256   | Circuit1ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 257   | Circuit1FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 258   | Circuit1FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 259   | Circuit1SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 260   | Circuit1SaturdayPM_                        | uint32 | 0   | 0     | schedule  | Persistent |
| 261   | Circuit1BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 262   | Circuit1TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 263   | Circuit1Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 269   | Circuit1TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 270   | Circuit1ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 271   | Circuit1MinTempFloor                       | uint8  | 24  | 0     |           | Persistent |
| 272   | Circuit1MaxTempFloor                       | uint8  | 0   | 0     |           | Persistent |
| 273   | Circuit1CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 274   | Circuit1CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 275   | Circuit1Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 276   | Circuit1longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 278   | Circuit1name                               | string | 0   | 0     | string    |            |
| 280   | Circuit1userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 281   | Circuit2Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 283   | Circuit2InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 286   | Circuit2WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 288   | Circuit2ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 289   | Circuit2EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 290   | Circuit2DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 291   | Circuit2MinSetTempRad                      | uint8  | 24  | 0     |           | Persistent |
| 292   | Circuit2MaxSetTempRad                      | uint8  | 0   | 75    | numeric   | Persistent |
| 293   | Circuit2MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 294   | Circuit2MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 296   | Circuit2ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 297   | Circuit2SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 298   | Circuit2SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 299   | Circuit2MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 300   | Circuit2MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 301   | Circuit2TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 302   | Circuit2TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 303   | Circuit2WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 304   | Circuit2WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 305   | Circuit2ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 306   | Circuit2ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 307   | Circuit2FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 308   | Circuit2FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 309   | Circuit2SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 310   | Circuit2SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 311   | Circuit2BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 312   | Circuit2TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 313   | Circuit2Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 316   | Mixer2valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 317   | Mixer2valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 319   | Circuit2TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 320   | Circuit2ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 321   | Circuit2MinSetTempFloor                    | uint8  | 24  | 45    | numeric   | Persistent |
| 322   | Circuit2MaxSetTempFloor                    | uint8  | 24  | 45    | numeric   | Persistent |
| 323   | Circuit2CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 324   | Circuit2CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 325   | Circuit2Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 326   | Circuit2longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 328   | Circuit2name                               | string | 0   | 0     | string    |            |
| 330   | Circuit2userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 331   | Circuit3Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 333   | Circuit3InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 336   | Circuit3WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 338   | Circuit3ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 339   | Circuit3EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 340   | Circuit3DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 341   | Circuit3MinSetTemp                         | uint8  | 24  | 75    | numeric   | Persistent |
| 342   | Circuit3MaxSetTemp                         | uint8  | 24  | 75    | numeric   | Persistent |
| 343   | Circuit3MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 344   | Circuit3MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 346   | Circuit3ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 349   | nr_schematu                                | uint8  | 0   | 0     |           |            |
| 350   | econet_Ver                                 | string | 0   | 0     | string    |            |
| 354   | AddSourceModuleSett                        | uint32 | 0   | 0     |           | Persistent |
| 356   | AddSoruceCriticalTemp                      | int8   | -30 | 0     |           | Persistent |
| 357   | AddSoruceCriticalTempEnd                   | int8   | 0   | 0     |           | Persistent |
| 360   | AddSoruceDelaySupport                      | uint8  | 1   | 120   | numeric   | Persistent |
| 361   | Circuit3BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 362   | Circuit3TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 363   | Circuit3Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 366   | Mixer3valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 367   | Mixer3valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 369   | Circuit3TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 370   | Circuit3ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 371   | Circuit3MinSetTempFloor                    | uint8  | 24  | 0     |           | Persistent |
| 372   | Circuit3MaxSetTempFloor                    | uint8  | 0   | 0     |           | Persistent |
| 375   | clientId                                   | uint16 | 0   | 0     |           | Persistent |
| 376   | Status_wifi                                | uint8  | 0   | 0     |           |            |
| 377   | SSID                                       | string | 0   | 0     | string    | Persistent |
| 378   | Szyfrowanie_WiFi                           | uint8  | 0   | 0     |           | Persistent |
| 379   | haslo_WiFi                                 | string | 0   | 0     | string    |            |
| 380   | Sila_sygnalu_WiFi                          | uint8  | 0   | 0     |           |            |
| 381   | Adres_IP_WiFi                              | uint32 | 0   | 0     |           |            |
| 382   | Maska_IP_WiFi                              | uint32 | 0   | 0     |           |            |
| 383   | Brama_IP_WiFi                              | uint32 | 0   | 0     |           |            |
| 384   | Adres_IP                                   | uint32 | 0   | 0     |           |            |
| 385   | Maska_IP                                   | uint32 | 0   | 0     |           |            |
| 386   | Brama_IP                                   | uint32 | 0   | 0     |           |            |
| 387   | Status_IP                                  | uint8  | 0   | 0     |           |            |
| 388   | Serwer_zewnetrzny                          | uint8  | 0   | 0     |           |            |
| 391   | ModuleB_C_OnOff                            | uint8  | 0   | 0     | bool      | Persistent |
| 395   | ModuleB_ManualOutputs                      | uint32 | 0   | 0     | bitfield  |            |
| 398   | ModuleC_ManualOutputs                      | uint32 | 0   | 0     | bitfield  |            |
| 403   | Controllers_detected                       | uint32 | 0   | 0     | bitfield  |            |
| 404   | Panels_detected                            | uint32 | 0   | 0     | bitfield  |            |
| 405   | ESTERsX40_detected                         | uint32 | 0   | 0     | bitfield  |            |
| 406   | EcoSters40_detected                        | uint32 | 0   | 0     | bitfield  |            |
| 429   | deltaForAHS                                | float  | 1   | 10    | numeric   | Persistent |
| 431   | CirculationSettings                        | uint32 | 0   | 0     | bitfield  | Persistent |
| 433   | CirculationTemp.Start                      | uint8  | 20  | 60    | numeric   | Persistent |
| 434   | CirculationTimework                        | uint8  | 1   | 120   | numeric   | Persistent |
| 435   | CirculationTimestop                        | uint8  | 1   | 100   | numeric   | Persistent |
| 436   | CirculationHist.Temp.                      | uint8  | 1   | 20    | numeric   |            |
| 438   | timeToSupportFromDelta                     | uint8  | 1   | 240   | numeric   | Persistent |
| 439   | CirculationHarmonogramSettings             | uint32 | 0   | 0     | bitfield  | Persistent |
| 440   | CirculationSundayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 441   | CirculationSundayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 442   | CirculationMondayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 443   | CirculationMondayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 444   | CirculationTuesdayAM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 445   | CirculationTuesdayPM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 446   | CirculationWednesdayAM                     | uint32 | 0   | 0     | schedule  | Persistent |
| 447   | CirculationWednesdayPM                     | uint32 | 0   | 0     | schedule  | Persistent |
| 448   | CirculationThursdayAM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 449   | CirculationThursdayPM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 450   | CirculationFridayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 451   | CirculationFridayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 452   | CirculationSaturdayAM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 453   | CirculationSaturdayPM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 454   | SpecHeatCap                                | float  | 3   | 4     | numeric   | Persistent |
| 455   | flow_default                               | float  | 0   | 40    | numeric   | Persistent |
| 456   | HeatSourceMainType                         | uint32 | 0   | 0     |           | Persistent |
| 457   | HeatSourceAddType                          | uint32 | 0   | 0     |           | Persistent |
| 458   | HeatSourceAddType                          | uint32 | 0   | 0     |           | Persistent |
| 459   | heaterPumpFirstSetpoint                    | uint8  | 40  | 65    | numeric   | Persistent |
| 460   | heaterPumpSecondtSetpoint                  | uint8  | 40  | 65    | numeric   | Persistent |
| 462   | HeatSourceAllowWorkSett                    | uint8  | 0   | 0     | enum      | Persistent |
| 465   | HeatSourceContactSett                      | uint32 | 0   | 0     |           | Persistent |
| 467   | HeatSourceContactStopHyst                  | uint8  | 0   | 20    | numeric   | Persistent |
| 468   | HeatSourceContactStartHyst                 | uint8  | 0   | 20    | numeric   | Persistent |
| 469   | HeatSourceCoolingSett                      | uint32 | 0   | 0     |           | Persistent |
| 471   | HeatSourceCoolingMainTemp                  | uint8  | 0   | 95    | numeric   | Persistent |
| 472   | HeatSourceCoolingAddTemp                   | uint8  | 60  | 120   | numeric   | Persistent |
| 473   | HeatSourceCoolingHyst                      | uint8  | 0   | 20    | numeric   | Persistent |
| 474   | HeatSourcePresetTempSett                   | uint32 | 0   | 0     |           | Persistent |
| 476   | HeatSourcePresetTemp                       | uint8  | 0   | 0     | enum      | Persistent |
| 477   | HeatSourceMinPresetTemp                    | uint8  | 25  | 0     |           | Persistent |
| 478   | HeatSourceMaxPresetTemp                    | uint8  | 0   | 75    | numeric   | Persistent |
| 480   | HeatSourceType                             | uint8  | 0   | 0     | enum      | Persistent |
| 481   | HeatSourceTempInc                          | uint8  | 0   | 20    | numeric   | Persistent |
| 482   | HeatSourceMinSupplyTemp                    | uint8  | 0   | 0     | enum      | Persistent |
| 483   | HeatSourceMinSupplyHistTemp                | uint8  | 0   | 0     | enum      | Persistent |
| 485   | HeatingCooling                             | uint8  | 0   | 0     | enum      | Persistent |
| 487   | HeatSourceTempIncBuffer                    | uint8  | 0   | 20    | numeric   | Persistent |
| 489   | detectAlarmState                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 490   | detectInputState                           | uint8  | 0   | 0     |           | Persistent |
| 491   | heaterPumpThirdtSetpoint                   | uint8  | 40  | 65    | numeric   | Persistent |
| 492   | heaterPumpDecreaseForDHW                   | uint8  | 2   | 10    | numeric   | Persistent |
| 493   | timeBeetwenHeatingCooling                  | uint8  | 0   | 100   | numeric   | Persistent |
| 498   | minWorkTime                                | uint8  | 0   | 120   | numeric   | Persistent |
| 499   | minBreakTime                               | uint8  | 0   | 120   | numeric   | Persistent |
| 500   | increaseOffsetInHeating                    | uint8  | 0   | 15    | numeric   | Persistent |
| 501   | decreaseOffsetInCooling                    | uint8  | 0   | 15    | numeric   | Persistent |
| 503   | compressorMinTimesSett                     | uint32 | 0   | 0     | numeric   | Persistent |
| 512   | lackFlowSettings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 513   | lackFlowInputState                         | uint8  | 0   | 0     |           | Persistent |
| 514   | lackFlowTime                               | uint8  | 0   | 0     | numeric   | Persistent |
| 515   | lackFlowPoint                              | float  | 0   | 0     |           | Persistent |
| 516   | lackFlowHist                               | float  | 0   | 0     | numeric   | Persistent |
| 520   | lackflowtimeAgain                          | uint8  | 30  | 255   | numeric   | Persistent |
| 522   | heaterPumpDecreaseForBuffer                | uint8  | 2   | 10    | numeric   | Persistent |
| 524   | THERMOSTAT_100                             | float  | 0   | 0     |           |            |
| 525   | THERMOSTAT_101                             | float  | 0   | 0     |           |            |
| 526   | THERMOSTAT_102                             | float  | 0   | 0     |           |            |
| 527   | THERMOSTAT_103                             | float  | 0   | 0     |           |            |
| 528   | THERMOSTAT_104                             | float  | 0   | 0     |           |            |
| 529   | THERMOSTAT_105                             | float  | 0   | 0     |           |            |
| 530   | THERMOSTAT_106                             | float  | 0   | 0     |           |            |
| 531   | THERMOSTAT_107                             | float  | 0   | 0     |           |            |
| 532   | THERMOSTAT_108                             | float  | 0   | 0     |           |            |
| 533   | THERMOSTAT_109                             | float  | 0   | 0     |           |            |
| 534   | THERMOSTAT_110                             | float  | 0   | 0     |           |            |
| 535   | THERMOSTAT_111                             | float  | 0   | 0     |           |            |
| 536   | THERMOSTAT_112                             | float  | 0   | 0     |           |            |
| 537   | THERMOSTAT_113                             | float  | 0   | 0     |           |            |
| 538   | THERMOSTAT_114                             | float  | 0   | 0     |           |            |
| 539   | THERMOSTAT_115                             | float  | 0   | 0     |           |            |
| 540   | THERMOSTAT_116                             | float  | 0   | 0     |           |            |
| 541   | THERMOSTAT_117                             | float  | 0   | 0     |           |            |
| 542   | THERMOSTAT_118                             | float  | 0   | 0     |           |            |
| 543   | THERMOSTAT_119                             | float  | 0   | 0     |           |            |
| 544   | THERMOSTAT_120                             | float  | 0   | 0     |           |            |
| 545   | THERMOSTAT_121                             | float  | 0   | 0     |           |            |
| 546   | THERMOSTAT_122                             | float  | 0   | 0     |           |            |
| 547   | THERMOSTAT_123                             | float  | 0   | 0     |           |            |
| 548   | THERMOSTAT_124                             | float  | 0   | 0     |           |            |
| 549   | THERMOSTAT_125                             | float  | 0   | 0     |           |            |
| 550   | THERMOSTAT_126                             | float  | 0   | 0     |           |            |
| 551   | THERMOSTAT_127                             | float  | 0   | 0     |           |            |
| 552   | THERMOSTAT_128                             | float  | 0   | 0     |           |            |
| 553   | THERMOSTAT_129                             | float  | 0   | 0     |           |            |
| 554   | THERMOSTAT_130                             | float  | 0   | 0     |           |            |
| 555   | THERMOSTAT_131                             | float  | 0   | 0     |           |            |
| 572   | Mix1PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 573   | Mix2PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 574   | Mix3PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 575   | Mix4PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 576   | Mix5PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 577   | Mix1PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 578   | Mix2PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 579   | Mix3PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 580   | Mix4PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 581   | Mix5PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 582   | Mix6PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 583   | Mix7PidKp                                  | float  | 0   | 100   | numeric   | Persistent |
| 584   | Mix6PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 585   | Mix7PidTi                                  | float  | 0   | 300   | numeric   | Persistent |
| 586   | MixCirc1HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 587   | MixCirc2HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 588   | MixCirc3HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 589   | MixCirc4HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 590   | MixCirc5HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 591   | MixCirc6HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 592   | MixCirc7HeatCurveFanCoil                   | float  | 0   | 4     | numeric   | Persistent |
| 593   | Circuit1DefaultSett                        | uint8  | 0   | 0     |           |            |
| 594   | Circuit2DefaultSett                        | uint8  | 0   | 0     |           |            |
| 595   | Circuit3DefaultSett                        | uint8  | 0   | 0     |           |            |
| 596   | Circuit4DefaultSett                        | uint8  | 0   | 0     |           |            |
| 597   | Circuit5DefaultSett                        | uint8  | 0   | 0     |           |            |
| 598   | Circuit6DefaultSett                        | uint8  | 0   | 0     |           |            |
| 599   | Circuit7DefaultSett                        | uint8  | 0   | 0     |           |            |
| 600   | Circuit1Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 601   | Circuit2Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 602   | Circuit3Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 603   | Circuit4Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 604   | Circuit5Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 605   | Circuit6Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 606   | Circuit7Picture                            | uint8  | 0   | 0     | enum      | Persistent |
| 608   | flow_time_erase_impulse_count              | uint8  | 0   | 0     | bool      | Persistent |
| 609   | lackFlowManualErase                        | uint8  | 0   | 0     | bool      |            |
| 611   | lackFlowTooOften                           | uint8  | 0   | 0     |           | Persistent |
| 613   | FlowPulseRate                              | uint16 | 0   | 2000  | numeric   | Persistent |
| 614   | energyCorrection                           | uint16 | 0   | 100   | numeric   | Persistent |
| 645   | DACtkala0                                  | float  | 0   | 0     |           |            |
| 646   | DACtkalb0                                  | float  | 0   | 0     |           |            |
| 647   | DACtkalc0                                  | float  | 0   | 0     |           |            |
| 648   | DACtkala1                                  | float  | 0   | 0     |           |            |
| 649   | DACtkalb1                                  | float  | 0   | 0     |           |            |
| 650   | DACtkalc1                                  | float  | 0   | 0     |           |            |
| 651   | outsCount                                  | uint8  | 0   | 0     |           |            |
| 652   | analogInCount                              | uint8  | 0   | 0     |           |            |
| 653   | pwmCount                                   | uint8  | 0   | 0     |           |            |
| 654   | digitalInCount                             | uint8  | 0   | 0     |           |            |
| 655   | dacCount                                   | uint8  | 0   | 0     |           |            |
| 656   | inEcoX_outs0                               | uint8  | 0   | 0     |           |            |
| 657   | inEcoX_outs1                               | uint8  | 0   | 0     |           |            |
| 658   | inEcoX_outs2                               | uint8  | 0   | 0     |           |            |
| 659   | inEcoX_outs3                               | uint8  | 0   | 0     |           |            |
| 660   | inEcoX_outs4                               | uint8  | 0   | 0     |           |            |
| 661   | inEcoX_outs5                               | uint8  | 0   | 0     |           |            |
| 662   | inEcoX_outs6                               | uint8  | 0   | 0     |           |            |
| 663   | inEcoX_outs7                               | uint8  | 0   | 0     |           |            |
| 664   | inEcoX_outs8                               | uint8  | 0   | 0     |           |            |
| 665   | inEcoX_outs9                               | uint8  | 0   | 0     |           |            |
| 666   | inEcoX_outs10                              | uint8  | 0   | 0     |           |            |
| 667   | inEcoX_ADC0                                | uint8  | 0   | 0     |           |            |
| 668   | inEcoX_ADC1                                | uint8  | 0   | 0     |           |            |
| 669   | inEcoX_ADC2                                | uint8  | 0   | 0     |           |            |
| 670   | inEcoX_ADC3                                | uint8  | 0   | 0     |           |            |
| 671   | inEcoX_ADC4                                | uint8  | 0   | 0     |           |            |
| 672   | inEcoX_ADC5                                | uint8  | 0   | 0     |           |            |
| 673   | inEcoX_ADC6                                | uint8  | 0   | 0     |           |            |
| 674   | inEcoX_ADC7                                | uint8  | 0   | 0     |           |            |
| 675   | inEcoX_ADC8                                | uint8  | 0   | 0     |           |            |
| 676   | inEcoX_ADC9                                | uint8  | 0   | 0     |           |            |
| 677   | inEcoX_DAC0                                | uint8  | 0   | 0     |           |            |
| 678   | inEcoX_DAC1                                | uint8  | 0   | 0     |           |            |
| 679   | inEcoX_pwm0                                | uint8  | 0   | 0     |           |            |
| 680   | inEcoX_pwm1                                | uint8  | 0   | 0     |           |            |
| 681   | out_type0                                  | uint8  | 0   | 0     |           |            |
| 682   | out_type1                                  | uint8  | 0   | 0     |           |            |
| 683   | out_type2                                  | uint8  | 0   | 0     |           |            |
| 684   | out_type3                                  | uint8  | 0   | 0     |           |            |
| 685   | out_type4                                  | uint8  | 0   | 0     |           |            |
| 686   | out_type5                                  | uint8  | 0   | 0     |           |            |
| 687   | out_type6                                  | uint8  | 0   | 0     |           |            |
| 688   | out_type7                                  | uint8  | 0   | 0     |           |            |
| 689   | out_type8                                  | uint8  | 0   | 0     |           |            |
| 690   | out_type9                                  | uint8  | 0   | 0     |           |            |
| 691   | out_type10                                 | uint8  | 0   | 0     |           |            |
| 692   | sensor_ADC0                                | uint8  | 0   | 0     |           |            |
| 693   | sensor_ADC1                                | uint8  | 0   | 0     |           |            |
| 694   | sensor_ADC2                                | uint8  | 0   | 0     |           |            |
| 695   | sensor_ADC3                                | uint8  | 0   | 0     |           |            |
| 696   | sensor_ADC4                                | uint8  | 0   | 0     |           |            |
| 697   | sensor_ADC5                                | uint8  | 0   | 0     |           |            |
| 698   | sensor_ADC6                                | uint8  | 0   | 0     |           |            |
| 699   | sensor_ADC7                                | uint8  | 0   | 0     |           |            |
| 700   | sensor_ADC8                                | uint8  | 0   | 0     |           |            |
| 701   | sensor_ADC9                                | uint8  | 0   | 0     |           |            |
| 702   | SummerOn                                   | uint8  | 22  | 30    | numeric   | Persistent |
| 703   | SummerOff                                  | uint8  | 0   | 24    | numeric   | Persistent |
| 739   | Circuit1MixerCoolBaseTemp                  | uint8  | 0   | 0     |           | Persistent |
| 749   | Circuit6Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 751   | Circuit6InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 753   | Circuit6WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 755   | Circuit6ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 756   | Circuit6EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 757   | Circuit6DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 758   | Circuit6MinSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 759   | Circuit6MaxSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 760   | Circuit6MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 761   | Circuit6MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 762   | Circuit6ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 763   | Circuit6BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 764   | Circuit6TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 765   | Circuit6Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 768   | Mixer6valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 769   | Mixer6valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 771   | Circuit6TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 772   | Circuit6ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 773   | Circuit6MinSetTempFloor                    | uint8  | 24  | 0     |           | Persistent |
| 774   | Circuit6MaxSetTempFloor                    | uint8  | 0   | 0     |           | Persistent |
| 775   | Circuit6CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 776   | Circuit6CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 777   | Circuit6Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 778   | Circuit6longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 780   | Circuit6name                               | string | 0   | 0     | string    |            |
| 782   | Circuit6userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 783   | Circuit6BaseTemp                           | uint8  | 0   | 0     |           | Persistent |
| 784   | Circuit6MixerCoolBaseTemp                  | uint8  | 10  | 30    | numeric   | Persistent |
| 785   | Circuit2BaseTemp                           | uint8  | 0   | 0     |           | Persistent |
| 787   | Circuit2MinSetPointCooling                 | uint8  | 18  | 25    | numeric   | Persistent |
| 788   | Circuit2MaxSetPointCooling                 | uint8  | 18  | 30    | numeric   | Persistent |
| 789   | Circuit2MixerCoolBaseTemp                  | uint8  | 18  | 25    | numeric   | Persistent |
| 799   | Circuit7Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 801   | Circuit7InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 803   | Circuit7WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 805   | Circuit7ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 806   | Circuit7EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 807   | Circuit7DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 808   | Circuit7MinSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 809   | Circuit7MaxSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 810   | Circuit7MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 811   | Circuit7MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 812   | Circuit7ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 813   | Circuit7BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 814   | Circuit7TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 815   | Circuit7Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 818   | Mixer7valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 819   | Mixer7valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 821   | Circuit7TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 822   | Circuit7ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 823   | Circuit7MinSetTempFloor                    | uint8  | 24  | 0     |           | Persistent |
| 824   | Circuit7MaxSetTempFloor                    | uint8  | 0   | 0     |           | Persistent |
| 825   | Circuit7CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 826   | Circuit7CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 827   | Circuit7Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 828   | Circuit7longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 830   | Circuit7name                               | string | 0   | 0     | string    |            |
| 832   | Circuit7userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 833   | Circuit7BaseTemp                           | uint8  | 0   | 0     |           | Persistent |
| 834   | Circuit7MixerCoolBaseTemp                  | uint8  | 10  | 30    | numeric   | Persistent |
| 835   | Circuit3BaseTemp                           | uint8  | 0   | 0     |           | Persistent |
| 837   | Circuit3MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 838   | Circuit3MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 839   | Circuit3MixerCoolBaseTemp                  | uint8  | 10  | 30    | numeric   | Persistent |
| 845   | Circuit7SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 846   | Circuit7SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 847   | Circuit7MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 848   | Circuit7MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 849   | Circuit7TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 850   | Circuit7TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 851   | Circuit7WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 852   | Circuit7WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 853   | Circuit7ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 854   | Circuit7ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 855   | Circuit7FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 856   | Circuit7FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 857   | Circuit7SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 858   | Circuit7SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 867   | Circuit6SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 868   | Circuit6SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 869   | Circuit6MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 870   | Circuit6MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 871   | Circuit6TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 872   | Circuit6TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 873   | Circuit6WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 874   | Circuit6WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 875   | Circuit6ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 876   | Circuit6ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 877   | Circuit6FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 878   | Circuit6FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 879   | Circuit6SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 880   | Circuit6SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 881   | Circuit3SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 882   | Circuit3SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 883   | Circuit3MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 884   | Circuit3MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 885   | Circuit3TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 886   | Circuit3TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 887   | Circuit3WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 888   | Circuit3WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 889   | Circuit3ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 890   | Circuit3ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 891   | Circuit3FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 892   | Circuit3FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 893   | Circuit3SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 894   | Circuit3SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 895   | Circuit3CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 896   | Circuit3CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 897   | Circuit3Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 898   | Circuit3longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 900   | Circuit3name                               | string | 0   | 0     | string    |            |
| 902   | Circuit3userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 903   | Circuit1MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 904   | Circuit1MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 905   | Circuit4MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 906   | Circuit4MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 907   | Circuit5MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 908   | Circuit5MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 909   | Circuit6MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 910   | Circuit6MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 911   | Circuit7MinSetPointCooling                 | uint8  | 0   | 0     | numeric   | Persistent |
| 912   | Circuit7MaxSetPointCooling                 | uint8  | 0   | 30    | numeric   | Persistent |
| 914   | energySettings                             | uint8  | 0   | 0     |           | Persistent |
| 915   | countOfImpulsesPer1kWh                     | uint16 | 0   | 0     |           | Persistent |
| 920   | ereaseEnergy                               | uint8  | 0   | 0     |           |            |
| 926   | HeatSourceSundayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 927   | HeatSourceSundayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 928   | HeatSourceMondayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 929   | HeatSourceMondayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 930   | HeatSourceTuesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 931   | HeatSourceTuesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 932   | HeatSourceWednesdayAM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 933   | HeatSourceWednesdayPM                      | uint32 | 0   | 0     | schedule  | Persistent |
| 934   | HeatSourceThursdayAM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 935   | HeatSourceThursdayPM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 936   | HeatSourceFridayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 937   | HeatSourceFridayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 938   | HeatSourceSaturdayAM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 939   | HeatSourceSaturdayPM                       | uint32 | 0   | 0     | schedule  | Persistent |
| 940   | Circuit4Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 942   | Circuit4InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 944   | Circuit4WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 946   | Circuit4ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 947   | Circuit4EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 948   | Circuit4DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 949   | Circuit4MinSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 950   | Circuit4MaxSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 951   | Circuit4MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 952   | Circuit4MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 953   | Circuit4ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 955   | Circuit4SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 956   | Circuit4SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 957   | Circuit4MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 958   | Circuit4MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 959   | Circuit4TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 960   | Circuit4TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 961   | Circuit4WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 962   | Circuit4WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 963   | Circuit4ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 964   | Circuit4ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 965   | Circuit4FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 966   | Circuit4FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 967   | Circuit4SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 968   | Circuit4SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 969   | Circuit4BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 970   | Circuit4TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 971   | Circuit4Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 974   | Mixer4valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 975   | Mixer4valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 977   | Circuit4TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 978   | Circuit4ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 979   | Circuit4MinSetTempFloor                    | uint8  | 24  | 0     |           | Persistent |
| 980   | Circuit4MaxSetTempFloor                    | uint8  | 0   | 0     |           | Persistent |
| 981   | Circuit4CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 982   | Circuit4CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 983   | Circuit4Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 984   | Circuit4longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 986   | Circuit4name                               | string | 0   | 0     | string    |            |
| 988   | Circuit4userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 989   | Circuit4BaseTemp                           | uint8  | 0   | 0     |           | Persistent |
| 990   | Circuit4MixerCoolBaseTemp                  | uint8  | 10  | 30    | numeric   | Persistent |
| 991   | Circuit5Settings                           | uint32 | 0   | 0     | bitfield  | Persistent |
| 993   | Circuit5InputDigitalLogic                  | uint8  | 0   | 0     |           | Persistent |
| 995   | Circuit5WorkState                          | uint8  | 0   | 3     | enum      | Persistent |
| 997   | Circuit5ComfortTemp                        | float  | 10  | 35    | numeric   | Persistent |
| 998   | Circuit5EcoTemp                            | float  | 10  | 35    | numeric   | Persistent |
| 999   | Circuit5DownHist                           | float  | 0   | 5     | numeric   | Persistent |
| 1000  | Circuit5MinSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 1001  | Circuit5MaxSetTempRad                      | uint8  | 24  | 75    | numeric   | Persistent |
| 1002  | Circuit5MaxTempHeat                        | uint8  | 30  | 55    | numeric   | Persistent |
| 1003  | Circuit5MaxTempHeatHist                    | uint8  | 0   | 10    | numeric   | Persistent |
| 1004  | Circuit5ThermostatAddress                  | uint16 | 0   | 0     |           | Persistent |
| 1006  | Circuit5SundayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1007  | Circuit5SundayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1008  | Circuit5MondayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1009  | Circuit5MondayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1010  | Circuit5TuesdayAM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 1011  | Circuit5TuesdayPM                          | uint32 | 0   | 0     | schedule  | Persistent |
| 1012  | Circuit5WednesdayAM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 1013  | Circuit5WednesdayPM                        | uint32 | 0   | 0     | schedule  | Persistent |
| 1014  | Circuit5ThursdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 1015  | Circuit5ThursdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 1016  | Circuit5FridayAM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1017  | Circuit5FridayPM                           | uint32 | 0   | 0     | schedule  | Persistent |
| 1018  | Circuit5SaturdayAM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 1019  | Circuit5SaturdayPM                         | uint32 | 0   | 0     | schedule  | Persistent |
| 1020  | Circuit5BaseTemp                           | uint8  | 24  | 75    | numeric   | Persistent |
| 1021  | Circuit5TempReduction                      | uint8  | 0   | 20    | numeric   | Persistent |
| 1022  | Circuit5Multiplier                         | float  | 0   | 10    | numeric   | Persistent |
| 1025  | Mixer5valveopeningtime                     | uint16 | 1   | 1200  | numeric   | Persistent |
| 1026  | Mixer5valvedeadzone                        | float  | 0   | 5     | numeric   | Persistent |
| 1028  | Circuit5TypeSettings                       | uint8  | 0   | 0     | enum      | Persistent |
| 1029  | Circuit5ThermostatSettings                 | uint8  | 0   | 0     |           | Persistent |
| 1030  | Circuit5MinSetTempFloor                    | uint8  | 24  | 0     |           | Persistent |
| 1031  | Circuit5MaxSetTempFloor                    | uint8  | 0   | 0     |           | Persistent |
| 1032  | Circuit5CurveRadiator                      | float  | 0   | 4     | numeric   | Persistent |
| 1033  | Circuit5CurveFloor                         | float  | 0   | 4     | numeric   | Persistent |
| 1034  | Circuit5Curveshift                         | int8   | -20 | 20    | numeric   | Persistent |
| 1035  | Circuit5longloading                        | uint8  | 0   | 60    | numeric   | Persistent |
| 1037  | Circuit5name                               | string | 0   | 0     | string    |            |
| 1039  | Circuit5userCor                            | int8   | -10 | 10    | numeric   | Persistent |
| 1040  | Circuit5BaseTemp                           | uint8  | 24  | 45    | numeric   | Persistent |
| 1041  | Circuit5MixerCoolBaseTemp                  | uint8  | 10  | 30    | numeric   | Persistent |
| 1054  | decreaseSetTemp                            | uint8  | 1   | 10    | numeric   | Persistent |
| 1055  | CopCalculateModuleSettings                 | uint32 | 0   | 0     | bitfield  | Persistent |
| 1056  | CopCalculateModuleState                    | uint32 | 0   | 0     | bitfield  |            |
| 1057  | PID_comp,_min_control                      | float  | 0   | 0     |           | Persistent |
| 1058  | PID_comp._max_control                      | float  | 0   | 0     |           | Persistent |
| 1059  | PID_comp._min_control_change               | float  | 0   | 0     |           | Persistent |
| 1060  | PID_comp._max_control_change               | float  | 0   | 0     |           | Persistent |
| 1061  | PID_comp._start_speed                      | uint8  | 0   | 0     |           | Persistent |
| 1062  | PID_comp._time                             | float  | 0   | 0     |           | Persistent |
| 1063  | analog_boiler_control_settings             | uint32 | 0   | 0     |           | Persistent |
| 1066  | SmartGrid_ModuleSettings                   | uint32 | 0   | 0     | bitfield  | Persistent |
| 1067  | SmartGrid_InputState                       | uint8  | 0   | 0     |           |            |
| 1068  | SmartGrid_IncreaseForCwu                   | uint8  | 0   | 10    | numeric   | Persistent |
| 1069  | SmartGrid_IncreaseForBufferHeating         | int8   | 0   | 10    | numeric   | Persistent |
| 1070  | SmartGrid_DecreaseForBufferCooling         | int8   | 0   | 10    | numeric   | Persistent |
| 1071  | SmartGrid_IncreaseForWaterHeatingCircuit1  | int8   | 0   | 10    | numeric   | Persistent |
| 1072  | SmartGrid_DecreaseForWaterCoolingCircuit1  | int8   | 0   | 10    | numeric   | Persistent |
| 1073  | SmartGrid_IncreaseForRoomHeatingCircuit1   | float  | 0   | 10    | numeric   | Persistent |
| 1074  | SmartGrid_DecreaseForRoomCoolingCircuit1   | float  | 0   | 10    | numeric   | Persistent |
| 1075  | SmartGrid_IncreaseForWaterHeatingCircuit2  | int8   | 0   | 10    | numeric   | Persistent |
| 1076  | SmartGrid_DecreaseForWaterCoolingCircuit2  | int8   | 0   | 10    | numeric   | Persistent |
| 1077  | SmartGrid_IncreaseForRoomHeatingCircuit2   | float  | 0   | 10    | numeric   | Persistent |
| 1078  | SmartGrid_DecreaseForRoomCoolingCircuit2   | float  | 0   | 10    | numeric   | Persistent |
| 1079  | SmartGrid_IncreaseForWaterHeatingCircuit3  | int8   | 0   | 10    | numeric   | Persistent |
| 1080  | SmartGrid_DecreaseForWaterCoolingCircuit3  | int8   | 0   | 10    | numeric   | Persistent |
| 1081  | SmartGrid_IncreaseForRoomHeatingCircuit3   | float  | 0   | 10    | numeric   | Persistent |
| 1082  | SmartGrid_DecreaseForRoomCoolingCircuit3   | float  | 0   | 10    | numeric   | Persistent |
| 1083  | SmartGrid_IncreaseForWaterHeatingCircuit4  | int8   | 0   | 10    | numeric   | Persistent |
| 1084  | SmartGrid_DecreaseForWaterCoolingCircuit4  | int8   | 0   | 10    | numeric   | Persistent |
| 1085  | SmartGrid_IncreaseForRoomHeatingCircuit4   | float  | 0   | 10    | numeric   | Persistent |
| 1086  | SmartGrid_DecreaseForRoomCoolingCircuit4   | float  | 0   | 10    | numeric   | Persistent |
| 1087  | SmartGrid_IncreaseForWaterHeatingCircuit5  | int8   | 0   | 10    | numeric   | Persistent |
| 1088  | SmartGrid_DecreaseForWaterCoolingCircuit5  | int8   | 0   | 10    | numeric   | Persistent |
| 1089  | SmartGrid_IncreaseForRoomHeatingCircuit5   | float  | 0   | 10    | numeric   | Persistent |
| 1090  | SmartGrid_DecreaseForRoomCoolingCircuit5   | float  | 0   | 10    | numeric   | Persistent |
| 1091  | SmartGrid_IncreaseForWaterHeatingCircuit6  | int8   | 0   | 10    | numeric   | Persistent |
| 1092  | SmartGrid_DecreaseForWaterCoolingCircuit6  | int8   | 0   | 10    | numeric   | Persistent |
| 1093  | SmartGrid_IncreaseForRoomHeatingCircuit6   | float  | 0   | 10    | numeric   | Persistent |
| 1094  | SmartGrid_DecreaseForRoomCoolingCircuit6   | float  | 0   | 10    | numeric   | Persistent |
| 1095  | SmartGrid_IncreaseForWaterHeatingCircuit7  | int8   | 0   | 10    | numeric   | Persistent |
| 1096  | SmartGrid_DecreaseForWaterCoolingCircuit7  | int8   | 0   | 10    | numeric   | Persistent |
| 1097  | SmartGrid_IncreaseForRoomHeatingCircuit7   | float  | 0   | 10    | numeric   | Persistent |
| 1098  | SmartGrid_DecreaseForRoomCoolingCircuit7   | float  | 0   | 10    | numeric   | Persistent |
| 1099  | SGFiltering                                | uint8  | 0   | 60    | numeric   | Persistent |
| 1101  | Count_time_elements_erase                  | uint8  | 0   | 0     | bool      |            |
| 1132  | AxenModuleState                            | uint32 | 0   | 0     | bitfield  |            |
| 1133  | AxenWorkState                              | uint32 | 0   | 0     | bitfield  | Persistent |
| 1251  | AXEN_REGISTER_2000_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1252  | AXEN_REGISTER_2001_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1253  | AXEN_REGISTER_2002_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1254  | AXEN_REGISTER_2003_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1255  | AXEN_REGISTER_2004_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1256  | AXEN_REGISTER_2005_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1257  | AXEN_REGISTER_2006_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1258  | AXEN_REGISTER_2007_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1259  | AXEN_REGISTER_2008_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1260  | AXEN_REGISTER_2009_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1261  | AXEN_REGISTER_2010_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1262  | AXEN_REGISTER_2011_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1263  | AXEN_REGISTER_2012_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1264  | AXEN_REGISTER_2013_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1265  | AXEN_REGISTER_2014_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1266  | AXEN_REGISTER_2015_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1267  | AXEN_REGISTER_2016_RW_R32                  | uint16 | 0   | 30000 | numeric   |            |
| 1268  | AXEN_REGISTER_2100_RW                      | uint16 | 0   | 2     | numeric   |            |
| 1269  | AXEN_REGISTER_2101_RW                      | uint16 | 0   | 3     | numeric   |            |
| 1270  | AXEN_REGISTER_2102_RW                      | uint16 | 0   | 1     | numeric   |            |
| 1271  | AXEN_REGISTER_2103_RW                      | uint16 | 0   | 65535 | numeric   |            |
| 1272  | AXEN_REGISTER_2104_RW                      | uint16 | 0   | 1     | numeric   |            |
| 1273  | AXEN_REGISTER_2105_RW                      | uint16 | 25  | 75    | numeric   |            |
| 1274  | AXEN_REGISTER_2106_RW                      | uint16 | 5   | 25    | numeric   |            |
| 1275  | AXEN_REGISTER_2107_RW                      | uint16 | 35  | 75    | numeric   |            |
| 1276  | AXEN_REGISTER_2108_RW                      | uint16 | 5   | 25    | numeric   |            |
| 1277  | AXEN_REGISTER_2109_RW                      | uint16 | 35  | 75    | numeric   |            |
| 1278  | AXEN_REGISTER_2110_RW                      | uint16 | 5   | 25    | numeric   |            |
| 1279  | AXEN_REGISTER_2111_RW                      | uint16 | 35  | 75    | numeric   |            |
| 1280  | AXEN_REGISTER_2112_RW                      | uint16 | 5   | 25    | numeric   |            |
| 1281  | AXEN_REGISTER_2113_RW                      | uint16 | 35  | 75    | numeric   |            |
| 1282  | AXEN_REGISTER_2114_RW                      | uint16 | 10  | 35    | numeric   |            |
| 1308  | AXEN_REGISTER_2200_RW                      | uint16 | 0   | 1     | numeric   |            |
| 1309  | hSMPTSIncreaseCirc                         | uint8  | 0   | 20    | numeric   | Persistent |
| 1310  | Circuit1inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1311  | Circuit2inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1312  | Circuit3inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1313  | Circuit4inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1314  | Circuit5inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1315  | Circuit6inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1316  | Circuit7inSetTempCoolingDownRange          | uint8  | 0   | 0     |           | Persistent |
| 1317  | Circuit1prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1318  | Circuit2prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1319  | Circuit3prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1320  | Circuit4prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1321  | Circuit5prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1322  | Circuit6prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1323  | Circuit7prevType                           | uint8  | 0   | 0     | enum      | Persistent |
| 1330  | AHSoutTempHyst                             | uint8  | 1   | 5     | numeric   | Persistent |
| 1331  | AHSstartTemp                               | int8   | 0   | 20    | numeric   | Persistent |
| 1332  | AHSSetTemp                                 | uint8  | 0   | 0     |           | Persistent |
| 1333  | AHSSetHysterezis                           | uint8  | 2   | 30    | numeric   | Persistent |
| 1334  | AHSDelayTime                               | uint8  | 0   | 30    | numeric   | Persistent |
| 1335  | AHSDelayCounter                            | uint16 | 0   | 0     |           | Persistent |
| 1336  | AhsTempDiffHystStart                       | int8   | -50 | 20    | numeric   | Persistent |
| 1337  | AhsTempDiffHystStop                        | int8   | -50 | 20    | numeric   | Persistent |
| 1338  | ahsPumpStartSpeed                          | uint8  | 1   | 100   | numeric   | Persistent |
| 1339  | pwmInverse                                 | uint8  | 0   | 255   | numeric   | Persistent |
| 1340  | ahsPump_kp                                 | float  | 0   | 20    | numeric   | Persistent |
| 1341  | ahsPump_ti                                 | float  | 0   | 300   | numeric   | Persistent |
| 1342  | ahsPump_td                                 | float  | 0   | 300   | numeric   | Persistent |
| 1343  | ahsPump_ts                                 | uint16 | 5   | 300   | numeric   | Persistent |
| 1344  | ahsPump_minSpeed                           | uint8  | 0   | 50    | numeric   | Persistent |
| 1345  | ahsPump_maxSpeed                           | uint8  | 50  | 100   | numeric   | Persistent |
| 1346  | ahsPump_maxStep                            | uint8  | 1   | 50    | numeric   | Persistent |
| 1369  | AXEN_REGISTER_2150_RW-reboot_unit          | uint16 | 0   | 0     |           |            |
| 1370  | AXEN_2155-uhsPumpManualPreset              | uint16 | 1   | 100   | numeric   |            |
| 1371  | uhsPumpPresetInAhsSupport                  | uint8  | 1   | 100   | numeric   | Persistent |
| 1372  | mhsBelowSetpointDelta                      | uint8  | 0   | 15    | numeric   | Persistent |
| 1373  | mhsBelowSetpointTime                       | uint8  | 0   | 180   | numeric   | Persistent |
| 1374  | mhsBelowSetpointAgainTime                  | uint8  | 0   | 180   | numeric   | Persistent |
| 1375  | mhsBelowSetpointDeltaForHdw                | uint8  | 0   | 15    | numeric   | Persistent |
| 1376  | mhsBelowSetpointTimeForHdw                 | uint8  | 0   | 180   | numeric   | Persistent |
| 1377  | endSupportSlowAhsPumpTime                  | uint8  | 0   | 180   | numeric   | Persistent |
| 1378  | endSupportSlowAhsPumpPower                 | uint8  | 0   | 100   | numeric   | Persistent |
| 1379  | stopMhsReturnReachDelta                    | uint8  | 0   | 15    | numeric   | Persistent |
| 1380  | manualControlAutoDeactivationTime          | uint16 | 1   | 65535 | numeric   | Persistent |
| 1385  | HPSMSett                                   | uint8  | 0   | 0     |           | Persistent |
| 1386  | HPSMMode                                   | uint8  | 0   | 2     | enum      | Persistent |
| 1387  | SilentModeSuAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1388  | SilentModeSuPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1389  | SilentModeMoAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1390  | SilentModeMoPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1391  | SilentModeTuAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1392  | SilentModeTuPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1393  | SilentModeWeAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1394  | SilentModeWePM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1395  | SilentModeThAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1396  | SilentModeThPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1397  | SilentModeFrAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1398  | SilentModeFrPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1399  | SilentModeSaAM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1400  | SilentModeSaPM                             | uint32 | 0   | 0     | schedule  | Persistent |
| 1401  | Circuit_1_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1402  | Circuit_1_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1404  | Circuit_2_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1405  | Circuit_2_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1407  | Circuit_3_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1408  | Circuit_3_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1410  | Circuit_4_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1411  | Circuit_4_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1413  | Circuit_5_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1414  | Circuit_5_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1416  | Circuit_6_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1417  | Circuit_6_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1419  | Circuit_7_ScreedDrying_Module_State        | uint8  | 0   | 1     | bool      | Persistent |
| 1420  | Circuit_7_ScreedDrying_Actual_Program      | uint8  | 1   | 7     | numeric   | Persistent |
| 1429  | ScreedDrying_Settings                      | uint8  | 0   | 0     |           | Persistent |
| 1430  | TimeHDWload                                | uint8  | 1   | 60    | numeric   | Persistent |
| 1432  | Circuit_1_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1433  | Circuit_2_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1434  | Circuit_3_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1435  | Circuit_4_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1436  | Circuit_5_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1437  | Circuit_6_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1438  | Circuit_7_boost_time_left                  | uint16 | 0   | 180   | numeric   |            |
| 1439  | HoldingRegister_6050                       | uint16 | 0   | 100   | numeric   |            |
| 1440  | HoldingRegister_6061                       | uint16 | 0   | 100   | numeric   |            |
| 1441  | HoldingRegister_6271                       | uint16 | 0   | 100   | numeric   |            |
| 1442  | HoldingRegister_6273                       | uint16 | 0   | 100   | numeric   |            |
| 1443  | H_FAN_SPEED_0_6244                         | uint16 | 0   | 1000  | numeric   | Persistent |
| 1444  | H_FAN_SPEED_1_6231                         | uint16 | 0   | 1000  | numeric   | Persistent |
| 1445  | H_FAN_SPEED_2_6232                         | uint16 | 0   | 1000  | numeric   | Persistent |
| 1446  | H_FAN_SPEED_3_6233                         | uint16 | 0   | 1000  | numeric   | Persistent |
| 10000 | time_panel                                 | string | 0   | 0     | string    |            |
| 10002 | year                                       | uint32 | 0   | 0     |           |            |
| 10003 | day_of_Year                                | uint16 | 0   | 0     |           |            |
| 10004 | second                                     | uint8  | 0   | 0     |           |            |
| 10005 | minute                                     | uint8  | 0   | 0     |           |            |
| 10006 | hour                                       | uint8  | 0   | 0     |           |            |
| 10007 | day_of_months                              | uint8  | 0   | 0     |           |            |
| 10008 | day_of_week                                | uint8  | 0   | 0     |           |            |
| 10009 | months                                     | uint8  | 0   | 0     |           |            |
| 10010 | PS                                         | string | 0   | 0     | string    |            |
| 10011 | PV                                         | string | 0   | 0     | string    |            |
| 10012 | HV                                         | string | 0   | 0     | string    |            |
| 10013 | FN                                         | string | 0   | 0     | string    |            |
| 10014 | Address                                    | uint16 | 0   | 0     |           |            |
| 10017 | data                                       | string | 0   | 0     | string    |            |
| 10018 | jasnosc                                    | uint8  | 0   | 0     |           |            |
| 10019 | Buzzer_alarmActive                         | uint8  | 0   | 0     |           |            |
| 10020 | jezyk                                      | uint8  | 0   | 0     |           |            |
| 10022 | panelName                                  | string | 0   | 0     | string    |            |
| 10023 | currentWebPage                             | uint16 | 0   | 0     |           |            |
| 10024 | factoryReset                               | uint8  | 0   | 0     |           |            |
| 10025 | remPage                                    | uint16 | 0   | 0     |           |            |
| 10026 | backToRemPage                              | uint8  | 0   | 0     |           |            |
| 10027 | panelReset                                 | uint8  | 0   | 0     |           |            |
| 10028 | lokcer                                     | uint8  | 0   | 0     |           |            |
| 10029 | ConfigVersion                              | string | 0   | 0     | string    |            |
| 10030 | Compilation_Date                           | string | 0   | 0     | string    |            |
| 10031 | Boot_Version                               | string | 0   | 0     | string    |            |
| 10037 | wygaszacz                                  | uint8  | 0   | 0     |           |            |
| 10038 | czas_wygasza                               | uint8  | 0   | 0     |           |            |
| 10039 | wartosc_wygasz                             | uint8  | 0   | 0     |           |            |
| 10040 | Buzzer_touchActive                         | uint8  | 0   | 0     |           |            |
| 10041 | kasowanie_alarmow                          | uint8  | 0   | 0     |           |            |
| 10043 | modification_block                         | uint8  | 0   | 0     |           |            |
| 10044 | currentMainLoop                            | uint32 | 0   | 0     |           |            |
| 10045 | Maxmainloop                                | uint32 | 0   | 0     |           |            |
| 10046 | MinMainLoop                                | uint32 | 0   | 0     |           |            |
| 10047 | preHeaterType                              | uint16 | 0   | 0     |           |            |
| 10048 | TS_slot                                    | uint8  | 0   | 0     |           |            |
| 10049 | TS_day                                     | uint8  | 0   | 0     |           |            |
| 10050 | TS_prev_webPage                            | uint8  | 0   | 0     |           |            |
| 10051 | TS_AM                                      | uint32 | 0   | 0     |           |            |
| 10052 | TS_PM                                      | uint32 | 0   | 0     |           |            |
| 10053 | TS_dp_idx                                  | uint32 | 0   | 0     |           |            |
| 10054 | TS_copy                                    | uint8  | 0   | 0     |           |            |
| 10055 | flagLangChange                             | uint8  | 0   | 0     |           |            |
| 10056 | TS_action                                  | uint8  | 0   | 0     |           |            |
| 10057 | TS_slot_action                             | uint8  | 0   | 0     |           |            |
| 10058 | StartSettings                              | uint8  | 0   | 0     |           |            |
| 10059 | NextSetting                                | uint8  | 0   | 0     |           |            |
| 10060 | settingsSet                                | uint8  | 0   | 0     |           |            |
| 10062 | helpForWholePages                          | int32  | 0   | 0     |           |            |
| 10069 | TS_slot_str                                | string | 0   | 0     | string    |            |
| 10071 | alarmCount                                 | uint16 | 0   | 0     |           |            |
| 10072 | alarmFlag                                  | uint8  | 0   | 0     |           |            |
| 10073 | alarmShow                                  | int16  | 0   | 0     |           |            |
| 10074 | alarmShowString                            | string | 0   | 0     | string    |            |
| 10075 | ConfigVersion2                             | string | 0   | 0     | string    |            |
| 10076 | accbutt                                    | uint8  | 0   | 0     |           |            |
| 10077 | clickaccbut                                | uint8  | 0   | 0     |           |            |
| 10083 | ecoNetForget                               | uint8  | 0   | 0     |           |            |
| 10084 | TS_validation_state                        | uint8  | 0   | 0     |           |            |
| 10090 | flag_back_webpage                          | uint8  | 0   | 0     |           |            |
| 10091 | webPage_int_help_1                         | int32  | 0   | 0     |           |            |
| 10092 | webPage_int_help_2                         | int32  | 0   | 0     |           |            |
| 10093 | webPage_int_help_3                         | int32  | 0   | 0     |           |            |
| 10094 | webPage_int_help_4                         | int32  | 0   | 0     |           |            |
| 10095 | webPage_float_help_1                       | float  | 0   | 0     |           |            |
| 10096 | webPage_float_help_2                       | float  | 0   | 0     |           |            |
| 10097 | webPage_float_help_3                       | float  | 0   | 0     |           |            |
| 10098 | webPage_float_help_4                       | float  | 0   | 0     |           |            |
| 10102 | tempDisableScrSaver                        | uint8  | 0   | 0     |           |            |
| 10120 | controller_use                             | uint16 | 0   | 0     |           |            |
| 10121 | Keyboard_text                              | string | 0   | 0     | string    |            |
| 10122 | Keyboard_min                               | string | 0   | 0     | string    |            |
| 10123 | Keyboard_max                               | string | 0   | 0     | string    |            |
| 10124 | Keyboard_current_button                    | uint8  | 0   | 0     |           |            |
| 10125 | Keyboard_value                             | string | 0   | 0     | string    |            |
| 10126 | Keyboard_unit                              | string | 0   | 0     | string    |            |
| 10127 | Keyboard_display_state                     | uint32 | 0   | 0     |           |            |
| 10129 | Update_Settings                            | uint8  | 0   | 0     |           |            |
| 10135 | Webpage_State                              | uint8  | 0   | 0     |           |            |
| 10136 | Change_program_state_std                   | uint32 | 0   | 0     |           |            |
| 10191 | Pair_State                                 | uint8  | 0   | 0     |           |            |
| 10197 | ISM_factoryReset                           | uint8  | 0   | 0     |           |            |
| 10198 | regOnce                                    | uint8  | 0   | 0     |           |            |
| 10211 | keyboard_set_range                         | uint8  | 0   | 0     |           |            |
| 10221 | Pair_State                                 | uint8  | 0   | 0     |           |            |
| 10229 | ChosenController                           | uint8  | 0   | 0     |           |            |
| 10230 | DpSdScreenView                             | uint8  | 0   | 0     |           |            |
| 10231 | SdToDo                                     | uint16 | 0   | 0     |           |            |
| 10237 | DpSdStatus                                 | uint16 | 0   | 0     |           |            |
| 10238 | ChosenFileToLoad                           | uint8  | 0   | 0     |           |            |
| 10239 | ChoseUpDownFile                            | int8   | 0   | 0     |           |            |
| 10252 | Change_program_phase                       | uint8  | 0   | 0     |           |            |
| 10253 | Change_program_state                       | uint32 | 0   | 0     |           |            |
| 10260 | DataReg_WorkState                          | uint8  | 0   | 0     |           |            |
| 10261 | DataReg_WebpageState                       | uint8  | 0   | 0     |           |            |
| 10262 | DataReg_Time                               | uint8  | 0   | 0     | numeric   |            |
| 10263 | DataReg_Param1                             | string | 0   | 0     | string    |            |
| 10264 | DataReg_Param2                             | string | 0   | 0     | string    |            |
| 10265 | DataReg_Param3                             | string | 0   | 0     | string    |            |
| 10266 | DataReg_Param4                             | string | 0   | 0     | string    |            |
| 10267 | DataReg_Param5                             | string | 0   | 0     | string    |            |
| 10268 | DataReg_ParamShow                          | uint8  | 0   | 0     |           |            |
| 10269 | DataReg_ChoseUpDownFile                    | int8   | 0   | 0     |           |            |
| 10270 | DataReg_ParamCheck                         | uint8  | 0   | 0     |           |            |
| 10271 | DataReg_ShowDataForUser                    | uint8  | 0   | 0     |           |            |
| 10272 | DataReg_IsStatusChanged                    | uint8  | 0   | 0     |           |            |
| 10273 | DataReg_CheckState                         | uint8  | 0   | 0     |           |            |
| 10280 | currentPAarent                             | uint32 | 0   | 0     |           |            |
| 10281 | currentScreenPos                           | uint8  | 0   | 0     |           |            |
| 10283 | ResetScreen_pos                            | uint8  | 0   | 0     |           |            |
| 10290 | info1                                      | uint32 | 0   | 0     |           |            |
| 10293 | info2                                      | uint32 | 0   | 0     |           |            |
| 10294 | PairDeviceGesture                          | uint8  | 0   | 0     |           |            |
| 10295 | PairDeviceVisibleMenu                      | uint8  | 0   | 0     |           |            |
| 10296 | PairDeviceVisibleState                     | uint32 | 0   | 0     | bitfield  |            |
| 10297 | CurrentCircuit                             | uint8  | 0   | 0     |           |            |
| 10298 | CurrentCurve                               | float  | 0   | 0     | numeric   |            |
| 10301 | CurrentCurveShift                          | int8   | 0   | 0     | numeric   |            |
| 10303 | CircuitSettingsBaseTemp                    | uint8  | 0   | 0     |           |            |
| 10304 | CircuitSettingsCoolingBaseTemp             | uint8  | 0   | 0     |           |            |
| 10310 | AlarmWebpageWorkState                      | uint8  | 0   | 0     |           |            |
| 10311 | AlarmWebpageWebpageState                   | uint8  | 0   | 0     |           |            |
| 10312 | AlarmWebpageCurrentAlarmsPoint             | uint8  | 0   | 0     |           |            |
| 10313 | AlarmWebpageAlarmType1                     | uint8  | 0   | 0     | enum      |            |
| 10314 | AlarmWebpageAlarmType2                     | uint8  | 0   | 0     | enum      |            |
| 10315 | AlarmWebpageAlarmType3                     | uint8  | 0   | 0     | enum      |            |
| 10316 | AlarmWebpageNextPage                       | int8   | 0   | 0     |           |            |
| 10317 | AlarmWebpageParentPage                     | uint8  | 0   | 0     |           |            |
| 10320 | AlarmDialogWorkState                       | uint8  | 0   | 0     |           |            |
| 10321 | AlarmDialogAction                          | uint8  | 0   | 0     |           |            |
| 10322 | AlarmDialogParentPage                      | uint16 | 0   | 0     |           |            |
| 10323 | AlarmDialogCurrentAlarm                    | uint16 | 0   | 0     |           |            |
| 10324 | AlarmDialogCompartment                     | string | 0   | 0     | string    |            |
| 10325 | AlarmDialogCurrentAlarmName1               | string | 0   | 0     | string    |            |
| 10326 | AlarmDialogCurrentAlarmName2               | string | 0   | 0     | string    |            |
| 10327 | AlarmDialogShowDialog                      | uint8  | 0   | 0     |           |            |
| 10337 | MainScreenGesture                          | uint8  | 0   | 0     |           |            |
| 10339 | EcoMax360iSuppSetPointTemp                 | float  | 0   | 0     | numeric   |            |
| 10340 | EcoMax360iSuppCurrentTemp                  | float  | 0   | 0     |           |            |
| 10341 | WebpageWorkstateState                      | uint8  | 0   | 0     |           |            |
| 10343 | ZoneSettingsHysteresis                     | float  | 0   | 0     |           |            |
| 10344 | ZoneSettingsSetPointEco                    | float  | 0   | 0     | numeric   |            |
| 10345 | ZoneSettingsSetPointComfort                | float  | 0   | 0     | numeric   |            |
| 10346 | WebpageSetPointTempGesture                 | uint8  | 0   | 0     | numeric   |            |
| 10350 | Choice_text_1                              | string | 0   | 0     | string    |            |
| 10351 | Choice_text_2                              | string | 0   | 0     | string    |            |
| 10352 | Choice_text_3                              | string | 0   | 0     | string    |            |
| 10353 | Choice_text_4                              | string | 0   | 0     | string    |            |
| 10354 | Choice_text_5                              | string | 0   | 0     | string    |            |
| 10355 | Choice_text_6                              | string | 0   | 0     | string    |            |
| 10356 | Choice_text_7                              | string | 0   | 0     | string    |            |
| 10357 | Choice_text_8                              | string | 0   | 0     | string    |            |
| 10358 | Choice_text_9                              | string | 0   | 0     | string    |            |
| 10359 | Choice_text_10                             | string | 0   | 0     | string    |            |
| 10360 | Choice_text                                | string | 0   | 0     | string    |            |
| 10361 | Choice_option                              | uint8  | 0   | 0     |           |            |
| 10362 | Choice_options                             | uint8  | 0   | 0     |           |            |
| 10363 | Choice_accpet                              | uint8  | 0   | 0     |           |            |
| 10364 | Choice_visibility_param                    | uint32 | 0   | 0     |           |            |
| 10365 | Choice_visibility                          | uint32 | 0   | 0     |           |            |
| 10366 | Choice_offset                              | uint8  | 0   | 0     |           |            |
| 10367 | Choice_offsetmax                           | uint8  | 0   | 0     |           |            |
| 10368 | Choice_show                                | uint8  | 0   | 0     |           |            |
| 10369 | time_date_panel                            | string | 0   | 0     | string    |            |
| 10370 | AlarmWebpageAlarmTypeNumber1               | uint8  | 0   | 0     | enum      |            |
| 10371 | AlarmWebpageAlarmTypeNumber2               | uint8  | 0   | 0     | enum      |            |
| 10372 | AlarmWebpageAlarmTypeNumber3               | uint8  | 0   | 0     | enum      |            |
| 10373 | AlarmWebpageShowDescription                | uint8  | 0   | 0     |           |            |
| 10380 | ZoneSettings                               | uint32 | 0   | 0     | bitfield  |            |
| 10389 | EcoNetConfiguratorModuleSettings           | uint32 | 0   | 0     | bitfield  |            |
| 10390 | EcoNetConfiguratorModuleControl            | uint32 | 0   | 0     |           |            |
| 10391 | EcoNetConfiguratorModuleState              | uint8  | 0   | 0     |           |            |
| 10393 | EcoNetConfiguratorButtonPressed            | uint8  | 0   | 0     |           |            |
| 10394 | webPageDateTimeModuleState                 | uint16 | 0   | 0     | numeric   |            |
| 10395 | webPageDateTimeGestureState                | uint16 | 0   | 0     | numeric   |            |
| 10399 | LangSetCurrentLang                         | uint8  | 0   | 0     |           |            |
| 10400 | LangSetModuleState                         | uint16 | 0   | 0     |           |            |
| 10401 | LangSetGestState                           | uint8  | 0   | 0     |           |            |
| 10402 | Heating_Curve_-_parallel_translation_param | uint32 | 0   | 0     | numeric   |            |
| 10403 | Heating_Curve_-_plus_minus                 | uint8  | 0   | 0     | numeric   |            |
| 10404 | Heating_Curve_-_parallel_translation       | int8   | 0   | 0     | numeric   |            |
| 10407 | StartUpWizardSet                           | uint8  | 0   | 0     |           |            |
| 10408 | ConfigurationManagerInputByte              | uint8  | 0   | 0     |           |            |
| 10409 | ConfigurationManagerInputFloat             | float  | 0   | 0     |           |            |
| 10410 | ConfigurationManagerInputInt8              | int8   | 0   | 0     |           |            |
| 10412 | Heating_Curve_-_save_params                | uint8  | 0   | 0     | numeric   |            |
| 10413 | Korekta_temperatury                        | float  | 0   | 0     |           |            |
| 10414 | Wizard_edit_img_idx                        | uint16 | 0   | 0     |           |            |
| 10415 | Wizard_edit_img_alpha_idx                  | uint16 | 0   | 0     |           |            |
| 10416 | wygaszaczTryb                              | uint8  | 0   | 0     |           |            |
| 10421 | currentCircuitBoost                        | uint8  | 0   | 0     |           |            |

### Read-Only Parameters

These parameters are read-only and cannot be modified.

| ID    | Name                                | Type   | Mechanism | Access                  | Value Example |
| ----- | ----------------------------------- | ------ | --------- | ----------------------- | ------------- |
| 0     | PS                                  | string | string    | S024.25                 |
| 1     | HV                                  | string | string    | H2.3.0                  |
| 2     | GitSHA1                             | string | string    | f91abdfc                |
| 3     | hardwarecode                        | uint8  |           | 2                       |
| 4     | curmainloop                         | uint32 |           | 1934                    |
| 10    | UID                                 | string | string    | 2L7SDPN6KQ38CIH2401K01U |
| 11    | DPv                                 | string | string    | 1.00                    |
| 12    | bootString                          | string | string    | B07                     |
| 13    | CompilationDate                     | string | string    | Jul 11 2025 11:19:57    |
| 14    | resetCounter                        | uint16 | numeric   | 28                      |
| 17    | TesterTableAddress                  | uint16 |           | 0                       |
| 18    | addres_ecoTOuch_port                | uint16 |           | 1                       |
| 21    | bin_ADCA0                           | uint16 | numeric   | 4094                    |
| 22    | bin_ADCA1                           | uint16 | numeric   | 1778                    |
| 23    | bin_ADCA2                           | uint16 | numeric   | 4094                    |
| 24    | bin_ADCA3                           | uint16 | numeric   | 1220                    |
| 25    | bin_ADCA4                           | uint16 | numeric   | 4093                    |
| 26    | bin_ADCA5                           | uint16 | numeric   | 4094                    |
| 27    | bin_ADCA6                           | uint16 | numeric   | 2631                    |
| 28    | bin_ADCA7                           | uint16 | numeric   | 4094                    |
| 29    | binADCB0                            | uint16 |           | 4094                    |
| 30    | binADCB1                            | uint16 |           | 4094                    |
| 31    | ADCA0                               | float  | numeric   | 999.0                   |
| 32    | ADCA1                               | float  | numeric   | 31.1                    |
| 33    | ADCA2                               | float  | numeric   | 999.0                   |
| 34    | ADCA3                               | float  | numeric   | 45.7                    |
| 35    | ADCA4                               | float  | numeric   | 999.0                   |
| 36    | ADCA5                               | float  | numeric   | 999.0                   |
| 37    | ADCA6                               | float  | numeric   | 12.1                    |
| 38    | ADCA7                               | float  | numeric   | 999.0                   |
| 39    | ADCB0                               | float  | numeric   | 999.0                   |
| 40    | ADCB1                               | float  | numeric   | 999.0                   |
| 61    | TempCWU                             | float  | numeric   | 45.7                    |
| 62    | TempBuforUp                         | float  | numeric   | None                    |
| 63    | TempBuforDown                       | float  | numeric   | 18.8                    |
| 64    | TempClutch                          | float  | numeric   | 19.3                    |
| 65    | TempPowGz                           | float  | numeric   | 18.8                    |
| 66    | TempCircuit2                        | float  | numeric   | 18.8                    |
| 67    | TempCircuit3                        | float  | numeric   | 18.8                    |
| 68    | TempWthr                            | float  | numeric   | 12.1                    |
| 70    | TempCircuit4                        | float  | numeric   | 18.8                    |
| 71    | TempCircuit5                        | float  | numeric   | 18.8                    |
| 72    | TempCircuit6                        | float  | numeric   | 18.8                    |
| 73    | TempCircuit7                        | float  | numeric   | 18.8                    |
| 74    | TempReturn                          | float  | numeric   | 18.8                    |
| 75    | TempOutlet                          | float  | numeric   | 19.3                    |
| 76    | TempState                           | uint32 | bitfield  | 4128                    |
| 77    | TempAhs                             | float  | numeric   | 999.0                   |
| 78    | TotalOutTemp                        | float  | numeric   | 999.0                   |
| 81    | Outputs                             | uint32 | bitfield  | 0                       |
| 82    | Inputs                              | uint32 | bitfield  | 0                       |
| 83    | flapValveStates                     | uint8  | bitfield  | 0                       |
| 85    | flapValveReason                     | uint8  | enum      | 10                      |
| 91    | Circuit1_romTempSet                 | float  | numeric   | 0                       |
| 92    | Circuit2_romTempSet                 | float  | numeric   | 19.0                    |
| 93    | Circuit3_romTempSet                 | float  | numeric   | 0                       |
| 94    | Circuit4_romTempSet                 | float  | numeric   | 0                       |
| 95    | Circuit5_romTempSet                 | float  | numeric   | 0                       |
| 96    | Circuit6_romTempSet                 | float  | numeric   | 0                       |
| 97    | Circuit7_romTempSet                 | float  | numeric   | 0                       |
| 99    | STB_state                           | uint32 | bitfield  | 0                       |
| 100   | ZT_state                            | uint32 | bitfield  | 0                       |
| 102   | HDWSTATE                            | uint32 | bitfield  | 2097280                 |
| 116   | HDWDBState                          | uint8  | bitfield  | 0                       |
| 134   | HDWsetpointcalculate                | uint8  | numeric   | 46                      |
| 148   | heatersState                        | uint8  | bitfield  | 4                       |
| 149   | heaterDhwDebug                      | uint8  | enum      | 1                       |
| 150   | heaterBuffDebug                     | uint8  | enum      | 1                       |
| 152   | AntifreezeState                     | uint32 | bitfield  | 0                       |
| 182   | BuforSTATE                          | uint32 | bitfield  | 0                       |
| 195   | BuforCalcSetTemp                    | float  | numeric   | 0                       |
| 219   | BuforminSetPointCooling             | uint8  | numeric   | 6                       |
| 220   | BuformaxSetPointCooling             | uint8  | numeric   | 20                      |
| 232   | Circuit1State                       | uint32 | bitfield  | 0                       |
| 235   | Circuit1PumpDebug                   | uint8  | enum      | 0                       |
| 237   | Circuit1CalcTemp                    | float  | numeric   | 0                       |
| 264   | Circuit1MixerState                  | uint8  | enum      | 0                       |
| 277   | Circuit1thermostat                  | float  |           | 0                       |
| 279   | Circuit1active                      | uint8  | bool      | 0                       |
| 282   | Circuit2State                       | uint32 | bitfield  | 8650752                 |
| 285   | Circuit2PumpDebug                   | uint8  | enum      | 10                      |
| 287   | Circuit2CalcTemp                    | float  | numeric   | 29.55                   |
| 314   | Circuit2MixerState                  | uint8  | enum      | 0                       |
| 315   | Mixer2valveposition                 | float  | numeric   | 0                       |
| 318   | Mixer2valvesetposition              | uint8  | numeric   | 0                       |
| 327   | Circuit2thermostatTemp              | float  | numeric   | 18.73                   |
| 329   | Circuit2active                      | uint8  | bool      | 1                       |
| 332   | Circuit3State                       | uint32 | bitfield  | 0                       |
| 335   | Circuit3PumpDebug                   | uint8  | enum      | 0                       |
| 337   | Circuit3CalcTemp                    | float  | numeric   | 0                       |
| 353   | AddSourceTimeToOnSupport            | int16  | numeric   | -1                      |
| 355   | AddSourceModuleState                | uint32 | bitfield  | 0                       |
| 364   | Circuit3MixerState                  | uint8  | enum      | 0                       |
| 365   | Mixer3valveposition                 | float  | numeric   | 0                       |
| 368   | Mixer3valvesetposition              | uint8  | numeric   | 0                       |
| 373   | UID                                 | string | string    | 2L7SDPN6KQ38CIH2401K01U |
| 374   | Nazwa                               | string | string    | ecoMAX360i              |
| 389   | ecoNet_ModuleState                  | uint8  |           | 0                       |
| 392   | ModuleB_C_AvailableDevices          | uint8  |           | 0                       |
| 393   | ModuleB_HwVersion                   | float  | numeric   | 0                       |
| 394   | ModuleB_FwVersion                   | float  | numeric   | 0                       |
| 396   | ModuleC_HwVersion                   | float  | numeric   | 0                       |
| 397   | ModuleC_FwVersion                   | float  | numeric   | 0                       |
| 399   | ADCB0                               | float  | numeric   | ---                     |
| 400   | ADCB1                               | float  | numeric   | ---                     |
| 401   | ADCC0                               | float  | numeric   | ---                     |
| 402   | ADCC1                               | float  | numeric   | ---                     |
| 410   | SystemBackgroundColorCircuit1       | uint8  | enum      | 4                       |
| 411   | SystemBackgroundColorCircuit2       | uint8  | enum      | 1                       |
| 412   | SystemBackgroundColorCircuit3       | uint8  | enum      | 4                       |
| 413   | SystemBackgroundColorCircuit4       | uint8  | enum      | 4                       |
| 414   | SystemBackgroundColorCircuit5       | uint8  | enum      | 4                       |
| 415   | SystemBackgroundColorCWU            | uint8  | enum      | 1                       |
| 416   | SystemBackgroundColorCircuit6       | uint8  | enum      | 4                       |
| 417   | SystemBackgroundColorCircuit7       | uint8  | enum      | 4                       |
| 419   | Circuit2MinTimeSwitching            | uint16 | numeric   | 1                       |
| 420   | Circuit2MaxTimeSwitching            | uint16 | numeric   | 500                     |
| 421   | Circuit3MinTimeSwitching            | uint16 | numeric   | 1                       |
| 422   | Circuit3MaxTimeSwitching            | uint16 | numeric   | 500                     |
| 423   | Circuit4MinTimeSwitching            | uint16 | numeric   | 1                       |
| 424   | Circuit4MaxTimeSwitching            | uint16 | numeric   | 500                     |
| 425   | Circuit5MinTimeSwitching            | uint16 | numeric   | 1                       |
| 426   | Circuit5MaxTimeSwitching            | uint16 | numeric   | 500                     |
| 430   | sourceTempAtStart                   | float  | numeric   | ---                     |
| 432   | CirculationState                    | uint32 | bitfield  | 0                       |
| 461   | HeatSourceAllowWork                 | uint8  |           | 1                       |
| 466   | HeatSourceContactState              | uint32 | bitfield  | 1024                    |
| 470   | HeatSourceCoolingState              | uint32 | bitfield  | 0                       |
| 475   | HeatSourcePresetTempState           | uint32 | bitfield  | 0                       |
| 479   | HeatSourceCalcPresetTemp            | uint8  |           | 25                      |
| 484   | HeatSourceMinSupplyState            | uint8  |           | 1                       |
| 486   | currentSourceWork                   | uint8  |           | 1                       |
| 488   | detectAlarmSettings                 | uint32 |           | 0                       |
| 494   | CurrenttimeBeetwenHeatingCooling    | uint16 | numeric   | 0                       |
| 495   | HeatingOrCooling                    | uint32 |           | 0                       |
| 496   | counterMinBreak                     | int32  | numeric   | -1                      |
| 497   | counterMinWork                      | int32  | numeric   | -1                      |
| 502   | compressorSpeed                     | float  |           | 0                       |
| 504   | currentOffset                       | float  |           | -16.3                   |
| 505   | countMinWorkTime                    | int32  | numeric   | -1                      |
| 506   | countMinBreakTime                   | int32  | numeric   | -1                      |
| 519   | lackFlowState                       | uint32 | bitfield  | 0                       |
| 521   | lackFlowActive                      | uint8  |           | 0                       |
| 523   | heaterPumpActualSetpoint            | uint8  | numeric   | 0                       |
| 607   | amount_Impulse                      | uint16 |           | 0                       |
| 610   | lackFlowState                       | uint32 | bitfield  | 0                       |
| 612   | currentFlow                         | float  |           | 0                       |
| 713   | HeatingPower_all                    | float  |           | 0                       |
| 714   | CoolingPower_all                    | float  |           | 0                       |
| 715   | HighCircuitTemp                     | uint8  |           | 0                       |
| 716   | DHWSetTemp                          | uint8  |           | 0                       |
| 717   | BufferSetTemp                       | uint8  |           | 0                       |
| 718   | HSST                                | uint8  |           | 25                      |
| 719   | Circuit1MinSetTemp                  | uint8  |           | 24                      |
| 750   | Circuit6State                       | uint32 | bitfield  | 0                       |
| 752   | Circuit6PumpDebug                   | uint8  | enum      | 0                       |
| 754   | Circuit6CalcTemp                    | float  | numeric   | 0                       |
| 766   | Circuit6MixerState                  | uint8  | enum      | 0                       |
| 767   | Mixer6valveposition                 | float  | numeric   | 0                       |
| 770   | Mixer6valvesetposition              | uint8  | numeric   | 0                       |
| 779   | Circuit6thermostatTemp              | float  | numeric   | 0                       |
| 781   | Circuit6active                      | uint8  | bool      | 0                       |
| 800   | Circuit7State                       | uint32 | bitfield  | 0                       |
| 802   | Circuit7PumpDebug                   | uint8  | enum      | 0                       |
| 804   | Circuit7CalcTemp                    | float  | numeric   | 0                       |
| 816   | Circuit7MixerState                  | uint8  | enum      | 0                       |
| 817   | Mixer7valveposition                 | float  | numeric   | 0                       |
| 820   | Mixer7valvesetposition              | uint8  | numeric   | 0                       |
| 829   | Circuit7thermostatTemp              | float  | numeric   | 0                       |
| 831   | Circuit7active                      | uint8  | bool      | 0                       |
| 859   | szyfWifi                            | string | string    | WPA2                    |
| 860   | ipWifi                              | string | string    | 192.168.0.52            |
| 861   | mwifi                               | string | string    | 255.255.255.0           |
| 862   | gwifi                               | string | string    | 192.168.0.1             |
| 863   | iplan                               | string | string    | 192.168.0.213           |
| 864   | mlan                                | string | string    | 255.255.255.0           |
| 865   | glan                                | string | string    | 192.168.0.1             |
| 899   | Circuit3thermostatTemp              | float  | numeric   | 0                       |
| 901   | Circuit3active                      | uint8  | bool      | 0                       |
| 917   | periodicEnergy                      | float  |           | 16694.51                |
| 918   | totalEnergy                         | float  |           | 16694.51                |
| 919   | workTime                            | uint32 | numeric   | 45                      |
| 921   | periodicWorkTime                    | uint32 | numeric   | 45                      |
| 922   | countOfImpulses                     | uint32 |           | 0                       |
| 923   | periodicCountOfImpulses             | uint32 |           | 0                       |
| 924   | workTime                            | uint32 | numeric   | 163130                  |
| 925   | periodicWorkTime                    | uint32 | numeric   | 163130                  |
| 941   | Circuit4State                       | uint32 | bitfield  | 0                       |
| 943   | Circuit4PumpDebug                   | uint8  | enum      | 0                       |
| 945   | Circuit4CalcTemp                    | float  | numeric   | 0                       |
| 972   | Circuit4MixerState                  | uint8  | enum      | 0                       |
| 973   | Mixer4valveposition                 | float  | numeric   | 0                       |
| 976   | Mixer4valvesetposition              | uint8  | numeric   | 0                       |
| 985   | Circuit4thermostatTemp              | float  | numeric   | 0                       |
| 987   | Circuit4active                      | uint8  | bool      | 0                       |
| 992   | Circuit5State                       | uint32 | bitfield  | 0                       |
| 994   | Circuit5PumpDebug                   | uint8  | enum      | 0                       |
| 996   | Circuit5CalcTemp                    | float  | numeric   | 0                       |
| 1023  | Circuit5MixerState                  | uint8  | enum      | 0                       |
| 1024  | Mixer5valveposition                 | float  | numeric   | 0                       |
| 1027  | Mixer5valvesetposition              | uint8  | numeric   | 0                       |
| 1036  | Circuit5thermostatTemp              | float  | numeric   | 0                       |
| 1038  | Circuit5active                      | uint8  | bool      | 0                       |
| 1042  | AlarmBits_1                         | uint32 |           | 0                       |
| 1043  | AlarmBits_2                         | uint32 |           | 0                       |
| 1044  | AlarmBits_3                         | uint32 |           | 0                       |
| 1045  | AlarmBits_4                         | uint32 |           | 0                       |
| 1046  | AlarmBits_5                         | uint32 |           | 0                       |
| 1047  | ElectricPower                       | float  |           | 0                       |
| 1048  | HeatingPower                        | float  |           | 0                       |
| 1049  | CoolingPower                        | float  |           | 0                       |
| 1050  | HeatingCopTemporary                 | float  | numeric   | 0                       |
| 1051  | HeatingCopAverage                   | float  |           | 7.62                    |
| 1052  | CoolingCopTemporary                 | float  | numeric   | 0                       |
| 1053  | CoolingCopAverage                   | float  |           | 11.34                   |
| 1064  | analog_boiler_control_state         | uint32 |           | 0                       |
| 1065  | ahsPumpPower                        | uint8  |           | 0                       |
| 1100  | SGModuleState                       | uint8  |           | 0                       |
| 1102  | Count_time_elements_second1         | uint32 | numeric   | 0                       |
| 1103  | Count_time_elements_second2         | uint32 | numeric   | 0                       |
| 1104  | Count_time_elements_second3         | uint32 | numeric   | 0                       |
| 1105  | Count_time_elements_second4         | uint32 | numeric   | 0                       |
| 1106  | Count_time_elements_second5         | uint32 | numeric   | 0                       |
| 1107  | Count_time_elements_second6         | uint32 | numeric   | 0                       |
| 1108  | Count_time_elements_second7         | uint32 | numeric   | 0                       |
| 1109  | Count_time_elements_second8         | uint32 | numeric   | 0                       |
| 1110  | Count_time_elements_second9         | uint32 | numeric   | 0                       |
| 1111  | Count_time_elements_second10        | uint32 | numeric   | 0                       |
| 1112  | counter_on-off_1                    | uint32 | numeric   | 0                       |
| 1113  | counter_on-off_2                    | uint32 | numeric   | 0                       |
| 1114  | counter_on-off_3                    | uint32 | numeric   | 0                       |
| 1115  | counter_on-off_4                    | uint32 | numeric   | 0                       |
| 1116  | counter_on-off_5                    | uint32 | numeric   | 0                       |
| 1117  | counter_on-off_6                    | uint32 | numeric   | 0                       |
| 1118  | counter_on-off_7                    | uint32 | numeric   | 0                       |
| 1119  | counter_on-off_8                    | uint32 | numeric   | 0                       |
| 1120  | counter_on-off_9                    | uint32 | numeric   | 0                       |
| 1121  | counter_on-off_10                   | uint32 | numeric   | 0                       |
| 1122  | Count_time_elements_minute1         | uint32 | numeric   | 0                       |
| 1123  | Count_time_elements_minute2         | uint32 | numeric   | 0                       |
| 1124  | Count_time_elements_minute3         | uint32 | numeric   | 0                       |
| 1125  | Count_time_elements_minute4         | uint32 | numeric   | 0                       |
| 1126  | Count_time_elements_minute5         | uint32 | numeric   | 0                       |
| 1127  | Count_time_elements_minute6         | uint32 | numeric   | 0                       |
| 1128  | Count_time_elements_minute7         | uint32 | numeric   | 0                       |
| 1129  | Count_time_elements_minute8         | uint32 | numeric   | 0                       |
| 1130  | Count_time_elements_minute9         | uint32 | numeric   | 0                       |
| 1131  | Count_time_elements_minute10        | uint32 | numeric   | 0                       |
| 1134  | AxenOutgoingTemp                    | float  | numeric   | 19.3                    |
| 1135  | AxenReturnTemp                      | float  | numeric   | 18.8                    |
| 1136  | AxenCompressorFreq                  | uint8  |           | 0                       |
| 1137  | AxenDischargeTemp                   | float  | numeric   | 28.5                    |
| 1138  | AxenFanSpeed                        | uint16 |           | 0                       |
| 1139  | AxenSuctionTemp                     | float  | numeric   | 26.0                    |
| 1140  | AxenUpperPump                       | uint8  |           | 0                       |
| 1141  | AxenOperatingMode                   | uint8  |           | 0                       |
| 1142  | AxenDefrostTemp                     | float  | numeric   | 0                       |
| 1143  | AxenOutdoorTemp                     | float  | numeric   | 14.3                    |
| 1144  | AxenErrorTemp                       | float  | numeric   | 0                       |
| 1145  | AxenDHWTemp                         | float  | numeric   | -30.0                   |
| 1146  | AxenBufferTemp                      | float  | numeric   | -50.0                   |
| 1147  | AXEN_REGISTER_00                    | uint16 |           | 132                     |
| 1148  | AXEN_REGISTER_01                    | uint16 |           | 0                       |
| 1149  | AXEN_REGISTER_02                    | uint16 |           | 0                       |
| 1150  | AXEN_REGISTER_03                    | uint16 |           | 0                       |
| 1151  | AXEN_REGISTER_04                    | uint16 |           | 0                       |
| 1152  | AXEN_REGISTER_05                    | uint16 |           | 0                       |
| 1153  | AXEN_REGISTER_06                    | uint16 |           | 0                       |
| 1154  | AXEN_REGISTER_07                    | uint16 |           | 1                       |
| 1155  | AXEN_REGISTER_08                    | uint16 |           | 3                       |
| 1156  | AXEN_REGISTER_09                    | uint16 |           | 4355                    |
| 1157  | AXEN_REGISTER_10                    | uint16 |           | 25                      |
| 1158  | AXEN_REGISTER_11                    | uint16 |           | 5                       |
| 1159  | AXEN_REGISTER_12                    | uint16 |           | 75                      |
| 1160  | AXEN_REGISTER_13                    | uint16 |           | 18                      |
| 1161  | AXEN_REGISTER_14                    | uint16 |           | 70                      |
| 1162  | AXEN_REGISTER_15                    | uint16 |           | 20                      |
| 1163  | AXEN_REGISTER_16                    | uint16 |           | 25                      |
| 1164  | AXEN_REGISTER_17                    | uint16 |           | 5                       |
| 1165  | AXEN_REGISTER_18                    | uint16 |           | 75                      |
| 1166  | AXEN_REGISTER_19                    | uint16 |           | 18                      |
| 1167  | AXEN_REGISTER_20                    | uint16 |           | 25                      |
| 1168  | AXEN_REGISTER_21                    | uint16 |           | 5                       |
| 1169  | AXEN_REGISTER_22                    | uint16 |           | 55                      |
| 1170  | AXEN_REGISTER_23                    | uint16 |           | 18                      |
| 1171  | AXEN_REGISTER_24                    | uint16 |           | 0                       |
| 1172  | AXEN_REGISTER_25                    | uint16 |           | 0                       |
| 1173  | AXEN_REGISTER_26                    | uint16 |           | 25                      |
| 1174  | AXEN_REGISTER_27                    | uint16 |           | 5                       |
| 1175  | AXEN_REGISTER_28                    | uint16 |           | 55                      |
| 1176  | AXEN_REGISTER_29                    | uint16 |           | 18                      |
| 1177  | AXEN_REGISTER_30                    | uint16 |           | 300                     |
| 1178  | AXEN_REGISTER_31                    | uint16 |           | 170                     |
| 1179  | AXEN_REGISTER_32                    | uint16 |           | 0                       |
| 1180  | AXEN_REGISTER_33                    | uint16 |           | 0                       |
| 1181  | AXEN_REGISTER_34                    | uint16 |           | 0                       |
| 1182  | AXEN_REGISTER_35                    | uint16 |           | 1                       |
| 1183  | AXEN_REGISTER_36                    | uint16 |           | 0                       |
| 1184  | AXEN_REGISTER_37                    | uint16 |           | 2                       |
| 1185  | AXEN_REGISTER_38                    | uint16 |           | 0                       |
| 1186  | AXEN_REGISTER_39                    | uint16 |           | 0                       |
| 1187  | AXEN_REGISTER_40                    | uint16 |           | 0                       |
| 1188  | AXEN_REGISTER_41                    | uint16 |           | 65036                   |
| 1189  | AXEN_REGISTER_42                    | uint16 |           | 188                     |
| 1190  | AXEN_REGISTER_43                    | uint16 |           | 193                     |
| 1191  | AXEN_REGISTER_44                    | uint16 |           | 65036                   |
| 1192  | AXEN_REGISTER_45                    | uint16 |           | 65036                   |
| 1193  | AXEN_REGISTER_46                    | uint16 |           | 65236                   |
| 1194  | AXEN_REGISTER_47                    | uint16 |           | 65036                   |
| 1195  | AXEN_REGISTER_48                    | uint16 |           | 65236                   |
| 1196  | AXEN_REGISTER_49                    | uint16 |           | 135                     |
| 1197  | AXEN_REGISTER_50                    | uint16 |           | 143                     |
| 1198  | AXEN_REGISTER_51                    | uint16 |           | 153                     |
| 1199  | AXEN_REGISTER_52                    | uint16 |           | 285                     |
| 1200  | AXEN_REGISTER_53                    | uint16 |           | 260                     |
| 1201  | AXEN_REGISTER_54                    | uint16 |           | 0                       |
| 1202  | AXEN_REGISTER_55                    | uint16 |           | 0                       |
| 1203  | AXEN_REGISTER_56                    | uint16 |           | 193                     |
| 1204  | AXEN_REGISTER_57                    | uint16 |           | 65036                   |
| 1205  | AXEN_REGISTER_58                    | uint16 |           | 0                       |
| 1206  | AXEN_REGISTER_59                    | uint16 |           | 0                       |
| 1207  | AXEN_REGISTER_60                    | uint16 |           | 0                       |
| 1208  | AXEN_REGISTER_61                    | float  |           | 2.1                     |
| 1209  | AXEN_REGISTER_62                    | uint16 |           | 0                       |
| 1210  | AXEN_REGISTER_63                    | uint16 |           | 0                       |
| 1211  | AXEN_REGISTER_64                    | float  |           | 0                       |
| 1212  | AXEN_REGISTER_65                    | uint16 |           | 0                       |
| 1213  | AXEN_REGISTER_66                    | uint16 |           | 190                     |
| 1214  | AXEN_REGISTER_67                    | uint16 |           | 410                     |
| 1215  | AXEN_REGISTER_68                    | uint16 |           | 190                     |
| 1216  | AXEN_REGISTER_69                    | uint16 |           | 300                     |
| 1217  | AXEN_REGISTER_70                    | uint16 |           | 480                     |
| 1218  | AXEN_REGISTER_71                    | uint16 |           | 10                      |
| 1219  | AXEN_REGISTER_72                    | uint16 |           | 0                       |
| 1220  | AXEN_REGISTER_73                    | uint16 |           | 0                       |
| 1221  | AXEN_REGISTER_74                    | uint16 |           | 232                     |
| 1222  | AXEN_REGISTER_75                    | uint16 |           | 0                       |
| 1223  | AXEN_REGISTER_76                    | uint16 |           | 323                     |
| 1224  | AXEN_REGISTER_77                    | uint16 |           | 0                       |
| 1225  | AXEN_REGISTER_78                    | uint16 |           | 0                       |
| 1226  | AXEN_REGISTER_79                    | uint16 |           | 0                       |
| 1227  | AXEN_REGISTER_80                    | uint16 |           | 0                       |
| 1228  | AXEN_REGISTER_81                    | uint16 |           | 0                       |
| 1229  | AXEN_REGISTER_82                    | uint16 |           | 0                       |
| 1230  | AXEN_REGISTER_83                    | uint16 |           | 0                       |
| 1231  | AXEN_REGISTER_84                    | uint16 |           | 0                       |
| 1232  | AXEN_REGISTER_85                    | uint16 |           | 0                       |
| 1233  | AXEN_REGISTER_86                    | uint16 |           | 570                     |
| 1234  | AXEN_REGISTER_87                    | uint16 |           | 587                     |
| 1235  | AXEN_REGISTER_88                    | uint16 |           | 0                       |
| 1236  | AXEN_REGISTER_89                    | uint16 |           | 0                       |
| 1237  | AXEN_REGISTER_90                    | uint16 |           | 0                       |
| 1238  | AXEN_REGISTER_91                    | uint16 |           | 0                       |
| 1239  | AXEN_REGISTER_92                    | uint16 |           | 0                       |
| 1240  | AXEN_REGISTER_93                    | uint16 |           | 0                       |
| 1241  | AXEN_REGISTER_94                    | uint16 |           | 0                       |
| 1242  | AXEN_REGISTER_95                    | uint16 |           | 0                       |
| 1243  | AXEN_REGISTER_96                    | uint16 |           | 0                       |
| 1244  | AXEN_REGISTER_97                    | uint16 |           | 0                       |
| 1245  | AXEN_REGISTER_98                    | uint16 |           | 0                       |
| 1246  | AXEN_REGISTER_99                    | uint16 |           | 0                       |
| 1247  | AXEN_REGISTER_100                   | uint16 |           | 0                       |
| 1248  | AXEN_REGISTER_101                   | uint16 |           | 0                       |
| 1249  | AXEN_REGISTER_102                   | uint16 |           | 8192                    |
| 1250  | AXEN_REGISTER_103                   | uint16 |           | 0                       |
| 1283  | AXEN_REGISTER_121                   | uint16 |           | 86                      |
| 1284  | AXEN_REGISTER_1201                  | uint16 |           | 0                       |
| 1285  | AXEN_REGISTER_1202_1203             | uint32 |           | 38765                   |
| 1286  | AXEN_REGISTER_1204_1205             | uint32 |           | 49                      |
| 1287  | AXEN_REGISTER_1206_1207             | uint32 |           | 33286                   |
| 1288  | AXEN_REGISTER_1208_1209             | uint32 |           | 0                       |
| 1289  | AXEN_REGISTER_1210_1211             | uint32 |           | 161                     |
| 1290  | AXEN_REGISTER_1212_1213             | uint32 |           | 159870                  |
| 1291  | AXEN_REGISTER_1214_1215             | uint32 |           | 0                       |
| 1292  | AXEN_REGISTER_1216_1217             | uint32 |           | 43                      |
| 1293  | AXEN_REGISTER_1218_1219             | uint32 |           | 29226                   |
| 1294  | AXEN_REGISTER_1220_1221             | uint32 |           | 0                       |
| 1295  | AXEN_REGISTER_1222                  | uint16 |           | 0                       |
| 1296  | AXEN_REGISTER_1223                  | uint16 |           | 0                       |
| 1297  | AXEN_REGISTER_1224                  | uint16 |           | 232                     |
| 1298  | AXEN_REGISTER_1225                  | uint16 |           | 0                       |
| 1299  | AXEN_REGISTER_1226                  | uint16 |           | 0                       |
| 1300  | AXEN_REGISTER_1227                  | uint16 |           | 0                       |
| 1301  | AXEN_REGISTER_1228                  | uint16 |           | 0                       |
| 1302  | AXEN_REGISTER_1229                  | uint16 |           | 0                       |
| 1303  | AXEN_REGISTER_1230_1231             | uint32 |           | 4                       |
| 1304  | AXEN_REGISTER_1232_1233             | uint32 |           | 0                       |
| 1305  | AXEN_REGISTER_1234_1235             | uint32 |           | 0                       |
| 1306  | AXEN_REGISTER_1236_1237             | uint32 |           | 0                       |
| 1307  | AXEN_REGISTER_1238                  | uint16 |           | 0                       |
| 1324  | EnerCount_HeatCh                    | float  |           | 150.03                  |
| 1325  | EnerCount_CoolCh                    | float  |           | 0.9                     |
| 1326  | EnerCount_Hdw                       | float  |           | 161.69                  |
| 1327  | EnerProd_HeatCh                     | float  |           | 796.2                   |
| 1328  | EnerProd_CoolCh                     | float  |           | 1.39                    |
| 1329  | EnerProd_Hdw                        | float  |           | 556.32                  |
| 1347  | ahsPumpState                        | uint8  |           | 0                       |
| 1348  | PumpSynced                          | bool   |           | 0                       |
| 1349  | HPStatusControl                     | uint8  |           | 0                       |
| 1350  | HPStatusWorkMode                    | uint8  |           | 0                       |
| 1351  | HPStatusPresetTemp                  | uint8  |           | 25                      |
| 1352  | HPStatusUhsStat                     | uint8  |           | 0                       |
| 1353  | HPStatusCircPStat0                  | uint8  |           | 0                       |
| 1354  | HPStatusCircPStat1                  | uint8  |           | 0                       |
| 1355  | HPStatusCircPStat2                  | uint8  |           | 0                       |
| 1356  | HPStatusCircPStat3                  | uint8  |           | 0                       |
| 1357  | HPStatusCircPStat4                  | uint8  |           | 0                       |
| 1358  | HPStatusCircPStat5                  | uint8  |           | 0                       |
| 1359  | HPStatusCircPStat6                  | uint8  |           | 0                       |
| 1360  | HPStatusBuffHeatStat                | uint8  |           | 0                       |
| 1361  | HPStatusHdwHeatStat                 | uint8  |           | 0                       |
| 1362  | HPStatusFlowHeatStat                | uint8  |           | 0                       |
| 1363  | HPStatusComprStat                   | uint8  |           | 0                       |
| 1364  | HPStatusFanStat                     | uint8  |           | 0                       |
| 1365  | HPStatusComprHz                     | uint16 |           | 0                       |
| 1366  | HPStatusFanRPM                      | uint16 |           | 0                       |
| 1367  | maxHeatTemp                         | uint8  |           | 75                      |
| 1368  | minCoolTemp                         | uint8  |           | 5                       |
| 1381  | belowSetpointCounter                | uint16 | numeric   | 0                       |
| 1382  | hdwBelowSetpointCounter             | uint16 | numeric   | 0                       |
| 1383  | endSuppSlowAhsPumpCounter           | uint16 | numeric   | 0                       |
| 1384  | HPSMState                           | uint8  |           | 2                       |
| 1403  | Circuit_1_ScreedDrying_Actual_Day   | uint8  |           | 1                       |
| 1406  | Circuit_2_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1409  | Circuit_3_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1412  | Circuit_4_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1415  | Circuit_5_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1418  | Circuit_6_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1421  | Circuit_7_ScreedDrying_Actual_Day   | uint8  |           | 0                       |
| 1422  | Circuit_1_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1423  | Circuit_2_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1424  | Circuit_3_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1425  | Circuit_4_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1426  | Circuit_5_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1427  | Circuit_6_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1428  | Circuit_7_ScreedDrying_TEMP         | uint8  |           | 0                       |
| 1431  | hdwLoadTimeLeft                     | uint16 | numeric   | 0                       |
| 10001 | Temp                                | float  | numeric   | 20.07                   |
| 10015 | compability                         | uint8  |           | 0                       |
| 10016 | Multimaster_State                   | uint32 | bitfield  | 1122                    |
| 10021 | isEcosterTouch                      | uint8  |           | 1                       |
| 10032 | Pop_zm._schematu                    | uint32 |           | 109771                  |
| 10033 | Pop_zm._schematu                    | uint32 |           | 39                      |
| 10034 | Ser1                                | uint32 |           | 140676                  |
| 10035 | Ser2                                | uint32 |           | 0                       |
| 10036 | Ser3                                | uint32 |           | 864804                  |
| 10042 | Prod                                | uint32 |           | 7470990                 |
| 10061 | lockChangeScreen                    | uint8  |           | 0                       |
| 10068 | prevLanguage                        | uint8  |           | 1                       |
| 10099 | webPage_in_from_zero                | uint16 |           | 0                       |
| 10100 | ecoTOuch_detected                   | uint32 | bitfield  | 1                       |
| 10101 | controller_detected                 | uint32 | bitfield  | 1                       |
| 10110 | controller_1_read_Param             | uint32 |           | 1447                    |
| 10111 | controller_2_read_Param             | uint32 |           | 0                       |
| 10112 | controller_3_read_Param             | uint32 |           | 236                     |
| 10113 | controller_4_read_Param             | uint32 |           | 1399                    |
| 10114 | controller_5_read_Param             | uint32 |           | 1389                    |
| 10115 | controller_6_read_Param             | uint32 |           | 0                       |
| 10116 | controller_7_read_Param             | uint32 |           | 0                       |
| 10117 | controller_8_read_Param             | uint32 |           | 0                       |
| 10118 | controller_9_read_Param             | uint32 |           | 0                       |
| 10119 | controller_10_read_Param            | uint32 |           | 0                       |
| 10128 | Perc._change                        | uint8  |           | 0                       |
| 10137 | New_hardware_pr                     | string | string    |                         |
| 10138 | New_software_pr                     | string | string    |                         |
| 10139 | New_comp._date_pr                   | string | string    |                         |
| 10140 | PairDevicesCircAndThermName1        | string | string    |                         |
| 10141 | PairDevicesCircAndThermName2        | string | string    |                         |
| 10142 | PairDevicesCircAndThermName3        | string | string    |                         |
| 10143 | PairDevicesCircAndThermName4        | string | string    |                         |
| 10144 | PairDevicesCircAndThermName5        | string | string    |                         |
| 10145 | PairDevicesCircAndThermName6        | string | string    |                         |
| 10146 | PairDevicesThermPairedCount         | uint8  |           | 0                       |
| 10174 | sliderPosition                      | uint8  | numeric   | 0                       |
| 10184 | alarmsGestureState                  | uint8  |           | 1                       |
| 10190 | SW_ESTER                            | string | string    |                         |
| 10192 | Circuit_1_battery                   | uint8  |           | 0                       |
| 10193 | Circuit_2_battery                   | uint8  |           | 0                       |
| 10194 | Circuit_3_battery                   | uint8  |           | 0                       |
| 10195 | Circuit_4_battery                   | uint8  |           | 0                       |
| 10196 | ESTER_moduleState                   | uint32 | bitfield  | 2                       |
| 10200 | Old_comp._date_pr                   | string | string    |                         |
| 10210 | keyobard_curretnRange               | uint8  |           | 0                       |
| 10212 | aktualna_jasnosc                    | uint8  |           | 5                       |
| 10219 | webPage_lineprint2                  | uint32 |           | 0                       |
| 10220 | SW_ESTER                            | string | string    |                         |
| 10222 | Circuit_1_battery                   | uint8  |           | 0                       |
| 10223 | Circuit_2_battery                   | uint8  |           | 0                       |
| 10224 | Circuit_3_battery                   | uint8  |           | 0                       |
| 10225 | Circuit_4_battery                   | uint8  |           | 0                       |
| 10232 | DpSdWorkingStatus                   | uint32 |           | 1                       |
| 10233 | TimeToLeftPutCard                   | uint8  | numeric   | 0                       |
| 10234 | FileNameSave                        | string | string    |                         |
| 10235 | ReadParamLevel                      | float  |           | 0                       |
| 10236 | FindFilesAtSd                       | uint8  |           | 0                       |
| 10240 | FilesName1                          | string | string    |                         |
| 10241 | FilesName2                          | string | string    |                         |
| 10242 | FilesName3                          | string | string    |                         |
| 10243 | FilesName4                          | string | string    |                         |
| 10244 | FilesName5                          | string | string    |                         |
| 10245 | sd_state                            | uint8  |           | 0                       |
| 10247 | CircSetMin                          | uint8  |           | 0                       |
| 10248 | CircSetMin                          | uint8  |           | 0                       |
| 10249 | CircTermostHystMin                  | float  |           | 0                       |
| 10250 | Number_of_founded_devices           | uint8  |           | 0                       |
| 10251 | Number_of_devices_to_update         | uint8  |           | 0                       |
| 10254 | Change_program_progress             | uint8  |           | 0                       |
| 10255 | Change_program_device_name          | string | string    |                         |
| 10256 | Change_program_device_address       | uint16 |           | 0                       |
| 10259 | heatingCurveMinTemp                 | float  | numeric   | 0.2                     |
| 10282 | enableGoDown                        | uint8  |           | 0                       |
| 10284 | posLeft                             | uint16 |           | 0                       |
| 10285 | webPage_lineprint                   | uint32 |           | 65535                   |
| 10286 | webPage_string_help_4               | string | string    |                         |
| 10287 | webPage_string_help_5               | string | string    |                         |
| 10288 | webPage_string_help_6               | string | string    |                         |
| 10291 | screenNumber                        | string | string    | 10/10                   |
| 10292 | last_screen_info_2                  | uint8  |           | 0                       |
| 10299 | ThermostatWebpageTypeActive         | uint8  |           | 3                       |
| 10300 | ThermostatWebpageNameActive         | string | string    | ecoSTER40: T2           |
| 10302 | CurrentCircuitType                  | uint8  |           | 2                       |
| 10305 | CircuitBaseTempMin                  | uint8  |           | 24                      |
| 10306 | CircuitBaseTempMax                  | uint8  |           | 45                      |
| 10307 | CircuitCoolingBaseTempMin           | uint8  |           | 18                      |
| 10308 | CircuitCoolingBaseTempMax           | uint8  |           | 25                      |
| 10318 | AlarmWebpageAmountServiceAlarms     | uint8  |           | 0                       |
| 10319 | AlarmWebpageSchowAllAlarms          | uint8  |           | 4                       |
| 10328 | AlarmTypeDescNumber                 | uint8  |           | 0                       |
| 10329 | EcoMax360iSuppZoneSettings          | uint32 |           | 8613375                 |
| 10330 | MainScreenMaxScreenShow             | uint8  |           | 1                       |
| 10331 | MainScreenCurrentScreenShow         | uint8  |           | 1                       |
| 10332 | MainScreenModuleState               | uint32 | bitfield  | 276                     |
| 10333 | MainScreenSetPointTempFrac          | string | string    | .0                      |
| 10334 | MainScreenSetPointTempInt           | string | string    | 19                      |
| 10335 | MainScreenCurrentTempFrac           | string | string    | .7                      |
| 10336 | MainScreenCurrentTempInt            | string | string    | 18                      |
| 10338 | EcoMax360iSuppZoneName              | string | string    | UFH                     |
| 10342 | WebpageWorkstateCurrent             | uint8  |           | 3                       |
| 10347 | WebpageSetPointTempSetTempInt       | string | string    | 19                      |
| 10348 | WebpageSetPointTempSetTempFrac      | string | string    | .0                      |
| 10349 | EcoMax360iSuppZoneState             | uint32 | bitfield  | 8650752                 |
| 10374 | SystemsPresenceModSettings          | uint32 |           | 0                       |
| 10375 | SystemsPresenceActiveSystems        | uint32 |           | 2                       |
| 10376 | SystemsPresenceCurrShowing          | uint8  |           | 1                       |
| 10377 | SystemsPresenceCurrActiveIdx        | uint8  |           | 0                       |
| 10378 | SystemsPresenceSysAvailable         | uint8  |           | 1                       |
| 10379 | EcoMax360iSuppActiveWorkState       | uint8  |           | 1                       |
| 10392 | EcoNetConfiguratorCurrentScreen     | uint8  |           | 0                       |
| 10396 | webPage_string_help_1               | string | string    | 20                      |
| 10397 | webPage_string_help_2               | string | string    | 07                      |
| 10398 | webPage_string_help_3               | string | string    | AM                      |
| 10405 | LangSetCurrentPage                  | uint8  |           | 0                       |
| 10406 | LangSetMaxPage                      | uint8  |           | 0                       |
| 10417 | ConfigurationManagerSummaryName     | string | string    |                         |
| 10418 | ConfigurationManagerSummarySettings | uint32 |           | 0                       |
| 10419 | ConfigurationManagerSummaryUint8    | uint8  |           | 0                       |
| 10420 | currentCircuitPicture               | uint8  |           | 2                       |
| 10422 | currentCircuitBoostTime             | uint16 | numeric   | 0                       |
