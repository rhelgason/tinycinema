"""Parsing media metadata out of `ffmpeg -i`.

The fixtures in tests/fixtures/ are real captured ffmpeg 7.1 stderr, so these
tests exercise the actual output format without needing ffmpeg installed.
"""

from pathlib import Path

import pytest

from tinycinema.sources.ffmpeg import (
    _DIMENSIONS_RE,
    _DURATION_RE,
    _FPS_RE,
    probe,
    probe_via_ffmpeg,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Point probe_via_ffmpeg at a captured stderr sample instead of a binary."""

    def use(fixture_name: str):
        text = (FIXTURES / fixture_name).read_bytes()

        class Result:
            returncode = 1  # `ffmpeg -i` with no output file always exits non-zero
            stderr = text
            stdout = b""

        monkeypatch.setattr("tinycinema.sources.ffmpeg.ffmpeg_path", lambda: "/bin/ffmpeg")
        monkeypatch.setattr("tinycinema.sources.ffmpeg.subprocess.run", lambda *a, **k: Result())

    return use


def test_video_with_audio(fake_ffmpeg):
    fake_ffmpeg("ffmpeg-i-video-audio.txt")
    info = probe_via_ffmpeg("clip.mp4")
    assert info is not None
    assert info.duration == pytest.approx(5.0)
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(30.0)
    assert info.has_audio


def test_video_without_audio(fake_ffmpeg):
    fake_ffmpeg("ffmpeg-i-video-only.txt")
    info = probe_via_ffmpeg("silent.mp4")
    assert info is not None
    assert info.duration == pytest.approx(1.0)
    assert (info.width, info.height) == (100, 100)
    assert info.fps == pytest.approx(25.0)
    assert not info.has_audio, "no audio track means no audio clock"


def test_audio_only_file(fake_ffmpeg):
    fake_ffmpeg("ffmpeg-i-audio-only.txt")
    info = probe_via_ffmpeg("song.wav")
    assert info is not None
    assert info.duration == pytest.approx(3.0)
    assert info.has_audio
    assert info.width is None and info.height is None


def test_unreadable_input_returns_none(fake_ffmpeg):
    """No 'Stream #' line means ffmpeg could not open it at all."""
    fake_ffmpeg("ffmpeg-i-missing.txt")
    assert probe_via_ffmpeg("nope.mp4") is None


def test_no_ffmpeg_binary_returns_none(monkeypatch):
    monkeypatch.setattr("tinycinema.sources.ffmpeg.ffmpeg_path", lambda: None)
    assert probe_via_ffmpeg("clip.mp4") is None


def test_a_crashing_ffmpeg_returns_none(monkeypatch):
    monkeypatch.setattr("tinycinema.sources.ffmpeg.ffmpeg_path", lambda: "/bin/ffmpeg")

    def boom(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr("tinycinema.sources.ffmpeg.subprocess.run", boom)
    assert probe_via_ffmpeg("clip.mp4") is None


# -- the regexes, which are the easy things to get subtly wrong --------------


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        # the real shape: dimensions, then SAR/DAR, then bitrate
        (
            "h264 (High) (avc1 / 0x31637661), yuv420p, 640x360 "
            "[SAR 1:1 DAR 16:9], 794 kb/s, 30 fps",
            (640, 360),
        ),
        ("h264, yuv420p, 1920x1080, 25 fps", (1920, 1080)),
        ("vp9, yuv420p(tv), 3840x2160, 30 fps", (3840, 2160)),
    ],
)
def test_dimension_extraction(detail, expected):
    m = _DIMENSIONS_RE.search(detail)
    assert m and (int(m.group(1)), int(m.group(2))) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("640x360, 794 kb/s, 29.97 fps, 30 tbr", "29.97"),
        ("640x360, 23.98 fps", "23.98"),
        ("100x100, 25 fps", "25"),
    ],
)
def test_fractional_frame_rates(text, expected):
    """NTSC rates print as a decimal here, not as the fraction ffprobe gives."""
    assert _FPS_RE.search(text).group(1) == expected


def test_long_durations_parse():
    m = _DURATION_RE.search("  Duration: 02:13:07.44, start: 0.000000, bitrate: 1 kb/s")
    assert m
    hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
    assert hours * 3600 + minutes * 60 + seconds == pytest.approx(7987.44)


def test_unknown_duration_is_left_none():
    """Live streams report 'Duration: N/A' -- that must not become 0.0."""
    assert not _DURATION_RE.search("  Duration: N/A, start: 0.000000, bitrate: N/A")


# -- probe() dispatch --------------------------------------------------------


def test_probe_uses_the_fallback_when_ffprobe_is_absent(monkeypatch):
    calls = []
    monkeypatch.setattr("tinycinema.sources.ffmpeg.ffprobe_path", lambda: None)
    monkeypatch.setattr(
        "tinycinema.sources.ffmpeg.probe_via_ffmpeg", lambda t: calls.append(t) or None
    )
    probe("clip.mp4")
    assert calls == ["clip.mp4"], "no ffprobe -> must try the ffmpeg parser"


def test_probe_falls_back_when_ffprobe_fails(monkeypatch):
    monkeypatch.setattr("tinycinema.sources.ffmpeg.ffprobe_path", lambda: "/bin/ffprobe")

    class Failed:
        returncode = 1
        stdout = b""
        stderr = b""

    monkeypatch.setattr("tinycinema.sources.ffmpeg.subprocess.run", lambda *a, **k: Failed())
    called = []
    monkeypatch.setattr(
        "tinycinema.sources.ffmpeg.probe_via_ffmpeg", lambda t: called.append(t) or None
    )
    probe("clip.mp4")
    assert called == ["clip.mp4"]


def test_probe_never_shells_out_for_stdin(monkeypatch):
    """There is nothing to probe on a pipe, and reading it would consume it."""

    def explode(*a, **k):
        raise AssertionError("must not run a subprocess for stdin")

    monkeypatch.setattr("tinycinema.sources.ffmpeg.subprocess.run", explode)
    monkeypatch.setattr("tinycinema.sources.ffmpeg.probe_via_ffmpeg", explode)
    info = probe("-")
    assert not info.seekable
