"""
Helper: write a tiny but structurally valid silent MP3 file. Used by metadata
tests that need an actual MP3 on disk to read/write ID3 frames against.

The bytes below are a single MPEG-1 Layer III frame at 44.1 kHz, 128 kbps, mono,
filled with zero data. Mutagen accepts this as a parsable MP3.
"""
from pathlib import Path
import struct


def write_silence_mp3(path: Path) -> None:
    # MPEG-1 Layer III header: 11 sync bits + version 1 + layer III + no CRC,
    # 128 kbps + 44.1 kHz + no padding + private + mono + no copy + original + emphasis none.
    # Decoded as 4-byte big-endian: 0xFFFB9064
    frame_header = struct.pack(">I", 0xFFFB9064)
    # 128 kbps @ 44.1 kHz mono frame size = 144 * 128000 / 44100 = ~417 bytes total
    frame_data = b"\x00" * (417 - 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        # A few frames so mutagen has enough to chew on
        for _ in range(10):
            f.write(frame_header + frame_data)
