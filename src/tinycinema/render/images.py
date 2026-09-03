"""Real pixels: terminal inline-image protocols.

These modes sidestep glyphs entirely. Where a cell renderer maps pixels onto
characters, these hand the terminal an actual bitmap and let it draw. On a
terminal that supports one, the result is simply the video.

Three protocols, all mutually incompatible, because of course they are:

  kitty   Kitty's graphics protocol. Raw RGB, base64, chunked. The best of the
          three: no re-encode, explicit cell placement, image ids so a frame
          replaces its predecessor instead of stacking up.
  iterm   iTerm2's OSC 1337. Wants a real image file, so each frame is PNG
          encoded first -- a few ms per frame we don't pay for kitty.
  sixel   The 1987 DEC standard, still the most widely supported: xterm, foot,
          WezTerm, mlterm, Windows Terminal. Palette-based, so it needs colour
          quantisation, and it is by far the most verbose on the wire.

They share a different shape from the cell renderers: one payload string per
frame rather than a grid of cells, so there is nothing to diff. See ImageWriter.
"""

from __future__ import annotations

import base64

import numpy as np

from ..png import encode_png
from ..term import CellGrid
from .base import Renderer, register

#: Kitty requires the base64 payload be split into chunks of at most 4096 bytes.
_KITTY_CHUNK = 4096

#: A sixel data byte encodes six stacked pixels as bits, offset by '?' (0x3F).
_SIXEL_CHARS = [chr(63 + i) for i in range(64)]


class ImageRenderer(Renderer):
    """Base for modes that emit a bitmap escape instead of a cell grid."""

    #: Lets the player pick the image writer instead of the diffing one.
    is_image = True

    #: Pixels per cell. Deliberately below a real cell's ~8x16: the terminal
    #: scales our bitmap up to the cell box it is given, and these modes are
    #: bandwidth-bound, not detail-bound.
    px_per_cell = (4, 8)

    #: Hard ceiling on pixels per frame. This is the whole ballgame for image
    #: modes: raw RGB at a full 200x50-cell terminal would be 1600x800 = 3.8 MB
    #: a frame, or 115 MB/s at 30fps, which no terminal will take. Capped here,
    #: a frame is ~170 KB raw and playback is merely expensive rather than
    #: impossible. Even so, --fps 15 is often the difference between smooth and
    #: not.
    MAX_PIXELS = 180_000

    @property
    def pixel_aspect(self) -> float:
        # 4x8 pixels in a cell that is 1x2 units: pixels come out square.
        return 1.0

    def pixel_size(self, cols: int, rows: int) -> tuple[int, int]:
        w, h = cols * self.px_per_cell[0], rows * self.px_per_cell[1]
        total = w * h
        if total > self.MAX_PIXELS:
            # Uniform scale, so the pixel aspect ratio is untouched.
            scale = (self.MAX_PIXELS / total) ** 0.5
            w, h = max(2, int(w * scale)), max(2, int(h * scale))
        return w, h

    def render(self, rgb: np.ndarray) -> CellGrid:  # pragma: no cover
        raise TypeError(f"{self.name} is an image mode; call encode_image()")

    def encode_image(self, rgb: np.ndarray, cols: int, rows: int) -> str:
        raise NotImplementedError


@register
class KittyRenderer(ImageRenderer):
    """Kitty graphics protocol -- raw RGB, no re-encode."""

    name = "kitty"

    def encode_image(self, rgb: np.ndarray, cols: int, rows: int) -> str:
        height, width = rgb.shape[:2]
        payload = base64.b64encode(np.ascontiguousarray(rgb, np.uint8).tobytes())

        # a=T transmit-and-display, f=24 packed RGB, c/r place it in the cell
        # grid, i=1 reuses one image id so each frame replaces the last rather
        # than piling up, q=2 suppresses the terminal's acknowledgements (which
        # would otherwise land in our keyboard input).
        head = f"a=T,f=24,s={width},v={height},c={cols},r={rows},i=1,q=2"

        out: list[str] = ["\x1b[H"]
        if len(payload) <= _KITTY_CHUNK:
            out.append(f"\x1b_G{head},m=0;{payload.decode('ascii')}\x1b\\")
            return "".join(out)

        chunks = [
            payload[i : i + _KITTY_CHUNK] for i in range(0, len(payload), _KITTY_CHUNK)
        ]
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            # Control keys go on the first chunk only; the rest carry just m=.
            prefix = f"{head},m={0 if last else 1}" if index == 0 else f"m={0 if last else 1}"
            out.append(f"\x1b_G{prefix};{chunk.decode('ascii')}\x1b\\")
        return "".join(out)


