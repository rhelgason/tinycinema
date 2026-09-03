"""Decoding via an ffmpeg subprocess piping raw rgb24.

Why a subprocess rather than PyAV bindings: it is one hard dependency people
already have, it handles every container and codec, and its scaler is SIMD-fast.
We ask ffmpeg to deliver frames at exactly the pixel size the renderer wants,
letterboxed, at a constant frame rate -- so this module hands the player a
trivially indexable stream and no resampling happens in Python.

Two subprocess hazards worth naming, because both are silent hangs:
  * a full stderr pipe deadlocks the child, so stderr is drained on a thread
  * a killed parent can orphan ffmpeg, so close() always terminates and reaps
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from ..binaries import (
    FFmpegMissingError,
    ffmpeg_path,
    ffprobe_path,
    require_ffmpeg,
)
from .base import Frame, FrameSource, MediaInfo, fit_box


class DecodeError(RuntimeError):
    pass


def _parse_rate(value: str | None) -> float | None:
    """ffprobe reports frame rates as fractions like '30000/1001'."""
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(value)
    except ValueError:
        return None


def probe(target: str) -> MediaInfo:
    """Ask ffprobe about a file or URL. Degrades to defaults if it cannot."""
    info = MediaInfo(title=Path(target).name or target)
    probe_bin = ffprobe_path()
    if not probe_bin or target == "-":
        info.seekable = target != "-"
        return info

    cmd = [
        probe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        target,
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return info
    if out.returncode != 0:
        return info

    try:
        data = json.loads(out.stdout or b"{}")
    except json.JSONDecodeError:
        return info

    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    info.has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if video:
        info.width = video.get("width")
        info.height = video.get("height")
        fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
        if fps and 0 < fps <= 1000:
            info.fps = fps

    duration = fmt.get("duration") or (video or {}).get("duration")
    try:
        if duration is not None:
            info.duration = float(duration)
    except (TypeError, ValueError):
        pass

    tags = fmt.get("tags") or {}
    info.title = tags.get("title") or info.title
    return info


class FFmpegSource(FrameSource):
    """A local file, a direct media URL, or stdin ('-')."""

    def __init__(self, target: str, *, fps: float | None = None, loop: bool = False):
        require_ffmpeg()
        self.target = target
        self.loop = loop
        self.info = probe(target)
        if fps:
            self.info.fps = fps
        self._proc: subprocess.Popen | None = None
        self._stderr_tail: deque[str] = deque(maxlen=25)
        self._stderr_thread: threading.Thread | None = None

    # -- filter graph ------------------------------------------------------

    def _filters(self, width: int, height: int, pixel_aspect: float) -> str:
        """Letterbox into the box, correcting for non-square terminal pixels.

        force_original_aspect_ratio=decrease would be the obvious tool, but it
        assumes square pixels -- in ascii mode that leaves the picture squeezed
        into half the width and stretched to twice the height. So we do the fit
        arithmetic in the filtergraph instead, using ffmpeg's `dar` variable, and
        divide through by the pixel aspect. Doing it in-graph rather than in
        Python means it still works when ffprobe is unavailable and we don't know
        the source dimensions.
        """
        pa = max(pixel_aspect, 1e-6)
        w_expr = f"trunc(max(2,min({width},{height}*dar/{pa:.6f})))"
        h_expr = f"trunc(max(2,min({height},{width}*{pa:.6f}/dar)))"
        return (
            f"scale=w='{w_expr}':h='{h_expr}':flags=bilinear,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={self.info.fps:.6f}"
        )

    def _command(self, width: int, height: int, start: float, pixel_aspect: float) -> list[str]:
        exe = require_ffmpeg()
        cmd = [exe, "-hide_banner", "-loglevel", "error"]
        if self.target != "-":
            # Keep ffmpeg's hands off the terminal; we need those keystrokes.
            cmd.append("-nostdin")
        if self.loop and self.target != "-":
            cmd += ["-stream_loop", "-1"]
        if start > 0 and self.info.seekable and self.target != "-":
            # -ss before -i is the fast (keyframe-accurate) seek.
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", "pipe:0" if self.target == "-" else self.target]
        cmd += [
            "-an",
            "-sn",
            "-vf", self._filters(width, height, pixel_aspect),
            "-pix_fmt", "rgb24",
            "-f", "rawvideo",
            "pipe:1",
        ]  # fmt: skip
        return cmd

    # -- streaming ---------------------------------------------------------

    def open(
        self,
        width: int,
        height: int,
        *,
        start: float = 0.0,
        pixel_aspect: float = 1.0,
    ) -> Iterator[Frame]:
        self.close()
        cmd = self._command(width, height, start, pixel_aspect)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Inherit stdin only when we're actually reading media from it.
                stdin=None if self.target == "-" else subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError as exc:
            raise DecodeError(f"could not start ffmpeg: {exc}") from exc

        self._drain_stderr()
        return self._iter_frames(width, height, start)

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return

        def pump(pipe, tail):
            try:
                for line in iter(pipe.readline, b""):
                    text = line.decode("utf-8", "replace").rstrip()
                    if text:
                        tail.append(text)
            except (ValueError, OSError):
                pass

        self._stderr_thread = threading.Thread(
            target=pump, args=(proc.stderr, self._stderr_tail), daemon=True
        )
        self._stderr_thread.start()

    def _iter_frames(self, width: int, height: int, start: float) -> Iterator[Frame]:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        stdout = proc.stdout
        frame_bytes = width * height * 3
        step = 1.0 / self.info.fps
        n = 0
        while True:
            buf = _read_exactly(stdout, frame_bytes)
            if buf is None:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            yield start + n * step, frame
            n += 1

        # Zero frames from the start of a stream means ffmpeg failed. Zero frames
        # after a seek just means the seek landed past the end -- that is an EOF,
        # not an error, and matters because without ffprobe we don't know the
        # duration and so can't clamp the seek target.
        # (Deliberately outside a finally: an early generator close is not an error.)
        if n == 0 and start <= 0:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=0.5)  # let the message land first
            rc = proc.returncode
            raise DecodeError(
                self.error_message() or f"ffmpeg produced no frames (exit code {rc})"
            )

    def error_message(self) -> str:
        return "\n".join(self._stderr_tail)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except (OSError, ValueError):
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        self._stderr_thread = None


def _read_exactly(stream, n: int) -> bytes | None:
    """Pipes hand back short reads constantly; loop until we have a whole frame."""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        try:
            chunk = stream.read(remaining)
        except (OSError, ValueError):
            return None
        if not chunk:
            return None  # clean EOF, or a partial trailing frame we discard
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks) if len(chunks) > 1 else chunks[0]


__all__ = [
    "DecodeError",
    "FFmpegMissingError",
    "FFmpegSource",
    "ffmpeg_path",
    "ffprobe_path",
    "fit_box",
    "probe",
    "require_ffmpeg",
]
