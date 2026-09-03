#!/usr/bin/env python3
"""A stand-in for ffplay, so the audio sink can be tested without a sound card.

Emits the same stderr status line the real one does, and -- importantly --
tracks *played* time by accumulating while it runs rather than reading a wall
clock. A real audio device behaves the same way: stop the process and its
position freezes, because no more samples are being consumed. A wall-clock fake
would leap forward on resume and hide exactly the bug we care about.

Flags mirror the subset the sink actually passes, plus a few for steering:
  --duration SECS      how long to "play" for
  --startup-delay S    simulated device warm-up before the first report
  --silent             never print status, to exercise the clock's fallback
  --absorb-pause       advance by wall time, so a SIGSTOP is silently absorbed
"""

import argparse
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("-i", dest="input")
ap.add_argument("-ss", dest="start", type=float, default=0.0)
ap.add_argument("-volume", type=int, default=100)
ap.add_argument("-loglevel", default="info")
ap.add_argument("-loop", type=int, default=None)
ap.add_argument("--duration", type=float, default=5.0)
ap.add_argument("--startup-delay", type=float, default=0.15)
ap.add_argument("--silent", action="store_true")
ap.add_argument("--absorb-pause", action="store_true")
for flag in ("-hide_banner", "-nodisp", "-autoexit", "-vn", "-sn"):
    ap.add_argument(flag, action="store_true")
args, _unknown = ap.parse_known_args()

time.sleep(args.startup_delay)

played = 0.0
last = time.perf_counter()
TICK = 0.03  # ffplay refreshes its status about this often

while played < args.duration:
    time.sleep(TICK)
    now = time.perf_counter()
    step = (now - last) if args.absorb_pause else min(now - last, TICK * 3)
    played += step
    last = now
    if not args.silent:
        sys.stderr.write(
            f"{played:7.2f} M-A:  0.000 fd=   0 aq=   17KB vq=    0KB sq=    0B f=0/0   \r"
        )
        sys.stderr.flush()
