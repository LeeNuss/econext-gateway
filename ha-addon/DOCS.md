# ecoNEXT Gateway

Runs the [ecoNEXT gateway](https://github.com/LeeNuss/econext-gateway) on the
Home Assistant machine itself, so no separate Raspberry Pi is needed. Wire a
USB-RS485 adapter to the controller's G1 bus and plug it into the Home
Assistant machine.

## Setup

1. Pick the adapter under **Serial port**, preferably its `/dev/serial/by-id/...`
   entry, and start the app.
2. The first start takes 2-3 minutes while the gateway registers itself on the
   bus. The address is stored, so later starts are immediate.
3. Install the ecoNEXT integration through HACS and point it at the Home
   Assistant host's IP address, port 8000.

## Options

- **Serial port**: the USB-RS485 adapter.
- **Log level**: `info` is quiet in steady state; use `debug` for bus traces.
- **Virtual thermostat**: lets Home Assistant act as a room thermostat. It only
  becomes active on the bus once you pair it from the integration.
- **Panel clock sync**: sets the panel clock from Home Assistant once a day and
  after DST changes.

The REST API port can be changed under **Network**. Bus address and
thermostat pairing are kept in the app's data and survive updates.

## Updates

The app version is the gateway release it installs. A new gateway release
shows up as an app update.
