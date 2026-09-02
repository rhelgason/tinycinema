"""The timing loop, driven by a fake clock.

The invariant that matters: we never render a frame that is later than the drop
threshold. Rendering everything late is far worse than rendering most on time.
"""

import types

import numpy as np
import pytest

from tinycinema import player as player_mod
from tinycinema.player import DROP_AFTER_FRAMES, PlaybackOptions, Player, _fmt_time, _truncate
from tinycinema.sources.base import FrameSource, MediaInfo
from tinycinema.term import Capabilities


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start
        self.slept = []

    def perf_counter(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakeSource(FrameSource):
    def __init__(self, n=30, fps=30.0, duration=None):
        self.info = MediaInfo(title="fake", fps=fps, duration=duration)
        self.n = n
        self.opened = []
        self.closed = 0

    def open(self, width, height, *, start=0.0, pixel_aspect=1.0):
        self.opened.append((width, height, start, pixel_aspect))
        step = 1.0 / self.info.fps
        frame = np.zeros((height, width, 3), np.uint8)
        return iter([(start + i * step, frame) for i in range(self.n)])

    def close(self):
        self.closed += 1


class FakeTerminal:
    def __init__(self, cols=40, rows=12):
        self.caps = Capabilities(
            is_tty=False, truecolor=True, color256=True, unicode=True,
            kitty=False, iterm=False, term="test", term_program="test",
        )
        self._size = (cols, rows)
        self.resizes = []

    def size(self):
        return self._size

    def take_resize(self):
        return self.resizes.pop(0) if self.resizes else False


class RecordingWriter:
    """Stands in for the real writer and charges the clock for each paint."""

    def __init__(self, clock, cost=0.0):
        self.clock = clock
        self.cost = cost
        self.frames = 0
        self.bytes_written = 0

    def invalidate(self):
        pass

    def draw(self, grid):
        self.frames += 1
        self.clock.t += self.cost


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(
        player_mod, "time", types.SimpleNamespace(perf_counter=c.perf_counter, sleep=c.sleep)
    )
    # The real _sleep_until ends in a busy-wait on perf_counter, which never
    # terminates against a clock that only moves when we tell it to. Jumping
    # straight to the target is what sleeping means here anyway.
    def jump(target):
        c.t = max(c.t, target)

    monkeypatch.setattr(player_mod, "_sleep_until", jump)
    return c


def make_player(clock, source, *, cost=0.0, **opts):
    term = FakeTerminal()
    opts.setdefault("hud", False)
    player = Player(source, term, PlaybackOptions(**opts))
    player.writer = RecordingWriter(clock, cost)
    return player


# -- timing -----------------------------------------------------------------


def test_frames_on_time_are_all_rendered(clock):
    src = FakeSource(n=30)
    p = make_player(clock, src, cost=0.0)
    p.run()
    assert p.stats.rendered == 30
    assert p.stats.dropped == 0


def test_slow_rendering_drops_frames_rather_than_falling_behind(clock):
    """Render cost of 3 frame intervals: roughly two in three must be dropped."""
    src = FakeSource(n=60, fps=30.0)
    p = make_player(clock, src, cost=0.1)
    p.run()
    assert p.stats.dropped > p.stats.rendered
    assert p.stats.rendered + p.stats.dropped == 60


def test_no_frame_is_ever_rendered_later_than_the_drop_threshold(clock):
    src = FakeSource(n=60, fps=30.0)
    p = make_player(clock, src, cost=0.1)

    lags = []
    real_paint = p._paint

    def spy(rgb, pts, cols, rows, video_rows):
        lags.append(clock.t - (p._origin + pts))
        real_paint(rgb, pts, cols, rows, video_rows)

    p._paint = spy
    p.run()

    threshold = DROP_AFTER_FRAMES / 30.0
    assert lags, "nothing rendered at all"
    assert max(lags) <= threshold + 1e-9


def test_running_ahead_of_the_clock_sleeps(clock, monkeypatch):
    waits = []
    monkeypatch.setattr(player_mod, "_sleep_until", lambda t: waits.append(t))
    p = make_player(clock, FakeSource(n=10), cost=0.0)
    p.run()
    assert len(waits) == 9  # every frame after the first is early


# -- lifecycle --------------------------------------------------------------


def test_once_renders_exactly_one_frame(clock):
    p = make_player(clock, FakeSource(n=30), once=True)
    p.run()
    assert p.writer.frames == 1


def test_once_never_drops_the_only_frame(clock):
    """--once must produce output even when it starts arbitrarily late."""
    src = FakeSource(n=30)
    p = make_player(clock, src, cost=0.0, once=True, start=0.0)
    clock.t += 100.0  # simulate a very slow startup
    p.run()
    assert p.writer.frames == 1


def test_loop_reopens_the_source_from_the_start(clock):
    src = FakeSource(n=5)
    p = make_player(clock, src, loop=True)

    calls = {"n": 0}
    real = p._play_once

    def limited():
        calls["n"] += 1
        if calls["n"] > 3:
            return "quit"
        return real()

    p._play_once = limited
    p.run()
    assert len(src.opened) == 3
    assert all(o[2] == 0.0 for o in src.opened)  # each pass starts at zero


def test_source_is_closed_even_when_the_loop_raises(clock):
    src = FakeSource(n=5)
    p = make_player(clock, src)
    p._play_once = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        p.run()
    assert src.closed >= 1


def test_start_position_is_passed_through(clock):
    src = FakeSource(n=3)
    p = make_player(clock, src, start=12.5)
    p.run()
    assert src.opened[0][2] == 12.5


def test_pixel_aspect_is_passed_to_the_source(clock):
    src = FakeSource(n=3)
    p = make_player(clock, src, mode="ascii")
    p.run()
    assert src.opened[0][3] == pytest.approx(0.5)

    src2 = FakeSource(n=3)
    p2 = make_player(clock, src2, mode="halfblock")
    p2.run()
    assert src2.opened[0][3] == pytest.approx(1.0)


# -- keys -------------------------------------------------------------------


def test_queued_keys_survive_a_pipeline_restart(clock):
    """'rrr' must advance three render modes, not one."""
    p = make_player(clock, FakeSource(n=5))
    p._pending_keys.extend(["r", "r", "r"])
    start_mode = p.renderer.name

    seen = []
    for _ in range(3):
        assert p._handle_keys() == "reopen"
        seen.append(p.renderer.name)

    assert len(set(seen)) == 3, "each 'r' must land on a distinct mode"
    assert start_mode not in seen


def test_quit_key_stops_playback(clock):
    p = make_player(clock, FakeSource(n=100))
    p._pending_keys.append("q")
    assert p._handle_keys() == "quit"


def test_seek_is_refused_on_a_non_seekable_source(clock):
    src = FakeSource(n=10)
    src.info.seekable = False
    p = make_player(clock, src)
    assert p._seek(5.0) is None
    assert p._position == 0.0


def test_seek_clamps_to_the_duration(clock):
    src = FakeSource(n=10, duration=8.0)
    p = make_player(clock, src)
    p._position = 6.0
    assert p._seek(60.0) == "reopen"
    assert p._position == pytest.approx(7.9)


def test_seek_never_goes_negative(clock):
    p = make_player(clock, FakeSource(n=10, duration=8.0))
    p._position = 1.0
    p._seek(-60.0)
    assert p._position == 0.0


def test_resize_restarts_at_the_current_position(clock):
    src = FakeSource(n=30)
    p = make_player(clock, src)
    p.term.resizes = [False, False, True]
    p._play_once()
    assert p._position > 0.0


# -- HUD --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (9, "00:09"), (61, "01:01"), (3600, "1:00:00"), (3725, "1:02:05"), (None, "--:--")],
)
def test_time_formatting(seconds, expected):
    assert _fmt_time(seconds) == expected


