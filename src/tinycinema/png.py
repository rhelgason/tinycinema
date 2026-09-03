"""A minimal PNG encoder, stdlib only.

iTerm2's inline-image protocol wants a real image file, and PNG is the one
worth hand-rolling: zlib is in the standard library, so the whole encoder is
a header, one DEFLATE stream and three CRCs. Pulling in Pillow to write a few
kilobytes of RGB would be a poor trade.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np


def encode_png(rgb: np.ndarray, *, level: int = 1) -> bytes:
    """(H, W, 3) uint8 -> PNG bytes.

    Compression defaults to level 1: this runs once per video frame, so the
    couple of milliseconds level 9 would cost matter far more than the bytes it
    would save on a picture that is discarded 33ms later.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"expected (H, W, 3) RGB, got {rgb.shape}")
    data = np.ascontiguousarray(rgb, dtype=np.uint8)
    height, width = data.shape[:2]

    # Every PNG scanline is prefixed with a filter byte; 0 means "no filter".
    raw = np.hstack(
        [np.zeros((height, 1), np.uint8), data.reshape(height, width * 3)]
    ).tobytes()

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, level))
        + _chunk(b"IEND", b"")
    )


def _chunk(tag: bytes, payload: bytes) -> bytes:
    body = tag + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
