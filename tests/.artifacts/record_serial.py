#!/usr/bin/env python3
"""Record raw serial data from GM3 device for testing."""

import argparse
import datetime
import sys
import time

import serial


def main():
    parser = argparse.ArgumentParser(description="Record serial data from GM3 device")
    parser.add_argument("--port", "-p", default="/dev/ttyUSB1", help="Serial port")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="Baud rate")
    parser.add_argument("--output", "-o", default="serial_capture.bin", help="Output file for raw bytes")
    parser.add_argument("--duration", "-d", type=int, default=60, help="Recording duration in seconds (0=infinite)")
    parser.add_argument("--hex", action="store_true", help="Also print hex dump to console")
    args = parser.parse_args()

    print(f"Opening {args.port} at {args.baud} baud...")

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            timeout=1.0,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
    except serial.SerialException as e:
        print(f"Failed to open serial port: {e}")
        sys.exit(1)

    print(f"Recording to {args.output}...")
    if args.duration > 0:
        print(f"Will record for {args.duration} seconds. Press Ctrl+C to stop early.")
    else:
        print("Recording indefinitely. Press Ctrl+C to stop.")

    start_time = time.time()
    total_bytes = 0
    frame_count = 0

    try:
        with open(args.output, "wb") as f:
            while True:
                if args.duration > 0 and (time.time() - start_time) >= args.duration:
                    break

                data = ser.read(1024)
                if data:
                    f.write(data)
                    total_bytes += len(data)

                    # Count frames (0x68 = BEGIN_FRAME marker)
                    frame_count += data.count(b"\x68")

                    if args.hex:
                        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        hex_str = data.hex(" ")
                        print(f"[{timestamp}] ({len(data):3d} bytes): {hex_str}")
                    else:
                        # Simple progress indicator
                        elapsed = time.time() - start_time
                        print(
                            f"\rBytes: {total_bytes:,}  Frames: ~{frame_count}  Time: {elapsed:.1f}s",
                            end="",
                            flush=True,
                        )

    except KeyboardInterrupt:
        print("\n\nRecording stopped by user.")

    finally:
        ser.close()

    elapsed = time.time() - start_time
    print(f"\nRecorded {total_bytes:,} bytes in {elapsed:.1f} seconds")
    print(f"Approximately {frame_count} frames detected (BEGIN markers)")
    print(f"Output saved to: {args.output}")


if __name__ == "__main__":
    main()
