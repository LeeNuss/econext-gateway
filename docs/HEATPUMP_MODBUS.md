# Heat Pump Modbus RTU Interface

The Grant Aerona heat pump exposes a Modbus RTU interface on the ecoNET
wiring centre's **G2 (M-BUS)** terminal. The wiring centre acts as Modbus
master and continuously polls the heat pump outdoor unit.

> **Manufacturer note:** This is a newer Grant Aerona manufactured by
> **Axen**, not the older Chofu-based Aerona3. The same ecoNET controller
> is used for both, so the Modbus register map is assumed to be identical
> to the Chofu, but this has not been fully verified. The register
> documentation below is based on the community-reverse-engineered
> [Chofu register map](https://github.com/aerona-chofu-ashp/modbus)
> and should be validated against this specific unit.

## Bus Settings

| Parameter      | Value               |
|----------------|---------------------|
| Baud rate      | 9600                |
| Data bits      | 8                   |
| Parity         | None                |
| Stop bits      | 2 (8N2)            |
| Slave address  | 251 (0xFB)          |
| Protocol       | Modbus RTU          |

> **Note:** The Chofu documentation states 19200 baud and slave address 1.
> This Axen unit uses 9600 baud and address 251 (0xFB). This may be an
> Axen default or a wiring centre configuration. The settings may be
> configurable via the HP service menu. Confirmed via logic analyzer
> (Saleae Logic Pro 8) and passive bus sniffing.

## Physical Connection

### G2 M-BUS terminal (wiring centre)

Connect a USB-RS485 adapter in **passive sniffer mode** (receive-only,
tapped in parallel):

| G2 Pin | Adapter Pin | Signal  |
|--------|-------------|---------|
| D+     | A+          | RS-485+ |
| D-     | B-          | RS-485- |

A common ground connection is recommended but not strictly required for
short distances. If data appears garbled at all baud rates, check GND
and try swapping A/B (polarity conventions vary between manufacturers).

### Direct HP connection (outdoor unit PCB)

The Chofu documentation describes direct connection to the outdoor unit:

| HP PCB Pin | Signal    |
|------------|-----------|
| 15         | RS-485+   |
| 16         | RS-485-   |
| 32         | RS-485 GND|

## USB Adapter Configuration

FTDI-based USB-RS485 adapters default to a 16ms latency timer, which
fragments Modbus frames longer than ~14 bytes. Reduce it to 1ms:

```bash
# Check which ttyUSB the adapter is on
ls -la /dev/heatpump  # shows e.g. -> ttyUSB2

# Set latency timer to 1ms
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB2/latency_timer
```

To make this persistent, add a udev rule:

```
ACTION=="add", SUBSYSTEM=="usb-serial", ATTR{latency_timer}="1"
```

## Polling Pattern

The wiring centre polls the HP in a repeating cycle of approximately 10
seconds. Each cycle reads:

1. Input registers 0-103 (in blocks of 10)
2. Input register 121
3. Input registers 1201-1238 (in blocks of 10)
4. Holding registers 2100-2155 and others
5. Various holding register reads (func 0x03)

Request-to-response latency is approximately 50-80ms. The bus is idle
for ~300ms between each request/response pair.

## Register Map

### Input Registers (Function Code 0x04, read-only)

Temperature registers from the outdoor unit use integer scaling.
Values above 32767 (0x7FFF) are signed negative (e.g. 65036 = -500).

#### Sensor Readings (addr 0-9, scale: 1 unit)

| Addr | Units | Param  | Description                             |
|------|-------|--------|-----------------------------------------|
| 0    | 1 C   | 01 00  | Return water temperature                |
| 1    | 1 Hz  | 01 01  | Compressor operating frequency          |
| 2    | 1 C   | 01 02  | Discharge temperature                   |
| 3    | 100 W | 01 03  | Current consumption value               |
| 4    | 10 rpm| 01 04  | Fan control number of rotation          |
| 5    | 1 C   | 01 05  | Defrost temperature                     |
| 6    | 1 C   | 01 06  | Outdoor air temperature                 |
| 7    | 100 rpm| 01 07 | Water pump control number of rotation   |
| 8    | 1 C   | 01 08  | Suction temperature                     |
| 9    | 1 C   | 01 09  | Outgoing water temperature              |

#### Operating Mode and Setpoints (addr 10-19)

| Addr | Units  | Param  | Description                             |
|------|--------|--------|-----------------------------------------|
| 10   | enum   | 01 10  | Operating mode: 0=Off, 1=Heating, 2=Cooling |
| 11   | 0.1 C  | 01 11  | Room air set temp Zone1 (Master)        |
| 12   | 0.1 C  | 01 12  | Room air set temp Zone2 (Slave)         |
| 13   | enum   | 01 13  | DHW mode: 0=Off, 1=Comfort, 2=Economy, 3=Force |
| 14   | enum   | 01 14  | Day: 0=Mon, 1=Tue .. 6=Sun             |
| 16   | 0.1 C  | 01 31  | DHW tank temperature (Terminal 7-8)     |
| 17   | 0.1 C  | 01 32  | Outdoor air temperature (Terminal 9-10) |
| 18   | 0.1 C  | 01 33  | Buffer tank temperature (Terminal 11-12)|
| 19   | 0.1 C  | 01 34  | Mix water temperature (Terminal 13-14)  |

#### Humidity, Errors, Indoor Temps (addr 20-34)

| Addr | Units  | Param  | Description                             |
|------|--------|--------|-----------------------------------------|
| 20   | %      | 01 35  | Humidity Sensor (Terminal 18-19)        |
| 21   |        | 01 50? | Current error code                      |
| 22   |        | 01 51? | Error code once before                  |
| 23-31|        | 01 52+ | Error code history (up to 10)           |
| 32   | 1 C    | 01 72  | Plate Heat Exchanger temperature        |
| 33   | 0.1 C  |        | Indoor Master temperature actual        |
| 34   | 0.1 C  |        | Indoor Slave temperature actual         |

#### Extended Input Registers (addr 40-121)

These registers are polled by the wiring centre but are not documented
in the Chofu register map. Observed values from sniffing:

| Addr  | Observed Value | Notes                                  |
|-------|----------------|----------------------------------------|
| 41    | 65036 (-500)   | Likely signed temperature              |
| 42    | 151            |                                        |
| 43    | 148            |                                        |
| 44-48 | 65036/65236    | Likely signed temperatures             |
| 49    | 114            |                                        |
| 50-51 | 115, 133       |                                        |
| 66-69 | 190-410        | Possibly setpoints (x0.1 C?)          |
| 70    | 480            |                                        |
| 86-87 | 548, 555       |                                        |
| 102   | 8192           |                                        |
| 121   | 86             | Single register, polled separately     |

#### Registers 1201-1238

Polled by the wiring centre, purpose unknown. Possibly compressor
runtime counters or energy accumulators.

| Addr  | Observed Value | Notes                                  |
|-------|----------------|----------------------------------------|
| 1203  | 45490          | Possibly runtime (hours?)              |
| 1205  | 3              |                                        |
| 1207  | 40270          |                                        |
| 1211  | 8              |                                        |
| 1213  | 12692          |                                        |
| 1224  | 232            |                                        |
| 1231  | 4              |                                        |

### Holding Registers (Function Code 0x03, read/write)

#### Zone Heating/Cooling Setpoints (addr 0-25, scale: 0.5 C)

| Addr | Default | Param  | Description                             |
|------|---------|--------|-----------------------------------------|
| 2    | 45.0 C  | 21 01  | Zone1 fixed outgoing water setpoint (heating) |
| 3    | 45.0 C  | 21 02  | Zone1 max outgoing water temp (heating) |
| 4    | 30.0 C  | 21 03  | Zone1 min outgoing water temp (heating) |
| 5    | 0.0 C   | 21 04  | Zone1 min outdoor air temp for max water (Te1) |
| 6    | 20.0 C  | 21 05  | Zone1 max outdoor air temp for max water (Te2) |
| 7-11 |         | 21 1x  | Zone2 heating setpoints (same structure) |
| 12   | 7.0 C   | 21 21  | Zone1 fixed outgoing water setpoint (cooling) |
| 13   | 20.0 C  | 21 22  | Zone1 max outgoing water temp (cooling) |
| 14   | 18.0 C  | 21 23  | Zone1 min outgoing water temp (cooling) |
| 15   | 25.0 C  | 21 24  | Zone1 min outdoor air for cooling (Te1) |
| 16   | 35.0 C  | 21 25  | Zone1 max outdoor air for cooling (Te2) |
| 17-21|         | 21 3x  | Zone2 cooling setpoints (same structure) |
| 22   | 8.0 C   | 21 41  | Hysteresis for heating/DHW              |
| 23   | 8.0 C   | 21 42  | Hysteresis for cooling                  |
| 24   | 5.0 C   | 21 51  | Low tariff differential (heating)       |
| 25   | 5.0 C   | 21 52  | Low tariff differential (cooling)       |

#### DHW Settings (addr 26-36, scale: 0.5 C unless noted)

| Addr | Default | Param  | Description                             |
|------|---------|--------|-----------------------------------------|
| 26   | enum    | 31 01  | DHW priority: 0=unavail, 1=DHW priority, 2=heating priority |
| 27   | enum    | 31 02  | DHW config: 0=HP+heater, 1=HP only, 2=heater only |
| 28   | 50.0 C  | 31 11  | DHW comfort set temperature             |
| 29   | 40.0 C  | 31 12  | DHW economy set temperature             |
| 30   | 3.0 C   | 31 13  | DHW setpoint hysteresis                 |
| 31   | 60.0 C  | 31 14  | DHW over boost mode setpoint            |
| 32   | 61 min  | 31 21  | Max time for DHW request                |
| 33   | 30 min  | 31 31  | Delay time on DHW heater from OFF compressor |
| 34   | -5.0 C  | 31 33  | Outdoor air temp to enable DHW heaters  |
| 35   | 5.0 C   | 31 34  | Outdoor air temp hysteresis for DHW heater |
| 36   | 65.0 C  | S 31 44| Anti-legionella setpoint                |

#### Compressor and Pump Settings (addr 37-70)

| Addr | Default | Param  | Description                             |
|------|---------|--------|-----------------------------------------|
| 37   | 80 %    | 41 11  | Max frequency of night mode             |
| 38   | 0 sec   | 41 21  | Min time compressor ON-OFF              |
| 39   | 30 sec  | 41 22  | Delay pump OFF from compressor OFF      |
| 40   | 30 sec  | 41 23  | Delay compressor ON from pump ON        |
| 41   | enum    | 42 00  | Main water pump mode: 0=always ON, 1=buffer temp, 2=sniffing |
| 42   | 3 min   | 42 01  | Sniffing cycle ON time                  |
| 43   | 5 min   | 42 02  | Pump OFF time                           |
| 44   | 3 min   | 42 03  | Delay OFF pump from OFF compressor      |
| 60   | 60 %    | 44 01  | Room relative humidity value            |
| 63   | 120 sec | 45 01  | Mixing valve runtime (x10 sec)          |
| 71   | enum    | 46 00  | Backup heater: 0=off, 1=replacement, 2=emergency, 3=supplementary |

#### Extended Holding Registers (addr 2100+)

These registers are polled by the wiring centre but are outside the
Chofu-documented range. The address mapping to physical parameters is
not yet known.

| Addr  | Observed    | Notes                                   |
|-------|-------------|-----------------------------------------|
| 2100  | 15872       | Read in block of 10                     |
| 2150  | 0           | Single read                             |
| 2155  | 100         | Single read                             |
| 2200  | ILLEGAL_DATA_ADDRESS | Not supported by HP           |

### Coils (Function Code 0x01/0x05, read/write)

| Addr | Default | Param  | Description                             |
|------|---------|--------|-----------------------------------------|
| 0    |         | S01 61 | Erase error history                     |
| 1    | 1       | 03 00  | Operation on reboot after blackout      |
| 2    | 1       | 21 00  | Zone1 heating: 0=fixed, 1=climatic curve|
| 3    | 0       | 21 10  | Zone2 heating: 0=fixed, 1=climatic curve|
| 4    | 0       | 21 20  | Zone1 cooling: 0=fixed, 1=climatic curve|
| 5    | 0       | 21 30  | Zone2 cooling: 0=fixed, 1=climatic curve|
| 6    | 0       | 31 40  | Anti-legionella: 0=off, 1=on           |
| 7    | 1       | 41 00  | ON/OFF based on: 0=room setpoint, 1=water setpoint |
| 8    | 1       | 43 00  | Frost protection on room temp           |
| 9    | 1       | 43 10  | Frost protection by outdoor temp        |
| 10   | 1       | 43 20  | Frost protection on outgoing water      |
| 11   | 1       | 43 30  | DHW frost protection                    |
| 12   | 1       | 43 40  | Secondary circuit frost protection      |
| 13   | 1       | 44 10  | Humidity compensation                   |
| 14   | 1       | 46 10  | Backup heater outdoor temp dependent    |
| 15   | 1       | 47 01  | EHS outdoor temp dependent              |
| 22   | 1       | 51 15  | RS-485 Modbus enable                    |

## Sniffer Usage

```bash
# Set FTDI latency first
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB2/latency_timer

# Capture traffic
python3 tools/modbus_sniffer.py capture \
    --port /dev/heatpump --baud 9600 --stopbits 2 --parity N

# Analyze captured data
python3 tools/modbus_sniffer.py analyze --db modbus_capture.db

# Export for correlation with emoncms
python3 tools/modbus_sniffer.py export --format pivot --db modbus_capture.db
```

## References

- [aerona-chofu-ashp/modbus](https://github.com/aerona-chofu-ashp/modbus) -
  Chofu/Grant Aerona3 Modbus register mappings (community reverse-engineered)
- Chofu service mode manual (accessible via HP installer menu)
