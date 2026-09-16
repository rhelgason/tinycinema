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

import contextlib
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
        self._state_lock = threading.Lock()
        self._paused = False
        self._offset = 0.0
        self._paused_position = 0.0

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
        self._reader = threading.Thread(
            target=self._pump, args=(self._proc, self._offset), daemon=True
        )
        self._reader.start()

    def _pump(self, proc: subprocess.Popen, offset: float) -> None:
        """Read one process's status lines. Bound to that process on purpose.

        A volume change restarts ffplay, and the pump for the old one is still
        blocked in read() when the new one launches. Once the old pipe is
        closed its descriptor number is free to be reused -- by the new
        process's stderr -- so a pump that trusted `self` would read the new
        process's output, steal bytes from the live pump, and stamp them with
        the old seek offset. Hold the process and offset we were started with,
        and never publish once superseded.
        """
        if proc.stderr is None:
            return
        fd = proc.stderr.fileno()
        buf = b""
        while self._proc is proc:
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
                with self._state_lock:
                    if self._proc is proc and not self._paused:
                        self._report = (reported + offset, time.perf_counter())

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
        return report

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # -- transport ---------------------------------------------------------

    def pause(self) -> None:
        """Kill ffplay rather than SIGSTOP.

        SIGSTOP freezes the process but not the audio device: CoreAudio keeps
        looping the last buffer, which sounds like the same sample hiccuping a
        few times before it dies. Tearing the process down actually stops the
        sound. Resume relaunches at the paused position -- a short gap, the
        same trade volume changes already make.
        """
        if self._paused:
            return
        with self._state_lock:
            self._paused = True
            self._paused_position = self._report[0] if self._report else self._offset
            self._report = None
        self._kill_proc()

    def resume(self) -> None:
        if not self._paused:
            return
        position = self._paused_position
        self._paused = False
        self.start(position)

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
        self._paused = False
        self._report = None
        self._kill_proc()

    def _kill_proc(self) -> None:
        proc, self._proc = self._proc, None
        self._reader = None
        if proc is None:
            return
        if proc.poll() is None:
            # In case an older pause left it SIGSTOPped, wake it so SIGTERM lands.
            with contextlib.suppress(OSError, ValueError):
                proc.send_signal(signal.SIGCONT)
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=1.0)
        with contextlib.suppress(OSError, ValueError):
            if proc.stderr is not None:
                proc.stderr.close()
