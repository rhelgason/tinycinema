"""URL resolution, format selection and the download cache.

yt-dlp is stubbed out: these tests are about *our* logic (which format string we
ask for, where files land, what gets evicted), not about scraping. The cache
tests use the real filesystem via tmp_path.
"""

import os
import sys
import types

import pytest

from tinycinema.sources import ytdlp
from tinycinema.sources.ytdlp import (
    DEFAULT_QUALITY,
    ResolveError,
    YtDlpMissingError,
    cache_dir,
    format_selector,
    is_extractor_url,
    parse_quality,
    prune_cache,
)

# -- URL classification ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://vimeo.com/12345",
        "https://www.twitch.tv/someone",
        "https://x.com/user/status/1",
        "https://soundcloud.com/artist/track",
    ],
)
def test_extractor_urls_are_recognised(url):
    assert is_extractor_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/clip.mp4",
        "http://192.168.1.5:8080/stream.m3u8",
        "https://cdn.example.org/a/b/video.webm",
    ],
)
def test_direct_media_urls_go_straight_to_ffmpeg(url):
    assert not is_extractor_url(url)


# -- quality -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, DEFAULT_QUALITY), (360, 360), ("360", 360), ("720p", 720), ("1080P", 1080)],
)
def test_parse_quality(value, expected):
    assert parse_quality(value) == expected


def test_parse_quality_rejects_nonsense():
    with pytest.raises(ValueError, match="bad quality"):
        parse_quality("very good")


# -- format selection --------------------------------------------------------


def test_cached_format_takes_separate_streams():
    """Downloading lets yt-dlp mux, so ask for the best video + best audio."""
    fmt = format_selector(480, progressive=False)
    assert "bestvideo[height<=?480]+bestaudio" in fmt
    assert fmt.endswith("/best"), "must have an unconditional fallback"


def test_streaming_format_must_be_progressive():
    """One URL has to carry both streams: ffmpeg and ffplay each open it."""
    fmt = format_selector(480, progressive=True)
    assert "vcodec!=none" in fmt and "acodec!=none" in fmt
    assert "bestvideo" not in fmt, "a video-only stream would play silently"


def test_format_filters_are_non_strict():
    """`?` means a video lacking the requested height still resolves."""
    assert "height<=?720" in format_selector(720, progressive=False)
    assert "height<=?720" in format_selector(720, progressive=True)


# -- cache location ----------------------------------------------------------


def test_cache_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TINYCINEMA_CACHE", str(tmp_path / "somewhere"))
    assert cache_dir() == tmp_path / "somewhere"


