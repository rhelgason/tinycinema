"""The render modes themselves.

Every mode is the same three steps -- luma, tone-map, map to glyphs+colours --
differing only in how many pixels it packs into one terminal cell.
"""

from __future__ import annotations

import numpy as np

from ..term import DEFAULT, CellGrid
from .base import Renderer, RenderOptions, apply_ordered_dither, register
from .ramps import adjust, luminance, map_to_ramp, ramp_table

_DEFAULT_RGB = np.array([DEFAULT, DEFAULT, DEFAULT], dtype=np.int16)


def _default_plane(rows: int, cols: int) -> np.ndarray:
    return np.broadcast_to(_DEFAULT_RGB, (rows, cols, 3)).copy()


def _tone(rgb: np.ndarray, opts: RenderOptions) -> np.ndarray:
    lum = adjust(
        luminance(rgb),
        brightness=opts.brightness,
        contrast=opts.contrast,
        gamma=opts.gamma,
    )
    if opts.dither == "ordered":
        lum = apply_ordered_dither(lum)
    return lum


@register
class AsciiRenderer(Renderer):
    """One character per cell, luminance ramp, no colour. The classic."""

    name = "ascii"
    px_per_cell = (1, 1)
    _color = False

    def render(self, rgb: np.ndarray) -> CellGrid:
        rows, cols = rgb.shape[:2]
        lum = _tone(rgb, self.opts)
        chars = map_to_ramp(lum, ramp_table(self.opts.ramp))

        if self._color and self.opts.color:
            fg = rgb.astype(np.int16)
        else:
            fg = _default_plane(rows, cols)
        return CellGrid(chars=chars, fg=fg, bg=_default_plane(rows, cols))


@register
class AsciiColorRenderer(AsciiRenderer):
    """Ramp character for detail, true colour for the pixel. Reads better than either alone."""

    name = "ascii-color"
    _color = True


@register
class BlocksRenderer(Renderer):
    """A solid coloured cell. Flat and chunky, but colour-accurate."""

    name = "blocks"
    px_per_cell = (1, 1)

    def render(self, rgb: np.ndarray) -> CellGrid:
        rows, cols = rgb.shape[:2]
        chars = np.full((rows, cols), ord(" "), dtype=np.uint32)
        if self.opts.color:
            bg = rgb.astype(np.int16)
        else:
            # No colour to work with, so fall back to shaded block glyphs.
            lum = _tone(rgb, self.opts)
            chars = map_to_ramp(lum, ramp_table("blocks"))
            bg = _default_plane(rows, cols)
        return CellGrid(chars=chars, fg=_default_plane(rows, cols), bg=bg)


@register
class HalfBlockRenderer(Renderer):
    """The default. U+2580 UPPER HALF BLOCK with fg=top pixel, bg=bottom pixel.

    Two independently coloured pixels per cell: 2x the vertical resolution for
    free, and because cells are roughly 2:1 tall:wide the effective pixels come
    out square -- no aspect correction needed anywhere else in the pipeline.
    """

    name = "halfblock"
    px_per_cell = (1, 2)

    def render(self, rgb: np.ndarray) -> CellGrid:
        h, cols = rgb.shape[:2]
        if h % 2:  # odd height: pad a black row so the split is clean
            rgb = np.vstack([rgb, np.zeros((1, cols, 3), dtype=rgb.dtype)])
        top = rgb[0::2]
        bottom = rgb[1::2]
        rows = top.shape[0]

        if not self.opts.color:
            # Degrade to a ramp rather than emitting a wall of identical blocks.
            lum = _tone(np.maximum(top, bottom), self.opts)
            return CellGrid(
                chars=map_to_ramp(lum, ramp_table(self.opts.ramp)),
                fg=_default_plane(rows, cols),
                bg=_default_plane(rows, cols),
            )

        chars = np.full((rows, cols), 0x2580, dtype=np.uint32)  # ▀
        return CellGrid(chars=chars, fg=top.astype(np.int16), bg=bottom.astype(np.int16))


# Braille dot -> bit mapping for the U+2800 block. Note the bottom row (dots 7
# and 8) was bolted on later, which is why bits 6 and 7 are out of order.
_BRAILLE_BITS = np.array(
    [
        [0x01, 0x08],
        [0x02, 0x10],
        [0x04, 0x20],
        [0x40, 0x80],
    ],
    dtype=np.uint32,
)


@register
class BrailleRenderer(Renderer):
    """2x4 dots per cell -- the highest spatial resolution pure text can reach.

    Effectively 1-bit per dot plus a single tint colour per cell, so it trades
    colour fidelity for detail. Superb on high-contrast and line-art content.
    """

    name = "braille"
    px_per_cell = (2, 4)

    def render(self, rgb: np.ndarray) -> CellGrid:
        h, w = rgb.shape[:2]
        ph, pw = -h % 4, -w % 2
        if ph or pw:
            rgb = np.pad(rgb, ((0, ph), (0, pw), (0, 0)))
            h, w = rgb.shape[:2]
        rows, cols = h // 4, w // 2

        lum = _tone(rgb, self.opts)
        if self.opts.dither == "none":
            # Without dithering a hard threshold blotches badly, so default the
            # braille path to ordered dithering unless told otherwise.
            lum = apply_ordered_dither(lum, strength=0.8)

        on = lum > self.opts.threshold  # (h, w) bool
        cells = on.reshape(rows, 4, cols, 2).transpose(0, 2, 1, 3)  # (rows, cols, 4, 2)
        bits = (cells * _BRAILLE_BITS).sum(axis=(2, 3), dtype=np.uint32)
        chars = (0x2800 + bits).astype(np.uint32)

        if not self.opts.color:
            return CellGrid(
                chars=chars, fg=_default_plane(rows, cols), bg=_default_plane(rows, cols)
            )

        # Tint each cell with the mean colour of its lit dots (falling back to the
        # cell mean when nothing is lit, so dark areas keep their hue).
        px = rgb.reshape(rows, 4, cols, 2, 3).transpose(0, 2, 1, 3, 4).astype(np.float32)
        mask = cells[..., None].astype(np.float32)
        lit = mask.sum(axis=(2, 3))
        tinted = (px * mask).sum(axis=(2, 3))
        mean = px.mean(axis=(2, 3))
        fg = np.where(lit > 0, tinted / np.maximum(lit, 1.0), mean)
        return CellGrid(
            chars=chars,
            fg=fg.astype(np.int16),
            bg=_default_plane(rows, cols),
        )
