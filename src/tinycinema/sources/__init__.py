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
    NoVideoStreamError,
    ffmpeg_path,
    ffprobe_path,
    probe,
    probe_via_ffmpeg,
    require_ffmpeg,
)
from .ytdlp import (
    DEFAULT_QUALITY,
    ResolveError,
    YtDlpMissingError,
    is_extractor_url,
    parse_quality,
)
from .ytdlp import resolve as resolve_url

__all__ = [
    "DEFAULT_QUALITY",
    "PATTERNS",
    "DecodeError",
    "DemoSource",
    "FFmpegMissingError",
    "FFmpegSource",
    "Frame",
    "FrameSource",
    "MediaInfo",
    "NoVideoStreamError",
    "ResolveError",
    "UnsupportedSourceError",
    "YtDlpMissingError",
    "ffmpeg_path",
    "ffprobe_path",
    "fit_box",
    "is_extractor_url",
    "open_source",
    "parse_quality",
    "probe",
    "probe_via_ffmpeg",
    "require_ffmpeg",
    "resolve_url",
]

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


class UnsupportedSourceError(RuntimeError):
    pass


def open_source(
    spec: str | None,
    *,
    demo: str | None = None,
    fps: float | None = None,
    loop: bool = False,
    quality: int = DEFAULT_QUALITY,
    use_cache: bool = True,
    quiet: bool = False,
) -> FrameSource:
    """Resolve a CLI argument into a FrameSource."""
    if demo:
        return DemoSource(pattern=demo, fps=fps or 30.0)

    if not spec:
        raise UnsupportedSourceError("no source given (pass a file, a URL, or --demo)")

    if spec == "-":
        return FFmpegSource("-", fps=fps, loop=False)

    if _URL_RE.match(spec):
        if is_extractor_url(spec):
            resolved = resolve_url(
                spec, quality=quality, use_cache=use_cache, quiet=quiet
            )
            source = FFmpegSource(resolved.target, fps=fps, loop=loop)
            # Trust the extractor's metadata over a probe of the media itself:
            # it knows the real title, and for a streamed URL a probe would
            # cost another round trip.
            source.info.title = resolved.info.title
            if resolved.info.duration:
                source.info.duration = resolved.info.duration
            source.info.has_audio = resolved.info.has_audio or source.info.has_audio
            return source
        return FFmpegSource(spec, fps=fps, loop=loop)

    path = Path(os.path.expanduser(spec))
    if not path.exists():
        raise UnsupportedSourceError(f"no such file: {path}")
    if path.is_dir():
        # The CLI flattens directories via playlist.expand() before we get
        # here, so this only fires for a direct API call.
        raise UnsupportedSourceError(
            f"{path} is a directory; expand it with playlist.expand() first"
        )
    return FFmpegSource(str(path), fps=fps, loop=loop)
