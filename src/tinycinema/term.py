"""Terminal control: raw mode, capability detection, and the diffed frame writer.

All of the escape-code ugliness lives here so nothing else has to know about it.

The writer is the highest-value code in the project. A naive full repaint of a
200x50 truecolor grid is ~420 KB/frame (12.6 MB/s at 30fps), which chokes most
terminal emulators and is hopeless over SSH. Three tricks cut that by one to two
orders of magnitude:

  1. diff against the previous frame and only touch cells that changed
  2. emit an SGR colour sequence only when the colour actually differs from the
     writer's current pen state
  3. group changed cells into runs so we pay for one cursor-move per run, not
     one per cell
"""

from __future__ import annotations

import atexit
import os
import re
import shutil
import signal
import sys
import termios
import tty
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# escape sequences
# ---------------------------------------------------------------------------

ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"
CURSOR_HIDE = "\x1b[?25l"
CURSOR_SHOW = "\x1b[?25h"
# Autowrap off, or painting the bottom-right cell scrolls the whole screen.
AUTOWRAP_OFF = "\x1b[?7l"
AUTOWRAP_ON = "\x1b[?7h"
CURSOR_HOME = "\x1b[H"
SYNC_BEGIN = "\x1b[?2026h"  # DECSET 2026: don't present a half-drawn frame
SYNC_END = "\x1b[?2026l"
CLEAR = "\x1b[2J"
SGR_RESET = "\x1b[0m"
SGR_DEFAULT_FG = "\x1b[39m"
SGR_DEFAULT_BG = "\x1b[49m"

DEFAULT = -1  # sentinel in a CellGrid colour channel meaning "terminal default"

# Merging two runs of changed cells costs us the unchanged cells in between, but
# saves a ~7-byte cursor-move. Below this gap width, merging wins.
_RUN_GAP_MERGE = 4


# ---------------------------------------------------------------------------
# the unit of rendering
# ---------------------------------------------------------------------------


@dataclass
class CellGrid:
    """A renderer's output: one character plus two colours per terminal cell.

    chars: (rows, cols) uint32 unicode codepoints
    fg:    (rows, cols, 3) int16 RGB, or DEFAULT in every channel
    bg:    (rows, cols, 3) int16 RGB, or DEFAULT in every channel
    """

    chars: np.ndarray
    fg: np.ndarray
    bg: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.chars.shape  # type: ignore[return-value]

    @classmethod
    def blank(cls, rows: int, cols: int) -> CellGrid:
        return cls(
            chars=np.full((rows, cols), ord(" "), dtype=np.uint32),
            fg=np.full((rows, cols, 3), DEFAULT, dtype=np.int16),
            bg=np.full((rows, cols, 3), DEFAULT, dtype=np.int16),
        )

    def to_text(self) -> str:
        """Plain unstyled text. Used for non-tty output and in tests."""
        return "\n".join("".join(chr(c) for c in row) for row in self.chars)


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------


