"""Non-blocking keyboard input for a terminal in cbreak mode."""

from __future__ import annotations

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
                if n - i < 6:
                    self._pending = data[i:]
                    break
                i += 1  # unknown CSI; drop the introducer and resync
                continue
            try:
                keys.append(byte.decode("utf-8"))
            except UnicodeDecodeError:
                pass  # multibyte input isn't a control key; ignore
            i += 1
        return keys
