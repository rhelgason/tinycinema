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

## First run on a new machine

Six steps, cheapest first. Each proves something the one before it didn't, so
whichever fails first is the layer to look at — nothing after it will work.

**1 — What's installed?**

```bash
tinycinema --doctor
```

Exits non-zero if something *required* is missing. `ffprobe` and `ffplay` are
warnings rather than failures: without ffprobe the duration is parsed out of
`ffmpeg -i` instead, and without ffplay playback is simply silent.

The bottom of the output is a glyph and colour test. All four glyph rows should
look distinct; if the braille row is empty boxes your font lacks those glyphs,
so stick to `--mode halfblock`. The colour strip should be a smooth gradient,
not banded.

**2 — Render with no media at all.**

```bash
tinycinema --demo
```

Needs neither ffmpeg nor a file — the frames are generated in numpy. A bouncing
ball, with a status bar along the bottom. Press <kbd>r</kbd> a few times to
cycle render modes, then <kbd>q</kbd>. If this works and step 4 doesn't, your
problem is ffmpeg, not the renderer.

**3 — Walk the whole real-hardware path.**

```bash
git clone https://github.com/rhelgason/tinycinema.git   # if you installed as a tool
cd tinycinema
python tools/verify.py
```

This is the one command worth running on new hardware, and it lives in the
repo rather than in the installed package — clone it even if you installed with
`uv tool install`. It walks six layers in order, cheapest first: dependencies,
rendering with no media, a real ffmpeg decode of a clip it builds itself, all
eight render modes, four seconds of timed playback under a real pty, and a
yt-dlp fetch if you pass it a URL. Each line names its layer, so a failure says
*what* broke rather than just that something did:

```
5. Timed playback (real terminal)
---------------------------------
  [PASS] played to completion  rendered 119 frames in 4.0s (30.0 fps), dropped 0
         (0.0%), 0 pipeline restarts, 1.54 MB written (12.6 KB/frame)
  [PASS] the timing loop actually ran  119 frames
  [PASS] kept up with the clock
```

`dropped 0 (0.0%)` is what a healthy machine looks like. Anything under a few
percent is fine; a large number means the terminal can't keep up — see the
table below.

**4 — A real file, with sound.**

```bash
tinycinema clip.mp4
```

Look at the right-hand end of the status bar. It ends with the render mode and
the **clock source**, which is the single most useful thing on screen:

| It says | Meaning |
|---|---|
| `audio` | ffplay is playing and the video is syncing to it — the good case |
| `wall` | no audio track, `--no-audio`, or no ffplay; video runs on elapsed time |
| `wall*` | audio *was* expected but the sink never reported, so it gave up on it |

`wall*` on a file that definitely has sound is the one result worth reporting —
rerun it with `--verbose` to see the exact ffplay command and its output.

**5 — Prove the interactive parts.**

<kbd>space</kbd> to pause, <kbd>.</kbd> to step a frame, <kbd>space</kbd> again.
Then <kbd>l</kbd> to seek forward, <kbd>r</kbd> to change mode, <kbd>-</kbd> and
<kbd>=</kbd> for volume, and **resize the window while it plays** — the picture
should rebuild at the new size without the audio stuttering. <kbd>q</kbd> quits;
the terminal should come back exactly as you left it, cursor and all.

**6 — YouTube.**

```bash
tinycinema "https://www.youtube.com/watch?v=FtutLA63Cp8" --quality 360 --verbose
python tools/verify.py "https://www.youtube.com/watch?v=FtutLA63Cp8"
```

Needs the `youtube` extra. The first run downloads and caches; `--verbose`
prints the resolved format and the cache path. `--clear-cache` cleans up after.

