"""Audio playback, and the clock the video chases."""

from __future__ import annotations

from ..sources.base import MediaInfo
from .base import AudioClock, AudioSink, Clock, NullSink, WallClock
from .ffplay import FFplaySink

__all__ = [
    "AudioClock",
    "AudioSink",
    "Clock",
    "FFplaySink",
    "NullSink",
    "WallClock",
    "make_clock",
]

BACKENDS = ("auto", "ffplay", "none")


def make_clock(
    target: str | None,
    info: MediaInfo,
    *,
    enabled: bool = True,
    backend: str = "auto",
    volume: int = 100,
    loop: bool = False,
) -> Clock:
    """Pick the best clock available for this source.

    Falls through to a wall clock whenever audio isn't possible -- no track, no
    ffplay, a generated pattern, or the user said no. The player never has to
    care which it got.
    """
    if not enabled or backend == "none" or not target or target == "-":
        return WallClock()
    if not info.has_audio:
        return WallClock()
    if backend in ("auto", "ffplay") and FFplaySink.available():
        return AudioClock(FFplaySink(target, volume=volume, loop=loop))
    return WallClock()