class FrameWriter:
    """Paints CellGrids to a tty, emitting the minimum plausible byte stream."""

    def __init__(self, stream=None, *, synchronized: bool = True) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._synchronized = synchronized
        self._prev: CellGrid | None = None
        # pen state, so we only emit SGR on an actual colour change
        self._pen_fg: tuple[int, int, int] | None = None
        self._pen_bg: tuple[int, int, int] | None = None
        self._sgr_cache: dict[tuple, str] = {}
        self.bytes_written = 0

    def invalidate(self) -> None:
        """Force the next draw to be a full repaint (after a resize, say)."""
        self._prev = None
        self._pen_fg = None
        self._pen_bg = None

    def draw(self, grid: CellGrid) -> None:
        payload = self.encode(grid)
        if not payload:
            return
        self._stream.write(payload)
        self._stream.flush()
        self.bytes_written += len(payload)

    def encode(self, grid: CellGrid) -> str:
        """Build the byte string for this frame. Separated out so it's testable."""
        rows, cols = grid.shape
        prev = self._prev
        full = (
            prev is None
            or prev.shape != grid.shape
            # a resize can leave stale cells outside the previous grid
        )

        if full:
            changed = np.ones((rows, cols), dtype=bool)
        else:
            assert prev is not None
            changed = (
                (grid.chars != prev.chars)
                | (grid.fg != prev.fg).any(axis=2)
                | (grid.bg != prev.bg).any(axis=2)
            )

        dirty_rows = np.flatnonzero(changed.any(axis=1))
        if dirty_rows.size == 0:
            self._prev = grid
            return ""

        out: list[str] = []
        if self._synchronized:
            out.append(SYNC_BEGIN)
        if full:
            # Reset the pen too: we can't trust state across a full repaint.
            out.append(SGR_RESET + CURSOR_HOME)
            self._pen_fg = None
            self._pen_bg = None

        chars = grid.chars
        fg = grid.fg
        bg = grid.bg
        append = out.append

        for r in int_iter(dirty_rows):
            for c0, c1 in _runs(np.flatnonzero(changed[r])):
                append(f"\x1b[{r + 1};{c0 + 1}H")
                for c in range(c0, c1 + 1):
                    f = (int(fg[r, c, 0]), int(fg[r, c, 1]), int(fg[r, c, 2]))
                    b = (int(bg[r, c, 0]), int(bg[r, c, 1]), int(bg[r, c, 2]))
                    if f != self._pen_fg or b != self._pen_bg:
                        append(self._sgr(f, b))
                        self._pen_fg = f
                        self._pen_bg = b
                    append(chr(chars[r, c]))

        if self._synchronized:
            append(SYNC_END)

        self._prev = grid
        return "".join(out)

    def _sgr(self, f: tuple[int, int, int], b: tuple[int, int, int]) -> str:
        """Colour-change escape, combining fg+bg into one sequence when both move."""
        need_fg = f != self._pen_fg
        need_bg = b != self._pen_bg
        key = (f if need_fg else None, b if need_bg else None)
        hit = self._sgr_cache.get(key)
        if hit is not None:
            return hit

        parts: list[str] = []
        if need_fg:
            parts.append("39" if f[0] < 0 else f"38;2;{f[0]};{f[1]};{f[2]}")
        if need_bg:
            parts.append("49" if b[0] < 0 else f"48;2;{b[0]};{b[1]};{b[2]}")
        seq = "\x1b[" + ";".join(parts) + "m" if parts else ""

        # Frames reuse colours heavily, but an unbounded cache would grow without
        # limit on noisy content.
        if len(self._sgr_cache) < 8192:
            self._sgr_cache[key] = seq
        return seq


class PlainWriter:
    """Unstyled output for pipes and redirects. No escapes, no cursor games."""

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self.bytes_written = 0

    def invalidate(self) -> None:  # noqa: D102 - interface parity
        pass

    def draw(self, grid: CellGrid) -> None:
        text = grid.to_text() + "\n"
        self._stream.write(text)
        self._stream.flush()
        self.bytes_written += len(text)


def int_iter(a: np.ndarray):
    return (int(x) for x in a)


def _runs(cols: np.ndarray) -> list[tuple[int, int]]:
    """Group sorted column indices into (start, end) inclusive runs.

    Gaps of up to _RUN_GAP_MERGE unchanged cells are absorbed into a run: paying
    for a few redundant cells is cheaper than another cursor-move escape.
    """
    if cols.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(cols) > _RUN_GAP_MERGE)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [cols.size - 1]))
    return [(int(cols[s]), int(cols[e])) for s, e in zip(starts, ends, strict=True)]


# ---------------------------------------------------------------------------
# capability detection
# ---------------------------------------------------------------------------


@dataclass
class Capabilities:
    is_tty: bool
    truecolor: bool
    color256: bool
    unicode: bool
    kitty: bool
    iterm: bool
    term: str
    term_program: str

    @property
    def color_depth(self) -> str:
        if self.truecolor:
            return "24-bit"
        if self.color256:
            return "256"
        return "none"

    def best_mode(self) -> str:
        """Pick the nicest render mode this terminal can actually handle."""
        if not self.is_tty:
            return "ascii"
        if self.unicode and (self.truecolor or self.color256):
            return "halfblock"
        if self.truecolor or self.color256:
            return "ascii-color"
        return "ascii"


