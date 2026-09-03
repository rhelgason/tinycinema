# tinycinema — design notes

Braindump of the whole idea before writing code. Nothing here is final; it's the
menu we order from. Decisions that are actually locked in are marked **DECIDED**.

> **Status:** Phases 0-5 are built. Section 15 records what the plan got right
> and wrong for Phases 0-1; section 16 explains the ffmpeg dependency; section 17
> covers Phase 2 (audio); section 18 covers Phases 3-5.

---

## 1. What it is

A terminal video player. You point it at a local file or a YouTube URL and it
plays the video *inline in your terminal* — colored Unicode cells for picture,
real audio out of your speakers, and the two stay in sync.

```
$ tinycinema bad-apple.mp4
$ tinycinema "https://youtube.com/watch?v=dQw4w9WgXcQ" --quality 480p
$ cat clip.mp4 | tinycinema -
```

Non-goals (keeps scope honest):
- Not a general media player. No transcoding, no library management, no GUI.
- Not a video editor.
- Not trying to look *good* at 4K. Trying to look surprisingly good at 200×50 cells.

---

## 2. Architecture

The core insight: this is four loosely-coupled stages plus a clock. Keep them
behind interfaces and every feature later becomes a plug-in rather than a rewrite.

```
                       ┌──────────────────────────────────────┐
   source              │              CLOCK                   │
   (file/URL/stdin)    │  audio playback position = truth     │
        │              └──────────────┬───────────────────────┘
        ▼                             │ now()
  ┌───────────┐                       │
  │ Resolver  │  URL → direct stream URL (yt-dlp), file → path
  └─────┬─────┘                       │
        ▼                             │
  ┌───────────┐   audio packets   ┌───┴────────┐
  │  Demuxer  ├──────────────────►│ AudioSink  │──► speakers
  │ (ffmpeg)  │                   └────────────┘
  └─────┬─────┘
        │ video frames (RGB, pre-scaled to cell grid)
        ▼
  ┌───────────┐      ┌───────────┐      ┌────────────┐
  │ FrameQueue├─────►│  Encoder  ├─────►│  Terminal  │──► your eyeballs
  │ (bounded) │      │ (px→cells)│      │  (diffed)  │
  └───────────┘      └───────────┘      └────────────┘
        ▲                                      ▲
        └── drop frames when clock is ahead ────┘
```

Module boundaries I want:

| Module | Responsibility | Swappable because… |
|---|---|---|
| `sources/` | anything → a seekable/streamable media handle | file vs YouTube vs stdin vs webcam vs test-pattern |
| `decode/` | demux + decode + scale to target cell grid | ffmpeg subprocess vs PyAV bindings |
| `render/` | RGB ndarray → bytes to write | ascii / halfblock / quadrant / braille / kitty |
| `audio/` | play a stream, report position | ffplay vs sounddevice vs mpv |
| `term/` | raw mode, size, diffing, write batching | one impl, but isolate all the escape-code ugliness |
| `player.py` | the loop that ties it together | — |

**The one rule that keeps this sane:** the decoder always hands the renderer a
frame *already scaled to the exact pixel dimensions the current render mode
wants*. Scaling is ffmpeg's job (it's SIMD-optimized and free), never ours.

---

## 3. Rendering — the fun part

There's a whole ladder of fidelity here. Building them all is cheap once the
`Renderer` interface exists (`render(rgb_array) -> str`), and being able to flip
between them with a keypress is a killer demo.

### The ladder

| Mode | Cell content | Pixels/cell | Color | Notes |
|---|---|---|---|---|
| `ascii` | ` .:-=+*#%@` | 1×1 | none | the classic; good for `--no-color` and pipes |
| `ascii-color` | ramp char, colored fg | 1×1 | 24-bit fg | ramp adds perceived detail on top of color |
| `blocks` | `█` or space, bg color | 1×1 | 24-bit bg | flat, blocky, but color-accurate |
| **`halfblock`** | `▀` fg=top px, bg=bottom px | **1×2** | 24-bit ×2 | **DECIDED: the default.** Free 2× vertical res, square-ish pixels |
| `quadrant` | `▘▝▖▗▚▐▄…` | 2×2 | 2 colors/cell | needs per-cell 2-color quantization |
| `sextant` | `🬀`–`🬻` (U+1FB00) | 2×3 | 2 colors/cell | best pure-text density; font support is spotty |
| `braille` | `⠀`–`⣿` (U+2800) | 2×4 | 1 fg color | highest spatial res, but effectively 1-bit + tint. Great for line art / Bad Apple |
| `kitty` | actual PNG/RGB chunks | real pixels | true | "cheat mode" — Kitty graphics protocol |
| `iterm` | inline image escape | real pixels | true | iTerm2 `ESC ]1337;File=` |
| `sixel` | sixel bitmap | real pixels | palette | xterm, foot, WezTerm, Windows Terminal |

