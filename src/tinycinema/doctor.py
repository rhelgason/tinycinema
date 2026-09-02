"""`tinycinema --doctor` -- tell people why it isn't working.

Almost every failure report for a tool like this is "ffmpeg isn't installed" or
"my terminal can't do truecolor". A one-screen diagnostic beats a traceback.
"""

from __future__ import annotations

import os
import shutil
import sys

from . import __version__
from .render import available_modes
from .sources.ffmpeg import ffmpeg_path, ffprobe_path
from .term import detect_capabilities

OK = "\x1b[32m✓\x1b[0m"
WARN = "\x1b[33m!\x1b[0m"
BAD = "\x1b[31m✗\x1b[0m"


def _mark(good: bool, warn: bool = False) -> str:
    if good:
        return OK
    return WARN if warn else BAD


def _version_of(path: str | None) -> str:
    if not path:
        return "not found"
    import subprocess

    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=5, check=False
        )
        first = (out.stdout or out.stderr).splitlines()[0]
        return first.strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        return path


def run_doctor() -> int:
    caps = detect_capabilities()
    lines: list[str] = []
    problems = 0

    lines.append(f"\x1b[1mtinycinema {__version__}\x1b[0m")
    lines.append("")

    # -- dependencies ------------------------------------------------------
    lines.append("\x1b[1mDependencies\x1b[0m")
    py_ok = sys.version_info >= (3, 11)
    lines.append(f"  {_mark(py_ok)} python      {sys.version.split()[0]}")
    if not py_ok:
        problems += 1

    try:
        import numpy

        lines.append(f"  {OK} numpy       {numpy.__version__}")
    except ImportError:  # pragma: no cover - numpy is a hard dependency
        lines.append(f"  {BAD} numpy       not installed")
        problems += 1

    ff = ffmpeg_path()
    lines.append(f"  {_mark(bool(ff))} ffmpeg      {_version_of(ff)}")
    if not ff:
        problems += 1

    fp = ffprobe_path()
    lines.append(f"  {_mark(bool(fp), warn=True)} ffprobe     {_version_of(fp)}")

    ytdlp = shutil.which("yt-dlp")
    try:
        import yt_dlp  # noqa: F401

        ytdlp_note = "importable (Phase 3, not wired up yet)"
        have_ytdlp = True
    except ImportError:
        ytdlp_note = ytdlp or "not installed -- needed for YouTube links (Phase 3)"
        have_ytdlp = bool(ytdlp)
    lines.append(f"  {_mark(have_ytdlp, warn=True)} yt-dlp      {ytdlp_note}")

    lines.append("")

    # -- terminal ----------------------------------------------------------
    cols, rows = shutil.get_terminal_size((80, 24))
    lines.append("\x1b[1mTerminal\x1b[0m")
    lines.append(f"  {_mark(caps.is_tty, warn=True)} tty         {caps.is_tty}")
    lines.append(f"    · TERM        {caps.term}")
    lines.append(f"    · TERM_PROGRAM {caps.term_program}")
    lines.append(f"  {_mark(caps.truecolor, warn=True)} color       {caps.color_depth}")
    lines.append(f"  {_mark(caps.unicode, warn=True)} unicode     {caps.unicode}")
    lines.append(f"    · size        {cols}x{rows} cells")
    if caps.kitty:
        lines.append("    · kitty graphics protocol detected (Phase 5)")
    if caps.iterm:
        lines.append("    · iTerm2 inline images detected (Phase 5)")
    if os.environ.get("SSH_CONNECTION"):
        lines.append(f"  {WARN} ssh         detected -- expect to need a lower --fps")
    lines.append("")

    # -- rendering ---------------------------------------------------------
    lines.append("\x1b[1mRendering\x1b[0m")
    lines.append(f"    · modes       {', '.join(available_modes())}")
    lines.append(f"    · auto picks  {caps.best_mode()}")
    lines.append("")

    lines.append("\x1b[1mGlyph check\x1b[0m  (all four rows should look distinct)")
    lines.append("    ascii     " + " .:-=+*#%@")
    lines.append("    blocks    " + " ░▒▓█")
    lines.append("    halfblock " + "▀" * 10)
    lines.append("    braille   " + "".join(chr(0x2800 + i * 17) for i in range(10)))
    lines.append("")

    if caps.truecolor:
        swatch = "".join(
            f"\x1b[48;2;{int(255 * i / 31)};{int(128 + 60 * (i % 3))};{255 - int(255 * i / 31)}m "
            for i in range(32)
        )
        lines.append("\x1b[1mColor check\x1b[0m  (should be a smooth gradient)")
        lines.append("    " + swatch + "\x1b[0m")
        lines.append("")

    if problems:
        lines.append(f"\x1b[31m{problems} problem(s) found.\x1b[0m tinycinema will not play media.")
    else:
        lines.append("\x1b[32mAll good.\x1b[0m Try: tinycinema --demo")

    print("\n".join(lines))
    return 1 if problems else 0
