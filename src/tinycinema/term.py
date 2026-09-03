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
import contextlib
import os
import re
import shutil
import signal
import sys
import termios
import time
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

DEFAULT = -1  # sentinel in a CellGrid colour channel meaning "terminal default"

#: Signals that mean "shut down now" and would otherwise kill us outright.
#: SIGINT is absent on purpose -- Python already turns it into KeyboardInterrupt.
FATAL_SIGNALS = ("SIGTERM", "SIGHUP")


class Terminated(BaseException):
    """Raised in the main thread when a fatal signal arrives.

    An exception rather than cleanup-in-the-handler, so that every `finally`
    already in the program runs: the terminal is restored, and ffmpeg and ffplay
    are terminated instead of being orphaned and left making noise.

    BaseException, like KeyboardInterrupt, so a stray `except Exception` cannot
    swallow a shutdown request.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(f"terminated by signal {signum}")
        self.signum = signum

    @property
    def exit_status(self) -> int:
        return 128 + self.signum

#: Seconds a new terminal size must hold before we rebuild the pipeline.
RESIZE_DEBOUNCE = 0.15

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


#: A colour channel triple packed into one int. DEFAULT maps outside 24-bit range
#: so "terminal default" compares unequal to every real colour.
_DEFAULT_KEY = 1 << 24
#: Multiplier that stacks the fg key above the bg key in a single int.
_FG_SHIFT = 1 << 25


def pack_colors(plane: np.ndarray) -> np.ndarray:
    """(rows, cols, 3) int16 RGB -> (rows, cols) int64, one integer per colour.

    Comparing packed integers instead of three channels makes both the frame
    diff and the run-splitting a single vectorised op, and gives the SGR cache a
    plain int key instead of a tuple that has to be rebuilt per cell.
    """
    p = plane.astype(np.int64)
    packed = (p[..., 0] << 16) | (p[..., 1] << 8) | p[..., 2]
    return np.where(p[..., 0] < 0, _DEFAULT_KEY, packed)


def _fg_seq(key: int) -> str:
    if key == _DEFAULT_KEY:
        return "39"
    return f"38;2;{(key >> 16) & 0xFF};{(key >> 8) & 0xFF};{key & 0xFF}"


def _bg_seq(key: int) -> str:
    if key == _DEFAULT_KEY:
        return "49"
    return f"48;2;{(key >> 16) & 0xFF};{(key >> 8) & 0xFF};{key & 0xFF}"


class FrameWriter:
    """Paints CellGrids to a tty, emitting the minimum plausible byte stream.

    The inner loop runs over *spans of constant colour* rather than cells, and
    every value it touches has been bulk-converted to Python ints and strings
    first. Per-cell numpy scalar indexing costs ~2us a cell, which at 7680 cells
    is 15ms a frame -- half the budget at 30fps, spent on nothing but boxing.
    """

    def __init__(self, stream=None, *, synchronized: bool = True, recorder=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._synchronized = synchronized
        #: Optional tap that receives the same bytes the terminal does.
        self.recorder = recorder
        self._prev_chars: np.ndarray | None = None
        self._prev_keys: np.ndarray | None = None
        # pen state, so we only emit SGR on an actual colour change
        self._pen_fg = -1
        self._pen_bg = -1
        self._fg_cache: dict[int, str] = {}
        self._bg_cache: dict[int, str] = {}
        self._both_cache: dict[int, str] = {}
        self.bytes_written = 0

    def invalidate(self) -> None:
        """Force the next draw to be a full repaint (after a resize, say)."""
        self._prev_chars = None
        self._prev_keys = None
        self._pen_fg = -1
        self._pen_bg = -1

    def draw(self, grid: CellGrid) -> None:
        payload = self.encode(grid)
        if not payload:
            return
        self._stream.write(payload)
        self._stream.flush()
        self.bytes_written += len(payload)
        if self.recorder is not None:
            self.recorder.write(payload)

    def encode(self, grid: CellGrid) -> str:
        """Build the byte string for this frame. Separated out so it's testable."""
        rows, cols = grid.shape
        chars = np.ascontiguousarray(grid.chars, dtype=np.uint32)
        if (chars == 0).any():
            # numpy strips trailing NULs from a 'U' view, which would silently
            # shorten a row string and misalign every span after it.
            chars = np.where(chars == 0, 32, chars)
        keys = pack_colors(grid.fg) * _FG_SHIFT + pack_colors(grid.bg)

        prev_chars, prev_keys = self._prev_chars, self._prev_keys
        # A resize leaves stale cells outside the old grid, so start over.
        full = prev_chars is None or prev_chars.shape != chars.shape

        if full:
            changed = np.ones((rows, cols), dtype=bool)
        else:
            changed = (chars != prev_chars) | (keys != prev_keys)

        self._prev_chars, self._prev_keys = chars, keys

        dirty_rows = np.flatnonzero(changed.any(axis=1))
        if dirty_rows.size == 0:
            return ""

        out: list[str] = []
        append = out.append
        if self._synchronized:
            append(SYNC_BEGIN)
        if full:
            # We can't trust the pen state across a full repaint.
            append(SGR_RESET + CURSOR_HOME)
            self._pen_fg = self._pen_bg = -1

        # uint32 codepoints ARE UTF-32, so a row reinterprets as a Python string
        # for free -- no per-character chr() call.
        row_text = chars.view(f"U{cols}").ravel().tolist()

        fg_cache, bg_cache, both_cache = self._fg_cache, self._bg_cache, self._both_cache
        pen_fg, pen_bg = self._pen_fg, self._pen_bg

        for r in dirty_rows.tolist():
            key_row = keys[r]
            key_list = key_row.tolist()
            text = row_text[r]

            for c0, c1 in _runs(np.flatnonzero(changed[r])):
                append(f"\x1b[{r + 1};{c0 + 1}H")
                span = key_row[c0 : c1 + 1]
                # split the run wherever the colour changes; emit each span whole
                bounds = (np.flatnonzero(span[1:] != span[:-1]) + 1).tolist()
                start = c0
                for b in (*bounds, span.size):
                    end = c0 + b
                    key = key_list[start]
                    fg = key // _FG_SHIFT
                    bg = key - fg * _FG_SHIFT
                    if fg != pen_fg:
                        if bg != pen_bg:
                            seq = both_cache.get(key)
                            if seq is None:
                                seq = f"\x1b[{_fg_seq(fg)};{_bg_seq(bg)}m"
                                if len(both_cache) < 8192:
                                    both_cache[key] = seq
                            pen_bg = bg
                        else:
                            seq = fg_cache.get(fg)
                            if seq is None:
                                seq = f"\x1b[{_fg_seq(fg)}m"
                                if len(fg_cache) < 8192:
                                    fg_cache[fg] = seq
                        pen_fg = fg
                        append(seq)
                    elif bg != pen_bg:
                        seq = bg_cache.get(bg)
                        if seq is None:
                            seq = f"\x1b[{_bg_seq(bg)}m"
                            if len(bg_cache) < 8192:
                                bg_cache[bg] = seq
                        pen_bg = bg
                        append(seq)
                    append(text[start:end])
                    start = end

        self._pen_fg, self._pen_bg = pen_fg, pen_bg
        if self._synchronized:
            append(SYNC_END)
        return "".join(out)


