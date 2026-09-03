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
from .binaries import ffmpeg_path, ffplay_path, ffprobe_path
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

    play = ffplay_path()
    note = _version_of(play) if play else "not installed -- playback will be silent"
    lines.append(f"  {_mark(bool(play), warn=True)} ffplay      {note}")

    try:
        import yt_dlp

        ytdlp_note = yt_dlp.version.__version__
        have_ytdlp = True
    except ImportError:
        ytdlp_note = "not installed -- needed for YouTube and friends"
        have_ytdlp = False
    lines.append(f"  {_mark(have_ytdlp, warn=True)} yt-dlp      {ytdlp_note}")

    lines.append("")

    from .sources.ytdlp import cache_dir, cache_size

    count, size = cache_size()
    lines.append("\x1b[1mDownload cache\x1b[0m")
    lines.append(f"    · location    {cache_dir()}")
    lines.append(f"    · contents    {count} file(s), {size / 1e6:.1f} MB")
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
    supported = caps.image_modes
    lines.append(
        f"  {_mark(bool(supported), warn=True)} images      "
        + (", ".join(supported) if supported else "none detected")
    )
    if os.environ.get("SSH_CONNECTION"):
        lines.append(f"  {WARN} ssh         detected -- expect to need a lower --fps")
    lines.append("")

    # -- rendering ---------------------------------------------------------
    lines.append("\x1b[1mAudio\x1b[0m")
    if play:
        lines.append("    · backend     ffplay (audio is the master clock)")
    else:
        lines.append("    · backend     none -- video will sync to a wall clock")
    lines.append("")

    from .render import cell_modes, image_modes

    lines.append("\x1b[1mRendering\x1b[0m")
    lines.append(f"    · text modes  {', '.join(cell_modes())}")
    lines.append(f"    · image modes {', '.join(image_modes())}")
    lines.append(f"    · auto picks  {caps.best_mode()}")
    if supported:
        lines.append(
            f"    · try         tinycinema clip.mp4 --mode {supported[0]} --fps 15"
        )
    else:
        lines.append("    · image modes need kitty, iTerm2/WezTerm, or a sixel terminal")
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
