"""Recording playback to an asciinema v2 cast file.

The writer already produces the exact byte stream the terminal receives, so
recording is little more than tapping it and stamping each write with a time.
That is also why a cast of a colour-video playback is small: it inherits the
diffing, so a static shot costs almost nothing.

Format (one JSON value per line):

    {"version": 2, "width": 96, "height": 28, ...}
    [0.031, "o", "\\u001b[1;1H..."]
    [0.064, "o", "..."]

Play it back with `asciinema play out.cast`, or convert to a GIF with agg.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class CastRecorder:
    """Tees terminal output into an asciinema v2 file."""

    def __init__(
        self,
        path: str | Path,
        cols: int,
        rows: int,
        *,
        title: str | None = None,
        timestamp: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")
        self._origin: float | None = None
        self.events = 0
        self.bytes_recorded = 0

        header = {
            "version": 2,
            "width": cols,
            "height": rows,
            "timestamp": int(timestamp if timestamp is not None else time.time()),
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/sh"},
        }
        if title:
            header["title"] = title
        self._file.write(json.dumps(header) + "\n")

    def write(self, data: str) -> None:
        if not data or self._file.closed:
            return
        now = time.perf_counter()
        if self._origin is None:
            # Start the clock at the first real output, so a slow startup
            # doesn't become dead air at the head of the recording.
            self._origin = now
        json.dump([round(now - self._origin, 6), "o", data], self._file)
        self._file.write("\n")
        self.events += 1
        self.bytes_recorded += len(data)

    def close(self) -> None:
        if not self._file.closed:
            # Leave the terminal in a sane state for anyone replaying this.
            self.write("\x1b[0m\x1b[?25h\n")
            self._file.close()

    def __enter__(self) -> CastRecorder:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FrameDumper:
    """Writes each rendered frame to DIR/frame-00001.txt as plain text.

    Useful for building a GIF outside the tool, and for eyeballing exactly what
    the renderer produced frame by frame.
    """

    def __init__(self, directory: str | Path, *, extension: str = "txt") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.extension = extension
        self.count = 0

    def write(self, text: str) -> Path:
        self.count += 1
        path = self.directory / f"frame-{self.count:05d}.{self.extension}"
        path.write_text(text + "\n", encoding="utf-8")
        return path
