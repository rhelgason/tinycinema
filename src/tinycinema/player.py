"""The playback loop -- decode, time, render, paint.

The loop asks the clock one question per frame ("what time is it in this
movie?") and everything follows from the answer. That clock is the audio
device's real playback position when there is audio, and elapsed wall time when
there isn't; the loop cannot tell the difference and doesn't need to.

The rule that makes playback feel right: never accumulate debt. If we are behind
the clock, drop the frame and move on. Rendering every frame late is far worse
than rendering most frames on time.

Restarting the pipeline is how every size- or position-change is handled, but
audio is deliberately *not* restarted for a resize or a mode switch -- only a
seek does that. Tearing down the audio device because someone dragged their
window corner would be an audible click for no reason.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from . import render as render_mod
from .audio import Clock, WallClock
from .keys import KeyReader
from .render import RenderOptions
from .sources import FrameSource
from .term import DEFAULT, CellGrid, FrameWriter, PlainWriter, Terminal

Restart = Literal["quit", "eof", "resize", "reopen", "seek"]

#: Restart reasons that only change the *picture*, so audio keeps playing.
VIDEO_ONLY_RESTARTS = ("resize", "reopen")

#: Behind by more than this many frame intervals -> drop rather than render late.
DROP_AFTER_FRAMES = 1.5

SEEK_SMALL = 5.0
SEEK_MEDIUM = 10.0
SEEK_LARGE = 60.0

_HUD_FG = (200, 200, 200)
_HUD_BG = (24, 24, 32)


@dataclass
class PlaybackOptions:
    mode: str = "halfblock"
    render: RenderOptions = field(default_factory=RenderOptions)
    fps: float | None = None
    hud: bool = True
    loop: bool = False
    start: float = 0.0
    once: bool = False
    stats: bool = False
    width: int | None = None
    height: int | None = None
    audio: bool = True


@dataclass
class Stats:
    rendered: int = 0
    dropped: int = 0
    reopens: int = 0
    elapsed: float = 0.0
    bytes_written: int = 0

    @property
    def fps(self) -> float:
        return self.rendered / self.elapsed if self.elapsed > 0 else 0.0


class Player:
    def __init__(
        self,
        source: FrameSource,
        terminal: Terminal,
        opts: PlaybackOptions,
        clock: Clock | None = None,
    ):
        self.source = source
        self.term = terminal
        self.opts = opts
        self.clock = clock if clock is not None else WallClock()
        self.stats = Stats()

        self.is_tty = terminal.caps.is_tty
        self.writer = FrameWriter() if self.is_tty else PlainWriter()
        self.keys = KeyReader()
        self.renderer = render_mod.create(opts.mode, opts.render)

        self._position = max(0.0, opts.start)
        self._paused = False
        self._recent = deque(maxlen=30)  # draw timestamps, for the live fps read-out
        self._pending_keys: deque[str] = deque()
        #: Should the next pipeline restart also restart audio? True on the
        #: first pass and after a seek; False for resize/mode changes.
        self._restart_audio = True
        self._message = ""
        self._message_until = 0.0

    # -- public ------------------------------------------------------------

    def run(self) -> int:
        started = time.perf_counter()
        try:
            while True:
                reason = self._play_once()
                if reason in ("quit", "eof"):
                    if reason == "eof" and self.opts.loop and not self.opts.once:
                        self._position = 0.0
                        self._restart_audio = True
                        continue
                    break
                # Only a seek moves the audio; a resize or mode switch rebuilds
                # the picture around audio that never stopped playing.
                self._restart_audio = reason not in VIDEO_ONLY_RESTARTS
                self.stats.reopens += 1
        finally:
            self.clock.stop()
            self.source.close()
            self.stats.elapsed = time.perf_counter() - started
            self.stats.bytes_written = self.writer.bytes_written
        return 0

    # -- one pipeline lifetime ---------------------------------------------

    def _play_once(self) -> Restart:
        cols, rows = self._grid_size()
        video_rows = rows - (1 if self._hud_enabled else 0)
        if video_rows < 1:
            video_rows = rows
        px_w, px_h = self.renderer.pixel_size(cols, video_rows)

        if self._restart_audio:
            self.clock.start(self._position)
            self._restart_audio = False
        else:
            # Audio kept playing through the restart, so pick the video up
            # wherever it has got to rather than where the old pipeline stopped.
            self._position = self.clock.now()

        frames = self.source.open(
            px_w, px_h, start=self._position, pixel_aspect=self.renderer.pixel_aspect
        )
        self.writer.invalidate()
        frame_interval = 1.0 / max(self.source.info.fps, 1.0)
        drop_threshold = DROP_AFTER_FRAMES * frame_interval

        for pts, rgb in frames:
            action = self._handle_keys()
            if action is not None:
                return action
            if self.term.take_resize():
                self._position = pts
                return "resize"

            if self._paused:
                # Repaint (the HUD needs updating) then idle until something happens.
                self._paint(rgb, pts, cols, rows, video_rows)
                action = self._wait_while_paused()
                if action is not None:
                    self._position = pts
                    return action

            lag = self.clock.now() - pts

            if lag > drop_threshold and not self.opts.once:
                self.stats.dropped += 1
                self._position = pts
                continue
            if lag < 0:
                # Ahead of the clock. Sleeping on wall time is right even when
                # the clock is the audio device: we only need to not paint yet.
                _sleep_for(-lag)

            self._paint(rgb, pts, cols, rows, video_rows)
            self._position = pts

            if self.opts.once:
                return "quit"

        return "eof"

    # -- painting ----------------------------------------------------------

    def _paint(self, rgb, pts: float, cols: int, rows: int, video_rows: int) -> None:
        grid = self.renderer.render(rgb)
        if self._hud_enabled and video_rows < rows:
            grid = self._compose_hud(grid, pts, cols, rows, video_rows)
        self.writer.draw(grid)
        self.stats.rendered += 1
        self._recent.append(time.perf_counter())

    def _compose_hud(
        self, video: CellGrid, pts: float, cols: int, rows: int, video_rows: int
    ) -> CellGrid:
        full = CellGrid.blank(rows, cols)
        vr = min(video_rows, video.shape[0])
        vc = min(cols, video.shape[1])
        full.chars[:vr, :vc] = video.chars[:vr, :vc]
        full.fg[:vr, :vc] = video.fg[:vr, :vc]
        full.bg[:vr, :vc] = video.bg[:vr, :vc]
        _blit(full, rows - 1, 0, self._hud_text(pts, cols), _HUD_FG, _HUD_BG)
        return full

    def _hud_text(self, pts: float, cols: int) -> str:
        if self._message and time.perf_counter() < self._message_until:
            left = self._message
        else:
            state = "||" if self._paused else "|>"
            title = self.source.info.title
            left = f"{state} {title}"

        duration = self.source.info.duration
        clock = _fmt_time(pts) + (f" / {_fmt_time(duration)}" if duration else "")
        right = f"{clock}  {self._live_fps():.0f}fps"
        if self.stats.dropped:
            right += f"  {self.stats.dropped} drop"
        # Which clock is driving matters when sync looks wrong, so surface it.
        right += f"  {self.renderer.name}  {self.clock.source}"

        space = cols - len(right) - 2
        if duration and space > 24:
            label = _truncate(left, max(space // 2, 8))
            bar_w = space - len(label) - 1
            filled = int(bar_w * min(pts / duration, 1.0))
            left = f"{label} " + "━" * filled + "─" * max(bar_w - filled, 0)
        else:
            left = _truncate(left, max(space, 0))

        gap = max(cols - len(left) - len(right), 1)
        return (left + " " * gap + right)[:cols].ljust(cols)

    def _live_fps(self) -> float:
        if len(self._recent) < 2:
            return 0.0
        span = self._recent[-1] - self._recent[0]
        return (len(self._recent) - 1) / span if span > 0 else 0.0

    # -- input -------------------------------------------------------------

    @property
    def _hud_enabled(self) -> bool:
        return self.opts.hud and self.is_tty and not self.opts.once

    def _handle_keys(self, timeout: float = 0.0) -> Restart | None:
        """Apply queued keys, stopping at the first that needs a pipeline restart.

        Keys behind that one stay queued. Returning early used to discard them,
        so pressing `r` three times to skip forward two render modes only ever
        advanced one.
        """
        pending = self._pending_keys
        if not pending:
            pending.extend(self.keys.poll(timeout))
        while pending:
            action = self._apply_key(pending.popleft())
            if action is not None:
                return action
        return None

    def _apply_key(self, key: str) -> Restart | None:
        if key in ("q", "Q", "ctrl-c", "escape"):
            return "quit"
        if key in ("space", "k"):
            self._paused = not self._paused
            if self._paused:
                self.clock.pause()
            else:
                self.clock.resume()
            return None
        if key == "h":
            self.opts.hud = not self.opts.hud
            self.writer.invalidate()
            return "reopen"  # the video area changes height
        if key == "c":
            self.opts.render.color = not self.opts.render.color
            self._notify(f"color {'on' if self.opts.render.color else 'off'}")
            self.writer.invalidate()
            return None
        if key == "r":
            return self._cycle_mode(+1)
        if key == "R":
            return self._cycle_mode(-1)
        if key in ("left", "right", "up", "down", "j", "l"):
            delta = {
                "left": -SEEK_SMALL,
                "right": SEEK_SMALL,
                "down": -SEEK_LARGE,
                "up": SEEK_LARGE,
                "j": -SEEK_MEDIUM,
                "l": SEEK_MEDIUM,
            }[key]
            return self._seek(delta)
        return None

    def _cycle_mode(self, step: int) -> Restart:
        modes = render_mod.available_modes()
        i = (modes.index(self.renderer.name) + step) % len(modes)
        self.renderer = render_mod.create(modes[i], self.opts.render)
        self.opts.mode = modes[i]
        self._notify(f"mode: {modes[i]}")
        return "reopen"  # pixel dimensions differ per mode

    def _seek(self, delta: float) -> Restart | None:
        if not self.source.info.seekable:
            self._notify("not seekable")
            return None
        duration = self.source.info.duration
        target = max(0.0, self._position + delta)
        if duration:
            target = min(target, max(duration - 0.1, 0.0))
        self._position = target
        self._notify(f"seek {_fmt_time(target)}")
        return "seek"

    def _notify(self, text: str, seconds: float = 1.5) -> None:
        self._message = text
        self._message_until = time.perf_counter() + seconds

    def _wait_while_paused(self) -> Restart | None:
        """Idle without burning CPU, but stay responsive to keys and resizes."""
        while self._paused:
            action = self._handle_keys(timeout=0.05)
            if action is not None:
                return action
            if self.term.take_resize():
                return "resize"
        return None

    # -- geometry ----------------------------------------------------------

    def _grid_size(self) -> tuple[int, int]:
        cols, rows = self.term.size()
        if self.opts.width:
            cols = self.opts.width
        if self.opts.height:
            rows = self.opts.height
        return max(cols, 8), max(rows, 2)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sleep_for(duration: float) -> None:
    """Sleep accurately. time.sleep() granularity is coarse enough to see as jitter.

    Takes a duration rather than an absolute deadline because the media clock is
    no longer necessarily the wall clock -- only the *interval* is comparable.
    """
    if duration <= 0:
        return
    target = time.perf_counter() + duration
    while True:
        remaining = target - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.002:
            time.sleep(remaining - 0.001)
        else:
            while time.perf_counter() < target:  # short, bounded spin
                pass
            return


def _blit(grid: CellGrid, row: int, col: int, text: str, fg, bg) -> None:
    rows, cols = grid.shape
    if not (0 <= row < rows):
        return
    fg_arr = np.array(fg if fg is not None else (DEFAULT,) * 3, dtype=np.int16)
    bg_arr = np.array(bg if bg is not None else (DEFAULT,) * 3, dtype=np.int16)
    for i, ch in enumerate(text):
        c = col + i
        if c >= cols:
            break
        if c < 0:
            continue
        grid.chars[row, c] = ord(ch)
        grid.fg[row, c] = fg_arr
        grid.bg[row, c] = bg_arr


def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: width - 1] + "…"