def test_truncate():
    assert _truncate("hello", 10) == "hello"
    assert _truncate("hello world", 5) == "hell…"
    assert _truncate("x", 0) == ""


def test_hud_is_exactly_one_line_wide(clock):
    src = FakeSource(n=10, duration=120.0)
    p = make_player(clock, src, hud=True)
    for cols in (20, 40, 80, 200):
        assert len(p._hud_text(12.0, cols)) == cols


def test_hud_survives_a_very_long_title(clock):
    src = FakeSource(n=10, duration=120.0)
    src.info.title = "a" * 500
    p = make_player(clock, src, hud=True)
    assert len(p._hud_text(1.0, 60)) == 60


def test_hud_shows_a_progress_bar_only_when_the_duration_is_known(clock):
    known = make_player(clock, FakeSource(n=10, duration=100.0), hud=True)
    unknown = make_player(clock, FakeSource(n=10, duration=None), hud=True)
    assert "━" in known._hud_text(50.0, 100)
    assert "━" not in unknown._hud_text(50.0, 100)


def test_hud_reserves_a_row_from_the_video(clock):
    src = FakeSource(n=1)
    p = make_player(clock, src, hud=True)
    p.is_tty = True  # _hud_enabled requires a tty
    p._play_once()
    # halfblock, 12 rows total, 1 reserved for the HUD -> 11 * 2 = 22 pixels
    assert src.opened[0][1] == 22
