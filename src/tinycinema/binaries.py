"""Locating the ffmpeg family of binaries.

Shared because both halves of the pipeline need them: sources/ wants ffmpeg and
ffprobe, audio/ wants ffplay. Each is overridable by environment variable --
people build their own ffmpeg all the time, and it is also how the test suite
points at a sandboxed static build.
"""

from __future__ import annotations

import os
import shutil


class FFmpegMissingError(RuntimeError):
    pass


def _resolve(name: str, env_var: str) -> str | None:
    override = os.environ.get(env_var)
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        return shutil.which(override)
    return shutil.which(name)


def ffmpeg_path() -> str | None:
    return _resolve("ffmpeg", "TINYCINEMA_FFMPEG")


def ffprobe_path() -> str | None:
    return _resolve("ffprobe", "TINYCINEMA_FFPROBE")


def ffplay_path() -> str | None:
    return _resolve("ffplay", "TINYCINEMA_FFPLAY")


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if not path:
        raise FFmpegMissingError(
            "ffmpeg not found on PATH.\n"
            "  macOS:  brew install ffmpeg\n"
            "  Debian: sudo apt install ffmpeg\n"
            "Run `tinycinema --doctor` for a full check."
        )
    return path