class ImageWriter:
    """Paints inline-image payloads (kitty / iTerm2 / sixel).

    There is nothing to diff here: the terminal owns the pixels once we hand
    them over, and every protocol replaces the whole picture each frame. So this
    is a much simpler writer -- one payload out, plus an optional HUD line drawn
    underneath with ordinary escapes.
    """

    def __init__(self, stream=None, *, synchronized: bool = True, recorder=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._synchronized = synchronized
        self.recorder = recorder
        self.bytes_written = 0
        self._last_hud = ""

    def invalidate(self) -> None:
        self._last_hud = ""

    def draw_image(
        self,
        payload: str,
        hud: str = "",
        hud_row: int = 0,
        caption: list[str] | None = None,
        caption_row: int = 0,
    ) -> None:
        parts = []
        if self._synchronized:
            parts.append(SYNC_BEGIN)
        parts.append(payload)
        for offset, line in enumerate(caption or []):
            # Drawn over the image; all three protocols allow text on top.
            # Lines arrive already padded to the grid width by the caller, which
            # is the only place that knows it.
            row = max(caption_row + offset, 0)
            parts.append(
                f"\x1b[{row + 1};1H\x1b[38;2;245;245;235;48;2;10;10;14m"
                f"{line}\x1b[0m"
            )
        if hud:
            fg, bg = (200, 200, 200), (24, 24, 32)
            parts.append(
                f"\x1b[{hud_row + 1};1H"
                f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]};48;2;{bg[0]};{bg[1]};{bg[2]}m"
                f"{hud}\x1b[0m"
            )
            self._last_hud = hud
        if self._synchronized:
            parts.append(SYNC_END)
        out = "".join(parts)
        self._stream.write(out)
        self._stream.flush()
        self.bytes_written += len(out)
        if self.recorder is not None:
            self.recorder.write(out)

    def draw(self, grid: CellGrid) -> None:  # pragma: no cover - interface parity
        raise TypeError("ImageWriter draws payloads, not cell grids")


