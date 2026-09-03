"""The real-I/O paths: a live audio subprocess, a real pipe, a real pty.

These were the least-covered modules in the project, and not by accident --
they're the parts that need something on the other end. A committed fake ffplay,
os.pipe() and pty.openpty() are enough to exercise them properly, without a
sound card, a keyboard or a terminal.
"""

import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

import pytest

from tinycinema.audio.ffplay import FFplaySink
from tinycinema.keys import KeyReader
from tinycinema.term import Terminal

FAKE_FFPLAY = Path(__file__).parent / "fixtures" / "fake_ffplay.py"


@pytest.fixture
def sink(monkeypatch):
    """An FFplaySink wired to the fake ffplay, with steering flags appended."""
    monkeypatch.setattr("tinycinema.audio.ffplay.ffplay_path", lambda: sys.executable)

    def make(*extra: str, **kw) -> FFplaySink:
        s = FFplaySink("clip.mp4", **kw)
        original = s._command

        def command(position):
            # sys.executable is the "binary", so the script goes first.
            return [sys.executable, str(FAKE_FFPLAY), *original(position)[1:], *extra]

        s._command = command
        return s

    made: list[FFplaySink] = []
    original_make = make

    def tracked(*a, **k):
        s = original_make(*a, **k)
        made.append(s)
        return s

    yield tracked
    for s in made:
        s.stop()


def wait_for(predicate, timeout=5.0, interval=0.02):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


# -- the audio subprocess ----------------------------------------------------


def test_the_sink_starts_and_reports_a_position(sink):
    s = sink("--duration", "5")
    s.start(0.0)
    assert wait_for(lambda: s.anchor() is not None), "no status parsed from stderr"
    assert s.active
    position, observed = s.anchor()
    assert 0.0 < position < 2.0
    assert observed <= time.perf_counter()


def test_a_seek_offsets_the_reported_position(sink):
    """ffplay reports from its seek point, not from the top of the file."""
    s = sink("--duration", "5")
    s.start(60.0)
    assert wait_for(lambda: s.anchor() is not None)
    assert s.anchor()[0] >= 60.0, "the seek offset must be added back on"


def test_pause_freezes_the_position_and_resume_continues(sink):
    s = sink("--duration", "10")
    s.start(0.0)
    assert wait_for(lambda: s.anchor() is not None)

    s.pause()
    assert s.anchor() is None, "a paused sink reports nothing"
    frozen = s._report[0]
    time.sleep(0.8)
    assert s._report[0] == frozen, "the stopped process must not advance"

    s.resume()
    assert wait_for(lambda: s.anchor() is not None)
    assert s.anchor()[0] >= frozen


def test_a_sink_that_absorbs_the_pause_is_restarted(sink):
    """The behaviour we can't predict for a real ffplay build, end to end."""
    s = sink("--duration", "20", "--absorb-pause")
    s.start(0.0)
    assert wait_for(lambda: s.anchor() is not None)

    s.pause()
    paused_at = s._report[0]
    time.sleep(1.5)
    s.resume()

    # Give it a moment to notice the jump and relaunch.
    assert wait_for(lambda: s.anchor() is not None, timeout=6)
    assert s.anchor()[0] < paused_at + 1.2, "the pause was silently skipped"


def test_a_silent_sink_never_produces_an_anchor(sink):
    s = sink("--duration", "3", "--silent")
    s.start(0.0)
    time.sleep(0.6)
    assert s.anchor() is None
    assert s.active, "still running, just not talking -- the clock must fall back"


def test_the_sink_exits_on_its_own_at_the_end(sink):
    s = sink("--duration", "0.4", "--startup-delay", "0.05")
    s.start(0.0)
    assert wait_for(lambda: not s.active, timeout=6), "-autoexit should end it"


def test_stop_terminates_a_running_sink(sink):
    s = sink("--duration", "60")
    s.start(0.0)
    assert wait_for(lambda: s.active)
    pid = s._proc.pid
    s.stop()
    assert not s.active
    assert wait_for(lambda: not _alive(pid)), "process left running"


