#!/usr/bin/env python3
"""Auto-detect Modbus RTU serial parameters by trying common settings and
validating received data against the Modbus CRC16.

Tries combinations of baud rate and parity, listens for a few seconds on each,
and reports which settings produce valid Modbus RTU frames.
"""

import argparse
import struct

import serial

# Common Modbus RTU settings to try
BAUD_RATES = [9600, 19200, 38400, 57600, 115200]
PARITIES = [
    ("None", serial.PARITY_NONE, 1),  # 8N1
    ("Even", serial.PARITY_EVEN, 1),  # 8E1
]


def modbus_crc16(data: bytes) -> int:
    """Compute Modbus CRC16 (reflected, poly 0xA001)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def inter_frame_gap(baud: int) -> float:
    """Modbus RTU inter-frame silence: 3.5 character times.

    One character = start + 8 data + parity + stop = ~11 bits.
    """
    char_time = 11.0 / baud
    gap = 3.5 * char_time
    # Modbus spec says minimum 1.75ms for baud > 19200
    return max(gap, 0.00175)


def extract_frames(data: bytes, baud: int) -> list[bytes]:
    """Split raw bytes into candidate frames using timing gaps.

    Since we read in bulk, we can't use real timing. Instead, treat the
    entire buffer as one or more frames and try sliding-window CRC checks.
    """
    frames = []
    # Modbus RTU frame: min 4 bytes (addr + func + 2 CRC)
    # Try to find valid frames by scanning for valid CRC at different lengths
    i = 0
    while i < len(data) - 3:
        # Try frame lengths from 4 (minimum) up to 256 (max practical)
        for length in range(4, min(257, len(data) - i + 1)):
            candidate = data[i : i + length]
            payload = candidate[:-2]
            received_crc = struct.unpack("<H", candidate[-2:])[0]
            if modbus_crc16(payload) == received_crc:
                # Sanity check: slave address 1-247, function code 1-127
                if 1 <= candidate[0] <= 247 and 1 <= candidate[1] <= 127:
                    frames.append(candidate)
                    i += length
                    break
        else:
            i += 1
    return frames


def try_settings(port: str, baud: int, parity: str, stopbits: int, listen_seconds: float) -> list[bytes]:
    """Listen on the given settings and return any valid Modbus frames found."""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            parity=parity,
            stopbits=stopbits,
            bytesize=serial.EIGHTBITS,
            timeout=listen_seconds,
        )
    except serial.SerialException as e:
        print(f"  Could not open port: {e}")
        return []

    try:
        # Flush any stale data
        ser.reset_input_buffer()
        # Read for the listen period
        data = ser.read(4096)
        if not data:
            return []
        return extract_frames(data, baud)
    finally:
        ser.close()


def main():
    parser = argparse.ArgumentParser(description="Auto-detect Modbus RTU serial parameters")
    parser.add_argument(
        "--port",
        default="/dev/modbus_sniff",
        help="Serial port (default: /dev/modbus_sniff)",
    )
    parser.add_argument(
        "--listen",
        type=float,
        default=5.0,
        help="Seconds to listen per setting (default: 5)",
    )
    args = parser.parse_args()

    print(f"Scanning {args.port} for Modbus RTU traffic...")
    print(f"Listening {args.listen:.1f}s per combination\n")

    results = []

    for baud in BAUD_RATES:
        for parity_name, parity_val, stopbits in PARITIES:
            label = f"{baud} 8{parity_name[0]}{stopbits}"
            print(f"Trying {label}...", end=" ", flush=True)

            frames = try_settings(args.port, baud, parity_val, stopbits, args.listen)

            if frames:
                print(f"FOUND {len(frames)} valid frame(s)")
                results.append((label, baud, parity_val, stopbits, frames))
                for j, frame in enumerate(frames[:5]):
                    addr = frame[0]
                    func = frame[1]
                    print(f"    [{j}] addr={addr} func=0x{func:02X} len={len(frame)}")
                if len(frames) > 5:
                    print(f"    ... and {len(frames) - 5} more")
            else:
                print("no valid frames")

    print("\n" + "=" * 50)
    if results:
        print("Detected settings:\n")
        for label, _, _, _, frames in results:
            print(f"  {label}: {len(frames)} valid frame(s)")
        best = results[0]
        print(f"\nRecommended: --baud {best[1]} --parity {'N' if best[2] == serial.PARITY_NONE else 'E'}")
    else:
        print("No valid Modbus RTU frames detected.")
        print("Check wiring and make sure the bus is active.")


if __name__ == "__main__":
    main()