### When something is wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| `ffmpeg not found on PATH` | not installed, or installed somewhere odd | `brew install ffmpeg`, or point `TINYCINEMA_FFMPEG` at the binary |
| Plays, but silent | no ffplay, or the file has no audio track | check the ffplay line in `--doctor`; `--verbose` prints the ffplay command |
| Status bar says `wall*` | ffplay launched but never reported a position | rerun with `--verbose`; playback still works, just unsynced |
| Choppy, or `--stats` shows heavy drops | terminal can't absorb the bytes | `--fps 15`, a smaller window, or `--mode ascii` (~1 KB/frame against ~43 for halfblock at 200×50) |
| Especially bad over SSH | same, plus the network | `--mode ascii` or `--mode blocks`; `--doctor` warns when it detects SSH |
| Everything is monochrome | `NO_COLOR` is set, or the terminal isn't truecolor | check the colour line in `--doctor`; <kbd>c</kbd> toggles colour at runtime |
| Braille mode shows empty boxes | the font has no braille glyphs | use `--mode halfblock`, or install a font that has them |
| An image mode sprays garbage | that terminal doesn't really support it | `--doctor` lists the ones it detected; image modes are never chosen by `auto` |
| Picture is squashed or stretched | should not happen — the aspect fit is per-mode | worth an issue, with the mode and your terminal |
| Piping produces one frame | working as intended | a pipe implies `--once` and plain text. To capture every frame, run it in a real terminal with `--frames DIR` (which is where the loop actually runs) or `--record out.cast` |
| Terminal left broken after a crash | should not happen — restore is in `atexit` *and* a signal handler | `reset`, then an issue please |

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

# subtitles are picked up automatically: clip.srt, clip.en.vtt,
# or a subtitle stream inside the container
tinycinema clip.mkv
tinycinema clip.mp4 --subs elsewhere.srt

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
| <kbd>s</kbd> | toggle subtitles |
| <kbd>h</kbd> | toggle HUD |
| <kbd>q</kbd> / <kbd>esc</kbd> | quit |

Keys are read in cbreak mode, so <kbd>ctrl-c</kbd> still works, and a burst is
never collapsed — holding <kbd>r</kbd> cycles through as many modes as you
pressed.

### The status bar

```
|> big-buck-bunny ━━━━━━━━━━━━━━━━━──────────────  01:12 / 09:56  30fps  halfblock  audio
│  │              │                                │              │      │          │
│  │              │                                │              │      │          └ clock source
│  │              │                                │              │      └ render mode
│  │              │                                │              └ measured fps, and drops if any
│  │              │                                └ position
│  │              └ progress
│  └ title
└ playing / paused
```

The last field is the one to watch when something looks off: `audio` means the
video is syncing to the audio device, `wall` means it's running on elapsed time
(no audio track, `--no-audio`, or no ffplay), and `wall*` means audio was
expected but the sink never reported a position, so it gave up and fell back.

<kbd>h</kbd> hides the bar; `--no-hud` starts without it, which is what you
want for `--record`.

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

--subs FILE       an .srt or .vtt to display
--no-subs         don't look for or show subtitles

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
--frames DIR      dump each rendered frame (.txt, or .png for an image mode)
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

## Known limitations

- **POSIX only.** The terminal layer uses `termios`/`tty`, so macOS and Linux
  work and Windows does not. WSL is fine.
- **A YouTube *playlist* URL plays only its first video.** Local directories
  expand to every file in them; remote playlists don't, because expanding one
  needs a network round trip during argument parsing.
- **Changing volume causes a brief gap in the audio.** ffplay takes its volume
  at launch and has no IPC, so each change relaunches it. Rapid changes are
  debounced into a single restart.
- **Image modes are bandwidth-hungry.** Comfortable locally, painful over SSH —
  kitty is ~10 MB/s at 30fps. Use `--fps 15`, or `sixel` at ~0.9 MB/s.
- **Audio-only files are refused**, with a message saying so — there is
  nothing to display. A visualiser would be a different project.
- **Live streams** report no duration, so there's no progress bar and seeking is
  limited to what the server allows.

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

pytest                              # 490 tests, no video, ffmpeg, audio or network
python tools/make_demo_assets.py    # regenerate the README images
tinycinema --demo --stats           # quick smoke test
```

`tools/verify.py` exists because of what the test suite deliberately *doesn't*
touch — see [First run on a new machine](#first-run-on-a-new-machine) for what
it checks and how to read its output.

The test suite itself needs no media, ffmpeg, sound card or network connection —
88% coverage, and the parts that genuinely need something on the other end get a
committed fake ffplay, `os.pipe()` and `pty.openpty()` rather than being skipped: the writer is verified with golden byte strings, the renderers with
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