def test_cache_dir_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("TINYCINEMA_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cache_dir() == tmp_path / "tinycinema"


def test_cache_dir_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TINYCINEMA_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert cache_dir() == tmp_path / ".cache" / "tinycinema"


# -- cache eviction ----------------------------------------------------------


def make_file(directory, name, size, atime):
    path = directory / name
    path.write_bytes(b"\0" * size)
    os.utime(path, (atime, atime))
    return path


def test_prune_evicts_least_recently_used_first(tmp_path):
    old = make_file(tmp_path, "old.mp4", 600, atime=1000)
    mid = make_file(tmp_path, "mid.mp4", 600, atime=2000)
    new = make_file(tmp_path, "new.mp4", 600, atime=3000)

    removed = prune_cache(tmp_path, limit=1300)

    assert old in removed and not old.exists()
    assert mid.exists() and new.exists(), "only evict as much as needed"


def test_prune_does_nothing_when_under_the_limit(tmp_path):
    make_file(tmp_path, "a.mp4", 100, atime=1)
    assert prune_cache(tmp_path, limit=10_000) == []
    assert (tmp_path / "a.mp4").exists()


def test_prune_ignores_partial_downloads(tmp_path):
    """A .part file belongs to a download in flight; deleting it corrupts it."""
    part = make_file(tmp_path, "x.mp4.part", 5000, atime=1)
    make_file(tmp_path, "done.mp4", 5000, atime=2)
    prune_cache(tmp_path, limit=1)
    assert part.exists()


def test_prune_on_a_missing_directory_is_harmless(tmp_path):
    assert prune_cache(tmp_path / "nope") == []


# -- a stand-in for yt_dlp ---------------------------------------------------

SAMPLE = {
    "id": "dQw4w9WgXcQ",
    "title": "A Video",
    "duration": 212.0,
    "width": 640,
    "height": 360,
    "fps": 25,
    "acodec": "mp4a.40.2",
    "url": "https://cdn.example.com/progressive.mp4",
}


class FakeYoutubeDL:
    """Records the options it was constructed with, and fakes a download."""

    instances: list["FakeYoutubeDL"] = []
    entry: dict = SAMPLE
    raise_on_extract: Exception | None = None
    write_to: str | None = None

    def __init__(self, opts):
        self.opts = opts
        FakeYoutubeDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if FakeYoutubeDL.raise_on_extract:
            raise FakeYoutubeDL.raise_on_extract
        return dict(FakeYoutubeDL.entry)

    def download(self, urls):
        if FakeYoutubeDL.write_to:
            path = self.opts["outtmpl"].replace("%(ext)s", "mp4")
            with open(path, "wb") as fh:
                fh.write(b"\0" * 1024)


@pytest.fixture
def fake_ytdlp(monkeypatch, tmp_path):
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.entry = SAMPLE
    FakeYoutubeDL.raise_on_extract = None
    FakeYoutubeDL.write_to = "yes"
    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = FakeYoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setenv("TINYCINEMA_CACHE", str(tmp_path / "cache"))
    return FakeYoutubeDL


# -- resolution --------------------------------------------------------------


def test_missing_yt_dlp_explains_the_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_ytdlp(name, *a, **k):
        if name == "yt_dlp":
            raise ImportError("nope")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ytdlp)
    with pytest.raises(YtDlpMissingError, match=r"tinycinema\[youtube\]"):
        ytdlp.import_yt_dlp()


def test_streaming_returns_the_direct_url(fake_ytdlp, tmp_path):
    got = ytdlp.resolve("https://youtu.be/x", use_cache=False, quiet=True)
    assert got.target == SAMPLE["url"]
    assert not got.cached
    assert got.info.title == "A Video"
    assert got.info.duration == pytest.approx(212.0)
    assert got.info.has_audio
    # nothing should have been written to disk
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").iterdir())


def test_streaming_without_a_progressive_format_says_so(fake_ytdlp):
    FakeYoutubeDL.entry = {**SAMPLE, "url": None}
    with pytest.raises(ResolveError, match="--no-cache"):
        ytdlp.resolve("https://youtu.be/x", use_cache=False, quiet=True)


def test_caching_downloads_then_returns_a_local_path(fake_ytdlp, tmp_path):
    got = ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    assert got.cached
    assert got.target.endswith("dQw4w9WgXcQ-360p.mp4")
    assert os.path.exists(got.target)


def test_a_second_call_reuses_the_cached_file(fake_ytdlp, tmp_path):
    first = ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    downloads_before = len(FakeYoutubeDL.instances)

    FakeYoutubeDL.write_to = None  # a second download would produce nothing
    second = ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)

    assert second.target == first.target
    assert second.cached
    # extract_info still runs (for metadata), but no second download happened
    assert len(FakeYoutubeDL.instances) == downloads_before + 1


def test_different_qualities_cache_separately(fake_ytdlp):
    a = ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    b = ytdlp.resolve("https://youtu.be/x", quality=720, quiet=True)
    assert a.target != b.target
    assert "360p" in a.target and "720p" in b.target


def test_cache_hit_refreshes_the_lru_timestamp(fake_ytdlp):
    got = ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    os.utime(got.target, (1000, 1000))
    ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    assert os.stat(got.target).st_atime > 1000, "a hit must not look stale to prune"


def test_a_failed_extract_is_reported_clearly(fake_ytdlp):
    FakeYoutubeDL.raise_on_extract = RuntimeError("video unavailable")
    with pytest.raises(ResolveError, match="video unavailable"):
        ytdlp.resolve("https://youtu.be/x", quiet=True)


def test_a_download_that_produces_nothing_is_an_error(fake_ytdlp):
    FakeYoutubeDL.write_to = None
    with pytest.raises(ResolveError, match="no file appeared"):
        ytdlp.resolve("https://youtu.be/x", quiet=True)


