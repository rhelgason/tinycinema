#!/usr/bin/env python3
"""Render demo frames to images for the README.

Uses only the built-in test patterns, so anyone can regenerate these with no
media files and no ffmpeg:

    python tools/make_demo_assets.py

Two output formats, chosen to suit what each mode actually produces:

  * Half-block -> PNG. That mode's output *is* two coloured pixels per cell, so
    a bitmap is the honest representation. (As SVG it needs one rect per
    subcell, and in a gradient no two neighbours share a colour, so nothing
    merges and the file balloons past 300 KB.)
  * Character modes -> plain .txt, to paste into a fenced code block. Text is
    what those modes emit, a code block always renders, and unlike an image it
    stays selectable and searchable.

Both record what the renderer actually emitted rather than what some terminal's
font happened to draw, and both diff meaningfully in review.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tinycinema.render import RenderOptions, create  # noqa: E402
from tinycinema.sources.demo import DemoSource  # noqa: E402
from tinycinema.term import CellGrid  # noqa: E402


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------


def write_png(path: Path, rgb: np.ndarray, scale: int = 8) -> int:
    """Minimal stdlib PNG writer, nearest-neighbour upscaled.

    Blocky upscaled output is almost entirely flat runs, which is exactly what
    PNG filtering and DEFLATE are best at -- it costs far less than the extra
    resolution suggests.
    """
    big = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1).astype(np.uint8)
    h, w = big.shape[:2]
    # every scanline is prefixed with its filter type; 0 is "None"
    raw = np.hstack([np.zeros((h, 1), np.uint8), big.reshape(h, w * 3)]).tobytes()

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return len(png)


def halfblock_pixels(grid: CellGrid) -> np.ndarray:
    """Undo the half-block packing: fg is the top pixel of a cell, bg the bottom."""
    rows, cols = grid.shape
    out = np.zeros((rows * 2, cols, 3), np.uint8)
    out[0::2] = np.clip(grid.fg, 0, 255).astype(np.uint8)
    out[1::2] = np.clip(grid.bg, 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------

ASSETS = [
    # name, pattern, mode, cols, rows, timestamp, render options
    ("demo-halfblock", "mandelbrot", "halfblock", 96, 28, 0.0, {}),
    ("demo-bars", "bars", "halfblock", 96, 12, 1.2, {}),
    # Narrower than the PNGs: a code block wider than ~78 columns makes the
    # README scroll sideways on GitHub.
    ("demo-ascii", "mandelbrot", "ascii", 78, 24, 0.0, {"ramp": "standard"}),
    # Braille is 1-bit per dot, so a smooth gradient dithers into speckle.
    # Cranking contrast turns the fractal into the clean silhouette it wants.
    ("demo-braille", "mandelbrot", "braille", 78, 20, 0.0,
     {"color": False, "contrast": 6.0}),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=Path("docs"), type=Path)
    ap.add_argument("--scale", default=6, type=int, help="PNG upscale factor")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for name, pattern, mode, cols, rows, when, opts in ASSETS:
        renderer = create(mode, RenderOptions(**opts))
        w, h = renderer.pixel_size(cols, rows)
        frames = DemoSource(pattern, fps=30.0).open(
            w, h, start=when, pixel_aspect=renderer.pixel_aspect
        )
        grid = renderer.render(next(iter(frames))[1])

        if mode == "halfblock":
            path = args.out / f"{name}.png"
            size = write_png(path, halfblock_pixels(grid), scale=args.scale)
        else:
            path = args.out / f"{name}.txt"
            text = grid.to_text() + "\n"
            path.write_text(text)
            size = len(text)
        print(f"{path}  {size / 1024:6.1f} KB  ({mode}, {cols}x{rows} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
