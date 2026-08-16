# Running Alongside ecoNET300

The gateway can run on the same RS-485 bus as the ecoNET300, so the econet24 cloud/app and installer remote access keep working while Home Assistant talks to the gateway locally. Confirmed working by multiple users, see [issue #4](https://github.com/LeeNuss/econext-gateway/issues/4).

Requires gateway v0.2.0 or later. Earlier alphas registered on the bus with the same identity as the ecoNET300 and could confuse it.

## Hardware

- ecoNET300 stays connected via its ecoLINK3 cable to the controller's **G3** socket.
- The gateway needs a **second USB-to-RS-485 converter**, wired to the **G1** socket in parallel with the touch panel. G1 and G3 share the same RS-485 bus. Do not use G2 (Modbus to the heat pump).
- Known-good converter: [Waveshare Industrial USB-RS485](https://www.amazon.co.uk/Waveshare-Industrial-USB-RS485-Transceiving/dp/B081NBCJRS/) (FTDI FT232RL, USB ID `0403:6001`). A second ecoLINK3 also works and is auto-detected by the default udev rule.
- Socket pinout: [Grant Aerona Smart Controller installer manual](https://www.grantuk.com/media/6037/grant-aerona-smart-controller-installer-and-operating-instructions-uk-doc-0203-rev-20-october-2024.pdf).

Power down the controller before wiring.

## Setup

1. Wire the converter to G1 and plug it into the Pi.
2. For a non-ecoLINK3 converter, create `/etc/udev/rules.d/99-econext-local.rules` (a separate file so upgrades do not overwrite it) with a line matching your adapter, e.g. for the Waveshare / FT232RL:
   ```
   SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="econext", MODE="0666"
   ```
   Check `idVendor`/`idProduct` with `udevadm info -a /dev/ttyUSB0 | grep -E 'idVendor|idProduct'`. Then:
   ```bash
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ls -la /dev/econext
   ```
   Alternatively skip the symlink and set `ECONEXT_SERIAL_PORT=/dev/ttyUSB0`.
3. If the gateway previously ran standalone (as the ecoNET300 replacement at address 131), delete the persisted address so it claims a fresh one:
   ```bash
   sudo rm -f /var/lib/econext-gateway/paired_address
   ```
4. Power the controller back up and (re)start the gateway. Initial registration takes 2-3 minutes.

## Bus addressing

No configuration is needed. The ecoNET300 uses the fixed address 131 and identifies as `PLUM EcoNET`. The gateway never claims 131; it identifies as `PLUM EcoNEXT` and auto-registers at a free panel peripheral address (105-130). Both devices are polled by the panel and receive their own token.

A healthy parallel bus in `ECONEXT_LOG_LEVEL=DEBUG` (gateway at 114, ecoNET300 at 131, thermostat at 166):

```
src=100 dst=131 IDENTIFY
src=131 dst=100 IDENTIFY_ANS  identity='PLUM EcoNET'
src=100 dst=131 SERVICE func=0x0801   <- token grant to ecoNET300
src=131 dst=100 SERVICE func=0x0200   <- ecoNET300 exchanges (repeats)
src=131 dst=100 SERVICE func=0x0800   <- token return
src=100 dst=114 IDENTIFY
src=114 dst=100 IDENTIFY_ANS  identity='PLUM EcoNEXT'
...
```

## Notes

- Both devices can write parameters. A write from one shows up in the other on its next poll, so avoid automations on both sides fighting over the same setpoint.
- Removing the ecoNET300 later needs no change on the gateway side.

## Troubleshooting

**ecoNET300 shows "Not connected" / empty tiles after wiring**

- Power cycle the controller so it rebuilds its device table.
- Re-run the ecoNET config wizard from the panel.
- Sniff the bus with the gateway stopped and `ECONEXT_LOG_LEVEL=DEBUG`: the panel should send `IDENTIFY` to 131 and the ecoNET300 should answer with `IDENTIFY_ANS`. If 131 never answers, the ecoNET300 itself is not registering; check its cable to G3.

**Gateway claims an address but returns no parameters**

- Delete `/var/lib/econext-gateway/paired_address` and restart; only addresses 105-130 are valid, older versions could pick others.
- Wait a full 2-3 minutes for registration and the first poll.