def test_a_playlist_resolves_to_its_first_entry(fake_ytdlp):
    FakeYoutubeDL.entry = {
        "_type": "playlist",
        "entries": [{**SAMPLE, "id": "first", "title": "First"}],
    }
    got = ytdlp.resolve("https://youtu.be/list", use_cache=False, quiet=True)
    assert got.info.title == "First"


def test_an_empty_playlist_is_an_error(fake_ytdlp):
    FakeYoutubeDL.entry = {"_type": "playlist", "entries": []}
    with pytest.raises(ResolveError, match="empty"):
        ytdlp.resolve("https://youtu.be/list", quiet=True)


def test_a_video_with_no_audio_track_is_reported(fake_ytdlp):
    FakeYoutubeDL.entry = {**SAMPLE, "acodec": "none", "requested_formats": []}
    got = ytdlp.resolve("https://youtu.be/x", use_cache=False, quiet=True)
    assert not got.info.has_audio, "no audio -> the player must use a wall clock"


def test_audio_detected_through_requested_formats(fake_ytdlp):
    """Separate DASH streams report acodec on the sub-formats, not the top level."""
    FakeYoutubeDL.entry = {
        **SAMPLE,
        "acodec": "none",
        "requested_formats": [{"acodec": "none"}, {"acodec": "opus"}],
    }
    got = ytdlp.resolve("https://youtu.be/x", use_cache=False, quiet=True)
    assert got.info.has_audio


def test_the_requested_format_reaches_yt_dlp(fake_ytdlp):
    ytdlp.resolve("https://youtu.be/x", quality=240, quiet=True)
    assert any("height<=?240" in i.opts.get("format", "") for i in FakeYoutubeDL.instances)


def test_download_prunes_the_cache(fake_ytdlp, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ytdlp, "prune_cache", lambda d, limit: calls.append(limit))
    ytdlp.resolve("https://youtu.be/x", quiet=True, cache_limit=123)
    assert calls == [123]


# -- cache management --------------------------------------------------------


def test_cache_size_and_clear(fake_ytdlp, tmp_path):
    ytdlp.resolve("https://youtu.be/x", quality=360, quiet=True)
    count, size = ytdlp.cache_size()
    assert count == 1 and size == 1024

    removed, freed = ytdlp.clear_cache()
    assert removed == 1 and freed == 1024
    assert ytdlp.cache_size() == (0, 0)


def test_clearing_an_absent_cache_is_harmless(monkeypatch, tmp_path):
    monkeypatch.setenv("TINYCINEMA_CACHE", str(tmp_path / "never-made"))
    assert ytdlp.clear_cache() == (0, 0)
    assert ytdlp.cache_size() == (0, 0)


# -- integration with open_source -------------------------------------------


def test_open_source_routes_extractor_urls_through_yt_dlp(fake_ytdlp, monkeypatch):
    from tinycinema import sources

    seen = {}

    class StubSource:
        def __init__(self, target, **kw):
            seen["target"] = target
            from tinycinema.sources.base import MediaInfo

            self.info = MediaInfo(title="from-probe")
            self.target = target

    monkeypatch.setattr(sources, "FFmpegSource", StubSource)
    src = sources.open_source("https://youtu.be/x", quality=360, quiet=True)

    assert seen["target"].endswith("dQw4w9WgXcQ-360p.mp4")
    assert src.info.title == "A Video", "extractor metadata should win over the probe"
    assert src.info.duration == pytest.approx(212.0)


def test_open_source_leaves_direct_urls_alone(monkeypatch):
    from tinycinema import sources

    def explode(*a, **k):
        raise AssertionError("must not invoke yt-dlp for a direct media URL")

    monkeypatch.setattr(sources, "resolve_url", explode)

    class StubSource:
        def __init__(self, target, **kw):
            from tinycinema.sources.base import MediaInfo

            self.info = MediaInfo()
            self.target = target

    monkeypatch.setattr(sources, "FFmpegSource", StubSource)
    src = sources.open_source("https://example.com/clip.mp4")
    assert src.target == "https://example.com/clip.mp4"
