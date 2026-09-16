<div align="center">

# 🎬 tinycinema

**Your terminal is a movie theater.**

Play videos — local files or YouTube links — directly in your terminal, with sound.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](DESIGN.md)

<img src="docs/demo-zoom.gif" width="720" alt="A Mandelbrot zoom playing in a terminal, rendered in half blocks">

</div>

## Install

```bash
uv tool install "tinycinema[youtube] @ git+https://github.com/rhelgason/tinycinema"
# or, local files only:
uv tool install "git+https://github.com/rhelgason/tinycinema"
```

Needs **Python 3.11+** and **ffmpeg** (`brew install ffmpeg`). `--demo` works without ffmpeg. Point `TINYCINEMA_FFMPEG` at the binary if it isn't on `PATH`.

```bash
tinycinema --doctor    # check ffmpeg, audio, and the terminal
```

## Examples

```bash
tinycinema --demo
tinycinema clip.mp4
tinycinema "https://www.youtube.com/watch?v=FtutLA63Cp8"
```

`space` pause · `r` cycle modes · `q` quit. Everything else is in `tinycinema --help`.

<img src="docs/demo-halfblock.png" width="640" alt="The Mandelbrot set rendered in half-block mode">

<!-- Add a clip you actually like. Drop the file in docs/, uncomment, tweak the alt text.
<img src="docs/example-1.gif" width="640" alt="">
-->

<!--
<img src="docs/example-2.png" width="640" alt="">
-->

<!--
<img src="docs/example-3.gif" width="640" alt="">
-->

## Development

```bash
git clone https://github.com/rhelgason/tinycinema.git
cd tinycinema
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Design notes, including what was considered and rejected: [DESIGN.md](DESIGN.md).

## License

[MIT](LICENSE) © 2026 Ryan Helgason
