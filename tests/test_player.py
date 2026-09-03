"""The timing loop, driven by a hand-cranked clock.

The invariant that matters: we never render a frame that is later than the drop
threshold. Rendering everything late is far worse than rendering most on time.
"""

import types

import numpy as np
import pytest

from tinycinema import player as player_mod
from tinycinema.player import (
    DROP_AFTER_FRAMES,
    PlaybackOptions,
    Player,
    _fmt_time,
    _truncate,
)
from tinycinema.sources.base import FrameSource, MediaInfo
from tinycinema.term import Capabilities


class FakeClock:
    """The Clock interface with a timeline we advance by hand.

    Injected rather than monkeypatched, so the tests exercise the same seam the
    audio clock plugs into.
    """

    def __init__(self, start=0.0):
        self.t = start
        self._paused = False
        self.starts = []
        self.pauses = 0
        self.resumes = 0
        self.stops = 0

    # -- Clock interface --
    def start(self, position=0.0):
        self.t = position
        self._paused = False
        self.starts.append(position)

    def now(self):
        return self.t

    def pause(self):
        self._paused = True
        self.pauses += 1

    def resume(self):
        self._paused = False
        self.resumes += 1

    def stop(self):
        self.stops += 1

    @property
    def paused(self):
        return self._paused

    @property
    def source(self):
        return "fake"

    # -- test helper: wall time tracks media time when there's no audio --
    def perf_counter(self):
        return 1000.0 + self.t

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
    # The real _sleep_for busy-waits on perf_counter, which never terminates
    # against a clock that only moves when we tell it to.
    monkeypatch.setattr(player_mod, "_sleep_for", lambda d: setattr(c, "t", c.t + max(d, 0.0)))
    return c


def make_player(clock, source, *, cost=0.0, **opts):
    opts.setdefault("hud", False)
    player = Player(source, FakeTerminal(), PlaybackOptions(**opts), clock)
    player.writer = RecordingWriter(clock, cost)
    return player


# -- timing -----------------------------------------------------------------


def test_frames_on_time_are_all_rendered(clock):
    p = make_player(clock, FakeSource(n=30), cost=0.0)
    p.run()
    assert p.stats.rendered == 30
    assert p.stats.dropped == 0


def test_slow_rendering_drops_frames_rather_than_falling_behind(clock):
    """Render cost of 3 frame intervals: roughly two in three must be dropped."""
    p = make_player(clock, FakeSource(n=60, fps=30.0), cost=0.1)
    p.run()
    assert p.stats.dropped > p.stats.rendered
    assert p.stats.rendered + p.stats.dropped == 60


def test_no_frame_is_ever_rendered_later_than_the_drop_threshold(clock):
    p = make_player(clock, FakeSource(n=60, fps=30.0), cost=0.1)

    lags = []
    real_paint = p._paint

    def spy(rgb, pts, cols, rows, video_rows):
        lags.append(clock.now() - pts)
        real_paint(rgb, pts, cols, rows, video_rows)

    p._paint = spy
    p.run()

    assert lags, "nothing rendered at all"
    assert max(lags) <= DROP_AFTER_FRAMES / 30.0 + 1e-9


def test_running_ahead_of_the_clock_waits(clock, monkeypatch):
    waits = []
    monkeypatch.setattr(player_mod, "_sleep_for", lambda d: waits.append(d))
    p = make_player(clock, FakeSource(n=10), cost=0.0)
    p.run()
    # The clock never advances, so every frame after the first is early.
    assert len(waits) == 9
    assert all(w > 0 for w in waits)


# -- the clock seam ---------------------------------------------------------


def test_clock_is_started_at_the_requested_position(clock):
    p = make_player(clock, FakeSource(n=3), start=12.5)
    p.run()
    assert clock.starts == [12.5]


def test_clock_is_stopped_on_exit(clock):
    p = make_player(clock, FakeSource(n=3))
    p.run()
    assert clock.stops >= 1


def test_pause_and_resume_move_the_clock(clock):
    p = make_player(clock, FakeSource(n=100))
    p._apply_key("space")
    assert p._paused and clock.pauses == 1
    p._apply_key("space")
    assert not p._paused and clock.resumes == 1


def test_a_seek_restarts_audio(clock):
    """Seeking moves the timeline, so the audio has to move with it."""
    src = FakeSource(n=10, duration=100.0)
    p = make_player(clock, src)
    p._position = 10.0
    assert p._seek(5.0) == "seek"
    p._restart_audio = p._seek(0.0) not in player_mod.VIDEO_ONLY_RESTARTS
    assert p._restart_audio


