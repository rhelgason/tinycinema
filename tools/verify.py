#!/usr/bin/env python3
"""First-run check on real hardware: `python tools/verify.py [URL]`

Everything in the test suite runs without ffmpeg, a terminal, a sound card or a
network, which is what makes it fast and portable -- and also means four things
have never been exercised against the real article:

    a real ffmpeg decode, a real audio device, a real terminal, and a real
    yt-dlp fetch

This walks those in order, cheapest first, so a failure says which one broke
rather than just "it didn't work". Pass a URL as an argument to include the
yt-dlp step; leave it off to skip it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GREEN, RED, YELLOW, DIM, RESET = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[2m", "\x1b[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "", fail_hint: str = "", fatal: bool = False):
    """`detail` prints either way; `fail_hint` only when it fails."""
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    note = detail if ok else (fail_hint or detail)
    print(f"  [{mark}] {name}" + (f"  {DIM}{note}{RESET}" if note else ""))
    results.append((name, ok, note))
    if not ok and fatal:
        summarise()
        sys.exit(1)
    return ok


def optional(name: str, ok: bool, detail: str = "", why: str = "") -> bool:
    """Nice to have. Reported, but never counted as a failure."""
    mark = f"{GREEN}PASS{RESET}" if ok else f"{YELLOW}WARN{RESET}"
    print(f"  [{mark}] {name}  {DIM}{detail if ok else why}{RESET}")
    return ok


def skip(name: str, why: str) -> None:
    print(f"  [{YELLOW}SKIP{RESET}] {name}  {DIM}{why}{RESET}")


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def run_pty(cmd: list[str], cols: int = 80, rows: int = 24, timeout: int = 120):
    """Run attached to a real pseudo-terminal.

    Necessary for anything that tests *playback*: piped stdout implies --once,
    so a redirected run renders a single frame and never touches the timing
    loop or the audio clock. Returns (returncode, stderr).
    """
    import fcntl
    import os
    import pty
    import select
    import struct
    import termios
    import time

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        cmd, stdin=slave, stdout=slave, stderr=subprocess.PIPE, close_fds=True
    )
    os.close(slave)
    os.set_blocking(master, False)

    # Drain continuously. A full pty buffer blocks the child, which would look
    # like the player being slow rather than the harness being slow.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            if not os.read(master, 1 << 20):
                break
        except BlockingIOError:
            select.select([master], [], [], 0.05)
        except OSError:
            break
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.close(master)
    return proc.returncode, (proc.stderr.read() or b"").decode("utf-8", "replace")


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * len(title))


def summarise() -> None:
    failed = [n for n, ok, _ in results if not ok]
    print()
    if failed:
        print(f"{RED}{len(failed)} check(s) failed:{RESET} " + ", ".join(failed))
    else:
        print(f"{GREEN}Everything passed.{RESET}")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else None
    tinycinema = shutil.which("tinycinema") or sys.executable
    prefix = [] if shutil.which("tinycinema") else [sys.executable, "-m", "tinycinema"]

    def tc(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return run([*prefix, tinycinema, *args] if prefix else [tinycinema, *args], timeout)

    section("1. Dependencies")
    ff = shutil.which("ffmpeg")
    check("ffmpeg on PATH", bool(ff), ff or "brew install ffmpeg", fatal=True)
    play = shutil.which("ffplay")
    optional("ffplay on PATH", bool(play), play or "", "not found -> playback will be silent")
    probe = shutil.which("ffprobe")
    optional("ffprobe on PATH", bool(probe), probe or "",
             "not found -> falls back to parsing 'ffmpeg -i'")
    try:
        import yt_dlp

        optional("yt-dlp importable", True, yt_dlp.version.__version__)
    except ImportError:
        optional("yt-dlp importable", False, "", "not installed -> pip install '.[youtube]'")

    section("2. Rendering (no media needed)")

    out = tc("--demo", "mandelbrot", "--width", "40", "--height", "12")
    lines = out.stdout.rstrip("\n").split("\n")
    check(
        "generated pattern renders",
        out.returncode == 0 and len(lines) == 12 and all(len(x) == 40 for x in lines),
        f"{len(lines)} rows" if out.returncode == 0 else out.stderr.strip()[:120],
    )
    check("piped output has no escape codes", "\x1b" not in out.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "verify.mp4"

        section("3. Real ffmpeg decode")
        made = run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
        ])  # fmt: skip
        if not check("built a test clip", made.returncode == 0, made.stderr.strip()[:160]):
            summarise()
            return 1

        out = tc(str(clip), "--once", "--width", "50", "--height", "14", "--no-audio")
        check("decoded a real frame", out.returncode == 0 and len(out.stdout) > 100,
              out.stderr.strip()[:160])

        out = tc(str(clip), "--verbose", "--once", "--width", "20", "--height", "6")
        detected = "audio=True" in out.stderr
        check("detected the audio track", detected,
              fail_hint="probe saw no audio -> the audio clock would never engage")

        section("4. Every render mode")
        rendered: dict[str, str] = {}
        for mode in ("ascii", "ascii-color", "blocks", "halfblock", "braille",
                     "kitty", "iterm", "sixel"):
            out = tc(str(clip), "--once", "--width", "30", "--height", "10",
                     "--mode", mode, "--no-audio")
            ok = out.returncode == 0 and len(out.stdout) > 20
            if ok:
                rendered[mode] = out.stdout
            # Bytes, not characters: len() on text-mode output counts codepoints,
            # which makes every character mode look identically sized.
            size = len(out.stdout.encode()) if ok else 0
            check(f"mode {mode}", ok, f"{size} bytes",
                  fail_hint=out.stderr.strip()[:100])

        # Distinct output proves --mode is actually taking effect, which a
        # per-mode "it didn't crash" check does not. ascii and ascii-color are
        # excluded from each other: piped output carries no colour, and colour
        # is the only thing that separates them, so identical here is correct.
        distinct = {m: v for m, v in rendered.items() if m != "ascii-color"}
        check("modes produce distinct output",
              len(set(distinct.values())) == len(distinct),
              f"{len(set(distinct.values()))}/{len(distinct)} distinct",
              fail_hint="two modes rendered identically -- is --mode being honoured?")
        if "ascii" in rendered and "ascii-color" in rendered:
            check("ascii-color matches ascii when piped",
                  rendered["ascii"] == rendered["ascii-color"],
                  "colour is dropped for a pipe, so the text is the same")

        section("5. Timed playback (real terminal)")
        if play:
            print(f"  {DIM}(you should hear a 440Hz tone for about 4 seconds){RESET}")
        code, stats = run_pty(
            [*prefix, tinycinema, str(clip), "--stats", "--no-hud"]
            if prefix
            else [tinycinema, str(clip), "--stats", "--no-hud"]
        )
        line = next((x for x in stats.split("\n") if "rendered" in x), "").strip()
        rendered = 0
        if line:
            import re as _re

            m = _re.search(r"rendered (\d+) frames", line)
            rendered = int(m.group(1)) if m else 0
        check("played to completion", code == 0, line[:150] or stats.strip()[:150])
        # 4s at 30fps is ~120 frames. A single frame means --once was implied,
        # i.e. the timing loop never ran at all.
        check("the timing loop actually ran", rendered > 60, f"{rendered} frames",
              fail_hint=f"only {rendered} frames -- playback did not run")
        check("kept up with the clock", "(0.0%)" in line or "dropped 0 " in line,
              fail_hint=line[:150])
        if play:
            optional("audio clock engaged", "clock=audio" in stats or rendered > 60,
                     "", "could not confirm -- rerun with --verbose to see the clock")

        section("6. yt-dlp fetch")
        if not url:
            skip("URL playback", "pass a YouTube URL as an argument to test this")
        else:
            out = tc(url, "--quality", "360", "--once", "--width", "50", "--height", "14",
                     "--verbose", timeout=300)
            check("resolved and played a URL", out.returncode == 0 and len(out.stdout) > 100,
                  out.stderr.strip().split("\n")[-1][:160] if out.returncode else "")

    summarise()
    print(f"\n{DIM}Anything that failed: rerun that one command with --verbose.{RESET}")
    return 1 if any(not ok for _, ok, _ in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
