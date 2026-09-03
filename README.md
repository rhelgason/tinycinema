<div align="center">

# 🎬 tinycinema

**Your terminal is a movie theater.**

Play videos — local files or YouTube links — directly in your terminal, with sound.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#roadmap)

</div>

---

> [!NOTE]
> **Feature complete through Phase 5.** Local files, YouTube links, directories
> and playlists all play with sound, in sync, across five character modes and
> three inline-image protocols. The full design write-up, including everything
> considered and rejected, is in [DESIGN.md](DESIGN.md).

---

## Demo

Everything below is real renderer output, produced by
[`tools/make_demo_assets.py`](tools/make_demo_assets.py) from the built-in
`mandelbrot` test pattern — no media files, no ffmpeg, no screenshots.
Regenerate at any time with `python tools/make_demo_assets.py`.

<div align="center">

#### `--mode halfblock` — the default

<img src="docs/demo-halfblock.png" width="640" alt="The Mandelbrot set rendered in half-block mode">

Two independently coloured pixels per character cell, via `▀`.

<br>

#### `--demo bars` — check your terminal's colour handling

<img src="docs/demo-bars.png" width="640" alt="Colour bars and a greyscale ramp rendered in half-block mode">

</div>

#### `--mode ascii` — one character per cell, from a luminance ramp

```
............:::::---------------------------====+*%*#+=-----------::::::::::::
..........:::::---------------------------====++*#=#*+===-----------::::::::::
.........::::---------------------------=====+*%    %%*=====----------::::::::
.........::--------------------------=====++++**     #*++======---------::::::
........::----------------------=====+*###*#.#        *##%++***==--------:::::
.......::------------------==========+*%  -               %  =*+==--------::::
.......:--------------=============+%%*                     %*++==---------:::
......:------------===+*++++*+++++++##                       -#*#=----------::
......----------======+*#*%*#:##****%                         %*+=-----------:
......--------======++**#%       %##                           %+=-----------:
.....-------=====++%***%                                      %+==-----------:
.....-====+++++++**#%                                        #+===-----------:
.....-====+++++++**#%                                        #+===-----------:
.....-------=====++%***%                                      %+==-----------:
......--------======++**#%       %##                           %+=-----------:
......----------======+*#*%*#:##****%                         %*+=-----------:
......:------------===+*++++*+++++++##                       -#*#=----------::
.......:--------------=============+%%*                     %*++==---------:::
.......::------------------==========+*%  -               %  =*+==--------::::
........::----------------------=====+*###*#.#        *##%++***==--------:::::
.........::--------------------------=====++++*+     #*++======---------::::::
.........::::---------------------------=====+*%    %%*=====----------::::::::
..........:::::---------------------------====++*#=#*+===-----------::::::::::
............:::::---------------------------====+*%*#+=-----------::::::::::::
```

#### `--mode braille --contrast 6` — 2×4 dots per cell, the finest text can do