def test_a_resize_does_not_restart_audio(clock):
    """Tearing down the audio device because a window moved would click audibly."""
    assert "resize" in player_mod.VIDEO_ONLY_RESTARTS
    assert "reopen" in player_mod.VIDEO_ONLY_RESTARTS
    assert "seek" not in player_mod.VIDEO_ONLY_RESTARTS

    src = FakeSource(n=200)
    p = make_player(clock, src)
    p.term.resizes = [False, False, True]
    p.run()
    # One clock.start() for the initial play, and none for the resize.
    assert clock.starts == [0.0]
    assert len(src.opened) >= 2, "video should have reopened"


def test_video_resumes_from_the_clock_after_a_video_only_restart(clock):
    """Audio kept playing during the resize, so video must catch up to it."""
    src = FakeSource(n=200)
    p = make_player(clock, src)
    p.term.resizes = [False, True]
    p._play_once()
    clock.t = 42.0  # audio ran on while the pipeline was rebuilt
    p._restart_audio = False
    p._play_once()
    assert src.opened[-1][2] == pytest.approx(42.0)


def test_mode_switch_is_a_video_only_restart(clock):
    p = make_player(clock, FakeSource(n=5))
    assert p._cycle_mode(+1) in player_mod.VIDEO_ONLY_RESTARTS


# -- lifecycle --------------------------------------------------------------


def test_once_renders_exactly_one_frame(clock):
    p = make_player(clock, FakeSource(n=30), once=True)
    p.run()
    assert p.writer.frames == 1


def test_once_never_drops_the_only_frame(clock):
    """--once must produce output even when it starts arbitrarily late."""
    p = make_player(clock, FakeSource(n=30), once=True)
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
        return "quit" if calls["n"] > 3 else real()

    p._play_once = limited
    p.run()
    assert len(src.opened) == 3
    assert all(o[2] == 0.0 for o in src.opened)
    assert clock.starts == [0.0, 0.0, 0.0]  # audio restarts each pass


def test_source_is_closed_even_when_the_loop_raises(clock):
    src = FakeSource(n=5)
    p = make_player(clock, src)
    p._play_once = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        p.run()
    assert src.closed >= 1
    assert clock.stops >= 1


def test_pixel_aspect_is_passed_to_the_source(clock):
    src = FakeSource(n=3)
    make_player(clock, src, mode="ascii").run()
    assert src.opened[0][3] == pytest.approx(0.5)

    src2 = FakeSource(n=3)
    make_player(FakeClock(), src2, mode="halfblock").run()
    assert src2.opened[0][3] == pytest.approx(1.0)


# -- keys -------------------------------------------------------------------


def test_queued_keys_survive_a_pipeline_restart(clock):
    """'rrr' must advance three render modes, not one."""
    p = make_player(clock, FakeSource(n=5))
    p._pending_keys.extend(["r", "r", "r"])
    start_mode = p.renderer.name

    seen = []
    for _ in range(3):
        assert p._handle_keys() in player_mod.VIDEO_ONLY_RESTARTS
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
    p = make_player(clock, FakeSource(n=10, duration=8.0))
    p._position = 6.0
    assert p._seek(60.0) == "seek"
    assert p._position == pytest.approx(7.9)


def test_seek_never_goes_negative(clock):
    p = make_player(clock, FakeSource(n=10, duration=8.0))
    p._position = 1.0
    p._seek(-60.0)
    assert p._position == 0.0


# -- volume, mute, stepping, playlist ---------------------------------------


def test_volume_keys_adjust_and_clamp(clock):
    p = make_player(clock, FakeSource(n=5), volume=100)
    p._apply_key("-")
    assert p.opts.volume == 95
    for _ in range(50):
        p._apply_key("-")
    assert p.opts.volume == 0, "must clamp at zero, not go negative"
    for _ in range(50):
        p._apply_key("=")
    assert p.opts.volume == 100, "must clamp at 100"


def test_volume_changes_are_debounced(clock):
    """ffplay takes its volume at launch, so each change relaunches it.
    Doing that per keypress while a key is held would shred the audio."""
    applied = []
    p = make_player(clock, FakeSource(n=5), volume=100)
    p.clock.set_volume = applied.append

    p._apply_key("-")
    p._apply_pending_volume()
    assert applied == [], "must not fire immediately"

    clock.t += player_mod.VOLUME_DEBOUNCE + 0.01
    p._apply_pending_volume()
    assert applied == [95]

    p._apply_pending_volume()
    assert applied == [95], "and only once per burst"


def test_mute_restores_the_previous_volume(clock):
    p = make_player(clock, FakeSource(n=5), volume=70)
    p._apply_key("m")
    assert p.opts.volume == 0 and p._muted
    p._apply_key("m")
    assert p.opts.volume == 70 and not p._muted


def test_adjusting_volume_cancels_mute(clock):
    p = make_player(clock, FakeSource(n=5), volume=70)
    p._apply_key("m")
    p._apply_key("=")
    assert not p._muted and p.opts.volume == 5


