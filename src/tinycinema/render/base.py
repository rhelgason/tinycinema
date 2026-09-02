"""The Renderer interface and its registry.

A renderer answers two questions:

  pixel_size(cols, rows) -> how many real pixels it wants for that cell grid
  render(rgb)            -> a CellGrid of exactly (rows, cols)

The decoder scales frames to whatever pixel_size() asks for, so renderers never
resample. That keeps all the expensive resampling inside ffmpeg's SIMD paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

import numpy as np

from ..term import CellGrid
from .ramps import DEFAULT_RAMP


@dataclass
class RenderOptions:
    ramp: str = DEFAULT_RAMP
    color: bool = True
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    threshold: float = 0.5  # braille / binary modes
    dither: str = "none"  # none | ordered


@dataclass
class Renderer:
    """Base class. Subclasses implement pixel_size() and render()."""

    # ClassVar, not a dataclass field: subclasses override these on the class and
    # must not have them clobbered by the generated __init__.
    name: ClassVar[str] = "base"

    #: pixels per cell, (horizontal, vertical)
    px_per_cell: ClassVar[tuple[int, int]] = (1, 1)

    opts: RenderOptions = field(default_factory=RenderOptions)

    #: Terminal cells are about twice as tall as they are wide. A renderer whose
    #: vertical subdivision already compensates (halfblock, braille) has square
    #: effective pixels and needs no correction; one that does not must squash
    #: the source vertically or everything looks stretched.
    @property
    def pixel_aspect(self) -> float:
        """Width / height of one effective pixel, in real display units."""
        w, h = self.px_per_cell
        return (1.0 / w) / (2.0 / h)

    def pixel_size(self, cols: int, rows: int) -> tuple[int, int]:
        w, h = self.px_per_cell
        return cols * w, rows * h

    def render(self, rgb: np.ndarray) -> CellGrid:  # pragma: no cover - abstract
        raise NotImplementedError


_REGISTRY: dict[str, type[Renderer]] = {}


def register(cls: type[Renderer]) -> type[Renderer]:
    _REGISTRY[cls.name] = cls
    return cls


def available_modes() -> list[str]:
    return list(_REGISTRY)


def create(mode: str, opts: RenderOptions | None = None) -> Renderer:
    try:
        cls = _REGISTRY[mode]
    except KeyError:
        raise ValueError(
            f"unknown render mode {mode!r}; choose from {', '.join(available_modes())}"
        ) from None
    return cls(opts=opts or RenderOptions())


# 4x4 Bayer matrix. Ordered dithering is cheap, deterministic, and -- unlike
# error diffusion, where each pixel depends on its neighbour -- it vectorises.
#
# The +0.5 before centring matters: without it the offsets span [-0.5, +0.4375]
# and pure white lands exactly on a 0.5 threshold, so the brightest pixel in the
# frame silently drops out. Centring on the bin makes the range symmetric, so
# full black and full white both survive at strength 1.0.
BAYER4 = (
    np.array(
        [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5],
        ],
        dtype=np.float32,
    )
    + 0.5
) / 16.0 - 0.5


def apply_ordered_dither(lum01: np.ndarray, strength: float = 1.0) -> np.ndarray:
    h, w = lum01.shape
    tile = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    return np.clip(lum01 + tile * strength, 0.0, 1.0)
