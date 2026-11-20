# Home Assistant App: ecoNEXT Gateway

Local control of ecoNET heat pump controllers, such as the Grant Aerona R290,
without the cloud.

![Supports aarch64 Architecture][aarch64-shield] ![Supports amd64 Architecture][amd64-shield]

## About

The ecoNEXT gateway talks to the heat pump controller over its RS-485 bus and
serves every controller parameter through a local REST API. The
[ecoNEXT integration][integration] turns that into Home Assistant entities:
temperatures, flow and power readings, heating and hot water settings,
schedules and alarms, all readable and writable.

This app runs the gateway on the Home Assistant machine itself, so no separate
Raspberry Pi is needed. All you need is a USB-RS485 adapter wired to the
controller.

## Features

- Reads all ~1870 controller and panel parameters, refreshed every 10 seconds
- Writes settings back: setpoints, modes, schedules, boost
- Alarm history
- Virtual thermostat: use any Home Assistant temperature sensor as the room
  thermostat the heat pump controls on
- Keeps the panel clock in sync, including DST changes
- Runs alongside the ecoNET300, so cloud and installer access keep working
- No cloud, no account, everything stays on your network

See the **Documentation** tab for wiring and setup.

[integration]: https://github.com/LeeNuss/econext
[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