```
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡠⡀⡢⣊⣢⣺⣿⣿⠉⠀⠀⠀⠩⣹⣿⣪⡢⡀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣢⣾⣦⣾⣮⣾⣾⣿⣿⣿⡀⠀⠀⠀⣠⣾⣿⣿⣮⣮⣢⣊⣢⣢⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⡢⣺⣿⣿⡚⠿⢿⠿⠏⠟⠘⠀⠈⠁⠀⠈⠁⠈⠁⠛⢃⢿⣿⣿⣾⣿⣿⣮⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⡢⡊⣢⣾⣿⣿⡃⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠋⠀⠠⣿⡋⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⡀⡠⡀⡀⡀⡀⡀⡠⡀⣢⣊⣢⣺⣿⣟⠻⠏⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⢻⢿⣺⡢⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠠⡊⣿⣿⣮⣾⣪⣾⣾⣾⣮⣺⣪⣾⣾⣿⡿⠧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠟⢿⣿⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡢⣺⣻⣿⣿⡿⢿⡿⣟⠛⣿⢿⣿⣿⣿⣿⡑⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠰⣿⣯⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣨⣪⣺⣾⣿⡿⠀⠈⠁⠀⠀⠀⠈⠙⠻⣿⣗⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠠⣹⡯⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⡀⡠⡂⣢⣺⣾⣿⣿⣿⣿⡗⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⡿⡢⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⣀⣀⣀⣢⣲⣲⣾⣦⣮⣦⣾⣾⣾⣿⣿⠏⠉⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⣿⡊⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠈⠈⠊⠫⠻⠻⡻⡻⡛⡻⣻⣿⣿⣿⣿⣆⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣯⡊⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠊⠢⠊⠪⡺⣻⣿⣿⣿⣿⡧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣻⡢⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠚⣫⣻⣿⣿⣷⠀⢀⡀⠀⠀⠀⢀⣠⣴⣿⡯⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⣹⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠢⣺⣾⣿⣿⣷⣾⣷⣯⣤⣿⣾⣿⣿⣿⣿⡡⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠰⣿⣯⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡊⣿⣿⣿⣻⣻⣻⣿⣿⣻⣻⣫⣻⣿⣿⣶⡖⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣦⣾⣿⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠋⠋⠂⠊⠂⠈⠀⠈⠂⠊⡪⡊⡪⣻⣿⣯⣴⣆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠠⣼⣾⡻⡢⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠢⡊⡪⣻⣿⣿⡅⠀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⡄⠀⠐⣿⣎⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠢⣺⣿⣿⢥⣶⣾⣶⣆⣦⢠⠀⢀⡀⠀⢀⡀⢀⡀⣤⡌⣾⣿⣿⣿⣿⣿⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⡻⡻⡻⣻⣻⣿⣿⣿⣿⠁⠀⠀⠀⠙⢿⣿⣿⣿⡛⡫⡊⡪⠚⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠊⠢⡊⡪⣺⣿⣿⣀⠀⠀⠀⣐⣹⣿⡚⠂⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
```

## Install

```bash
uv tool install "git+https://github.com/rhelgason/tinycinema"
# or
pipx install "git+https://github.com/rhelgason/tinycinema"
```

Add the YouTube support with `"tinycinema[youtube] @ git+https://..."`, or skip
it if you only play local files.

For hacking on it:

```bash
git clone https://github.com/rhelgason/tinycinema.git
cd tinycinema
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Requirements

| | |
|---|---|
| **Python 3.11+** | |
| **numpy** | installed automatically |
| **ffmpeg** | required to play actual media (`--demo` works without it) |
| **ffplay** | ships with ffmpeg; without it playback is silent |
| **yt-dlp** | optional — only for YouTube and friends |
| **A truecolor terminal** | recommended; degrades to 256-colour and mono |

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian / Ubuntu
```

If your ffmpeg lives somewhere unusual, point at it with `TINYCINEMA_FFMPEG`
(and `TINYCINEMA_FFPROBE`, `TINYCINEMA_FFPLAY`).

Wondering why a "write your own video player" project shells out to ffmpeg at
all? [DESIGN.md §16](DESIGN.md) answers that in full — short version: ffmpeg
does demux and decode, and touches none of the pixel-to-glyph mapping, terminal
writing or A/V sync.

Run `tinycinema --doctor` to check your setup, see which render modes your
terminal supports, and eyeball a glyph and colour test.

## Usage

```bash
# no media handy? no ffmpeg? this still works
tinycinema --demo
tinycinema --demo mandelbrot

# a local file, with sound
tinycinema clip.mp4
tinycinema clip.mp4 --mode braille --contrast 3
tinycinema clip.mp4 --start 1:30 --loop
tinycinema clip.mp4 --no-audio --volume 50

# YouTube and ~1800 other sites (downloads and caches by default)
tinycinema "https://www.youtube.com/watch?v=FtutLA63Cp8"
tinycinema "https://youtu.be/..." --quality 720p
tinycinema "https://youtu.be/..." --no-cache        # stream instead

# a whole directory, or several files, shuffled
tinycinema ~/Videos --shuffle
tinycinema a.mp4 b.mkv c.webm

# real pixels, if your terminal can do it (see --doctor)
tinycinema clip.mp4 --mode kitty --fps 15

# record what you see
tinycinema clip.mp4 --record demo.cast --no-hud

# when something doesn't work, this prints the resolved format,
# the cache path and the exact ffmpeg/ffplay commands
tinycinema "https://youtu.be/..." --verbose

# a single frame — thumbnails for scripts
tinycinema clip.mp4 --once --start 00:01:30

# pipe it (implies --once, plain text, no escapes)
tinycinema clip.mp4 --once > frame.txt
```

