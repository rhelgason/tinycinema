"""Resolving YouTube (and ~1800 other sites) into something ffmpeg can open.

yt-dlp is an optional extra, not a base dependency: it is a large site-scraping
framework and most people playing local files should not have to carry it.

The design question here is that YouTube serves video and audio as *separate*
DASH streams, while tinycinema runs two processes over the same media -- ffmpeg
for pictures and ffplay for sound. Two answers, and we ship both:

  cache  (default)  download and mux once into ~/.cache/tinycinema, then play it
                    exactly like a local file. Seeking and replays are instant,
                    both processes read the same file, and nothing is special.

  stream (--no-cache)
                    pick a *progressive* format -- one URL carrying both streams,
                    e.g. YouTube's format 18 -- and hand that URL to both
                    processes. Starts immediately, costs a second connection and
                    limits you to whatever muxed formats the site offers.

Quality defaults deliberately low. We render to roughly 200x100 pixels, so a
360p source is already far more detail than survives; fetching 1080p would be
slower, heavier and produce identical output.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..log import note
from .base import MediaInfo

#: Sites that serve HTML rather than media, so ffmpeg cannot open them directly.
EXTRACTOR_HOSTS = re.compile(
    r"(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|twitter\.com|x\.com|tiktok\.com"
    r"|reddit\.com|instagram\.com|dailymotion\.com|soundcloud\.com|bilibili\.com"
    r"|nicovideo\.jp|bsky\.app|facebook\.com)",
    re.IGNORECASE,
)

DEFAULT_QUALITY = 480
#: Evict least-recently-used downloads past this. Terminal-grade video is small;
#: a few hundred 480p clips fit comfortably.
DEFAULT_CACHE_LIMIT = 2 * 1024**3


class YtDlpMissingError(RuntimeError):
    pass


class ResolveError(RuntimeError):
    pass


def is_extractor_url(url: str) -> bool:
    return bool(EXTRACTOR_HOSTS.search(url))


def parse_quality(value: str | int | None) -> int:
    """Accept 360, '360', '360p', '720P' -> 360 / 720."""
    if value is None:
        return DEFAULT_QUALITY
    if isinstance(value, int):
        return value
    text = str(value).strip().lower().removesuffix("p")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"bad quality {value!r}; try 360, 480 or 720") from exc


def import_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:
        raise YtDlpMissingError(
            "yt-dlp is needed for this URL but isn't installed.\n"
            "  pip install 'tinycinema[youtube]'\n"
            "  or:  pip install yt-dlp\n"
            "Direct media URLs work without it."
        ) from exc
    return yt_dlp


# ---------------------------------------------------------------------------
# format selection
# ---------------------------------------------------------------------------


def format_selector(quality: int, *, progressive: bool) -> str:
    """A yt-dlp format string.

    `?` on each filter makes it non-strict, so a video with no matching format
    still resolves to something rather than failing outright.
    """
    if progressive:
        # One URL with both streams in it, for the no-cache path.
        return (
            f"best[height<=?{quality}][vcodec!=none][acodec!=none]"
            f"/best[vcodec!=none][acodec!=none]"
            f"/best"
        )
    return f"bestvideo[height<=?{quality}]+bestaudio/best[height<=?{quality}]/best"


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


def cache_dir() -> Path:
    override = os.environ.get("TINYCINEMA_CACHE")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "tinycinema"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]


def prune_cache(directory: Path, limit: int = DEFAULT_CACHE_LIMIT) -> list[Path]:
    """Evict least-recently-used files until the directory fits in `limit`."""
    if not directory.is_dir():
        return []
    files = []
    for path in directory.iterdir():
        if path.is_file() and not path.name.endswith((".part", ".ytdl")):
            with contextlib.suppress(OSError):
                files.append((path.stat().st_atime, path.stat().st_size, path))
    total = sum(size for _, size, _ in files)
    removed: list[Path] = []
    for _atime, size, path in sorted(files):  # oldest access first
        if total <= limit:
            break
        with contextlib.suppress(OSError):
            path.unlink()
            removed.append(path)
            total -= size
    return removed


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


@dataclass
class Resolved:
    #: What to hand to ffmpeg/ffplay: a local path, or a direct media URL.
    target: str
    info: MediaInfo
    cached: bool


def _media_info(entry: dict, *, seekable: bool) -> MediaInfo:
    info = MediaInfo(title=entry.get("title") or "video", seekable=seekable)
    if entry.get("duration"):
        with contextlib.suppress(TypeError, ValueError):
            info.duration = float(entry["duration"])
    if entry.get("width"):
        info.width = entry.get("width")
    if entry.get("height"):
        info.height = entry.get("height")
    fps = entry.get("fps")
    if fps:
        with contextlib.suppress(TypeError, ValueError):
            rate = float(fps)
            if 0 < rate <= 1000:
                info.fps = rate
    # Whether audio survives depends on the format actually chosen.
    info.has_audio = entry.get("acodec", "none") != "none" or any(
        f.get("acodec", "none") != "none" for f in (entry.get("requested_formats") or [])
    )
    return info


class _Progress:
    """A one-line download progress indicator on stderr.

    stderr on purpose: stdout may be a pipe someone is capturing frames from,
    and this runs before the alt screen is entered, so it scrolls away cleanly.
    """

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet or not sys.stderr.isatty()
        self._last = 0.0

    def __call__(self, status: dict) -> None:
        if self.quiet:
            return
        if status.get("status") == "finished":
            sys.stderr.write("\r\x1b[Kfetched.\n")
            sys.stderr.flush()
            return
        if status.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - self._last < 0.1:
            return
        self._last = now
        done = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        speed = status.get("speed") or 0
        mb = done / 1e6
        if total:
            pct = 100.0 * done / total
            bar_width = 24
            filled = int(bar_width * done / total)
            bar = "━" * filled + "─" * (bar_width - filled)
            msg = f"\r\x1b[Kfetching {bar} {pct:5.1f}%  {mb:6.1f} MB"
        else:
            msg = f"\r\x1b[Kfetching {mb:6.1f} MB"
        if speed:
            msg += f"  {speed / 1e6:4.1f} MB/s"
        sys.stderr.write(msg)
        sys.stderr.flush()


def resolve(
    url: str,
    *,
    quality: int = DEFAULT_QUALITY,
    use_cache: bool = True,
    cache_limit: int = DEFAULT_CACHE_LIMIT,
    quiet: bool = False,
) -> Resolved:
    """Turn a page URL into a playable file path or direct media URL."""
    yt_dlp = import_yt_dlp()
    progressive = not use_cache
    note(f"resolving {url}")
    note(f"format selector: {format_selector(quality, progressive=progressive)}")

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": format_selector(quality, progressive=progressive),
    }

    if not use_cache:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            try:
                entry = ydl.extract_info(url, download=False)
            except Exception as exc:  # yt_dlp raises a wide variety
                raise ResolveError(f"could not resolve {url}\n{exc}") from exc
        entry = _first_entry(entry)
        note(f"chose format {entry.get('format_id')} ({entry.get('format')})")
        direct = entry.get("url")
        if not direct:
            raise ResolveError(
                f"{url}\nNo single progressive stream is available for this video.\n"
                "Drop --no-cache to download and mux it instead."
            )
        # A remote URL is seekable in principle, but every seek re-opens the
        # connection and re-buffers, which is miserable. Say so honestly.
        return Resolved(direct, _media_info(entry, seekable=True), cached=False)

    directory = cache_dir()
    directory.mkdir(parents=True, exist_ok=True)

    with yt_dlp.YoutubeDL(base_opts) as ydl:
        try:
            entry = _first_entry(ydl.extract_info(url, download=False))
        except Exception as exc:
            raise ResolveError(f"could not resolve {url}\n{exc}") from exc

    video_id = _safe(entry.get("id") or entry.get("title") or "video")
    stem = f"{video_id}-{quality}p"
    note(f"chose format {entry.get('format_id')} ({entry.get('format')})")
    note(f"cache dir: {directory}")
    existing = _find_cached(directory, stem)
    if existing is not None:
        note(f"cache hit: {existing}")
        os.utime(existing, None)  # refresh for the LRU
        return Resolved(str(existing), _media_info(entry, seekable=True), cached=True)

    opts = dict(base_opts)
    opts["outtmpl"] = str(directory / f"{stem}.%(ext)s")
    opts["progress_hooks"] = [_Progress(quiet)]
    opts["noprogress"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
        except Exception as exc:
            raise ResolveError(f"could not download {url}\n{exc}") from exc

    downloaded = _find_cached(directory, stem)
    note(f"downloaded to {downloaded}")
    if downloaded is None:
        raise ResolveError(f"download finished but no file appeared for {url}")

    prune_cache(directory, cache_limit)
    return Resolved(str(downloaded), _media_info(entry, seekable=True), cached=True)


def _first_entry(entry):
    """Playlists resolve to a list; take the first item until Phase 5."""
    if entry is None:
        raise ResolveError("no video found at that URL")
    while entry.get("_type") in ("playlist", "multi_video"):
        entries = [e for e in (entry.get("entries") or []) if e]
        if not entries:
            raise ResolveError("that playlist is empty")
        entry = entries[0]
    return entry


def _find_cached(directory: Path, stem: str) -> Path | None:
    for path in sorted(directory.glob(f"{stem}.*")):
        if path.is_file() and not path.name.endswith((".part", ".ytdl")):
            return path
    return None


def clear_cache() -> tuple[int, int]:
    """Delete everything. Returns (files removed, bytes freed)."""
    directory = cache_dir()
    if not directory.is_dir():
        return (0, 0)
    count = total = 0
    for path in directory.iterdir():
        if path.is_file():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
                path.unlink()
                count += 1
    with contextlib.suppress(OSError):
        shutil.rmtree(directory, ignore_errors=True)
    return (count, total)


def cache_size() -> tuple[int, int]:
    """(file count, total bytes) currently cached."""
    directory = cache_dir()
    if not directory.is_dir():
        return (0, 0)
    count = total = 0
    for path in directory.iterdir():
        if path.is_file():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
                count += 1
    return (count, total)
