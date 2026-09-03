"""The audio clock, its fallback behaviour, and ffplay status parsing."""

import types

import pytest

from tinycinema import audio as audio_mod
from tinycinema.audio import base as base_mod
from tinycinema.audio.base import AudioClock, NullSink, WallClock
from tinycinema.audio.ffplay import _STATUS_RE, FFplaySink
from tinycinema.sources.base import MediaInfo


class FakeTime:
    def __init__(self):
        self.t = 500.0

    def perf_counter(self):
        return self.t


@pytest.fixture
def fake_time(monkeypatch):
    ft = FakeTime()
    monkeypatch.setattr(base_mod, "time", types.SimpleNamespace(perf_counter=ft.perf_counter))
    return ft


class ScriptedSink:
    """An audio sink whose reported position we control exactly.

    report() stamps the observation time, exactly as a real sink's reader thread
    does, so the clock's interpolation is exercised rather than bypassed.
    """

    def __init__(self):
        self._anchor = None
        self.started = []
        self.pauses = 0
        self.resumes = 0
        self.stops = 0

    def report(self, position):
        """The device just told us it is at `position`, as of now."""
        self._anchor = (position, base_mod.time.perf_counter())

    def silence(self):
        """Stop producing fresh reports (the clock must coast)."""
        self._anchor = None

    def start(self, position=0.0):
        self.started.append(position)

    def anchor(self):
        return self._anchor

    def pause(self):
        self.pauses += 1

    def resume(self):
        self.resumes += 1

    def stop(self):
        self.stops += 1

    alive = True

    @property
    def active(self):
        return self.alive


# -- wall clock -------------------------------------------------------------


def test_wall_clock_tracks_elapsed_time(fake_time):
    c = WallClock()
    c.start(0.0)
    assert c.now() == pytest.approx(0.0)
    fake_time.t += 2.5
    assert c.now() == pytest.approx(2.5)


def test_wall_clock_starts_from_a_position(fake_time):
    c = WallClock()
    c.start(30.0)
    fake_time.t += 1.0
    assert c.now() == pytest.approx(31.0)


def test_wall_clock_freezes_while_paused(fake_time):
    c = WallClock()
    c.start(0.0)
    fake_time.t += 1.0
    c.pause()
    assert c.paused
    fake_time.t += 100.0
    assert c.now() == pytest.approx(1.0), "a pause must not accrue debt"
    c.resume()
    fake_time.t += 0.5
    assert c.now() == pytest.approx(1.5)


def test_wall_clock_reports_its_source():
    assert WallClock().source == "wall"


# -- audio clock ------------------------------------------------------------


def test_audio_clock_follows_the_sink(fake_time):
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    assert sink.started == [0.0]

    sink.report(1.25)
    assert c.now() == pytest.approx(1.25)
    sink.report(3.5)
    assert c.now() == pytest.approx(3.5)
    assert c.source == "audio"


def test_audio_clock_holds_at_the_start_until_audio_actually_begins(fake_time):
    """Video must wait for the audio device to spin up, or they start misaligned."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)

    fake_time.t += 0.3  # audio still buffering, nothing reported
    assert c.now() == pytest.approx(0.0)

    sink.report(0.02)  # sound finally starts
    assert c.now() == pytest.approx(0.02)


def test_audio_clock_interpolates_between_reports(fake_time):
    """The sink reports every ~30ms; video asks every frame.

    Returning the last report verbatim would make the timeline a staircase with
    30ms steps -- most of a frame interval at 30fps. Interpolate instead.
    """
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(5.0)
    assert c.now() == pytest.approx(5.0)

    # Same report, time moving on: the clock must keep advancing smoothly.
    fake_time.t += 0.01
    assert c.now() == pytest.approx(5.01)
    fake_time.t += 0.01
    assert c.now() == pytest.approx(5.02)

    # A fresh report re-anchors without a jump when the device agrees with us.
    sink.report(5.02)
    assert c.now() == pytest.approx(5.02)


def test_a_new_report_re_anchors_and_corrects_drift(fake_time):
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(5.0)
    c.now()

    fake_time.t += 1.0
    assert c.now() == pytest.approx(6.0)

    # The device ran ahead of our extrapolation; follow the truth.
    sink.report(6.4)
    assert c.now() == pytest.approx(6.4)


def test_the_timeline_never_runs_backwards(fake_time):
    """A late report behind our extrapolation must stall, not rewind -- a
    rewind makes the player re-wait frames it has already shown."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(5.0)
    fake_time.t += 1.0
    assert c.now() == pytest.approx(6.0)

    sink.report(5.4)  # device is actually behind where we extrapolated
    assert c.now() == pytest.approx(6.0), "must hold, not rewind"

    fake_time.t += 1.0  # and catch up naturally from the corrected anchor
    assert c.now() == pytest.approx(6.4)