@register
class ITermRenderer(ImageRenderer):
    """iTerm2 inline images (OSC 1337). Each frame is PNG encoded."""

    name = "iterm"

    def encode_image(self, rgb: np.ndarray, cols: int, rows: int) -> str:
        png = encode_png(rgb)
        data = base64.b64encode(png).decode("ascii")
        # preserveAspectRatio=0: we already letterboxed to the exact cell box,
        # so letting iTerm2 fit it again would inset it a second time.
        return (
            "\x1b[H\x1b]1337;File=inline=1;"
            f"width={cols};height={rows};preserveAspectRatio=0;"
            f"size={len(png)}:{data}\x07"
        )


# Sixel encodes six vertical pixels per character, one bit each, per colour
# pass. A 6x6x6 colour cube (the same one xterm uses for 256-colour mode) keeps
# quantisation to a single vectorised numpy op -- no median cut, no octree --
# and 216 colours is plenty once the image is this small.
_CUBE_STEPS = 6
_SIXEL_PALETTE_SIZE = _CUBE_STEPS**3


@register
class SixelRenderer(ImageRenderer):
    """DEC sixel graphics. The most widely supported, and the most verbose."""

    name = "sixel"

    def encode_image(self, rgb: np.ndarray, cols: int, rows: int) -> str:
        height, width = rgb.shape[:2]
        # Quantise to the colour cube. Rounding rather than truncating avoids a
        # systematic darkening of the whole picture.
        levels = np.clip(
            np.rint(rgb.astype(np.float32) / 255.0 * (_CUBE_STEPS - 1)), 0, _CUBE_STEPS - 1
        ).astype(np.int32)
        index = (
            levels[..., 0] * _CUBE_STEPS**2 + levels[..., 1] * _CUBE_STEPS + levels[..., 2]
        )

        out: list[str] = ["\x1b[H", "\x1bPq"]
        out.append(f'"1;1;{width};{height}')
        out.extend(_palette_definitions(index))

        # Pad to a whole number of 6-row bands.
        pad = -height % 6
        if pad:
            index = np.vstack([index, np.zeros((pad, width), np.int32)])
        bands = index.reshape(-1, 6, width)

        weights = (1 << np.arange(6)).astype(np.int32)[:, None]
        for band_no, band in enumerate(bands):
            if band_no:
                out.append("-")  # next band
            for run, colour in enumerate(np.unique(band)):
                if run:
                    out.append("$")  # carriage return, overprint same band
                out.append(f"#{int(colour)}")
                # bit k of the sixel byte is row k of this band
                bits = ((band == colour) * weights).sum(axis=0)
                out.append(_run_length_encode(bits))
        out.append("\x1b\\")
        return "".join(out)


def _palette_definitions(index: np.ndarray) -> list[str]:
    """Emit `#n;2;r;g;b` for every colour actually used, in 0-100 units."""
    defs = []
    for colour in np.unique(index):
        c = int(colour)
        r = (c // _CUBE_STEPS**2) % _CUBE_STEPS
        g = (c // _CUBE_STEPS) % _CUBE_STEPS
        b = c % _CUBE_STEPS
        scale = 100 // (_CUBE_STEPS - 1)
        defs.append(f"#{c};2;{r * scale};{g * scale};{b * scale}")
    return defs


def _run_length_encode(bits: np.ndarray) -> str:
    """Sixel run-length: `!<count><char>` beats repeating a char 4+ times.

    Vectorised deliberately. The obvious version walks one Python step per
    *pixel*, which at 384 pixels x ~100 colours x 37 bands is ~1.4M iterations
    and measured 42ms a frame -- more than the entire 30fps budget. Finding run
    boundaries with diff() makes the loop proportional to the number of runs
    instead, and flat colour (letterbox bars especially) collapses to almost
    nothing.
    """
    if bits.size == 0:
        return ""
    boundaries = np.flatnonzero(np.diff(bits)) + 1
    starts = np.concatenate(([0], boundaries))
    lengths = np.diff(np.concatenate((starts, [bits.size])))

    out: list[str] = []
    for value, count in zip(bits[starts].tolist(), lengths.tolist(), strict=True):
        char = _SIXEL_CHARS[value]
        # `!4?` is 3 bytes against 4 literal; below that the escape costs more.
        out.append(f"!{count}{char}" if count > 3 else char * count)
    return "".join(out)
