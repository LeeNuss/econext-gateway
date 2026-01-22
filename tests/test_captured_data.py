"""Tests using real captured serial data from GM3 device."""

from pathlib import Path

import pytest

from econet_gm3_gateway.protocol.constants import BEGIN_FRAME, END_FRAME, Command
from econet_gm3_gateway.protocol.frames import Frame

# Path to captured data
ARTIFACTS_DIR = Path(__file__).parent / ".artifacts"
CAPTURE_FILE = ARTIFACTS_DIR / "serial_capture.bin"


def extract_frames_from_capture(data: bytes) -> list[tuple[int, bytes, Frame | None]]:
    """
    Extract frames from raw captured data.

    Returns list of (offset, raw_bytes, parsed_frame_or_none) tuples.
    """
    frames = []
    offset = 0

    while offset < len(data):
        # Find next BEGIN marker
        begin_idx = data.find(bytes([BEGIN_FRAME]), offset)
        if begin_idx == -1:
            break

        # Check if we have enough bytes for length field
        if begin_idx + 3 > len(data):
            break

        # Extract length (little-endian 16-bit)
        length = data[begin_idx + 1] | (data[begin_idx + 2] << 8)
        frame_end = begin_idx + length + 6  # Total frame size

        # Sanity check on length
        if length > 1024 or frame_end > len(data):
            offset = begin_idx + 1
            continue

        # Extract potential frame
        frame_bytes = data[begin_idx:frame_end]

        # Check END marker
        if frame_bytes[-1] != END_FRAME:
            offset = begin_idx + 1
            continue

        # Try to parse frame
        parsed = Frame.from_bytes(frame_bytes)
        frames.append((begin_idx, frame_bytes, parsed))

        offset = frame_end

    return frames


@pytest.fixture
def capture_data() -> bytes:
    """Load captured serial data."""
    if not CAPTURE_FILE.exists():
        pytest.skip(f"Capture file not found: {CAPTURE_FILE}")
    return CAPTURE_FILE.read_bytes()


class TestCapturedFrames:
    """Tests using real captured serial data."""

    def test_capture_file_exists(self):
        """Verify capture file exists."""
        assert CAPTURE_FILE.exists(), f"Capture file not found: {CAPTURE_FILE}"

    def test_capture_file_not_empty(self, capture_data):
        """Verify capture file has data."""
        assert len(capture_data) > 0, "Capture file is empty"

    def test_contains_begin_markers(self, capture_data):
        """Verify capture contains frame begin markers."""
        begin_count = capture_data.count(bytes([BEGIN_FRAME]))
        assert begin_count > 0, "No BEGIN_FRAME markers found in capture"
        print(f"\nFound {begin_count} BEGIN_FRAME markers")

    def test_contains_end_markers(self, capture_data):
        """Verify capture contains frame end markers."""
        end_count = capture_data.count(bytes([END_FRAME]))
        assert end_count > 0, "No END_FRAME markers found in capture"
        print(f"\nFound {end_count} END_FRAME markers")

    def test_extract_frames(self, capture_data):
        """Extract and count frames from capture."""
        frames = extract_frames_from_capture(capture_data)

        valid_count = sum(1 for _, _, parsed in frames if parsed is not None)
        invalid_count = sum(1 for _, _, parsed in frames if parsed is None)

        print(f"\nExtracted {len(frames)} potential frames")
        print(f"  Valid (CRC OK): {valid_count}")
        print(f"  Invalid (CRC failed): {invalid_count}")

        assert len(frames) > 0, "No frames extracted from capture"

    def test_frame_parsing_success_rate(self, capture_data):
        """Check that most frames parse successfully."""
        frames = extract_frames_from_capture(capture_data)
        valid_count = sum(1 for _, _, parsed in frames if parsed is not None)

        if len(frames) > 0:
            success_rate = valid_count / len(frames)
            print(f"\nFrame parsing success rate: {success_rate:.1%}")
            # We expect at least some frames to be valid
            assert valid_count > 0, "No valid frames found in capture"

    def test_valid_frame_structure(self, capture_data):
        """Verify structure of valid parsed frames."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [(offset, raw, parsed) for offset, raw, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to test")

        for offset, raw, parsed in valid_frames[:10]:  # Check first 10 valid frames
            # Verify frame attributes exist
            assert hasattr(parsed, "destination")
            assert hasattr(parsed, "source")
            assert hasattr(parsed, "command")
            assert hasattr(parsed, "data")

            # Verify roundtrip works
            rebuilt = parsed.to_bytes()
            assert rebuilt == raw, f"Frame at offset {offset} doesn't roundtrip correctly"

    def test_command_distribution(self, capture_data):
        """Analyze command codes in captured frames."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [parsed for _, _, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to analyze")

        command_counts: dict[int, int] = {}
        for frame in valid_frames:
            cmd = frame.command
            command_counts[cmd] = command_counts.get(cmd, 0) + 1

        print("\nCommand distribution:")
        for cmd, count in sorted(command_counts.items()):
            # Try to get command name
            try:
                cmd_name = Command(cmd).name
            except ValueError:
                cmd_name = "UNKNOWN"
            print(f"  0x{cmd:02X} ({cmd_name}): {count}")

    def test_destination_addresses(self, capture_data):
        """Analyze destination addresses in captured frames."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [parsed for _, _, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to analyze")

        dest_counts: dict[int, int] = {}
        for frame in valid_frames:
            dest = frame.destination
            dest_counts[dest] = dest_counts.get(dest, 0) + 1

        print("\nDestination address distribution:")
        for dest, count in sorted(dest_counts.items()):
            print(f"  {dest}: {count} frames")

    def test_source_addresses(self, capture_data):
        """Analyze source addresses in captured frames."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [parsed for _, _, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to analyze")

        src_counts: dict[int, int] = {}
        for frame in valid_frames:
            src = frame.source
            src_counts[src] = src_counts.get(src, 0) + 1

        print("\nSource address distribution:")
        for src, count in sorted(src_counts.items()):
            print(f"  {src}: {count} frames")

    def test_frame_data_lengths(self, capture_data):
        """Analyze payload lengths in captured frames."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [parsed for _, _, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to analyze")

        lengths = [len(frame.data) for frame in valid_frames]
        min_len = min(lengths)
        max_len = max(lengths)
        avg_len = sum(lengths) / len(lengths)

        print("\nPayload lengths:")
        print(f"  Min: {min_len} bytes")
        print(f"  Max: {max_len} bytes")
        print(f"  Avg: {avg_len:.1f} bytes")

    def test_first_valid_frame_details(self, capture_data):
        """Print details of first valid frame for debugging."""
        frames = extract_frames_from_capture(capture_data)
        valid_frames = [(offset, raw, parsed) for offset, raw, parsed in frames if parsed is not None]

        if not valid_frames:
            pytest.skip("No valid frames to display")

        offset, raw, parsed = valid_frames[0]
        print(f"\nFirst valid frame at offset {offset}:")
        print(f"  Raw hex: {raw.hex(' ')}")
        print(f"  Destination: {parsed.destination}")
        print(f"  Source: {parsed.source}")
        print(f"  Command: 0x{parsed.command:02X}")
        print(f"  Data length: {len(parsed.data)} bytes")
        if len(parsed.data) <= 32:
            print(f"  Data hex: {parsed.data.hex(' ')}")
