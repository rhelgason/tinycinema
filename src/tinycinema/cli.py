"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .render import RAMPS, RenderOptions, available_modes
from .sources import PATTERNS, DecodeError, FFmpegMissingError, UnsupportedSourceError, open_source
from .term import Terminal, detect_capabilities

EPILOG = """\
examples:
  tinycinema clip.mp4              play a local file
  tinycinema --demo                built-in test pattern, no media needed
  tinycinema clip.mp4 --mode braille --no-color
  tinycinema clip.mp4 --once       render a single frame and exit
  tinycinema --doctor              check ffmpeg and terminal support

keys during playback:
  space pause    q quit      r/R cycle render mode
  h HUD          c colour    j/l seek -/+10s     arrows seek -/+5s / -/+60s

note: when stdout is not a terminal, --once is implied and output is plain text.
"""


def parse_time(value: str) -> float:
    """Accept seconds, MM:SS, or HH:MM:SS."""
    parts = value.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad timestamp: {value!r}") from None
    if len(nums) > 3:
        raise argparse.ArgumentTypeError(f"bad timestamp: {value!r}")
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tinycinema",
        description="Play video in your terminal.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", nargs="?", help="file path, direct media URL, or - for stdin")

    g = p.add_argument_group("input")
    g.add_argument("--demo", nargs="?", const="ball", choices=PATTERNS,
                   metavar="PATTERN", help=f"generated test pattern ({', '.join(PATTERNS)})")
    g.add_argument("--start", type=parse_time, default=0.0, metavar="TIME",
                   help="start at a timestamp (seconds, MM:SS or HH:MM:SS)")
    g.add_argument("--loop", action="store_true", help="repeat forever")

    g = p.add_argument_group("video")
    g.add_argument("--mode", default="auto", choices=["auto", *available_modes()],
                   help="render mode (default: auto)")
    g.add_argument("--ramp", default="blocks", choices=sorted(RAMPS),
                   help="luminance ramp for the character modes")
    g.add_argument("--width", type=int, metavar="N", help="override grid width in cells")
    g.add_argument("--height", type=int, metavar="N", help="override grid height in cells")
    g.add_argument("--fps", type=float, metavar="N", help="cap the render rate")
    g.add_argument("--no-color", dest="color", action="store_false", help="monochrome output")
    g.add_argument("--brightness", type=float, default=0.0, metavar="F", help="-1.0 to 1.0")
    g.add_argument("--contrast", type=float, default=1.0, metavar="F", help="1.0 is unchanged")
    g.add_argument("--gamma", type=float, default=1.0, metavar="F", help="1.0 is unchanged")
    g.add_argument("--dither", default="none", choices=["none", "ordered"],
                   help="dithering for the low-bit-depth modes")
    g.add_argument("--threshold", type=float, default=0.5, metavar="F",
                   help="on/off cutoff for braille mode")

    g = p.add_argument_group("audio (Phase 2 -- not implemented yet)")
    g.add_argument("--no-audio", action="store_true", help="currently a no-op; playback is silent")

    g = p.add_argument_group("output")
    g.add_argument("--no-hud", dest="hud", action="store_false", help="hide the status bar")
    g.add_argument("--once", action="store_true", help="render one frame and exit")
    g.add_argument("--stats", action="store_true", help="print a timing summary on exit")

    g = p.add_argument_group("misc")
    g.add_argument("--doctor", action="store_true", help="check dependencies and terminal support")
    g.add_argument("--version", action="version", version=f"tinycinema {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.doctor:
        from .doctor import run_doctor

        return run_doctor()

    if not args.source and not args.demo:
        parser.print_help()
        return 2

    caps = detect_capabilities()
    mode = caps.best_mode() if args.mode == "auto" else args.mode
    # A pipe can't render colour or move a cursor, so a single plain frame is the
    # only sensible thing to emit.
    once = args.once or not caps.is_tty

    render_opts = RenderOptions(
        ramp=args.ramp,
        color=args.color and (caps.truecolor or caps.color256),
        brightness=args.brightness,
        contrast=args.contrast,
        gamma=args.gamma,
        threshold=args.threshold,
        dither=args.dither,
    )

    try:
        source = open_source(args.source, demo=args.demo, fps=args.fps, loop=args.loop)
    except (UnsupportedSourceError, FFmpegMissingError) as exc:
        print(f"tinycinema: {exc}", file=sys.stderr)
        return 1

    # Import late so `--doctor` and `--help` still work if something here is broken.
    from .player import PlaybackOptions, Player

    playback = PlaybackOptions(
        mode=mode,
        render=render_opts,
        fps=args.fps,
        hud=args.hud,
        loop=args.loop,
        start=args.start,
        once=once,
        stats=args.stats,
        width=args.width,
        height=args.height,
    )

    status = 0
    player = None
    try:
        with Terminal(alt_screen=caps.is_tty and not once, hide_cursor=caps.is_tty) as term:
            player = Player(source, term, playback)
            status = player.run()
    except KeyboardInterrupt:
        status = 130
    except DecodeError as exc:
        print(f"tinycinema: decode failed\n{exc}", file=sys.stderr)
        status = 1
    finally:
        source.close()

    if args.stats and player is not None:
        s = player.stats
        total = s.rendered + s.dropped
        drop_pct = (100.0 * s.dropped / total) if total else 0.0
        print(
            f"\nrendered {s.rendered} frames in {s.elapsed:.1f}s "
            f"({s.fps:.1f} fps), dropped {s.dropped} ({drop_pct:.1f}%), "
            f"{s.reopens} pipeline restarts, {s.bytes_written / 1e6:.2f} MB written "
            f"({s.bytes_written / max(s.rendered, 1) / 1024:.1f} KB/frame)",
            file=sys.stderr,
        )

    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
