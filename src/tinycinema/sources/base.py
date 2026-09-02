"""The source interface: anything -> a stream of RGB frames at a requested size.

Local files, URLs, stdin and generated test patterns are all interchangeable
behind this. Crucially, a source yields frames *already scaled* to the exact
pixel dimensions the renderer asked for -- resampling is ffmpeg's job, never ours.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

#: (presentation timestamp in seconds, HxWx3 uint8 RGB)
Frame = tuple[float, np.ndarray]


@dataclass
class MediaInfo:
    title: str = "unknown"
    width: int | None = None
    height: int | None = None
    fps: float = 30.0
    duration: float | None = None
    has_audio: bool = False
    seekable: bool = True

    @property
    def aspect(self) -> float | None:
        if self.width and self.height:
            return self.width / self.height
        return None


class FrameSource:
    """Base class for frame producers."""

    info: MediaInfo

    def open(
        self,
        width: int,
        height: int,
        *,
        start: float = 0.0,
        pixel_aspect: float = 1.0,
    ) -> Iterator[Frame]:
        """Yield frames scaled to exactly (height, width) pixels, from `start`.

        `pixel_aspect` is the width/height of one *effective* pixel on screen.
        The source must letterbox using it, or the picture comes out stretched:
        in a one-pixel-per-cell mode each pixel is twice as tall as it is wide.
        """
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def fit_box(
    src_w: int, src_h: int, box_w: int, box_h: int, *, pixel_aspect: float = 1.0
) -> tuple[int, int]:
    """Largest (w, h) inside the box preserving aspect, given non-square pixels.

    `pixel_aspect` is the width/height of one *effective* pixel. Modes that pack
    two pixels vertically into a cell have square pixels (1.0); modes that use
    one pixel per cell have pixels twice as tall as they are wide (0.5), so the
    image must be squashed vertically to compensate.
    """
    if src_w <= 0 or src_h <= 0:
        return box_w, box_h
    src_ratio = (src_w / src_h) / pixel_aspect
    box_ratio = box_w / box_h
    if src_ratio > box_ratio:
        w = box_w
        h = max(1, round(box_w / src_ratio))
    else:
        h = box_h
        w = max(1, round(box_h * src_ratio))
    return w, h
