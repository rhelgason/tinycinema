"""Expanding command-line arguments into an ordered list of things to play."""

from __future__ import annotations

import os
import random
import re
from pathlib import Path

#: Containers ffmpeg will happily open. Used only to decide what to pick up when
#: someone points us at a directory -- an explicit filename is never filtered.
MEDIA_SUFFIXES = frozenset(
    """
    .mp4 .m4v .mkv .webm .mov .avi .flv .wmv .mpg .mpeg .ts .m2ts .ogv .3gp
    .gif .apng
    .mp3 .m4a .wav .flac .ogg .opus .aac .wma
    """.split()
)

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def is_url(spec: str) -> bool:
    return bool(_URL_RE.match(spec))


def expand(
    specs: list[str],
    *,
    shuffle: bool = False,
    recursive: bool = True,
    seed: int | None = None,
) -> list[str]:
    """Turn CLI arguments into a flat play order.

    Directories expand to the media files inside them, sorted naturally so
    `ep2` comes before `ep10`. URLs, `-` and explicit file paths pass straight
    through untouched -- if someone names a file, we play it, extension be
    damned.
    """
    items: list[str] = []
    for spec in specs:
        if spec == "-" or is_url(spec):
            items.append(spec)
            continue
        path = Path(os.path.expanduser(spec))
        if path.is_dir():
            items.extend(str(p) for p in _media_in(path, recursive=recursive))
        else:
            items.append(str(path) if path.exists() else spec)

    if shuffle:
        random.Random(seed).shuffle(items)
    return items


def _media_in(directory: Path, *, recursive: bool) -> list[Path]:
    walker = directory.rglob("*") if recursive else directory.glob("*")
    found = [
        p
        for p in walker
        if p.is_file()
        and p.suffix.lower() in MEDIA_SUFFIXES
        and not p.name.startswith(".")
    ]
    return sorted(found, key=lambda p: _natural_key(str(p)))


def _natural_key(text: str):
    """Sort so ep2 precedes ep10, which plain lexicographic order gets wrong."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]
