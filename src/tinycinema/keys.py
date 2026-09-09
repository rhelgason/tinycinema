"""Non-blocking keyboard input for a terminal in cbreak mode."""

from __future__ import annotations

import contextlib
import os
import select
import sys
import time

# Escape sequences we care about, longest first so prefixes don't shadow.
_SEQUENCES: dict[bytes, str] = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
    b"\x1bOA": "up",
    b"\x1bOB": "down",
    b"\x1bOC": "right",
    b"\x1bOD": "left",
    b"\x1b[5~": "pageup",
    b"\x1b[6~": "pagedown",
    b"\x1b[H": "home",
    b"\x1b[F": "end",
    b"\x7f": "backspace",
    b"\r": "enter",
    b"\n": "enter",
    b"\t": "tab",
    b" ": "space",
    b"\x1b": "escape",
    b"\x03": "ctrl-c",
    b"\x04": "ctrl-d",
}

#: Introducers whose payload runs to a String Terminator (ESC \) or a BEL:
#: OSC replies, kitty graphics acks, DCS/sixel status.
_STRING_INTRODUCERS = b"]P_^X"

#: An escape sequence longer than this is not one we are waiting to complete,
#: so stop holding the buffer and resynchronise.
_MAX_PARTIAL = 32


def _escape_length(data: bytes, i: int) -> int | None:
    """Length of the escape sequence at data[i:], or None if it's still partial.

    Terminals talk back. A Primary Device Attributes reply, a cursor position
    report, a graphics acknowledgement, a bracketed paste marker -- all arrive
    on stdin mixed in with real keystrokes. Dropping only the ESC and
    resynchronising on the remainder feeds the *body* to the key handler, and
    those bodies end in the bytes that matter most: `c` in a DA reply, `R` in a
    cursor report, `h` in a paste marker, `=` in a kitty ack. The picture would
    rearrange itself -- colour off, render mode cycled, HUD gone -- whenever the
    terminal said anything at all. So skip the whole sequence.
    """
    n = len(data)
    if i + 1 >= n:
        return None
    kind = data[i + 1]
    if kind == 0x5B:  # CSI: parameter and intermediate bytes, then a final byte
        j = i + 2
        while j < n and 0x20 <= data[j] <= 0x3F:
            j += 1
        if j < n and 0x40 <= data[j] <= 0x7E:
            return j + 1 - i
        return None
    if kind in _STRING_INTRODUCERS:
        end = data.find(b"\x1b\\", i + 2)
        if end != -1:
            return end + 2 - i
        end = data.find(b"\x07", i + 2)
        if end != -1:
            return end + 1 - i
        return None
    return 2  # a two-byte escape: ESC O, ESC (, and friends


def _resync_after(data: bytes, i: int) -> int:
    """Where to resume after an escape sequence that never terminated.

    It is not one we are still waiting on, so it is malformed -- but its body
    is no more a keystroke than a well-formed one's, so skip the body too. A
    string sequence has no bounded shape, so nothing after it can be trusted.
    """
    n = len(data)
    if i + 1 < n and data[i + 1] in _STRING_INTRODUCERS:
        return n
    j = i + 2
    while j < n and 0x20 <= data[j] <= 0x3F:
        j += 1
    return min(j + 1, n)


class KeyReader:
    """Drains whatever is waiting on stdin and decodes it into key names."""

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdin
        try:
            self._fd = self._stream.fileno()
            self._usable = self._stream.isatty()
        except (AttributeError, ValueError, OSError):
            self._fd = -1
            self._usable = False
        self._pending = b""

    @property
    def usable(self) -> bool:
        return self._usable

    def poll(self, timeout: float = 0.0) -> list[str]:
        """Return every key pressed since the last call. Never blocks past `timeout`."""
        if not self._usable:
            # Still honour the timeout. Callers poll in a loop (the pause idle
            # does), and returning instantly turns that into a busy-wait that
            # pins a core whenever stdin isn't a terminal.
            if timeout > 0:
                time.sleep(timeout)
            return []
        data = self._pending
        self._pending = b""
        while True:
            try:
                ready, _, _ = select.select([self._fd], [], [], timeout)
            except (OSError, ValueError):
                return []
            if not ready:
                break
            try:
                chunk = os.read(self._fd, 1024)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                return []
            if not chunk:
                break
            data += chunk
            timeout = 0.0  # only the first wait may block
        return self._decode(data)

    def _decode(self, data: bytes) -> list[str]:
        keys: list[str] = []
        i = 0
        n = len(data)
        while i < n:
            # A lone ESC at the very end is probably a truncated sequence; hold
            # it back so the next poll can complete it.
            matched = False
            for length in (4, 3, 2, 1):
                if i + length > n:
                    continue
                name = _SEQUENCES.get(data[i : i + length])
                if name is not None:
                    if name == "escape" and i + 1 < n:
                        break  # start of a longer sequence we don't know; skip it
                    keys.append(name)
                    i += length
                    matched = True
                    break
            if matched:
                continue

            byte = data[i : i + 1]
            if byte == b"\x1b":
                length = _escape_length(data, i)
                if length is None:
                    if n - i < _MAX_PARTIAL:
                        # Probably still arriving; let the next poll finish it.
                        self._pending = data[i:]
                        break
                    i = _resync_after(data, i)
                    continue
                i += length
                continue
            # Multibyte input isn't a control key; ignore it.
            with contextlib.suppress(UnicodeDecodeError):
                keys.append(byte.decode("utf-8"))
            i += 1
        return keys