def test_step_forward_advances_exactly_one_frame(clock):
    """Regression: the pause branch used to pull a frame before waiting, so a
    single step showed one frame and then immediately jumped to the next."""
    src = FakeSource(n=20, fps=30.0)
    p = make_player(clock, src)
    painted = []
    real = p._paint

    def spy(rgb, pts, *rest):
        painted.append(pts)
        return real(rgb, pts, *rest)

    p._paint = spy
    p._wait_while_paused = lambda: "quit"  # stop after the step settles

    p._pending_keys.append(".")
    p._play_once()

    assert p._paused and not p._step_once
    assert len(set(painted)) == 1, f"a step must advance one frame, showed {painted}"
    assert painted[0] == 0.0


def test_step_backward_seeks_by_one_frame(clock):
    src = FakeSource(n=20, fps=30.0, duration=10.0)
    p = make_player(clock, src)
    p._paused = True
    p._position = 5.0
    assert p._step(-1) == "seek"
    assert p._position < 5.0
    assert p._position == pytest.approx(5.0 - 1.5 / 30.0)


def test_step_backward_is_refused_when_not_seekable(clock):
    src = FakeSource(n=20)
    src.info.seekable = False
    p = make_player(clock, src)
    p._paused = True
    assert p._step(-1) is None


def test_a_restart_while_paused_stays_paused(clock):
    """A backward step reopens the pipeline; it must not resume playing."""
    src = FakeSource(n=20)
    p = make_player(clock, src)
    p._paused = True
    p._restart_audio = True
    p._wait_while_paused = lambda: "quit"
    p._play_once()
    assert clock.paused, "the clock must be re-paused after the restart"


def test_playlist_keys_only_work_with_a_playlist(clock):
    alone = make_player(clock, FakeSource(n=5), playlist=False)
    assert alone._apply_key("n") is None
    assert alone._apply_key("p") is None

    inlist = make_player(FakeClock(), FakeSource(n=5), playlist=True)
    assert inlist._apply_key("n") == "next"
    assert inlist._apply_key("p") == "prev"


def test_exit_reason_is_recorded_for_the_playlist_driver(clock):
    p = make_player(clock, FakeSource(n=3), playlist=True)
    p.run()
    assert p.exit_reason == "eof"

    q = make_player(FakeClock(), FakeSource(n=100), playlist=True)
    q._pending_keys.append("n")
    q.run()
    assert q.exit_reason == "next"


def test_hud_shows_volume_and_mute(clock):
    p = make_player(clock, FakeSource(n=5, duration=60.0), hud=True, volume=40)
    assert "40%" in p._hud_text(1.0, 140)
    p._apply_key("m")
    assert "muted" in p._hud_text(1.0, 140)


# -- HUD --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"), (9, "00:09"), (61, "01:01"),
        (3600, "1:00:00"), (3725, "1:02:05"), (None, "--:--"),
    ],
)
def test_time_formatting(seconds, expected):
    assert _fmt_time(seconds) == expected


def test_truncate():
    assert _truncate("hello", 10) == "hello"
    assert _truncate("hello world", 5) == "hell…"
    assert _truncate("x", 0) == ""


def test_hud_is_exactly_one_line_wide(clock):
    p = make_player(clock, FakeSource(n=10, duration=120.0), hud=True)
    for cols in (20, 40, 80, 200):
        assert len(p._hud_text(12.0, cols)) == cols


def test_hud_survives_a_very_long_title(clock):
    src = FakeSource(n=10, duration=120.0)
    src.info.title = "a" * 500
    p = make_player(clock, src, hud=True)
    assert len(p._hud_text(1.0, 60)) == 60


def test_hud_shows_a_progress_bar_only_when_the_duration_is_known(clock):
    known = make_player(clock, FakeSource(n=10, duration=100.0), hud=True)
    unknown = make_player(FakeClock(), FakeSource(n=10, duration=None), hud=True)
    assert "━" in known._hud_text(50.0, 100)
    assert "━" not in unknown._hud_text(50.0, 100)


def test_hud_names_the_clock_driving_playback(clock):
    """When sync looks wrong, the first question is which clock is in charge."""
    p = make_player(clock, FakeSource(n=10, duration=100.0), hud=True)
    assert "fake" in p._hud_text(1.0, 120)


def test_hud_reserves_a_row_from_the_video(clock):
    src = FakeSource(n=1)
    p = make_player(clock, src, hud=True)
    p.is_tty = True  # _hud_enabled requires a tty
    p._play_once()
    # halfblock, 12 rows total, 1 reserved for the HUD -> 11 * 2 = 22 pixels
    assert src.opened[0][1] == 22