def test_audio_clock_falls_back_when_the_sink_never_reports(fake_time):
    """A silently broken sink must not freeze the video forever."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)

    fake_time.t += AudioClock.FALLBACK_AFTER - 0.01
    assert c.now() == pytest.approx(0.0)
    assert not c.fell_back

    fake_time.t += 0.02
    c.now()
    assert c.fell_back
    assert c.source == "wall*"


def test_a_dead_sink_falls_back_immediately(fake_time):
    """Waiting out the timeout for a sink that already exited just shows the
    viewer a frozen first frame for no reason."""
    sink = ScriptedSink()
    sink.alive = False
    c = AudioClock(sink)
    c.start(0.0)
    c.now()
    assert c.fell_back


def test_the_fallback_timeline_does_not_jump_forward(fake_time):
    """Falling back must not teleport playback past the whole timeout."""
    c = AudioClock(ScriptedSink())
    c.start(0.0)
    fake_time.t += AudioClock.FALLBACK_AFTER + 0.01
    first = c.now()
    assert first == pytest.approx(0.0, abs=0.05)

    fake_time.t += 1.0
    assert c.now() == pytest.approx(1.0, abs=0.05)


def test_once_fallen_back_the_sink_is_ignored(fake_time):
    """Otherwise a sink that wakes up late would yank the timeline backwards."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    fake_time.t += AudioClock.FALLBACK_AFTER + 0.1
    c.now()
    assert c.fell_back

    fake_time.t += 5.0
    sink.report(0.1)  # far behind where we are now
    assert c.now() > 4.0


def test_audio_clock_pause_and_resume_reach_the_sink(fake_time):
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(2.0)
    c.now()

    c.pause()
    assert sink.pauses == 1
    fake_time.t += 10.0
    assert c.now() == pytest.approx(2.0), "paused clock must not advance"

    c.resume()
    assert sink.resumes == 1
    assert c.now() == pytest.approx(2.0)


def test_audio_clock_resume_discards_the_stale_anchor(fake_time):
    """A pre-pause anchor would extrapolate through the whole pause."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(2.0)
    c.now()
    c.pause()
    fake_time.t += 30.0
    sink.silence()
    c.resume()
    assert c.now() == pytest.approx(2.0, abs=0.01)


def test_resume_does_not_restart_the_sink(fake_time):
    """Regression: Clock.resume() used to call self.start(), which dispatched to
    AudioClock.start() and relaunched the whole audio process on every pause --
    paying a fresh device startup latency and desyncing what we just paused."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(2.0)
    c.now()

    c.pause()
    c.resume()

    assert sink.started == [0.0], "resume must not re-seek or relaunch the sink"
    assert sink.resumes == 1


def test_a_stale_pre_pause_anchor_is_rejected(fake_time):
    """Regression: a sink that doesn't clear its own report on resume used to
    hand back a pre-pause observation, and the clock extrapolated straight
    through the entire pause."""
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    sink.report(2.0)
    c.now()

    c.pause()
    fake_time.t += 10.0
    c.resume()  # ScriptedSink deliberately keeps its stale anchor
    assert sink.anchor() is not None
    assert c.now() == pytest.approx(2.0), "must ignore an observation from before the pause"


def test_fallback_is_a_one_way_door(fake_time):
    """Regression: the fallback branch re-based the wall-clock origin on every
    call, pinning the timeline at the start position forever."""
    c = AudioClock(ScriptedSink())
    c.start(0.0)
    fake_time.t += AudioClock.FALLBACK_AFTER + 0.01
    c.now()
    assert c.fell_back

    fake_time.t += 1.0
    first = c.now()
    fake_time.t += 1.0
    assert c.now() == pytest.approx(first + 1.0)


def test_audio_clock_stop_reaches_the_sink(fake_time):
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    c.stop()
    assert sink.stops == 1


def test_restarting_re_seeks_the_sink(fake_time):
    sink = ScriptedSink()
    c = AudioClock(sink)
    c.start(0.0)
    c.start(45.0)
    assert sink.started == [0.0, 45.0]
    assert c.now() == pytest.approx(45.0)


# -- null sink --------------------------------------------------------------


def test_null_sink_reports_nothing():
    s = NullSink()
    s.start(1.0)
    assert s.anchor() is None
    assert not s.active
    s.pause(); s.resume(); s.stop()  # must not raise