Why `halfblock` as default: it's the best fidelity-per-compatibility ratio.
Every terminal from the last decade renders `▀` and truecolor, and a terminal
cell is roughly 1:2 aspect ratio — so one `▀` cell holding two stacked pixels
gives you *square pixels* for free. No aspect correction hacks needed.

### Aspect ratio

Cells are ~2:1 tall:wide. Effective pixel grid for a `cols × rows` terminal:

- `ascii`/`blocks`: `cols × rows` pixels, each pixel 2× taller than wide → must
  squash vertically by 2 when scaling, or everything looks stretched.
- `halfblock`: `cols × 2·rows` → pixels are square. Just fit-to-box.
- `braille`: `2·cols × 4·rows` → pixels are square (2:1 cell × 4/2 subdivision).

Letterbox to preserve source aspect. Reserve bottom N rows for the HUD (opt-out
with `--no-hud` for a clean recording).

### Color → character mapping

- Luminance: use Rec. 709 (`0.2126R + 0.7152G + 0.0722B`), not a naive average.
  Optionally gamma-correct before ramping — sRGB values are not linear light and
  a naive ramp crushes the midtones.
- Apply the ramp *after* a configurable contrast/gamma knob (`--gamma`,
  `--contrast`) — CLI video almost always wants punchier contrast than the source.
- For `ascii-color`, character comes from luminance, color from the pixel. Cheap
  and it reads much better than either alone.
- For `quadrant`/`sextant`: per-cell, this is 2-means clustering over 4–6 pixels
  to pick fg/bg, then a bitmask selects the glyph. Small enough to brute force.
- `braille`: threshold per-cell (Otsu or fixed) → 8-bit mask → `0x2800 + mask`.
  Add Floyd–Steinberg or ordered (Bayer) dithering; it makes a *huge* difference
  on gradients and is what makes braille mode look good instead of blotchy.

### Character ramp choices

Ship a few, selectable via `--ramp`:
- `blocks`: ` ░▒▓█` — smoothest luminance steps, best for photo content
- `standard`: ` .:-=+*#%@` — the classic
- `long`: the 70-char `$@B%8&WM#*oahkbdpq…` ramp — more steps, noisier
- `binary`: ` █` — for high-contrast/silhouette content

