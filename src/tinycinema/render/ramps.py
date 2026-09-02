"""Luminance ramps and the tone adjustments applied before them.

The "correct" ramp is really a question of ink coverage per glyph in your font,
so there is no single right answer -- ship a few and let people pick.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

RAMPS: dict[str, str] = {
    # Smoothest luminance steps; best for photographic content.
    "blocks": " ░▒▓█",
    # The classic.
    "standard": " .:-=+*#%@",
    # More steps, but noisier -- glyph coverage is not actually monotonic here.
    "long": (
        " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
    ),
    # Silhouette content (Bad Apple, line art).
    "binary": " █",
}

DEFAULT_RAMP = "blocks"

# Rec. 709 luma coefficients. A naive (r+g+b)/3 average badly misjudges the
# apparent brightness of saturated colours -- green reads far brighter than blue.
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def get_ramp(name: str) -> str:
    try:
        return RAMPS[name]
    except KeyError:
        raise ValueError(
            f"unknown ramp {name!r}; choose from {', '.join(sorted(RAMPS))}"
        ) from None


def luminance(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) uint8 RGB -> (...) float32 luma in 0..1."""
    return (rgb.astype(np.float32) @ _LUMA) / 255.0


def adjust(
    lum: np.ndarray,
    *,
    brightness: float = 0.0,
    contrast: float = 1.0,
    gamma: float = 1.0,
) -> np.ndarray:
    """Tone-map normalised luma. CLI video almost always wants punchier contrast.

    Order matters: gamma first (it is about the transfer curve of the source),
    then contrast around mid-grey, then a flat brightness offset.
    """
    x = lum
    if gamma != 1.0:
        x = np.power(np.clip(x, 0.0, 1.0), 1.0 / gamma)
    if contrast != 1.0:
        x = (x - 0.5) * contrast + 0.5
    if brightness:
        x = x + brightness
    return np.clip(x, 0.0, 1.0)


def ramp_codepoints(ramp: str) -> np.ndarray:
    """The ramp *characters* as a uint32 codepoint lookup table."""
    return np.array([ord(ch) for ch in ramp], dtype=np.uint32)


@lru_cache(maxsize=16)
def ramp_table(name: str) -> np.ndarray:
    """Lookup table for a ramp by *name*. Cached; renderers call this per frame."""
    table = ramp_codepoints(get_ramp(name))
    table.flags.writeable = False  # shared across callers
    return table


def map_to_ramp(lum01: np.ndarray, ramp_cp: np.ndarray) -> np.ndarray:
    """Normalised luma -> ramp codepoints, vectorised."""
    n = ramp_cp.size
    idx = np.clip((lum01 * n).astype(np.int32), 0, n - 1)
    return ramp_cp[idx]