class PlainWriter:
    """Unstyled output for pipes and redirects. No escapes, no cursor games."""

    def __init__(self, stream=None, *, recorder=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self.recorder = recorder
        self.bytes_written = 0

    def invalidate(self) -> None:  # noqa: D102 - interface parity
        pass

    def draw(self, grid: CellGrid) -> None:
        text = grid.to_text() + "\n"
        self._stream.write(text)
        self._stream.flush()
        self.bytes_written += len(text)


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
    sixel: bool = False

    @property
    def image_modes(self) -> list[str]:
        """Inline-image protocols this terminal claims to support, best first."""
        modes = []
        if self.kitty:
            modes.append("kitty")
        if self.iterm:
            modes.append("iterm")
        if self.sixel:
            modes.append("sixel")
        return modes

    @property
    def color_depth(self) -> str:
        if self.truecolor:
            return "24-bit"
        if self.color256:
            return "256"
        return "none"

    def best_mode(self) -> str:
        """Pick the nicest *character* mode this terminal can handle.

        Deliberately never returns an inline-image mode, even when one is
        available. The design notes originally had `auto` climb all the way to
        kitty/sixel, but the whole point of this tool is video rendered out of
        characters -- silently swapping in a bitmap would quietly defeat it.
        Image modes are one flag away and --doctor advertises them.
        """
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
    iterm = term_program in ("iTerm.app", "WezTerm")
    sixel = detect_sixel(stream) if is_tty else False

    if os.environ.get("NO_COLOR"):
        truecolor = color256 = False

    return Capabilities(
        is_tty=is_tty,
        truecolor=truecolor,
        color256=color256,
        unicode=unicode_ok,
        kitty=kitty,
        iterm=iterm,
        sixel=sixel,
        term=term or "(unset)",
        term_program=term_program or "(unset)",
    )


#: Attribute 4 in a Primary Device Attributes reply means sixel support.
_DA_TIMEOUT = 0.25


def detect_sixel(stream=None) -> bool:
    """Ask the terminal directly, via a Primary Device Attributes query.

    There is no environment variable for sixel, so this writes `ESC [ c` and
    reads the reply. Terminals that don't answer simply time out -- hence the
    short deadline, and hence doing this once at startup rather than ever again.
    """
    if os.environ.get("TINYCINEMA_SIXEL"):
        return os.environ["TINYCINEMA_SIXEL"] not in ("0", "", "no")
    stream = stream if stream is not None else sys.stdout
    try:
        if not stream.isatty() or not sys.stdin.isatty():
            return False
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return False

    import select

    try:
        saved = termios.tcgetattr(fd)
    except (termios.error, ValueError, OSError):
        return False
    try:
        tty.setcbreak(fd)
        stream.write("\x1b[c")
        stream.flush()
        reply = b""
        deadline = time.monotonic() + _DA_TIMEOUT
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([fd], [], [], max(remaining, 0))
            if not ready:
                break
            chunk = os.read(fd, 64)
            if not chunk:
                break
            reply += chunk
            if b"c" in chunk:  # the reply terminates with 'c'
                break
    except (OSError, ValueError, termios.error):
        return False
    finally:
        with contextlib.suppress(termios.error, ValueError, OSError):
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    # Reply looks like ESC [ ? 62 ; 4 ; 6 c -- attribute 4 is sixel.
    text = reply.decode("ascii", "ignore")
    if "?" not in text:
        return False
    body = text.split("?", 1)[1].split("c", 1)[0]
    return "4" in body.split(";")


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
        self._prev_fatal: dict[int, object] = {}
        self._entered = False
        self.resized = False
        self._settled_size = self.size()
        self._observed_size = self._settled_size
        self._observed_at = 0.0

    # -- sizing ------------------------------------------------------------

    def size(self) -> tuple[int, int]:
        """(cols, rows) of the terminal, with a sane fallback when not a tty."""
        try:
            cols, rows = os.get_terminal_size(sys.stdout.fileno())
        except OSError:
            cols, rows = shutil.get_terminal_size((80, 24))
        return max(cols, 8), max(rows, 4)

    def take_resize(self) -> bool:
        """True once the window has settled at a size different from the last one.

        Polls rather than trusting SIGWINCH alone. The signal is not delivered
        when the process has no controlling terminal, and a missed resize leaves
        the picture permanently the wrong size -- so the signal is treated as a
        hint that saves us a little latency, not as the mechanism.

        Debounced, because a drag-resize fires a flood of events and tearing the
        decoder down for each one stutters horribly.
        """
        self.resized = False
        size = self.size()
        if size == self._settled_size:
            self._observed_size = size
            return False
        now = time.monotonic()
        if size != self._observed_size:
            self._observed_size = size
            self._observed_at = now
            return False
        if now - self._observed_at < RESIZE_DEBOUNCE:
            return False
        self._settled_size = size
        return True

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

        # Without these, `kill` or closing the terminal tab leaves the alt
        # screen up and the cursor hidden, because a signal death skips atexit.
        for name in FATAL_SIGNALS:
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                self._prev_fatal[sig] = signal.signal(sig, self._on_fatal)
            except (ValueError, OSError):
                pass  # not the main thread, or the platform disallows it

        atexit.register(self.restore)
        return self

    def _on_fatal(self, signum, frame):
        raise Terminated(signum)

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

        for sig, previous in self._prev_fatal.items():
            try:
                signal.signal(sig, previous)
            except (ValueError, OSError, TypeError):
                pass
        self._prev_fatal.clear()

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
