"""Shutdown, signals, and the stream plumbing that can hang.

The subprocess paths were the least-covered code in the project, and they are
exactly where the design notes said the silent hangs live: short reads on a
pipe, a full stderr buffer, a stopped child ignoring SIGTERM. None of that needs
a real ffmpeg -- a pipe and a stub process are enough.
"""

import os
import signal
import subprocess
import threading
import time

import pytest

from tinycinema.sources.ffmpeg import FFmpegSource, _read_exactly
from tinycinema.term import FATAL_SIGNALS, Terminal, Terminated


# -- fatal signals -----------------------------------------------------------


def test_terminated_reports_the_conventional_status():
    assert Terminated(signal.SIGTERM).exit_status == 143
    assert Terminated(signal.SIGHUP).exit_status == 129


def test_terminated_is_not_swallowed_by_except_exception():
    """A stray `except Exception` must not eat a shutdown request, which is why
    this subclasses BaseException the way KeyboardInterrupt does."""
    assert not issubclass(Terminated, Exception)
    assert issubclass(Terminated, BaseException)


def test_sigint_is_left_alone():
    """Python already turns it into KeyboardInterrupt; overriding would only
    make ctrl-c behave differently from every other program."""
    assert "SIGINT" not in FATAL_SIGNALS


def test_the_handler_raises_rather_than_cleaning_up_inline():
    """Raising lets every existing `finally` run -- restoring the terminal and,
    crucially, terminating ffmpeg and ffplay instead of orphaning them."""
    term = Terminal(alt_screen=False, hide_cursor=False)
    with pytest.raises(Terminated) as exc:
        term._on_fatal(signal.SIGTERM, None)
    assert exc.value.signum == signal.SIGTERM


def test_handlers_are_installed_and_then_restored():
    original = {getattr(signal, n): signal.getsignal(getattr(signal, n))
                for n in FATAL_SIGNALS if hasattr(signal, n)}
    term = Terminal(alt_screen=False, hide_cursor=False)
    with term:
        for sig in original:
            assert signal.getsignal(sig) == term._on_fatal
    for sig, previous in original.items():
        assert signal.getsignal(sig) == previous, "must not leak handlers"


# -- reading frames off a pipe ----------------------------------------------


class ChunkedStream:
    """A stream that hands back short reads, the way a real pipe does."""

    def __init__(self, data: bytes, chunk: int):
        self.data = data
        self.chunk = chunk
        self.pos = 0
        self.reads = 0

    def read(self, n):
        self.reads += 1
        take = min(n, self.chunk, len(self.data) - self.pos)
        out = self.data[self.pos : self.pos + take]
        self.pos += take
        return out


def test_a_whole_frame_is_assembled_from_short_reads():
    """The classic pipe bug: assuming read(n) returns n bytes."""
    payload = bytes(range(256)) * 40  # 10240 bytes
    stream = ChunkedStream(payload, chunk=97)
    got = _read_exactly(stream, len(payload))
    assert got == payload
    assert stream.reads > 1, "the test is pointless if it came back in one read"


def test_a_single_read_is_not_copied_needlessly():
    stream = ChunkedStream(b"abcd", chunk=4)
    assert _read_exactly(stream, 4) == b"abcd"


def test_eof_partway_through_a_frame_returns_none():
    """A truncated trailing frame must be discarded, not rendered as garbage."""
    stream = ChunkedStream(b"abc", chunk=2)
    assert _read_exactly(stream, 10) is None


def test_a_closed_stream_returns_none():
    class Closed:
        def read(self, n):
            raise ValueError("I/O operation on closed file")

    assert _read_exactly(Closed(), 10) is None


def test_reading_a_real_pipe():
    read_fd, write_fd = os.pipe()
    payload = os.urandom(9000)

    def feed():
        with os.fdopen(write_fd, "wb") as w:
            for i in range(0, len(payload), 512):
                w.write(payload[i : i + 512])
                w.flush()
                time.sleep(0.001)

    threading.Thread(target=feed, daemon=True).start()
    with os.fdopen(read_fd, "rb", buffering=0) as r:
        assert _read_exactly(r, len(payload)) == payload


# -- subprocess teardown -----------------------------------------------------


def make_source(monkeypatch) -> FFmpegSource:
    monkeypatch.setattr("tinycinema.sources.ffmpeg.require_ffmpeg", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(
        "tinycinema.sources.ffmpeg.probe",
        lambda t: __import__("tinycinema.sources.base", fromlist=["MediaInfo"]).MediaInfo(
            title="x", fps=30.0
        ),
    )
    return FFmpegSource("clip.mp4")


def test_close_on_a_never_opened_source_is_harmless(monkeypatch):
    make_source(monkeypatch).close()  # must not raise


def test_close_is_idempotent(monkeypatch):
    src = make_source(monkeypatch)
    src.close()
    src.close()


def test_close_terminates_a_live_child(monkeypatch):
    src = make_source(monkeypatch)
    # `cat` with no input sits forever, like ffmpeg waiting on a slow pipe.
    src._proc = subprocess.Popen(
        ["cat"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    pid = src._proc.pid
    src.close()
    # Reaped, not merely signalled: an unreaped child is a zombie.
    with pytest.raises(OSError):
        os.kill(pid, 0)


def test_close_kills_a_child_that_ignores_terminate(monkeypatch):
    """A stopped or wedged process must not hang us forever."""
    src = make_source(monkeypatch)
    src._proc = subprocess.Popen(
        ["python3", "-c", "import signal,time\n"
         "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
         "time.sleep(60)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    pid = src._proc.pid
    started = time.perf_counter()
    src.close()
    assert time.perf_counter() - started < 4, "close() must not block indefinitely"
    with pytest.raises(OSError):
        os.kill(pid, 0)


def test_stderr_is_drained_so_a_chatty_child_cannot_deadlock(monkeypatch):
    """A full stderr pipe blocks the writer. ffmpeg is chatty; this is a real
    hang, not a theoretical one."""
    src = make_source(monkeypatch)
    noise = "x" * 200
    src._proc = subprocess.Popen(
        ["python3", "-c",
         f"import sys\nfor i in range(2000): sys.stderr.write('{noise}\\n')\n"
         "sys.stderr.flush()"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    src._drain_stderr()
    assert src._proc.wait(timeout=10) == 0, "child deadlocked on a full stderr pipe"
    src.close()


def test_only_the_stderr_tail_is_kept(monkeypatch):
    """Unbounded retention would grow without limit on a long, noisy decode."""
    src = make_source(monkeypatch)
    src._proc = subprocess.Popen(
        ["python3", "-c",
         "import sys\nfor i in range(500): sys.stderr.write(f'line{i}\\n')\nsys.stderr.flush()"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    src._drain_stderr()
    src._proc.wait(timeout=10)
    if src._stderr_thread:
        src._stderr_thread.join(timeout=2)
    assert len(src._stderr_tail) <= 25
    assert "line499" in src.error_message(), "the tail should be the most recent lines"
    src.close()