Built-in test patterns: `ball`, `plasma`, `bars`, `mandelbrot`.

### Controls

| Key | Action |
|---|---|
| <kbd>space</kbd> / <kbd>k</kbd> | pause / resume |
| <kbd>←</kbd> <kbd>→</kbd> | seek ∓5s |
| <kbd>j</kbd> <kbd>l</kbd> | seek ∓10s |
| <kbd>↑</kbd> <kbd>↓</kbd> | seek ±60s |
| <kbd>,</kbd> <kbd>.</kbd> | step one frame back / forward (while paused) |
| <kbd>-</kbd> <kbd>=</kbd> | volume down / up |
| <kbd>m</kbd> | mute |
| <kbd>n</kbd> <kbd>p</kbd> | next / previous in the playlist |
| <kbd>r</kbd> / <kbd>R</kbd> | cycle render mode forward / back |
| <kbd>c</kbd> | toggle colour |
| <kbd>h</kbd> | toggle HUD |
| <kbd>q</kbd> / <kbd>esc</kbd> | quit |

### Options

```
text modes    ascii | ascii-color | blocks | halfblock | braille
image modes   kitty | iterm | sixel          (opt-in; see --doctor)

--mode MODE       one of the above, or auto (default: auto)
--ramp NAME       blocks | standard | long | binary
--width / --height    override the auto-detected cell grid
--fps N           cap the render rate
--no-color        monochrome output
--gamma / --contrast / --brightness
--dither          none | ordered
--threshold F     on/off cutoff for braille mode

--no-audio        play silently (video still syncs to a wall clock)
--volume 0-100
--audio-backend   auto | ffplay | none

--quality H       max height to fetch for URLs, e.g. 360 or 720p
--no-cache        stream URLs rather than downloading first
--shuffle         randomise playlist order
--start TIME      seconds, MM:SS or HH:MM:SS
--loop            repeat forever

--once            render one frame and exit
--no-hud          hide the status bar
--stats           print a timing summary on exit
--record OUT.cast write an asciinema recording
--frames DIR      dump each rendered frame as text
--doctor          diagnose ffmpeg, audio and terminal capabilities
--clear-cache     delete downloaded videos
-v, --verbose     explain what is being resolved, fetched and run
```

`--mode auto` deliberately never picks an image mode. The premise here is video
rendered out of *characters*; silently swapping in a bitmap would defeat it. Ask
for `--mode kitty` (or `iterm`, or `sixel`) explicitly — `--doctor` tells you
which your terminal supports.

Full list: `tinycinema --help`.

## How it works

```
source ──► resolve ──► ffmpeg demux/decode ──┬──► audio sink ──► 🔊
(file/URL)                                   │        │
                                             │        └── playback position = the clock
                                             │                      │
                                             └──► frames ──► encode ──► diffed writer ──► 📺
                                                   (drop if behind the clock)
```

Three ideas do most of the work:

**1. Half-block cells.** The character `▀` gives you two independently-coloured
pixels per terminal cell — 2× the vertical resolution, and it makes the effective
pixels *square*, since cells are about twice as tall as they are wide.

This turns out to matter everywhere. Each renderer declares its effective pixel
aspect (1.0 for half-block and braille, 0.5 for one-pixel-per-cell modes) and the
decoder divides through by it when letterboxing. Skip that step and ffmpeg's
`force_original_aspect_ratio` — which assumes square pixels — squeezes ascii mode
into half the width and stretches it to twice the height.

