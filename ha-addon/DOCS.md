# ecoNEXT Gateway

Runs the [ecoNEXT gateway][gateway] on the Home Assistant machine. The gateway
connects to the heat pump controller over RS-485 and serves its parameters
through a local REST API that the [ecoNEXT integration][integration] uses.

```
[Home Assistant] --HTTP--> [ecoNEXT Gateway app] --RS-485--> [Heat pump controller]
```

## Hardware

- A **USB-RS485 adapter**. The ecoLINK3 cable that comes with the ecoNET300
  works, as does any FTDI-based adapter (for example Waveshare FT232RL).
- A free USB port on the Home Assistant machine.

### Wiring

Power the controller down before wiring.

- **Replacing the ecoNET300**: unplug the ecoLINK3 cable from the ecoNET300
  module and plug its USB end into the Home Assistant machine.
- **Alongside the ecoNET300** (keeps the econet24 cloud and installer access):
  leave the ecoNET300 on the controller's **G3** socket and wire a second
  USB-RS485 adapter to the **G1** socket, in parallel with the touch panel.
  See [running alongside the ecoNET300][parallel].

## Installation

1. Install this app and open its **Configuration** tab.
2. Pick the adapter under **Serial port**. Prefer the `/dev/serial/by-id/...`
   entry, it stays the same across reboots.
3. Start the app and open the **Log** tab. The first start takes 2-3 minutes
   while the gateway registers itself on the bus. The address is stored, so
   later starts are immediate.
4. Install the ecoNEXT integration through HACS and add it with the Home
   Assistant host's IP address and port 8000.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| Serial port | `/dev/ttyUSB0` | The USB-RS485 adapter. |
| Log level | `info` | `info` is quiet in steady state. `debug` shows bus traffic. |
| Panel clock sync | on | Sets the panel clock from Home Assistant once a day at 03:30 and after DST changes. |

The API port can be changed in the **Network** section. Use the new port in
the integration as well.

## Virtual thermostat

The gateway can pose as a wireless room thermostat, using any Home Assistant
temperature sensor as the room temperature. Pick the sensor in the ecoNEXT
integration's options, turn on its **Pairing** switch, then start the
thermostat wizard on the panel within 60 seconds. Until it is paired the
virtual thermostat does nothing on the bus. Details in the
[gateway README][thermostat].

## Data and updates

The bus address and the thermostat pairing are kept in the app's data and
survive restarts and updates. Uninstalling the app removes them; the gateway
then registers again on the next install.

The app version is the gateway release it installs. A new gateway release
shows up as an app update.

## Troubleshooting

**The app does not start**: check the **Log** tab. If the serial port cannot
be opened, pick the adapter again in the configuration; the device name can
change when it is plugged into another port.

**No parameters after several minutes**: make sure nothing else uses the
adapter, then set the log level to `debug` and restart. The log shows whether
the panel probes the gateway (`IDENTIFY`) and grants it the bus token.

**Values freeze**: if the bus goes quiet for 30 seconds the gateway reopens
the serial port on its own and logs `Bus silent for ...s, reconnecting serial
port`. If that happens often, the adapter or its wiring is the first suspect.

Questions and bug reports: [GitHub issues][issues] or the
[OpenEnergyMonitor forum thread][forum].

[gateway]: https://github.com/LeeNuss/econext-gateway
[integration]: https://github.com/LeeNuss/econext
[parallel]: https://github.com/LeeNuss/econext-gateway/blob/main/docs/PARALLEL_ECONET300.md
[thermostat]: https://github.com/LeeNuss/econext-gateway#virtual-thermostat
[issues]: https://github.com/LeeNuss/econext-gateway/issues
[forum]: https://community.openenergymonitor.org/t/econext-direct-local-control-of-grant-hp290-econet-replacement-plum-ecomax360i/29758
