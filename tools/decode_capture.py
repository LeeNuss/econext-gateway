#!/usr/bin/env python3
"""Decode and print frames from a captured serial binary file."""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from econet_gm3_gateway.protocol.constants import BEGIN_FRAME, END_FRAME, Command
from econet_gm3_gateway.protocol.frames import Frame


def get_command_name(cmd: int) -> str:
    """Get human-readable command name."""
    try:
        return Command(cmd).name
    except ValueError:
        return f"UNKNOWN(0x{cmd:02X})"


def format_data_hex(data: bytes, max_len: int = 64) -> str:
    """Format data as hex string, truncating if needed."""
    if len(data) <= max_len:
        return data.hex(" ")
    return data[:max_len].hex(" ") + f"... (+{len(data) - max_len} bytes)"


def extract_frames(data: bytes) -> list[tuple[int, bytes, Frame | None]]:
    """Extract frames from raw captured data."""
    frames = []
    offset = 0

    while offset < len(data):
        begin_idx = data.find(bytes([BEGIN_FRAME]), offset)
        if begin_idx == -1:
            break

        if begin_idx + 3 > len(data):
            break

        length = data[begin_idx + 1] | (data[begin_idx + 2] << 8)
        frame_end = begin_idx + length + 6

        if length > 1024 or frame_end > len(data):
            offset = begin_idx + 1
            continue

        frame_bytes = data[begin_idx:frame_end]

        if frame_bytes[-1] != END_FRAME:
            offset = begin_idx + 1
            continue

        parsed = Frame.from_bytes(frame_bytes)
        frames.append((begin_idx, frame_bytes, parsed))
        offset = frame_end

    return frames


def decode_get_params_request(data: bytes) -> str:
    """Decode GET_PARAMS request payload."""
    if len(data) < 3:
        return f"(invalid: {len(data)} bytes)"

    start_idx = data[0] | (data[1] << 8)
    count = data[2]
    return f"start_idx={start_idx}, count={count}"


def decode_get_params_response(data: bytes) -> str:
    """Decode GET_PARAMS response payload (parameter values)."""
    if len(data) < 4:
        return f"(too short: {len(data)} bytes)"

    # Response format varies, just show summary
    return f"{len(data)} bytes of parameter data"


def print_frame(idx: int, offset: int, raw: bytes, frame: Frame | None, verbose: bool = False):
    """Print a single frame."""
    if frame is None:
        print(f"[{idx:4d}] @{offset:5d} INVALID FRAME: {raw.hex(' ')[:80]}")
        return

    cmd_name = get_command_name(frame.command)

    # Direction indicator based on source/dest
    if frame.source == 255 or frame.source == 131:
        direction = ">>>"  # Gateway to controller
    else:
        direction = "<<<"  # Controller to gateway

    print(f"[{idx:4d}] @{offset:5d} {direction} {cmd_name}")
    print(f"       dest={frame.destination}, src={frame.source}, rsv=0x{frame.reserved:02X}")

    if verbose and frame.data:
        # Try to decode based on command
        if frame.command == Command.GET_PARAMS:
            decoded = decode_get_params_request(frame.data)
            print(f"       payload: {decoded}")
        elif frame.command == Command.GET_PARAMS_RESPONSE:
            decoded = decode_get_params_response(frame.data)
            print(f"       payload: {decoded}")
        else:
            print(f"       data[{len(frame.data)}]: {format_data_hex(frame.data)}")
    elif frame.data:
        print(f"       data[{len(frame.data)}]: {format_data_hex(frame.data, 32)}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Decode frames from captured serial data")
    parser.add_argument("input", help="Input binary file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed payload decoding")
    parser.add_argument("--limit", "-n", type=int, default=0, help="Limit number of frames to show (0=all)")
    parser.add_argument("--command", "-c", type=str, help="Filter by command (e.g., GET_PARAMS, 0x40)")
    parser.add_argument("--stats", "-s", action="store_true", help="Show statistics only")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    data = input_path.read_bytes()
    print(f"Loaded {len(data):,} bytes from {input_path}")
    print()

    frames = extract_frames(data)
    valid_frames = [(i, o, r, f) for i, (o, r, f) in enumerate(frames) if f is not None]
    invalid_count = len(frames) - len(valid_frames)

    print(f"Extracted {len(frames)} frames ({len(valid_frames)} valid, {invalid_count} invalid)")
    print()

    if args.stats:
        # Show statistics only
        cmd_counts: dict[int, int] = {}
        dest_counts: dict[int, int] = {}
        src_counts: dict[int, int] = {}

        for _, _, _, frame in valid_frames:
            cmd_counts[frame.command] = cmd_counts.get(frame.command, 0) + 1
            dest_counts[frame.destination] = dest_counts.get(frame.destination, 0) + 1
            src_counts[frame.source] = src_counts.get(frame.source, 0) + 1

        print("Command distribution:")
        for cmd, count in sorted(cmd_counts.items(), key=lambda x: -x[1]):
            print(f"  {get_command_name(cmd):30s}: {count}")

        print("\nDestination addresses:")
        for dest, count in sorted(dest_counts.items(), key=lambda x: -x[1]):
            print(f"  {dest:5d}: {count}")

        print("\nSource addresses:")
        for src, count in sorted(src_counts.items(), key=lambda x: -x[1]):
            print(f"  {src:5d}: {count}")
        return

    # Filter by command if specified
    if args.command:
        try:
            if args.command.startswith("0x"):
                filter_cmd = int(args.command, 16)
            else:
                filter_cmd = Command[args.command].value
        except (ValueError, KeyError):
            print(f"Unknown command: {args.command}")
            print("Available commands:", ", ".join(c.name for c in Command))
            sys.exit(1)

        valid_frames = [(i, o, r, f) for i, o, r, f in valid_frames if f.command == filter_cmd]
        print(f"Filtered to {len(valid_frames)} frames with command {args.command}")
        print()

    # Apply limit
    if args.limit > 0:
        valid_frames = valid_frames[: args.limit]

    # Print frames
    print("=" * 70)
    for idx, offset, raw, frame in valid_frames:
        print_frame(idx, offset, raw, frame, verbose=args.verbose)


if __name__ == "__main__":
    main()