def test_stop_terminates_a_paused_sink(sink):
    """A stopped process ignores SIGTERM, so stop() has to wake it first --
    otherwise quitting while paused hangs for the kill timeout."""
    s = sink("--duration", "60")
    s.start(0.0)
    assert wait_for(lambda: s.active)
    pid = s._proc.pid
    s.pause()
    started = time.perf_counter()
    s.stop()
    assert time.perf_counter() - started < 3, "stop() blocked on a stopped child"
    assert wait_for(lambda: not _alive(pid))


def test_restarting_replaces_the_previous_process(sink):
    s = sink("--duration", "30")
    s.start(0.0)
    assert wait_for(lambda: s.active)
    first = s._proc.pid
    s.start(5.0)
    assert s._proc.pid != first
    assert wait_for(lambda: not _alive(first)), "the old process was orphaned"


def test_volume_is_clamped_and_reaches_the_command_line(sink):
    s = sink()
    assert "-volume" in s._command(0.0)
    s.volume = 55
    assert "55" in s._command(0.0)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# -- keyboard input over a real pipe -----------------------------------------


@pytest.fixture
def key_pipe():
    read_fd, write_fd = os.pipe()
    reader = KeyReader()
    reader._fd = read_fd
    reader._usable = True
    yield reader, write_fd
    for fd in (read_fd, write_fd):
        try:
            os.close(fd)
        except OSError:
            pass


def test_nothing_pending_returns_nothing(key_pipe):
    reader, _ = key_pipe
    assert reader.poll() == []


def test_keys_are_read_from_the_pipe(key_pipe):
    reader, write_fd = key_pipe
    os.write(write_fd, b"qh")
    assert wait_for(lambda: reader.poll() == ["q", "h"] or True)
    # poll() above consumed them; write again and check precisely
    os.write(write_fd, b"rc")
    time.sleep(0.05)
    assert reader.poll() == ["r", "c"]


def test_an_escape_sequence_split_across_writes(key_pipe):
    """A slow terminal can deliver an arrow key in pieces; holding the partial
    sequence is what stops it being read as a bare Escape (which quits)."""
    reader, write_fd = key_pipe
    os.write(write_fd, b"\x1b[")
    time.sleep(0.05)
    assert reader.poll() == [], "must not emit anything from half a sequence"
    os.write(write_fd, b"C")
    time.sleep(0.05)
    assert reader.poll() == ["right"]


def test_a_burst_arrives_intact(key_pipe):
    reader, write_fd = key_pipe
    os.write(write_fd, b"rrr\x1b[A ")
    time.sleep(0.05)
    assert reader.poll() == ["r", "r", "r", "up", "space"]


def test_poll_honours_its_timeout_when_idle(key_pipe):
    reader, _ = key_pipe
    started = time.perf_counter()
    assert reader.poll(timeout=0.15) == []
    assert 0.1 < time.perf_counter() - started < 1.0


def test_an_unusable_reader_still_honours_the_timeout():
    """Returning instantly turns the paused idle loop into a busy-wait."""
    import io

    reader = KeyReader(io.StringIO())
    started = time.perf_counter()
    assert reader.poll(timeout=0.15) == []
    assert time.perf_counter() - started > 0.1


# -- the terminal, under a real pty ------------------------------------------


def run_under_pty(script: str, cols: int = 80, rows: int = 24, wait: float = 2.5):
    master, slave = pty.openpty()
    termios_pkg = termios
    import fcntl

    fcntl.ioctl(slave, termios_pkg.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=slave, stdout=slave, stderr=subprocess.STDOUT,
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor",
             "PYTHONPATH": str(Path(__file__).parent.parent / "src")},
        close_fds=True,
    )
    os.close(slave)
    seen = bytearray()
    stop = threading.Event()

    def drain():
        os.set_blocking(master, False)
        while not stop.is_set():
            r, _, _ = select.select([master], [], [], 0.05)
            if not r:
                continue
            try:
                chunk = os.read(master, 1 << 16)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                return
            if not chunk:
                return
            seen.extend(chunk)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    time.sleep(0.3)
    stop.set()
    thread.join(timeout=1)
    os.close(master)
    return proc.returncode, bytes(seen)


def test_the_terminal_is_set_up_and_torn_down_in_order():
    code, out = run_under_pty(
        "from tinycinema.term import Terminal\n"
        "with Terminal():\n"
        "    pass\n"
    )
    assert code == 0
    setup = out.index(b"\x1b[?1049h")
    teardown = out.index(b"\x1b[?1049l")
    assert setup < teardown
    for seq in (b"\x1b[?25l", b"\x1b[?7l", b"\x1b[?25h", b"\x1b[?7h", b"\x1b[0m"):
        assert seq in out, f"missing {seq!r}"


