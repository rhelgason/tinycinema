#!/usr/bin/env python3
"""Render the README's animated demo: a built-in pattern, through the real renderer.

    python tools/make_motion_gif.py

Separate from `make_demo_assets.py` on purpose. That script is deliberately
ffmpeg-free so anyone can regenerate the stills, and CI enforces that its output
is current. Assembling a GIF needs ffmpeg, so it lives here and CI leaves both
this and `docs/demo-zoom.gif` alone.

Why the Mandelbrot zoom rather than `plasma` or `ball`: the smooth patterns are
diagnostics, not showcases -- `ball` reads as a green smudge, and `plasma` is a
full-frame colour churn that costs 3 MB as a GIF for something that looks like a
screensaver. The fractal is instantly recognisable, has hard edges at every
scale (which is what actually shows a renderer off), and compresses to under a
megabyte because most of the frame is flat.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from make_demo_assets import halfblock_pixels, write_png  # noqa: E402

from tinycinema.binaries import ffmpeg_path  # noqa: E402
from tinycinema.render import RenderOptions, create  # noqa: E402
from tinycinema.sources.demo import DemoSource  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=Path("docs/demo-zoom.gif"), type=Path)
    ap.add_argument("--pattern", default="mandelbrot")
    ap.add_argument("--cols", default=96, type=int)
    ap.add_argument("--rows", default=28, type=int)
    ap.add_argument("--fps", default=15.0, type=float)
    ap.add_argument("--seconds", default=6.0, type=float)
    ap.add_argument("--scale", default=6, type=int)
    ap.add_argument("--colors", default=128, type=int)
    args = ap.parse_args()

    exe = ffmpeg_path()
    if not exe:
        print("ffmpeg not found; this one asset needs it", file=sys.stderr)
        return 1

    renderer = create("halfblock", RenderOptions())
    width, height = renderer.pixel_size(args.cols, args.rows)
    frames = DemoSource(args.pattern, fps=args.fps, duration=args.seconds).open(
        width, height, pixel_aspect=renderer.pixel_aspect
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        count = 0
        for _pts, rgb in frames:
            count += 1
            write_png(
                tmp / f"f{count:04d}.png",
                halfblock_pixels(renderer.render(rgb)),
                scale=args.scale,
            )

        # Two passes: one palette for the whole clip, or each frame picks its own
        # and the colours crawl. `stats_mode=diff` weights it towards the moving
        # part rather than the flat background it would otherwise be dominated by.
        palette = tmp / "palette.png"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        for cmd in (
            [exe, "-y", "-loglevel", "error", "-i", str(tmp / "f%04d.png"),
             "-vf", f"palettegen=max_colors={args.colors}:stats_mode=diff", str(palette)],
            [exe, "-y", "-loglevel", "error", "-framerate", str(args.fps),
             "-i", str(tmp / "f%04d.png"), "-i", str(palette),
             "-lavfi", "paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(args.out)],
        ):  # fmt: skip
            subprocess.run(cmd, capture_output=True, check=True)

    kb = args.out.stat().st_size / 1024
    print(f"{args.out}  {kb:.0f} KB  ({count} frames, "
          f"{width * args.scale}x{height * args.scale}px, {args.colors} colours)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
