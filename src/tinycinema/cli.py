"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .audio import BACKENDS, make_clock
from .playlist import expand
from .render import RAMPS, RenderOptions, available_modes
from .sources import (
    DEFAULT_QUALITY,
    PATTERNS,
    DecodeError,
    FFmpegMissingError,
    ResolveError,
    UnsupportedSourceError,
    YtDlpMissingError,
    open_source,
    parse_quality,
)
from .term import Terminal, Terminated, detect_capabilities

EPILOG = """\
examples:
  tinycinema clip.mp4              play a local file
  tinycinema "https://youtu.be/..."   play a YouTube video
  tinycinema --demo                built-in test pattern, no media needed
  tinycinema clip.mp4 --mode braille --no-color
  tinycinema clip.mp4 --once       render a single frame and exit
  tinycinema --doctor              check ffmpeg and terminal support

keys during playback:
  space pause    q quit        r/R cycle render mode   , . frame step
  h HUD          c colour      s subtitles             m mute   -/= volume
  j/l seek -/+10s              arrows seek -/+5s / -/+60s
  n/p next/previous in a playlist

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
    p.add_argument("source", nargs="*", default=[],
                   help="file(s), directory, URL, or - for stdin")

    g = p.add_argument_group("input")
    g.add_argument("--demo", nargs="?", const="ball", choices=PATTERNS,
                   metavar="PATTERN", help=f"generated test pattern ({', '.join(PATTERNS)})")
    g.add_argument("--start", type=parse_time, default=0.0, metavar="TIME",
                   help="start at a timestamp (seconds, MM:SS or HH:MM:SS)")
    g.add_argument("--loop", action="store_true", help="repeat forever")
    g.add_argument("--quality", type=parse_quality, default=DEFAULT_QUALITY, metavar="H",
                   help=f"max height to fetch for URLs, e.g. 360 or 720p "
                        f"(default: {DEFAULT_QUALITY})")
    g.add_argument("--no-cache", dest="cache", action="store_false",
                   help="stream URLs instead of downloading them first")
    g.add_argument("--shuffle", action="store_true", help="randomise playlist order")

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

    g = p.add_argument_group("audio")
    g.add_argument("--no-audio", dest="audio", action="store_false",
                   help="play silently (video still syncs to a wall clock)")
    g.add_argument("--volume", type=int, default=100, metavar="0-100")
    g.add_argument("--audio-backend", default="auto", choices=list(BACKENDS),
                   help="audio sink to use (default: auto)")

    g = p.add_argument_group("subtitles")
    g.add_argument("--subs", metavar="FILE", help="an .srt or .vtt file to display")
    g.add_argument("--no-subs", dest="subtitles", action="store_false",
                   help="don't look for or show subtitles")

    g = p.add_argument_group("output")
    g.add_argument("--no-hud", dest="hud", action="store_false", help="hide the status bar")
    g.add_argument("--once", action="store_true", help="render one frame and exit")
    g.add_argument("--stats", action="store_true", help="print a timing summary on exit")
    g.add_argument("--record", metavar="OUT.cast",
                   help="record playback to an asciinema v2 file")
    g.add_argument("--frames", dest="frames_dir", metavar="DIR",
                   help="write each rendered frame to DIR as plain text")

    g = p.add_argument_group("misc")
    g.add_argument("-v", "--verbose", action="store_true",
                   help="explain what is being resolved, fetched and run (stderr)")
    g.add_argument("--doctor", action="store_true", help="check dependencies and terminal support")
    g.add_argument("--clear-cache", action="store_true", help="delete downloaded videos and exit")
    g.add_argument("--version", action="version", version=f"tinycinema {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from .log import note, set_verbose

    set_verbose(args.verbose)

    if args.clear_cache:
        from .sources.ytdlp import clear_cache

        count, freed = clear_cache()
        print(f"removed {count} file(s), freed {freed / 1e6:.1f} MB")
        return 0

    if args.doctor:
        from .doctor import run_doctor

        return run_doctor()

    if not args.source and not args.demo:
        parser.print_help()
        return 2

    items = expand(args.source, shuffle=args.shuffle) if args.source else [None]
    if not items:
        print("tinycinema: nothing to play in that directory", file=sys.stderr)
        return 1

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

    # Import late so `--doctor` and `--help` still work if something here is broken.
    from .player import PlaybackOptions, Player

    playback = PlaybackOptions(
        mode=mode,
        render=render_opts,
        fps=args.fps,
        hud=args.hud,
        # With several items, --loop repeats the playlist rather than one file.
        loop=args.loop and len(items) == 1,
        start=args.start,
        once=once,
        stats=args.stats,
        width=args.width,
        height=args.height,
        audio=args.audio,
        volume=args.volume,
        playlist=len(items) > 1,
        record=args.record,
        frames_dir=args.frames_dir,
        subtitles=args.subtitles,
        subs_path=args.subs,
    )

    from .player import Stats

    status = 0
    totals = Stats(items=0)
    index = 0
    try:
        with Terminal(alt_screen=caps.is_tty and not once, hide_cursor=caps.is_tty) as term:
            while 0 <= index < len(items):
                spec = items[index]
                try:
                    source = open_source(
                        spec,
                        demo=args.demo,
                        fps=args.fps,
                        loop=playback.loop,
                        quality=args.quality,
                        use_cache=args.cache,
                    )
                except (
                    UnsupportedSourceError,
                    FFmpegMissingError,
                    YtDlpMissingError,
                    ResolveError,
                ) as exc:
                    print(f"tinycinema: {exc}", file=sys.stderr)
                    if len(items) == 1:
                        return 1
                    # One bad file shouldn't abandon the rest of the playlist.
                    status = 1
                    index += 1
                    continue

                note(
                    f"playing {source.info.title!r}: "
                    f"{source.info.width}x{source.info.height} "
                    f"{source.info.fps:.2f}fps "
                    f"dur={source.info.duration} audio={source.info.has_audio}"
                )
                clock = make_clock(
                    getattr(source, "target", spec),
                    source.info,
                    # A single frame has no timeline to sync to.
                    enabled=args.audio and not once,
                    backend=args.audio_backend,
                    volume=args.volume,
                    loop=playback.loop,
                )
                note(f"mode={mode} clock={type(clock).__name__}")
                try:
                    player = Player(source, term, playback, clock)
                    player.run()
                finally:
                    source.close()
                totals.merge(player.stats)
                totals.items += 1

                if player.exit_reason == "quit" or once:
                    break
                index += -1 if player.exit_reason == "prev" else 1
                if args.loop and len(items) > 1:
                    index %= len(items)
    except KeyboardInterrupt:
        status = 130
    except Terminated as exc:
        # The terminal has already been restored by Terminal.__exit__ on the
        # way out; report the conventional 128+signal status.
        status = exc.exit_status
    except DecodeError as exc:
        print(f"tinycinema: decode failed\n{exc}", file=sys.stderr)
        status = 1

    if args.stats and totals.items:
        s = totals
        total = s.rendered + s.dropped
        drop_pct = (100.0 * s.dropped / total) if total else 0.0
        scope = f" across {s.items} files" if s.items > 1 else ""
        print(
            f"\nrendered {s.rendered} frames in {s.elapsed:.1f}s{scope} "
            f"({s.fps:.1f} fps), dropped {s.dropped} ({drop_pct:.1f}%), "
            f"{s.reopens} pipeline restarts, {s.bytes_written / 1e6:.2f} MB written "
            f"({s.bytes_written / max(s.rendered, 1) / 1024:.1f} KB/frame)",
            file=sys.stderr,
        )

    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
