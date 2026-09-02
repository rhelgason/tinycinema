"""Generated test patterns -- `tinycinema --demo`.

Zero dependencies, zero media files: someone can try the tool the moment they
install it. Also the perfect fixture for renderer tests and throughput profiling,
since it produces deterministic frames at any size on demand.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import numpy as np

from .base import Frame, FrameSource, MediaInfo

PATTERNS = ("ball", "plasma", "bars", "mandelbrot")


class DemoSource(FrameSource):
    def __init__(self, pattern: str = "ball", fps: float = 30.0, duration: float | None = None):
        if pattern not in PATTERNS:
            raise ValueError(f"unknown demo pattern {pattern!r}; choose from {', '.join(PATTERNS)}")
        self.pattern = pattern
        self.info = MediaInfo(
            title=f"demo:{pattern}",
            fps=fps,
            duration=duration,
            has_audio=False,
            seekable=True,
        )

    def open(
        self,
        width: int,
        height: int,
        *,
        start: float = 0.0,
        pixel_aspect: float = 1.0,
    ) -> Iterator[Frame]:
        fps = self.info.fps
        duration = self.info.duration
        draw = {
            "ball": _ball,
            "plasma": _plasma,
            "bars": _bars,
            "mandelbrot": _mandelbrot,
        }[self.pattern]
        grid = _Grid(width, height, pixel_aspect)

        n = int(start * fps)
        while True:
            t = n / fps
            if duration is not None and t >= duration:
                return
            yield t, draw(grid, t)
            n += 1


class _Grid:
    """Cached coordinate meshes -- rebuilding these per frame dominates the cost."""

    def __init__(self, w: int, h: int, pixel_aspect: float = 1.0) -> None:
        self.w, self.h = w, h
        #: width/height of one pixel on screen; the ball needs it to look round
        self.pa = pixel_aspect
        self.xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
        self.ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        self.px = np.arange(w, dtype=np.float32)[None, :]
        self.py = np.arange(h, dtype=np.float32)[:, None]


def _plasma(g: _Grid, t: float) -> np.ndarray:
    x, y = g.xs * 6.0, g.ys * 6.0
    v = (
        np.sin(x + t)
        + np.sin(y * 1.3 + t * 0.7)
        + np.sin((x + y) * 0.8 + t * 1.3)
        + np.sin(np.sqrt(x * x + y * y) * 1.5 - t * 2.0)
    )
    v = v / 4.0
    r = 0.5 + 0.5 * np.sin(math.pi * v)
    gr = 0.5 + 0.5 * np.sin(math.pi * v + 2.094)
    b = 0.5 + 0.5 * np.sin(math.pi * v + 4.188)
    return (np.stack(np.broadcast_arrays(r, gr, b), axis=-1) * 255).astype(np.uint8)


def _bars(g: _Grid, t: float) -> np.ndarray:
    """SMPTE-ish colour bars with a sweeping highlight -- a colour-accuracy check."""
    colors = np.array(
        [
            [192, 192, 192],
            [192, 192, 0],
            [0, 192, 192],
            [0, 192, 0],
            [192, 0, 192],
            [192, 0, 0],
            [0, 0, 192],
        ],
        dtype=np.float32,
    )
    idx = np.clip((g.px[0] / g.w * len(colors)).astype(int), 0, len(colors) - 1)
    frame = np.broadcast_to(colors[idx][None, :, :], (g.h, g.w, 3)).astype(np.float32).copy()

    # bottom fifth: a linear greyscale ramp, for checking ramp monotonicity
    split = int(g.h * 0.8)
    ramp = np.broadcast_to((g.px[0] / max(g.w - 1, 1) * 255.0)[:, None], (g.w, 3))
    frame[split:] = ramp[None, :, :]

    # sweeping highlight so there is motion to sync against
    sweep = (t * 0.4) % 1.0
    band = np.exp(-(((g.xs - sweep) * 12.0) ** 2))
    frame = np.clip(frame + band[..., None] * 60.0, 0, 255)
    return frame.astype(np.uint8)


def _mandelbrot(g: _Grid, t: float) -> np.ndarray:
    """A slow zoom into the Mandelbrot set.

    Unlike the smooth patterns, this has hard edges and fine detail at every
    scale, which is what actually exercises a renderer -- it is the difference
    between "a gradient" and "you can see what it is" in braille and ascii.
    """
    # Start on the whole set -- instantly recognisable -- then drift in towards a
    # classic Misiurewicz point, where the detail stays interesting all the way.
    zoom = 0.90 ** (t * 2.0)
    span = 3.2 * zoom
    blend = 1.0 - zoom
    cx = -0.6 + (-0.743643887037151 + 0.6) * blend
    cy = 0.0 + 0.13182590420533 * blend

    x = cx + (g.xs - 0.5) * span
    # keep the plane square on screen, accounting for non-square pixels
    y = cy + (g.ys - 0.5) * span * (g.h / max(g.w * g.pa, 1e-6))

    zx = np.zeros_like(x + y)
    zy = np.zeros_like(zx)
    count = np.zeros_like(zx)
    iterations = 90
    for _ in range(iterations):
        inside = (zx * zx + zy * zy) <= 4.0
        if not inside.any():
            break
        zx_new = np.where(inside, zx * zx - zy * zy + x, zx)
        zy_new = np.where(inside, 2.0 * zx * zy + y, zy)
        zx, zy = zx_new, zy_new
        count += inside

    escaped = count < iterations
    v = np.sqrt(count / iterations)  # sqrt spreads the bands out near the edge
    # The classic blue -> white -> amber ramp. Gentler than raw sinusoids, and
    # the wide luminance range is what makes it read in the monochrome modes.
    r = 9.0 * (1 - v) * v**3
    gr = 15.0 * (1 - v) ** 2 * v**2
    b = 8.5 * (1 - v) ** 3 * v
    rgb = np.stack(np.broadcast_arrays(r, gr, b), axis=-1)
    rgb = np.where(escaped[..., None], rgb, 0.0)  # the set itself stays black
    return (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)


def _ball(g: _Grid, t: float) -> np.ndarray:
    """A bouncing ball over a slow gradient. The Phase 0 hello-world."""
    # background: slowly rotating gradient
    hue = (g.xs * 0.5 + g.ys * 0.3 + t * 0.05) % 1.0
    bg = np.stack(
        np.broadcast_arrays(
            0.10 + 0.10 * np.sin(hue * 6.283),
            0.12 + 0.10 * np.sin(hue * 6.283 + 2.094),
            0.20 + 0.15 * np.sin(hue * 6.283 + 4.188),
        ),
        axis=-1,
    )

    # Radius in display units. Horizontally that is more pixels when pixels are
    # narrow, which is what keeps the ball round rather than egg-shaped.
    radius = max(3.0, min(g.w * g.pa, g.h) * 0.12)
    rx, ry = radius / g.pa, radius

    # triangle wave bounce, so it reverses cleanly at the walls
    def bounce(period: float, span: float, r: float) -> float:
        u = (t / period) % 2.0
        u = u if u < 1.0 else 2.0 - u
        return r + u * max(span - 2 * r, 1.0)

    cx = bounce(3.1, g.w, rx)
    cy = bounce(2.3, g.h, ry)

    # measure distance in display units, not pixel units
    d = np.sqrt(((g.px - cx) * g.pa) ** 2 + (g.py - cy) ** 2)
    edge = np.clip((radius - d) / max(radius * 0.35, 1.0), 0.0, 1.0)[..., None]

    ball = np.array(
        [
            0.55 + 0.45 * math.sin(t * 1.7),
            0.55 + 0.45 * math.sin(t * 1.7 + 2.094),
            0.55 + 0.45 * math.sin(t * 1.7 + 4.188),
        ],
        dtype=np.float32,
    )
    # a little shading so it reads as a sphere rather than a disc
    shade = np.clip(1.0 - d / (radius * 2.2), 0.35, 1.0)[..., None]

    out = bg * (1.0 - edge) + ball * shade * edge
    return (np.clip(out, 0.0, 1.0) * 255).astype(np.uint8)