def detect_capabilities(stream=None) -> Capabilities:
    stream = stream if stream is not None else sys.stdout
    try:
        is_tty = stream.isatty()
    except (AttributeError, ValueError):
        is_tty = False

    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    colorterm = os.environ.get("COLORTERM", "").lower()

    truecolor = colorterm in ("truecolor", "24bit") or "truecolor" in term
    color256 = truecolor or "256color" in term or term_program in ("iTerm.app", "vscode")

    encoding = (getattr(stream, "encoding", None) or "").lower()
    unicode_ok = "utf" in encoding or "utf" in os.environ.get("LANG", "").lower()

    kitty = "kitty" in term.lower() or bool(os.environ.get("KITTY_WINDOW_ID"))
    iterm = term_program == "iTerm.app"

    if os.environ.get("NO_COLOR"):
        truecolor = color256 = False

    return Capabilities(
        is_tty=is_tty,
        truecolor=truecolor,
        color256=color256,
        unicode=unicode_ok,
        kitty=kitty,
        iterm=iterm,
        term=term or "(unset)",
        term_program=term_program or "(unset)",
    )


# ---------------------------------------------------------------------------
# terminal session
# ---------------------------------------------------------------------------


class Terminal:
    """Context manager owning raw mode, the alt screen, and resize notification.

    Restoring the terminal is not optional: an atexit hook backs up __exit__ so a
    hard crash still leaves the user with a working shell.
    """

    def __init__(self, *, alt_screen: bool = True, hide_cursor: bool = True) -> None:
        self.caps = detect_capabilities()
        self._alt_screen = alt_screen and self.caps.is_tty
        self._hide_cursor = hide_cursor and self.caps.is_tty
        self._saved_termios = None
        self._prev_winch = None
        self._entered = False
        self.resized = False

    # -- sizing ------------------------------------------------------------

    def size(self) -> tuple[int, int]:
        """(cols, rows) of the terminal, with a sane fallback when not a tty."""
        try:
            cols, rows = os.get_terminal_size(sys.stdout.fileno())
        except OSError:
            cols, rows = shutil.get_terminal_size((80, 24))
        return max(cols, 8), max(rows, 4)

    def take_resize(self) -> bool:
        """Consume the resize flag; True if the window changed since last call."""
        if self.resized:
            self.resized = False
            return True
        return False

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Terminal:
        if self._entered:
            return self
        self._entered = True

        if self.caps.is_tty:
            fd = sys.stdin.fileno()
            try:
                self._saved_termios = termios.tcgetattr(fd)
                # cbreak, not full raw: keeps ISIG so ctrl-c still interrupts.
                tty.setcbreak(fd)
            except (termios.error, ValueError, OSError):
                self._saved_termios = None

        parts = []
        if self._alt_screen:
            parts.append(ALT_SCREEN_ON)
            parts.append(CLEAR)
            parts.append(CURSOR_HOME)
        if self._hide_cursor:
            parts.append(CURSOR_HIDE)
        if self.caps.is_tty:
            parts.append(AUTOWRAP_OFF)
        if parts:
            sys.stdout.write("".join(parts))
            sys.stdout.flush()

        if self.caps.is_tty and hasattr(signal, "SIGWINCH"):
            self._prev_winch = signal.signal(signal.SIGWINCH, self._on_winch)

        atexit.register(self.restore)
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    def _on_winch(self, signum, frame) -> None:
        self.resized = True

    def restore(self) -> None:
        if not self._entered:
            return
        self._entered = False

        if self._prev_winch is not None and hasattr(signal, "SIGWINCH"):
            try:
                signal.signal(signal.SIGWINCH, self._prev_winch)
            except (ValueError, OSError):
                pass
            self._prev_winch = None

        if self.caps.is_tty:
            # Never emit escapes into a pipe -- it would corrupt piped output.
            parts = [SGR_RESET, AUTOWRAP_ON]
            if self._hide_cursor:
                parts.append(CURSOR_SHOW)
            if self._alt_screen:
                parts.append(ALT_SCREEN_OFF)
            try:
                sys.stdout.write("".join(parts))
                sys.stdout.flush()
            except (ValueError, OSError):
                pass

        if self._saved_termios is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved_termios)
            except (termios.error, ValueError, OSError):
                pass
            self._saved_termios = None

        try:
            atexit.unregister(self.restore)
        except Exception:  # noqa: BLE001 - never let teardown raise
            pass


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(s: str) -> str:
    """Handy in tests and for measuring the visible width of HUD strings."""
    return _ANSI_RE.sub("", s)
