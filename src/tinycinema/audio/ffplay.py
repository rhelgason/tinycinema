"""Audio playback via an ffplay subprocess.

ffplay ships with ffmpeg, which is already a hard requirement, so this costs no
new dependency -- that is the entire reason it is the first backend. It is not
the *best* backend: decoding to raw PCM and feeding an audio device ourselves
would give a sample-accurate position, but it needs a PortAudio binding.

Getting a position out of ffplay is the interesting part. It has no IPC, but it
prints a status line to stderr roughly every 30ms:

    2.34 M-A:  0.000 fd=   0 aq=   17KB vq=    0KB sq=    0B f=0/0

The leading float is its master clock, which for an audio-only stream *is* the
audio playback position. Parsing a human-readable progress line is admittedly
fragile, so the design makes it safe to fail: if nothing parses within a couple
of seconds, AudioClock quietly falls back to the wall clock and playback carries
on un-synced rather than freezing. Degrading to Phase 1 behaviour is a fine
worst case.

Note the `\\r`: ffplay overwrites the line in place rather than emitting newlines,
so this reads fixed-size chunks and regex-scans them instead of using readline(),
which would block until the process exited.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time

from ..binaries import ffplay_path
from ..log import note

#: "   2.34 M-A:  0.000 fd=..." -- the sync marker is A-V, M-V or M-A depending
#: on which streams exist, so match the shape rather than a literal.
_STATUS_RE = re.compile(rb"(\d+\.\d+)\s+[A-Z]-[A-Z]:")

#: Reports older than this are stale (the process wedged, or was stopped).
_REPORT_TTL = 1.0

#: How far the first post-resume report may sit from where we paused before we
#: conclude the process did not keep its clock across the stop. Generous, so an
#: ordinary report interval never trips it.
_RESUME_TOLERANCE = 0.5


class FFplaySink:
    """Plays a file's audio and reports where it has got to."""

    def __init__(self, target: str, *, volume: int = 100, loop: bool = False) -> None:
        self.target = target
        self.volume = max(0, min(100, volume))
        self.loop = loop
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        #: (media position, perf_counter when observed). Assigned as a whole
        #: tuple so the reader thread and the player never see a torn value.
        self._report: tuple[float, float] | None = None
        self._paused = False
        self._offset = 0.0
        self._paused_position = 0.0
        #: (position we paused at, perf_counter when we resumed). Used to check
        #: whether SIGCONT actually preserved the clock. None when not resuming.
        self._resume_check: tuple[float, float] | None = None

    # -- lifecycle ---------------------------------------------------------

    @staticmethod
    def available() -> bool:
        return ffplay_path() is not None

    def _command(self, position: float) -> list[str]:
        exe = ffplay_path()
        assert exe is not None
        cmd = [
            exe,
            "-hide_banner",
            "-nodisp",       # no SDL window
            "-autoexit",     # quit at end of stream
            "-vn", "-sn",    # skip video and subtitles entirely; saves real CPU
            "-loglevel", "info",  # the status line is logged at INFO
            "-volume", str(self.volume),
        ]  # fmt: skip
        if self.loop:
            cmd += ["-loop", "0"]
        if position > 0:
            cmd += ["-ss", f"{position:.3f}"]
        cmd += ["-i", self.target]
        return cmd

    def start(self, position: float = 0.0) -> None:
        self.stop()
        self._report = None
        self._paused = False
        self._resume_check = None
        self._paused_position = position
        # ffplay reports time from the seek point, not from zero.
        self._offset = position
        cmd = self._command(position)
        note("ffplay " + " ".join(cmd[1:]))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,  # never let it eat our keystrokes
                bufsize=0,
            )
        except OSError:
            self._proc = None
            return
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        fd = proc.stderr.fileno()
        buf = b""
        while True:
            try:
                chunk = os.read(fd, 4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            buf = buf[-64:] + chunk  # keep a little tail for split status lines
            matches = _STATUS_RE.findall(buf)
            if matches:
                try:
                    reported = float(matches[-1])  # most recent wins
                except ValueError:
                    continue
                self._report = (reported + self._offset, time.perf_counter())

    # -- clock -------------------------------------------------------------

    def anchor(self) -> tuple[float, float] | None:
        """The last observed position, paired with when we observed it."""
        if self._paused:
            return None
        report = self._report
        if report is None:
            return None
        if time.perf_counter() - report[1] > _REPORT_TTL:
            # ffplay stopped talking; let the clock coast on the old anchor
            # rather than re-anchoring to something stale.
            return None

        if self._resume_check is not None:
            paused_at, resumed_when = self._resume_check
            # Compare against where playback *should* be by now, not against
            # where it was when we paused: the device has legitimately been
            # running since resume, and however long the caller took to ask is
            # time it was entitled to advance by.
            expected = paused_at + (time.perf_counter() - resumed_when)
            self._resume_check = None
            if abs(report[0] - expected) > _RESUME_TOLERANCE:
                # SIGCONT did not preserve the clock -- the process caught its
                # timeline up to wall time while it was stopped, so resuming
                # would silently skip however long the pause lasted. Whether a
                # given ffmpeg build behaves this way is not something we can
                # know in advance, so detect it and fall back to a clean
                # restart at the right position.
                note(
                    f"ffplay drifted {report[0] - expected:+.1f}s across the pause; "
                    "restarting it in the right place"
                )
                self.start(expected)
                return None
        return report

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- transport ---------------------------------------------------------

    def pause(self) -> None:
        """SIGSTOP rather than a restart: ffplay has no IPC, and restarting on
        every pause would cost a few hundred ms of startup each time."""
        if self._paused or not self.active:
            self._paused = True
            return
        self._paused = True
        # Remember where we stopped; resume() stamps the time so anchor() can
        # tell whether the process kept its clock while it was stopped.
        self._paused_position = self._report[0] if self._report else self._offset
        try:
            self._proc.send_signal(signal.SIGSTOP)  # type: ignore[union-attr]
        except (OSError, AttributeError, ValueError):
            pass

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self._report = None  # anything from before the pause is stale
        if not self.active:
            self._resume_check = None
            return
        self._resume_check = (self._paused_position, time.perf_counter())
        try:
            self._proc.send_signal(signal.SIGCONT)  # type: ignore[union-attr]
        except (OSError, AttributeError, ValueError):
            pass

    def set_volume(self, volume: int) -> None:
        """ffplay takes its volume at launch and offers no way to change it.

        So relaunch at the current position. That costs a short gap in the
        sound, which is why the player debounces rapid adjustments into one
        restart rather than one per keypress.
        """
        volume = max(0, min(100, volume))
        if volume == self.volume:
            return
        self.volume = volume
        if self._proc is None:
            return
        resume_from = self._report[0] if self._report else self._offset
        self.start(resume_from)

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self._report = None
        self._paused = False
        if proc is None:
            return
        if proc.poll() is None:
            # A stopped process ignores SIGTERM, so wake it first or we hang.
            try:
                proc.send_signal(signal.SIGCONT)
            except (OSError, ValueError):
                pass
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        try:
            if proc.stderr is not None:
                proc.stderr.close()
        except (OSError, ValueError):
            pass
        self._reader = None
