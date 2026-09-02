"""Anything -> a stream of RGB frames."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .base import Frame, FrameSource, MediaInfo, fit_box
from .demo import PATTERNS, DemoSource
from .ffmpeg import (
    DecodeError,
    FFmpegMissingError,
    FFmpegSource,
    ffmpeg_path,
    ffprobe_path,
    probe,
    require_ffmpeg,
)

__all__ = [
    "PATTERNS",
    "DecodeError",
    "DemoSource",
    "FFmpegMissingError",
    "FFmpegSource",
    "Frame",
    "FrameSource",
    "MediaInfo",
    "UnsupportedSourceError",
    "ffmpeg_path",
    "ffprobe_path",
    "fit_box",
    "open_source",
    "probe",
    "require_ffmpeg",
]

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

# Sites that need yt-dlp to resolve into a playable stream. ffmpeg cannot open
# these directly -- the page is HTML, not media.
_NEEDS_EXTRACTOR = re.compile(
    r"(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|twitter\.com|x\.com|tiktok\.com"
    r"|reddit\.com|instagram\.com|dailymotion\.com|soundcloud\.com)",
    re.IGNORECASE,
)


class UnsupportedSourceError(RuntimeError):
    pass


def open_source(
    spec: str | None,
    *,
    demo: str | None = None,
    fps: float | None = None,
    loop: bool = False,
) -> FrameSource:
    """Resolve a CLI argument into a FrameSource."""
    if demo:
        return DemoSource(pattern=demo, fps=fps or 30.0)

    if not spec:
        raise UnsupportedSourceError("no source given (pass a file, a URL, or --demo)")

    if spec == "-":
        return FFmpegSource("-", fps=fps, loop=False)

    if _URL_RE.match(spec):
        if _NEEDS_EXTRACTOR.search(spec):
            # Phase 3. Say so plainly rather than handing the user an ffmpeg
            # "Invalid data found when processing input" from an HTML page.
            raise UnsupportedSourceError(
                f"{spec}\n"
                "Extractor-backed sites (YouTube and friends) need yt-dlp, which is\n"
                "Phase 3 and not wired up yet. Direct media URLs already work today."
            )
        return FFmpegSource(spec, fps=fps, loop=loop)

    path = Path(os.path.expanduser(spec))
    if not path.exists():
        raise UnsupportedSourceError(f"no such file: {path}")
    if path.is_dir():
        raise UnsupportedSourceError(f"{path} is a directory (playlists are Phase 5)")
    return FFmpegSource(str(path), fps=fps, loop=loop)