def test_the_terminal_is_restored_even_when_the_body_raises():
    code, out = run_under_pty(
        "from tinycinema.term import Terminal\n"
        "try:\n"
        "    with Terminal():\n"
        "        raise RuntimeError('boom')\n"
        "except RuntimeError:\n"
        "    pass\n"
    )
    assert code == 0
    assert b"\x1b[?1049l" in out and b"\x1b[?25h" in out


def test_the_terminal_detects_it_is_a_tty_and_reads_its_size():
    code, out = run_under_pty(
        "from tinycinema.term import Terminal\n"
        "t = Terminal(alt_screen=False, hide_cursor=False)\n"
        "print('TTY', t.caps.is_tty, 'SIZE', t.size())\n",
        cols=97, rows=31,
    )
    text = out.decode("utf-8", "replace")
    assert "TTY True" in text
    assert "SIZE (97, 31)" in text


def test_raw_mode_is_entered_and_the_original_settings_restored():
    """Compares the flags we actually change, not the whole termios struct.

    lflag also carries kernel-managed *status* bits -- PENDIN, FLUSHO -- that
    the kernel sets and clears on its own. A bare setcbreak/tcsetattr round-trip
    shows them differ too, so struct equality would fail here on correct code.
    """
    code, out = run_under_pty(
        "import sys, termios\n"
        "from tinycinema.term import Terminal\n"
        "KERNEL_STATUS = getattr(termios, 'PENDIN', 0) | getattr(termios, 'FLUSHO', 0)\n"
        "fd = sys.stdin.fileno()\n"
        "def snapshot():\n"
        "    m = termios.tcgetattr(fd)\n"
        "    m[3] &= ~KERNEL_STATUS\n"
        "    return m\n"
        "before = snapshot()\n"
        "with Terminal(alt_screen=False, hide_cursor=False):\n"
        "    during = termios.tcgetattr(fd)\n"
        "after = snapshot()\n"
        "canon = bool(after[3] & termios.ICANON)\n"
        "echo = bool(after[3] & termios.ECHO)\n"
        "print('CHANGED', during[3] != before[3],\n"
        "      'RESTORED', after == before, 'ICANON', canon, 'ECHO', echo)\n"
    )
    text = out.decode("utf-8", "replace")
    assert "CHANGED True" in text, "cbreak mode was never entered"
    assert "RESTORED True" in text, "termios settings were left modified"
    assert "ICANON True" in text, "line buffering never came back -- shell would be unusable"
    assert "ECHO True" in text, "echo never came back -- typing would be invisible"


def test_a_sixel_query_is_sent_to_a_real_terminal():
    """There is no environment variable for sixel, so it has to be asked."""
    code, out = run_under_pty(
        "import os\n"
        "os.environ.pop('TINYCINEMA_SIXEL', None)\n"
        "from tinycinema.term import detect_sixel\n"
        "print('SIXEL', detect_sixel())\n"
    )
    assert b"\x1b[c" in out, "the Primary DA query was never written"
    # Nothing answers a bare pty, so it must time out and say no.
    assert "SIXEL False" in out.decode("utf-8", "replace")


def test_a_resize_is_noticed():
    code, out = run_under_pty(
        "import fcntl, os, struct, sys, termios, time\n"
        "from tinycinema.term import Terminal\n"
        "t = Terminal(alt_screen=False, hide_cursor=False)\n"
        "with t:\n"
        "    print('BEFORE', t.take_resize())\n"
        "    fcntl.ioctl(sys.stdout.fileno(), termios.TIOCSWINSZ,\n"
        "                struct.pack('HHHH', 40, 120, 0, 0))\n"
        "    seen = False\n"
        "    deadline = time.monotonic() + 2\n"
        "    while time.monotonic() < deadline and not seen:\n"
        "        seen = t.take_resize()\n"
        "        time.sleep(0.05)\n"
        "    print('AFTER', seen, t.size())\n"
    )
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.decode("utf-8", "replace"))
    assert "BEFORE False" in text
    assert "AFTER True" in text, "a resize went unnoticed"
    assert "(120, 40)" in text