# -- ffplay status parsing --------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"   2.34 M-A:  0.000 fd=   0 aq=   17KB vq=    0KB sq=    0B f=0/0   \r", "2.34"),
        (b"  12.07 A-V: -0.012 fd=   3 aq=    9KB vq=   12KB sq=    0B f=0/0   \r", "12.07"),
        (b"   0.00 M-V:  0.000 fd=   0 aq=    0KB vq=    0KB sq=    0B f=0/0   \r", "0.00"),
    ],
)
def test_status_line_parsing(line, expected):
    m = _STATUS_RE.findall(line)
    assert m and m[-1].decode() == expected


def test_status_regex_ignores_ordinary_log_lines():
    noise = b"[mp3 @ 0x14f00] Estimating duration from bitrate, this may be inaccurate\n"
    assert not _STATUS_RE.findall(noise)


def test_status_regex_takes_the_most_recent_of_a_batch():
    """ffplay overwrites with \\r, so one read can hold several updates."""
    chunk = (
        b"   1.00 M-A:  0.000 fd=0 aq=1KB vq=0KB sq=0B f=0/0   \r"
        b"   1.03 M-A:  0.000 fd=0 aq=1KB vq=0KB sq=0B f=0/0   \r"
        b"   1.06 M-A:  0.000 fd=0 aq=1KB vq=0KB sq=0B f=0/0   \r"
    )
    assert _STATUS_RE.findall(chunk)[-1] == b"1.06"


# -- ffplay sink ------------------------------------------------------------


def test_ffplay_command_shape(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    cmd = FFplaySink("clip.mp4", volume=60)._command(0.0)
    assert "-nodisp" in cmd, "must not try to open a window"
    assert "-autoexit" in cmd, "must quit at end of stream"
    assert "-vn" in cmd, "decoding video we never show wastes real CPU"
    assert cmd[cmd.index("-volume") + 1] == "60"
    assert "-ss" not in cmd


def test_ffplay_command_seeks(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    cmd = FFplaySink("clip.mp4")._command(31.25)
    assert cmd[cmd.index("-ss") + 1] == "31.250"
    assert cmd.index("-ss") < cmd.index("-i")


def test_ffplay_volume_is_clamped(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    assert FFplaySink("x", volume=500).volume == 100
    assert FFplaySink("x", volume=-5).volume == 0


def test_ffplay_position_is_offset_by_the_seek(monkeypatch):
    """ffplay reports time from its seek point, not from the top of the file."""
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    sink = FFplaySink("clip.mp4")
    sink._offset = 60.0
    import time as real_time

    sink._report = (2.0 + sink._offset, real_time.perf_counter())
    assert sink.anchor()[0] == pytest.approx(62.0)


def test_ffplay_stale_reports_are_discarded(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    sink = FFplaySink("clip.mp4")
    import time as real_time

    sink._report = (5.0, real_time.perf_counter() - 30.0)
    assert sink.anchor() is None, "a wedged process must not pin the timeline"


def test_ffplay_reports_nothing_while_paused(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    sink = FFplaySink("clip.mp4")
    import time as real_time

    sink._report = (5.0, real_time.perf_counter())
    sink._paused = True
    assert sink.anchor() is None


# -- backend selection ------------------------------------------------------


def audio_info(has_audio=True):
    return MediaInfo(title="x", fps=30.0, has_audio=has_audio)


def test_no_audio_flag_gives_a_wall_clock():
    c = audio_mod.make_clock("clip.mp4", audio_info(), enabled=False)
    assert isinstance(c, WallClock) and not isinstance(c, AudioClock)


def test_a_file_without_an_audio_track_gives_a_wall_clock():
    c = audio_mod.make_clock("clip.mp4", audio_info(has_audio=False))
    assert not isinstance(c, AudioClock)


def test_generated_patterns_never_get_audio():
    assert not isinstance(audio_mod.make_clock(None, audio_info()), AudioClock)


def test_stdin_never_gets_audio():
    """ffplay can't share our stdin, and there is no file for it to open."""
    assert not isinstance(audio_mod.make_clock("-", audio_info()), AudioClock)


def test_backend_none_gives_a_wall_clock():
    c = audio_mod.make_clock("clip.mp4", audio_info(), backend="none")
    assert not isinstance(c, AudioClock)


def test_missing_ffplay_degrades_to_a_wall_clock(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: None)
    c = audio_mod.make_clock("clip.mp4", audio_info())
    assert not isinstance(c, AudioClock)


def test_ffplay_is_used_when_available(monkeypatch):
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: "/bin/ffplay")
    c = audio_mod.make_clock("clip.mp4", audio_info())
    assert isinstance(c, AudioClock)
    assert isinstance(c.sink, FFplaySink)
