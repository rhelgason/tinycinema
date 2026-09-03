import numpy as np
import pytest

from tinycinema.render import create
from tinycinema.sources import (
    NoVideoStreamError,
    UnsupportedSourceError,
    open_source,
)
from tinycinema.sources.base import fit_box
from tinycinema.sources.demo import PATTERNS, DemoSource
from tinycinema.sources.ffmpeg import FFmpegSource, _parse_rate


# -- aspect fitting ---------------------------------------------------------


def test_fit_box_square_pixels():
    assert fit_box(1920, 1080, 100, 100) == (100, 56)
    assert fit_box(1080, 1920, 100, 100) == (56, 100)


def test_fit_box_compensates_for_tall_pixels():
    """One pixel per cell means pixels are 2:1 tall, so a square source needs
    twice as many columns as rows to come out looking square."""
    assert fit_box(1000, 1000, 100, 100, pixel_aspect=1.0) == (100, 100)
    assert fit_box(1000, 1000, 100, 100, pixel_aspect=0.5) == (100, 50)


def test_fit_box_never_exceeds_the_box():
    for sw, sh in [(4000, 10), (10, 4000), (1, 1), (1920, 1080)]:
        w, h = fit_box(sw, sh, 80, 24)
        assert 0 < w <= 80 and 0 < h <= 24


def test_fit_box_survives_degenerate_input():
    assert fit_box(0, 0, 80, 24) == (80, 24)


# -- frame rate parsing -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30/1", 30.0),
        ("30000/1001", pytest.approx(29.97, abs=0.01)),
        ("25", 25.0),
        ("0/0", None),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_rate(text, expected):
    assert _parse_rate(text) == expected


# -- the demo source --------------------------------------------------------


@pytest.mark.parametrize("pattern", PATTERNS)
def test_demo_produces_correctly_shaped_frames(pattern):
    src = DemoSource(pattern, fps=30, duration=0.2)
    frames = list(src.open(40, 20))
    assert len(frames) == 6
    for pts, rgb in frames:
        assert rgb.shape == (20, 40, 3)
        assert rgb.dtype == np.uint8
    assert frames[0][0] == 0.0
    assert frames[1][0] == pytest.approx(1 / 30)


def test_demo_respects_the_start_position():
    src = DemoSource("ball", fps=10, duration=1.0)
    first = list(src.open(20, 10, start=0.5))[0]
    assert first[0] == pytest.approx(0.5)


def test_demo_is_deterministic():
    a = list(DemoSource("plasma", fps=10, duration=0.3).open(16, 8))
    b = list(DemoSource("plasma", fps=10, duration=0.3).open(16, 8))
    assert all(np.array_equal(x[1], y[1]) for x, y in zip(a, b, strict=True))


def test_demo_animates():
    frames = list(DemoSource("ball", fps=10, duration=1.0).open(40, 20))
    assert not np.array_equal(frames[0][1], frames[-1][1])


def test_demo_ball_stays_round_under_tall_pixels():
    """With 2:1 pixels the ball must be drawn twice as wide to display round."""
    src = DemoSource("ball", fps=1, duration=1.0)

    def extent(pa):
        _, rgb = next(iter(src.open(200, 100, pixel_aspect=pa)))
        lit = rgb.max(axis=2) > 120  # comfortably above the background gradient
        ys, xs = np.nonzero(lit)
        return np.ptp(xs), np.ptp(ys)

    sw, sh = extent(1.0)
    tw, th = extent(0.5)
    assert sw == pytest.approx(sh, rel=0.15)  # square pixels -> round ball
    assert tw == pytest.approx(th * 2, rel=0.15)  # tall pixels -> 2x wider


def test_demo_rejects_unknown_pattern():
    with pytest.raises(ValueError, match="unknown demo pattern"):
        DemoSource("kaleidoscope")


# -- source resolution ------------------------------------------------------


def test_youtube_urls_are_routed_to_the_extractor(monkeypatch):
    """Detailed resolution behaviour lives in test_ytdlp.py; this is the routing."""
    from tinycinema import sources

    seen = []
    monkeypatch.setattr(sources, "resolve_url", lambda url, **kw: seen.append(url) or 1 / 0)
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/x"):
        with pytest.raises(ZeroDivisionError):
            open_source(url)
    assert len(seen) == 2


def test_missing_file_is_reported_clearly():
    with pytest.raises(UnsupportedSourceError, match="no such file"):
        open_source("/nope/definitely-not-here.mp4")


