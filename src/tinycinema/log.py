"""Opt-in diagnostic output for `--verbose`.

Always stderr, never stdout: stdout may be a pipe someone is capturing frames
from, and these messages are printed before the alt screen is entered so they
scroll away on their own.
"""

from __future__ import annotations

import sys

_enabled = False


def set_verbose(enabled: bool) -> None:
    global _enabled
    _enabled = enabled


def is_verbose() -> bool:
    return _enabled


def note(message: str) -> None:
    if _enabled:
        sys.stderr.write(f"\x1b[2m· {message}\x1b[0m\n")
        sys.stderr.flush()
