<div align="center">

# 🎬 tinycinema

**Your terminal is a movie theater.**

Play videos — local files or YouTube links — directly in your terminal, with sound.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: early](https://img.shields.io/badge/status-early%20development-orange.svg)](DESIGN.md)

</div>

---

> [!WARNING]
> **tinycinema is under active development and not yet usable.** The design is
> written up in [DESIGN.md](DESIGN.md); code is on the way. Stars and ideas
> welcome — working software is not here yet.

---

## Demo

<!-- TODO: replace with a real recording once Phase 2 lands.
     Plan: capture with asciinema (`tinycinema --record demo.cast`), convert with
     agg or vhs, and drop the result in docs/. Keep it under ~5 MB so GitHub
     renders it inline. -->

<div align="center">

_A demo GIF goes here once playback works._

<!-- ![tinycinema playing a video in a terminal](docs/demo.gif) -->

| ASCII | Half-block | Braille |
|:---:|:---:|:---:|
| _coming soon_ | _coming soon_ | _coming soon_ |

</div>

## What it does

- 🎥 **Plays video in your terminal** — colored Unicode cells, ~60fps capable
- 🔊 **With actual audio** — and it stays in sync (audio is the master clock)
- 📺 **YouTube URLs or local files** — same pipeline, interchangeable inputs
- 🎨 **Multiple render modes** — ASCII, half-block, braille, quadrants, and true
  inline images on terminals that support them (Kitty, iTerm2, sixel)
- ⌨️ **Real player controls** — pause, seek, volume, frame-step, mode switching
- 🪟 **Survives a window resize** mid-playback

## Install

> Not published yet. This is the intended install story.

```bash
# once released
uv tool install tinycinema      # or: pipx install tinycinema

# with YouTube support
uv tool install "tinycinema[youtube]"
```

### Requirements

| | |
|---|---|
| **ffmpeg** | required — does all decoding and scaling |
| **Python 3.11+** | |
| **A truecolor terminal** | recommended; degrades gracefully to 256-color and mono |

```bash
# macOS
brew install ffmpeg

# Debian / Ubuntu
sudo apt install ffmpeg
```

Run `tinycinema --doctor` to check your setup and see which render modes your
terminal supports.

## Usage

```bash
# a local file
tinycinema clip.mp4

# a YouTube link
tinycinema "https://www.youtube.com/watch?v=FtutLA63Cp8"

# no media handy? built-in test pattern
tinycinema --demo

# a single frame — thumbnails for scripts
tinycinema clip.mp4 --once --start 00:01:30

# pipe it
curl -sL https://example.com/clip.mp4 | tinycinema -
```

### Controls

| Key | Action |
|---|---|
| <kbd>space</kbd> | pause / resume |
| <kbd>←</kbd> <kbd>→</kbd> | seek ∓5s |
| <kbd>j</kbd> <kbd>l</kbd> | seek ∓10s |
| <kbd>,</kbd> <kbd>.</kbd> | frame step (while paused) |
| <kbd>-</kbd> <kbd>=</kbd> | volume |
| <kbd>m</kbd> | mute |
| <kbd>r</kbd> | cycle render mode |
| <kbd>h</kbd> | toggle HUD |
| <kbd>q</kbd> | quit |

### Options

```
--mode MODE       ascii | ascii-color | blocks | halfblock | quadrant
                  | braille | kitty | auto        (default: auto)
--ramp NAME       blocks | standard | long | binary
--fps N           cap the render rate
--no-color        monochrome output
--no-audio        video only
--quality Q       yt-dlp format preference (e.g. 480p)
--once            render one frame and exit
--doctor          diagnose ffmpeg / terminal capabilities
```

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

1. **Half-block cells.** The character `▀` gives you two independently-colored
   pixels per terminal cell — 2× the vertical resolution, and it makes the
   effective pixels square, since cells are about twice as tall as they are wide.

2. **Audio is the master clock.** People notice an audio glitch instantly and a
   dropped video frame almost never. So audio plays uninterrupted and video
   chases it, dropping frames whenever it falls behind.

3. **Only repaint what changed.** A naive full-color repaint of a 200×50 grid is
   ~420 KB per frame — 12 MB/s at 30fps, which chokes most terminals. Diffing
   against the previous frame and coalescing color escape sequences cuts that by
   one to two orders of magnitude.

The full write-up, including everything considered and rejected, is in
[DESIGN.md](DESIGN.md).

## Roadmap

- [ ] **Phase 0** — project skeleton, `--doctor`, `--demo` test pattern
- [ ] **Phase 1** — silent playback of local files
- [ ] **Phase 2** — audio + A/V sync 🎯 _the good part_
- [ ] **Phase 3** — YouTube URLs
- [ ] **Phase 4** — seeking, HUD, resize handling, alternate render modes
- [ ] **Phase 5** — inline image protocols, recording, PyPI release

## Contributing

Early days — issues and ideas are the most useful contribution right now.
If you want to write code, [DESIGN.md](DESIGN.md) has the module layout and the
list of things that are genuinely hard.

## Prior art & thanks

Standing on the shoulders of a long line of terminal-video hacks — `mpv`'s
`--vo=tct`, `hasciicam`, `ascii-image-converter`, `chafa`, `timg`, `catimg`,
`termvideo`, and of course the original `telnet towel.blinkenlights.nl`.
`ffmpeg` and `yt-dlp` do the actual heavy lifting.

## License

[MIT](LICENSE) © 2026 Ryan Helgason