def test_directory_is_rejected(tmp_path):
    with pytest.raises(UnsupportedSourceError, match="directory"):
        open_source(str(tmp_path))


def test_no_source_at_all():
    with pytest.raises(UnsupportedSourceError, match="no source"):
        open_source(None)


def test_demo_flag_takes_precedence():
    assert isinstance(open_source(None, demo="bars"), DemoSource)


# -- the ffmpeg filter graph ------------------------------------------------


def _source_without_probing(monkeypatch, fps=30.0):
    monkeypatch.setattr("tinycinema.sources.ffmpeg.require_ffmpeg", lambda: "/bin/ffmpeg")
    monkeypatch.setattr("tinycinema.sources.ffmpeg.probe", lambda t: __import__(
        "tinycinema.sources.base", fromlist=["MediaInfo"]
    ).MediaInfo(title="x", fps=fps))
    return FFmpegSource("clip.mp4")


def test_filters_letterbox_and_pin_the_frame_rate(monkeypatch):
    src = _source_without_probing(monkeypatch)
    vf = src._filters(100, 50, 1.0)
    assert "pad=100:50" in vf
    assert "fps=30" in vf
    assert "dar" in vf  # aspect fit is done in-graph, not from ffprobe


def test_filters_divide_through_by_pixel_aspect(monkeypatch):
    """The whole point: ffmpeg must not assume square pixels."""
    src = _source_without_probing(monkeypatch)
    assert "0.500000" in src._filters(100, 50, 0.5)
    assert "1.000000" in src._filters(100, 50, 1.0)


def test_command_seeks_before_input_for_speed(monkeypatch):
    src = _source_without_probing(monkeypatch)
    cmd = src._command(80, 24, 12.5, 1.0)
    assert cmd.index("-ss") < cmd.index("-i")
    assert "12.500" in cmd


def test_command_omits_seek_at_the_start(monkeypatch):
    src = _source_without_probing(monkeypatch)
    assert "-ss" not in src._command(80, 24, 0.0, 1.0)


def test_command_keeps_ffmpeg_off_our_stdin(monkeypatch):
    """Without -nostdin, ffmpeg eats the keystrokes meant for the player."""
    src = _source_without_probing(monkeypatch)
    assert "-nostdin" in src._command(80, 24, 0.0, 1.0)


def test_renderers_and_sources_agree_on_pixel_aspect():
    """The contract between the two halves of the pipeline."""
    for mode in ("ascii", "halfblock", "braille"):
        r = create(mode)
        w, h = r.pixel_size(100, 30)
        assert w > 0 and h > 0
        # a 1:1 source fitted into this box, then displayed, should stay square
        fw, fh = fit_box(500, 500, w, h, pixel_aspect=r.pixel_aspect)
        assert (fw * r.pixel_aspect) == pytest.approx(fh, rel=0.05)


# -- files with nothing to show ---------------------------------------------


def _probe_returning(monkeypatch, **fields):
    from tinycinema.sources.base import MediaInfo

    monkeypatch.setattr("tinycinema.sources.ffmpeg.require_ffmpeg", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(
        "tinycinema.sources.ffmpeg.probe", lambda t: MediaInfo(title="x", **fields)
    )


def test_an_audio_only_file_is_refused_with_a_useful_message(monkeypatch):
    """Otherwise ffmpeg fails later with 'Error opening output files: Invalid
    argument', which tells the user nothing."""
    _probe_returning(monkeypatch, has_audio=True, has_video=False)
    with pytest.raises(NoVideoStreamError, match="audio-only file"):
        FFmpegSource("song.mp3")


def test_a_file_with_neither_stream_is_refused(monkeypatch):
    _probe_returning(monkeypatch, has_audio=False, has_video=False)
    with pytest.raises(NoVideoStreamError, match="no video stream"):
        FFmpegSource("empty.mkv")


def test_an_unreadable_probe_does_not_refuse_the_file(monkeypatch):
    """has_video is None when the probe couldn't tell. Refusing then would
    reject perfectly good videos on a box with no ffprobe."""
    _probe_returning(monkeypatch, has_video=None)
    FFmpegSource("mystery.mp4")  # must not raise


def test_a_normal_video_is_accepted(monkeypatch):
    _probe_returning(monkeypatch, has_audio=True, has_video=True)
    FFmpegSource("clip.mp4")