The "correct" ramp is font-dependent (it's really about ink coverage per glyph).
Possible stretch: a `--calibrate` mode that renders glyphs offscreen and sorts
them by measured coverage. Very over-engineered. Very fun.

---

## 4. Terminal throughput — where naive implementations die

Do the math. A 200×50 grid in halfblock truecolor, painted naively:

```
"\x1b[38;2;255;255;255m\x1b[48;2;255;255;255m▀"  ≈ 42 bytes/cell
200 × 50 × 42                                    ≈ 420 KB/frame
× 30 fps                                         ≈ 12.6 MB/s
```

That will choke most terminal emulators (and *definitely* chokes over SSH). The
bottleneck is almost never decode — it's bytes-to-terminal and the emulator's
own parse+shape+raster cost. Mitigations, roughly in order of payoff:

1. **Diff against the previous frame.** Only emit cells that changed. Typical
   video has 60–90% inter-frame cell coherence at low resolution. Biggest single
   win, by far.
2. **Coalesce SGR sequences.** Don't re-emit the color if the run of cells shares
   it. Track current fg/bg as renderer state and only emit deltas. Combined with
   #1, a talking-head shot drops to a few KB/frame.
3. **Cursor-position runs.** Changed cells cluster. Emit `\x1b[row;colH` once per
   run of contiguous changes rather than per cell.
4. **One `write()` per frame.** Build the whole frame into a `bytearray`, one
   syscall. Never `print()` per cell.
5. **Synchronized output** — wrap each frame in `\x1b[?2026h` … `\x1b[?2026l`.
   Terminals that support it won't present a half-drawn frame; kills tearing.
6. **Frame skip on backpressure.** If the write blocks or the clock has moved
   past the next frame's PTS, drop it. Never queue up debt.
7. **Cap the render rate independently of source fps** (`--fps 24`). A 60fps
   source doesn't need 60 repaints.

Escape-code hygiene: alt screen (`\x1b[?1049h`), hide cursor (`\x1b[?25l`), and a
`finally:`/atexit that *always* restores — including on `SIGINT`, `SIGTERM`, and
uncaught exceptions. Nothing sours a demo like a wrecked terminal. Restore raw
mode via `termios` snapshot.

---

## 5. Audio

Yes, audio is completely doable — the terminal is just a display surface; the
process can open an audio device like anything else.

### Options

| Approach | Pros | Cons |
|---|---|---|
| **`ffplay -nodisp -vn` subprocess** | trivial; handles any codec; separate process = no GIL contention | position must be inferred from wall clock; startup latency varies; extra dep |
| `sounddevice`/PyAudio + PyAV decode | exact sample-accurate position from frames written; no subprocess | must resample; must manage the ring buffer; PortAudio dep |
| `mpv --no-video --idle` + IPC socket | rock solid, gives you exact `time-pos`, seeking, gapless | heavy dep; JSON-IPC plumbing |

**Plan:** start with `ffplay` (fastest to a working demo), design the
`AudioSink` interface around `position() -> float` so swapping to `sounddevice`
later — which gives a genuinely better clock — is a one-file change.

```python
class AudioSink(Protocol):
    def start(self, t: float = 0.0) -> None: ...
    def position(self) -> float: ...   # seconds of audio actually played
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
```

### A/V sync — audio is the master clock

Humans notice audio glitches instantly and dropped video frames barely at all.
So: **audio plays uninterrupted, video chases it.** Never the reverse.

```
for frame in decoded_frames:
    lag = clock.now() - frame.pts
    if lag > DROP_THRESHOLD:   # ~2 frame intervals behind → skip, don't render
        stats.dropped += 1
        continue
    if lag < 0:                # ahead of the clock → wait
        sleep(-lag)
    render(frame)
```

- Sleep with a hybrid: `time.sleep(remaining - 1ms)` then spin, because Python's
  sleep granularity is ~1–15ms depending on platform and that's visible jitter.
- On a big desync (seek, suspend/resume, laptop lid), *resync* rather than
  crawling: flush the frame queue and jump to the nearest frame ≥ clock.
- If there's no audio track, fall back to a monotonic wall clock started at t=0.
- Show real fps / dropped-frame count in the HUD. Cheap, and it makes the
  performance work visible and satisfying.

---

## 6. Input sources

Design the input layer as `source → (video stream, audio stream, metadata)` so a
local file and a URL are genuinely interchangeable.

- **Local file** — anything ffmpeg reads.
- **YouTube / 1000+ other sites** — `yt-dlp` resolves a URL to direct media URLs.
  Two modes:
  - *stream*: hand the direct URL straight to ffmpeg (instant start, no disk)
  - *cache*: download to `~/.cache/tinycinema/<video-id>.<fmt>` first, so replays
    and seeks are instant and offline. Worth an LRU eviction with a size cap.
  Let `--quality` pick a format so we're not pulling 4K to render 200×50 cells.
  `worstvideo[height>=360]+bestaudio` is genuinely the right selector here —
  we're downscaling to postage-stamp size anyway, so a small format is *better*:
  faster start, less bandwidth, identical output.
- **stdin** (`-`) — for `curl … | tinycinema -`. No seeking.
- **Webcam** (`--device 0` → avfoundation/v4l2) — silly, delightful, ~10 lines.
- **Image / GIF** — same pipeline, trivially free.
- **Test pattern** (`tinycinema --demo`) — SMPTE bars / plasma / a bouncing ball,
  generated in-process. Lets someone try the tool with zero dependencies and zero
  media, and it's the perfect renderer unit-test fixture.

---

## 7. UX / controls

Raw mode keyboard, single-key:

| Key | Action |
|---|---|
| `space` / `k` | pause / resume |
| `←` / `→` | seek −/+ 5s |
| `↓` / `↑` | seek −/+ 60s |
| `j` / `l` | seek −/+ 10s (mpv/YouTube muscle memory) |
| `,` / `.` | frame step back/forward while paused |
| `-` / `=` | volume down / up |
| `m` | mute |
| `r` | cycle render mode (ascii → halfblock → braille → …) — the demo move |
| `c` | toggle color |
| `h` | toggle HUD |
| `f` | toggle fit mode (contain / cover / stretch) |
| `s` | save current frame as ANSI text / PNG |
| `q` / `ctrl-c` | quit |

HUD (bottom 1–2 rows): title, `01:23 / 04:56`, a seek bar, fps, dropped frames,
render mode. Draw it as an overlay in the same diff buffer, not with separate
writes.

**Resize** — `SIGWINCH` handler sets a flag; the loop notices, recomputes the
grid, tears down and restarts the scaler at the new size, and force-repaints
(invalidate the whole diff buffer). Debounce it — drag-resizing fires dozens of
events and restarting ffmpeg's scaler each time will stutter badly. Handling
resize *mid-playback without dying* is one of the three genuinely hard parts.

---

## 8. CLI surface

```
tinycinema [SOURCE] [options]

Input
  SOURCE                 file path, URL, or - for stdin
  --demo                 built-in test pattern, no media needed
  --device N             webcam
  --start TIME           start at timestamp
  --loop                 repeat forever

Video
  --mode MODE            ascii|ascii-color|blocks|halfblock|quadrant|braille|kitty|auto
  --ramp NAME            blocks|standard|long|binary
  --width N / --height N override auto-detected grid
  --fps N                cap render rate
  --no-color             monochrome
  --gamma F --contrast F --brightness F
  --dither TYPE          none|ordered|floyd
  --fit MODE             contain|cover|stretch

Audio
  --no-audio
  --volume 0-100
  --audio-backend        ffplay|sounddevice|mpv

Output
  --hud / --no-hud
  --record OUT.cast      write an asciinema recording
  --frames DIR           dump per-frame ANSI text (for GIF-building)
  --once                 render one frame and exit (thumbnails in scripts!)

Misc
  --quality Q            yt-dlp format preference
  --cache / --no-cache
  --stats                print timing summary on exit
  --doctor               check ffmpeg/yt-dlp/terminal capabilities and report
```

`--doctor` is worth building early — "why doesn't it work" is going to be
99% missing ffmpeg, and a good diagnostic beats a stack trace.

`--once` is sneakily the most *useful* feature: it makes tinycinema composable
with `ls`, `fzf`, file managers, git hooks — anywhere you want a thumbnail.

---

## 9. Terminal capability detection (`--mode auto`)

Probe, in order, and pick the best available:

1. `$TERM_PROGRAM == "iTerm.app"` → iterm inline images
2. `$TERM` contains `kitty`, or `$KITTY_WINDOW_ID` set → kitty graphics
3. Query `\x1b[c` (Primary DA) and look for `4` in the response → sixel
4. `$COLORTERM in (truecolor, 24bit)` → halfblock truecolor
5. `$TERM` ends in `-256color` → halfblock, quantized to the 256-color cube
6. otherwise → plain ascii, no color

Also: not a TTY (`not sys.stdout.isatty()`) → plain ascii, no escapes, no raw
mode, no HUD. Makes `tinycinema x.mp4 > out.txt` do something sensible.

Cache the probe result; DA queries need a timeout so we don't hang on terminals
that never answer.

---

## 10. Stack decision

**DECIDED: Python 3.11+.** Reasoning:

- `yt-dlp` *is* a Python library — the YouTube half becomes an import, not a
  subprocess-and-parse-JSON dance.
- The heavy lifting (decode, colorspace convert, scale) is all inside ffmpeg
  regardless of host language. We're not writing the hot loop, we're gluing.
- The actual per-frame Python work is pure array math, which is `numpy`
  vectorized → C speed. Rough budget for 200×50 halfblock @ 30fps: ~10k cells,
  a few numpy ops + one string build. Comfortably inside the 33ms budget.
- Fastest path to a thing that works and is fun to iterate on, which for a side
  project is the whole ballgame. `pipx install tinycinema` is a fine story.

Escape hatches if Python bites us: `Cython`/`numba` on the encoder hot loop,
or rewrite `render/` in Rust via `maturin` while keeping the Python shell.

Considered and set aside:
- **Rust** — genuinely the "right" language for throughput and single-binary
  distribution (`cargo install`, no runtime). But `yt-dlp` has no good native
  equivalent, ffmpeg bindings are heavier to work with, and iteration is slower.
  A worthy v2 if this turns out to be more than a weekend.
- **Go** — nice concurrency story for the decode/render/audio split, single
  binary, but weakest media ecosystem of the three.
- **Node** — fine, but numpy has no real peer for the pixel math.

### Dependencies

| Dep | Why | Required? |
|---|---|---|
| `ffmpeg` (binary) | decode/scale everything | **yes** — hard requirement, check at startup |
| `numpy` | frame math | yes |
| `yt-dlp` | URL resolution | optional extra `[youtube]` |
| `av` (PyAV) | in-process decode; better seeking than pipes | optional, phase 2 |
| `sounddevice` | better audio clock | optional extra `[audio]` |
| `click`/`typer` | CLI | yes (or stdlib argparse to stay dep-free) |
| `rich` | *not* using — need raw byte control, and it fights us | no |

Ship as `pyproject.toml` + `hatchling`, console script `tinycinema` (+ short
alias `tcin`). `uv tool install` / `pipx install` as the install story.

---

## 11. Roadmap

Each phase should end in something demoable — that's what keeps a side project alive.

**Phase 0 — skeleton**
`pyproject.toml`, package layout, `--doctor`, `--demo` test pattern, terminal
setup/teardown that never wrecks your shell. Ends with: a bouncing ball in ASCII.

**Phase 1 — silent local playback**
ffmpeg subprocess → raw rgb24 over a pipe → numpy → halfblock renderer → diffed
writer. Wall-clock timing with frame drop. Ends with: **a local mp4 actually plays.**

**Phase 2 — audio + sync**
`ffplay` audio sink, audio-as-master-clock, drop/wait logic, pause/quit keys.
Ends with: **a music video plays in sync.** This is the "wow" moment; get here fast.

**Phase 3 — YouTube**
yt-dlp resolution, format selection, cache dir, progress during fetch.
Ends with: `tinycinema <youtube-url>` works.

**Phase 4 — polish**
Full keymap, seeking, HUD + seek bar, SIGWINCH resize, `--once`, alternate render
modes with the `r` hotkey, dithering.

**Phase 5 — pretty**
kitty/iterm/sixel modes, `--calibrate`, `--record` to asciinema, `--frames` → GIF,
README demo assets, PyPI release, CI.

**Stretch / silly ideas** (the stuff that makes it shareable)
- `tinycinema --screensaver` — plays something after N seconds idle
- SSH-able: `ssh tinycinema.example.com` and it just plays. Very telnet-star-wars.
- Subtitle rendering (`.srt` / embedded), which is *easy* and nobody expects it
- Playlists / `--shuffle` over a directory
- Bad Apple as the canonical benchmark + a `make badapple` target
- ANSI art export → paste into a README (dogfooding our own demo assets)
- A tiny built-in HTTP server so `--record` output can be shared as a webpage

---

## 12. The three genuinely hard parts

Naming them up front so they don't ambush us.

1. **A/V sync.** Mitigated by the audio-is-master architecture, but the details
   (drop thresholds, sleep granularity, resync after seek) are where the tuning
   time goes.
2. **Terminal throughput.** The diff + SGR-coalescing writer is the highest-value
   code in the project. Build it carefully; it's also the most testable piece
   (golden-file tests on emitted byte sequences — no video needed).
3. **Resize mid-playback.** Every stage holds a size assumption. Isolate size
   into one object that gets rebuilt atomically.

Runners-up: teardown correctness on every exit path; the ffmpeg subprocess
lifecycle (zombie processes, broken pipes, deadlocking on a full stderr buffer —
*always* drain stderr on a thread).

---

## 13. Testing

Mostly it looks untestable, but the important parts aren't:

- **Renderer**: fixed RGB array in → exact expected string out. Golden files.
- **Diff writer**: two frames in → assert emitted bytes are minimal & correct.
- **Ramp/luminance**: property tests (monotonic — brighter pixel never maps to a
  lighter-ink glyph).
- **Clock/drop logic**: inject a fake clock, assert the exact drop/wait decisions.
- **Sources**: mock yt-dlp; a tiny 2-second checked-in test clip for integration.
- **Smoke**: `tinycinema --demo --once` in CI across macOS/Linux, py3.11–3.14.

---

## 14. Naming

Repo is already **tinycinema** — good name, keep it. Command: `tinycinema`,
alias `tcin`. Tagline candidates:

- "Your terminal is a movie theater."
- "Video, but make it text."
- "A cinema that fits in 80×24."

Other names considered, kept here for a future rename or a sibling project:
`asciiplex`, `termflix`, `catflix`, `pixelvomit`, `glyphstream`, `cellophane`,
`ANSItheater`, `moviecat`, `vt100-video`, `blockbuster` (this one is very good).

---

## 15. What Phases 0–1 actually taught us

Written after the fact. The plan above was mostly right; these are the places it
wasn't, and the things that only showed up with real frames moving.

### The plan held up

- **Half-block as the default** is exactly as good as hoped.
- **Audio-as-master-clock shaped correctly.** Phase 1 uses a wall clock, but the
  loop is written against a single `now()`, so Phase 2 replaces one method call.
- **The diffed writer is the whole ballgame.** Measured at 160×48: 38.6 KB/frame
  for half-block, 0.8 KB/frame for ascii. A naive repaint would be ~250 KB.
- **Testing works out better than expected.** 159 tests, none needing video or a
  terminal. Golden byte strings for the writer, exact grids for the renderers,
  and a fake clock for the timing loop.

### What the plan missed

**Pixel aspect leaks past the renderer.** Section 3 has the aspect maths, but
treats it as a rendering concern. It isn't — the *decoder* has to know, because
ffmpeg does the scaling. `force_original_aspect_ratio=decrease` assumes square
pixels, so ascii mode came out squeezed into half the width and stretched to
twice the height. Fixed by having each renderer publish `pixel_aspect` and
passing it into `open()`, where the fit is computed in the filtergraph from
ffmpeg's `dar` variable. Doing it in-graph rather than in Python also means it
still works when ffprobe is missing and we don't know the source dimensions.

**numpy scalar indexing, not bytes, was the encoder bottleneck.** Section 4 is
all about byte volume, and byte volume does matter — but the first cut spent
15 ms/frame in Python before writing anything, because `int(fg[r, c, 0])` costs
~2 µs and there are 7680 cells. Two fixes got it to 10 ms: pack each cell's two
colours into one `int64` (so the diff and the run-splitting are single vectorised
comparisons and the SGR cache keys on a plain int), and iterate *spans of
constant colour* rather than cells, bulk-converting with `tolist()` first. The
neat trick: uint32 codepoints already *are* UTF-32, so a row of characters
reinterprets as a Python string via `.view(f"U{cols}")` with no per-char `chr()`.

**SIGWINCH is not sufficient for resize.** It is never delivered to a process
with no controlling terminal, and a missed resize leaves the picture permanently
wrong. Now the size is polled every frame (an ioctl, ~1 µs) and the signal is
just a latency hint. The debounce the plan called for turned out to be essential:
a 20-event drag storm collapses to one pipeline restart.

**Zero frames is ambiguous.** ffmpeg producing nothing means failure at the start
of a stream but plain EOF after a seek — and without ffprobe there's no duration
to clamp the seek target against, so seeking past the end is routine, not
exotic.

**Queued keystrokes need to survive a restart.** Anything that changes the cell
grid (mode switch, HUD toggle, seek) tears down and reopens the pipeline. The
first cut returned from the key handler immediately and dropped whatever was
still queued, so pressing `r` three times advanced one mode.

### Still open

- 10 ms/frame for a fully-changing half-block frame is a third of the 30 fps
  budget. The remaining cost is building colour escapes for cells whose colour
  the cache has never seen — unavoidable for photographic content in Python, so
  this is the natural place for Cython or a Rust `render/`.
- Braille needs adaptive thresholding. A fixed cutoff plus dithering turns smooth
  gradients into speckle; the demo assets need `--contrast 6` to look right,
  which real content shouldn't have to.
- No ffprobe means no duration, so no progress bar and no seek clamping. Worth a
  fallback that estimates duration from the container.

---

## 16. Why ffmpeg is a hard dependency — **DECIDED**

For a project whose appeal is "I built a video player", leaning on ffmpeg
deserves a straight answer rather than a shrug. Recorded here because the
question will come back.

### What ffmpeg is actually asked to do

Exactly five jobs, in one subprocess:

| # | Job | Could we? |
|---|---|---|
| 1 | Demux the container (MP4/MKV box parsing) | Yes, a few hundred lines |
| 2 | **Decode H.264 / HEVC / VP9 / AV1** | **No — see below** |
| 3 | YUV 4:2:0 → RGB | Yes, 0.44 ms in numpy |
| 4 | Scale + letterbox to the cell grid | Yes |
| 5 | Normalise to a constant frame rate | Yes |

And what it does *not* touch: the pixel→glyph mapping, the diffed writer, A/V
sync, frame dropping, capability detection, raw mode, resize. All of that — the
part that makes this project this project — is ours. ffmpeg is not a video
*player*; it is a codec and container library, filling the same role a PNG
decoder fills in an image viewer.

Only item 2 is genuinely load-bearing, and it is not a component of this project
so much as a different, much larger one. The H.264 spec runs to ~800 pages;
libavcodec's decoder for it alone is tens of thousands of lines of C. CABAC is
strictly serial per-bit, and that is before motion compensation across reference
frames, deblocking and B-frame reordering. It is also patent-encumbered.

### What pure Python *could* manage (measured)

Worth knowing, because the answer is more encouraging than expected. The serial
bit-reading that entropy decoding demands — the part that cannot be vectorised —
runs at **8.4 M bits/s ≈ 0.84 M coefficients/s** in CPython. Everything
downstream vectorises and is nearly free (IDCT over 1350 blocks: **0.25 ms**;
YUV→RGB at 320×180: **0.44 ms**).

For an MJPEG-class codec that works out to:

| Resolution | Max fps | |
|---|---:|---|
| 200×100 (terminal-sized) | 150 | comfortable |
| 320×180 | 52 | workable |
| 640×360 | 13 | too slow |
| 1920×1080 | 1.4 | hopeless |

The interesting part: **we render to ~200×100 pixels**, so we never needed to
decode 1080p. At the resolutions this project actually consumes, hand-written
decoders for Y4M, GIF, PNG/APNG, MJPEG/AVI and WAV (all stdlib + numpy, ~800
lines total) would be fast enough. That is a real option and it stays on the
table as a `sources/native/` backend — `sources/` is behind an interface
precisely so it can drop in without a rewrite.

### The decision

**ffmpeg stays a hard requirement.** Being able to point the thing at any video
file on disk is worth more than decoder purity, and the decode layer is not
where this project's interest lies. numpy stays too: it is an array primitive
that knows nothing about video or terminals, and without it the per-pixel and
per-cell work is ~50× slower, which puts 30 fps out of reach entirely.

yt-dlp (Phase 3) is a different matter — a whole site-scraping framework — and
stays an **optional extra**, not a base dependency.


---

## 17. What Phase 2 (audio) actually taught us

The claim in section 15 was that swapping the wall clock for audio would be a
one-method change. That held: the loop still asks `clock.now()` once per frame
and the diff to `player.py` is small. Everything interesting was in the clock.

### Measured

Against a simulated audio device (a stand-in that emits ffplay's status format
and, importantly, freezes under SIGSTOP the way a real device does):

| | |
|---|---|
| interpolation error when a fresh report lands | **2.7 ms** mean, 13.5 ms max |
| video offset from the audio clock, full pipeline | **±1 ms** mean, 24 ms max |
| frames shown, 5s @30fps, all render modes | **149/149**, zero drops |
| backwards jumps in the timeline | **0** |

The drop threshold is 50 ms, so there is a comfortable margin.

### Four bugs the plan didn't anticipate

**`Clock.resume()` restarted the audio process.** It called `self.start()`,
which dispatches to the subclass override, which relaunches ffplay. Every pause
therefore paid a fresh device startup latency and desynced the very thing it had
just paused. Fixed with a non-virtual `_rebase()`; resume() uses that, start()
stays polymorphic. A textbook "don't call overridable methods from a base class"
trap, and invisible without measuring.

**Returning the reported position verbatim makes a staircase.** The obvious
implementation — `now()` returns whatever the sink last said — pins the timeline
between reports, so it advances in 30 ms steps. That is most of a frame interval
at 30fps. The sink already knows *when* it observed each value, so the fix was to
report `(position, observed_at)` and always interpolate. 34 ms → 2.7 ms.

**The fallback branch had no "only once" guard.** After giving up on audio it
re-based the wall-clock origin on *every* call, which pinned the timeline at the
start position forever — a worse failure than the one it was there to prevent.

**A stale pre-pause report survives resume.** Relying on each sink to clear its
own is fragile, so the clock now records an anchor floor at every start/resume
and rejects observations older than it. Otherwise the clock extrapolates
straight through the entire pause.

### Decisions worth recording

- **A resize must not restart audio.** Every size or mode change rebuilds the
  video pipeline; doing that to the audio device too would be an audible click
  for no reason. Only a seek restarts audio, and after a video-only restart the
  decoder is reopened at wherever the audio has *got to*, not where video
  stopped.
- **Video waits for audio to actually start.** The clock holds at the start
  position until the first real report, so the two begin aligned instead of
  video running 250 ms ahead. This looks like a bug in a naive drift measurement
  and is in fact the entire point.
- **The timeline is monotonic.** A late report behind our extrapolation stalls
  the clock rather than rewinding it; rewinding makes the player re-wait frames
  it has already shown.
- **Failure degrades, never freezes.** Parsing a human-readable progress line is
  fragile, so if nothing parses within 1 s — or the sink is already dead — the
  clock silently becomes a wall clock and playback continues. Worst case is
  Phase 1 behaviour. The HUD shows `audio` or `wall*` so which one is in charge
  is never a mystery.

### Still open

- **ffplay's behaviour under SIGSTOP/SIGCONT is unverified against the real
  binary.** The simulated device stalls its position while stopped, which is
  what a real audio device should do, but a real ffplay might absorb the paused
  interval and jump forward on resume. If it does, the fix is to stop and
  restart the sink at the exact position instead of signalling it.
- Live volume and mute need either a restart or a different backend; deferred to
  Phase 4, where volume already lives.
- A `sounddevice` backend would give a sample-accurate position and remove the
  status-line parsing entirely, at the cost of a PortAudio dependency. Worth it
  only if ffplay proves flaky in practice.


---

## 18. What Phases 3-5 taught us

### Phase 3 — YouTube

The plan said "resolve a URL, then stream or cache". What it missed is *why*
caching has to be the default: YouTube serves video and audio as separate DASH
streams, and tinycinema runs two processes over the same media (ffmpeg for
pictures, ffplay for sound). Two processes cannot each open half of a DASH pair
and stay in sync.

So the default downloads and muxes once, after which the file is indistinguishable
from any local file and nothing downstream is special-cased. `--no-cache` still
works, but only by asking for a *progressive* format — one URL carrying both
streams — which is a real constraint worth stating rather than a preference.

The design note about fetching low quality on purpose turned out to be even more
right than written: at ~200x100 rendered pixels, 480p and 1080p are
byte-identical on screen, so the default is 480p.

### Phase 4 — polish

**Frame stepping exposed a latent bug in pause.** The loop checked for pause
*after* pulling a frame from the decoder, so a single step advanced two: one for
the step, one for the repaint behind it. Checking before consuming, and
repainting the last shown frame rather than a fresh one, fixed it. This was
invisible during normal playback, which is why it survived Phases 1-2.

**Volume is where ffplay's lack of IPC finally bites.** It takes its volume at
launch and offers no way to change it, so every adjustment relaunches the
process at the current position. Debouncing collapses a burst of keypresses into
one restart; without that, holding a volume key shreds the audio. This is the
strongest argument yet for a `sounddevice` backend.

**KeyReader busy-waited on a pipe.** `poll()` returned instantly when stdin was
not a terminal, so the paused idle loop pinned a core. Honouring the timeout
regardless fixed it.

### Phase 5 — real pixels

**Bandwidth, not fidelity, is the constraint.** A 200x50-cell terminal is
1600x800 physical pixels; raw RGB at 30fps is 115 MB/s, which no terminal will
take. Capping at 180k pixels and letting the terminal scale up makes these modes
merely expensive. Measured at 96x28 through the full player:

| | bytes/frame | encode | notes |
|---|---:|---:|---|
| kitty | 337 KB | 0.5 ms | raw RGB, so heavy on the wire |
| iterm | 42 KB | 0.8 ms | PNG, 8x lighter for one extra millisecond |
| sixel | 29 KB | 15.2 ms | lightest and most portable, slowest to encode |

All three hold 30fps with zero drops. The wire cost is the thing to watch over
SSH, where kitty's 10 MB/s would be hopeless and sixel's 0.9 MB/s would not.

**The sixel encoder needed the same lesson as the cell encoder in Phase 1.** The
obvious run-length loop steps once per pixel: 384px x ~100 colours x 37 bands is
1.4M Python iterations, measured at 42ms a frame — more than the entire 30fps
budget. Finding run boundaries with `diff()` makes it proportional to runs
instead: 42ms -> 15ms, and letterbox bars become nearly free. Twice now the fix
has been "stop iterating per pixel"; it is worth assuming this is the answer
next time too.

**A deliberate deviation from section 9.** That section had `--mode auto` climb
the whole ladder to kitty/iTerm2/sixel when available. Built and looked at, that
is the wrong default: the premise of this project is video rendered out of
characters, and silently substituting a bitmap defeats it. `auto` now stops at
`halfblock`, image modes are explicit, and `--doctor` advertises which ones work.
There is a test pinning this so it cannot drift back.

Relatedly, `r` cycles only through modes the terminal can actually display.
Cycling into sixel on a terminal that cannot decode it sprays garbage.

### Still open

- Sixel's remaining 15ms is the per-colour pass over each band. Fewer palette
  entries or a smarter grouping would help; 66fps is enough for now.
- Live volume still costs an audio gap. A `sounddevice` backend would fix that
  and the status-line parsing in one go, at the cost of a PortAudio dependency.
- No PyPI release yet.
