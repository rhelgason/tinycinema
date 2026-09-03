"""Subtitles: SubRip (.srt) and WebVTT (.vtt).

Cheap to support and genuinely useful, which is a rare combination. Both
formats are the same shape -- a start time, an end time, and some text -- so one
parser handles them with a couple of conditionals.

Where cues come from, in order of preference:

  1. an explicit --subs FILE
  2. a sidecar next to the media (clip.srt, clip.en.vtt, ...)
  3. a subtitle stream inside the container, extracted with ffmpeg

Rendering is deliberately plain: centred, word-wrapped, on a dim band across the
bottom of the picture. Terminal cells are large, so anything fancier eats the
video.
"""

from __future__ import annotations

import bisect
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .binaries import ffmpeg_path
from .log import note

#: Sidecar extensions, and the language-tagged variants people actually have.
SUBTITLE_SUFFIXES = (".srt", ".vtt")

# 00:01:02,500  (SubRip) or 00:01:02.500 (WebVTT). Hours are optional in VTT.
_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE_RE = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")

# Formatting we can't honour in a terminal cell grid.
_TAG_RE = re.compile(r"<[^>]+>")           # <i>, <b>, <font ...>
_ASS_RE = re.compile(r"\{\\[^}]*\}")        # {\an8} positioning
_VTT_CLASS_RE = re.compile(r"</?[cv][^>]*>")  # WebVTT <c.classname>, <v Name>


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _seconds(hours, minutes, secs, frac) -> float:
    # WebVTT allows 2-digit fractions; pad so ".5" means 500ms, not 5ms.
    millis = int((frac or "0").ljust(3, "0")[:3])
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + millis / 1000.0


def clean_text(text: str) -> str:
    text = _ASS_RE.sub("", text)
    text = _VTT_CLASS_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return text.replace("​", "").strip()


def parse(content: str) -> list[Cue]:
    """Parse SubRip or WebVTT. Malformed blocks are skipped, not fatal.

    Subtitle files in the wild are frequently a bit broken -- stray blank lines,
    a truncated final cue, mixed line endings. Dropping one bad cue beats
    refusing to show any.
    """
    content = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []

    for block in re.split(r"\n{2,}", content):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        # Find the timing line; anything before it is an index or a cue id.
        timing_at = next((i for i, ln in enumerate(lines) if _CUE_RE.search(ln)), None)
        if timing_at is None:
            continue
        m = _CUE_RE.search(lines[timing_at])
        start = _seconds(*m.group(1, 2, 3, 4))
        end = _seconds(*m.group(5, 6, 7, 8))
        text = clean_text("\n".join(lines[timing_at + 1 :]))
        if text and end > start:
            cues.append(Cue(start, end, text))

    cues.sort(key=lambda c: c.start)
    return cues


class SubtitleTrack:
    """Cues plus a fast "what is on screen at time t" lookup."""

    def __init__(self, cues: list[Cue], source: str = "") -> None:
        self.cues = cues
        self.source = source
        self._starts = [c.start for c in cues]

    def __len__(self) -> int:
        return len(self.cues)

    def active_at(self, when: float) -> str:
        """Text to show at `when`, or "" for none.

        Binary search rather than a scan: this runs once per rendered frame, and
        a feature-length file has thousands of cues.
        """
        if not self.cues:
            return ""
        index = bisect.bisect_right(self._starts, when) - 1
        # Overlapping cues are legal, so look back a little for a longer one
        # that is still on screen.
        for i in range(index, max(index - 4, -1), -1):
            if i < 0:
                break
            cue = self.cues[i]
            if cue.start <= when < cue.end:
                return cue.text
        return ""


def load(path: str | Path) -> SubtitleTrack:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    return SubtitleTrack(parse(raw), source=str(path))


def find_sidecar(media: str | Path) -> Path | None:
    """Look for clip.srt, clip.en.srt, clip.vtt ... beside clip.mp4."""
    media = Path(media)
    if not media.parent.is_dir():
        return None
    stem = media.stem
    candidates: list[Path] = []
    for suffix in SUBTITLE_SUFFIXES:
        exact = media.with_suffix(suffix)
        if exact.is_file():
            candidates.append(exact)
    # Language-tagged siblings: clip.en.srt, clip.forced.srt
    for sibling in sorted(media.parent.glob(f"{glob_escape(stem)}.*")):
        if sibling.suffix.lower() in SUBTITLE_SUFFIXES and sibling not in candidates:
            candidates.append(sibling)
    return candidates[0] if candidates else None


def glob_escape(text: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", text)


def extract_embedded(media: str, index: int = 0) -> SubtitleTrack | None:
    """Pull a subtitle stream out of the container with ffmpeg.

    Returns None whenever there isn't one, which is the common case -- a missing
    subtitle track is not an error worth reporting.
    """
    exe = ffmpeg_path()
    if not exe:
        return None
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", media, "-map", f"0:s:{index}", "-f", "srt", "-",
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    track = SubtitleTrack(
        parse(out.stdout.decode("utf-8", "replace")), source=f"{media} (embedded)"
    )
    return track or None


def discover(media: str | None, explicit: str | None = None) -> SubtitleTrack | None:
    """Find subtitles for this media, cheapest source first."""
    if explicit:
        track = load(explicit)
        note(f"subtitles: {len(track)} cues from {explicit}")
        return track
    if not media:
        return None

    sidecar = find_sidecar(media)
    if sidecar is not None:
        track = load(sidecar)
        if track.cues:
            note(f"subtitles: {len(track)} cues from {sidecar}")
            return track

    embedded = extract_embedded(media)
    if embedded is not None and embedded.cues:
        note(f"subtitles: {len(embedded)} cues embedded in the container")
        return embedded
    return None


def wrap(text: str, width: int, max_lines: int = 3) -> list[str]:
    """Word-wrap a cue to the grid, keeping its own line breaks.

    Trailing lines are dropped rather than scrolled: subtitles that cover half
    the picture are worse than subtitles that are slightly clipped.
    """
    if width < 1:
        return []
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            continue
        current = words[0][:width]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= width:
                current = f"{current} {word}"
            else:
                lines.append(current)
                current = word[:width]
        lines.append(current)
    return lines[:max_lines]