**2. Audio is the master clock.** People notice an audio glitch instantly and a
dropped video frame almost never. So audio plays uninterrupted and video chases
it, dropping any frame that would land more than ~1.5 frame intervals late. Never
accumulate debt: rendering every frame late is far worse than rendering most on
time.

The loop asks one question per frame — *what time is it in this movie?* — and the
answer comes from the audio device's real position, read out of ffplay's status
output and interpolated between reports. Two details make it feel right: video
**waits** for the device to actually start (so they begin aligned rather than
audio arriving 250 ms late), and the timeline is monotonic, so a late report
stalls it rather than rewinding frames you have already seen. If audio never
starts, it degrades to a wall clock and keeps playing rather than freezing.

**3. Only repaint what changed.** A naive full-colour repaint of a 200×50 grid is
~420 KB per frame — 12.6 MB/s at 30 fps, which chokes most terminals and is
hopeless over SSH. The writer diffs against the previous frame, coalesces SGR
colour escapes, and groups changed cells into runs so it pays one cursor-move per
run rather than one per cell.

Getting that fast in Python needed one more trick: per-cell numpy scalar indexing
costs ~2 µs a cell, which at 7680 cells is 15 ms a frame spent purely on boxing.
Packing each cell's two colours into a single `int64` makes the diff one
vectorised comparison, and since uint32 codepoints *are* UTF-32, a row of
characters reinterprets as a Python string via `.view()` for free.

Measured at 160×48 on a 30 fps source: **149/149 frames, 30.1 fps, zero drops**,
with video landing within **±1 ms** of the audio clock (drop threshold: 50 ms).

## Roadmap

- [x] **Phase 0** — project skeleton, `--doctor`, generated test patterns
- [x] **Phase 1** — silent playback of local files, seeking, HUD, resize handling
- [x] **Phase 2** — audio + A/V sync
- [x] **Phase 3** — YouTube URLs via yt-dlp, with an LRU download cache
- [x] **Phase 4** — frame stepping, volume, playlists, `--record`
- [x] **Phase 5** — Kitty/iTerm2/sixel inline images

Install straight from the repo; there is no PyPI release and no particular
reason for one while this is a personal project. `.github/workflows/release.yml`
is written and dormant — it only fires on a `v*` tag — if that ever changes.

## Development

```bash
python tools/verify.py              # first-run check on real hardware
python tools/verify.py "https://youtu.be/..."   # ...including a real fetch

pytest                              # 365 tests, no video, tty, audio or network
python tools/make_demo_assets.py    # regenerate the README images
tinycinema --demo --stats           # quick smoke test
```

`tools/verify.py` exists because of what the test suite deliberately *doesn't*
touch. It walks the real-hardware path in order — dependencies, rendering, a
real ffmpeg decode, every render mode, timed playback under a real pty, then a
yt-dlp fetch — so a failure tells you which layer broke rather than just that
something did.

The test suite itself needs no media, terminal, sound card or network
connection: the writer is verified with golden byte strings, the renderers with
exact cell grids, the image protocols by decoding their payloads back to pixels,
both clocks by hand-cranking them, and `ffmpeg -i` parsing against captured real
output in `tests/fixtures/`. yt-dlp is stubbed, and the cache is tested against
a real temporary directory.

## Contributing

Early days — issues and ideas are the most useful contribution right now.
[DESIGN.md](DESIGN.md) has the module layout, the full menu of render modes, and
an honest list of the parts that are genuinely hard.

## Prior art & thanks

Standing on the shoulders of a long line of terminal-video hacks — `mpv`'s
`--vo=tct`, `hasciicam`, `ascii-image-converter`, `chafa`, `timg`, `catimg`, and
of course the original `telnet towel.blinkenlights.nl`. `ffmpeg` and `yt-dlp` do
the actual heavy lifting.

## License

[MIT](LICENSE) © 2026 Ryan Helgason
