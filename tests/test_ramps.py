import numpy as np
import pytest

from tinycinema.render.ramps import (
    RAMPS,
    adjust,
    get_ramp,
    luminance,
    map_to_ramp,
    ramp_table,
)


def test_get_ramp_rejects_unknown():
    with pytest.raises(ValueError, match="unknown ramp"):
        get_ramp("nope")


def test_luminance_uses_rec709_weights():
    """A naive average would rank these equally; Rec. 709 must not."""
    pure = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8)
    lum = luminance(pure)[0]
    assert lum[1] > lum[0] > lum[2]  # green brightest, blue darkest
    assert lum[0] == pytest.approx(0.2126, abs=1e-3)


def test_luminance_range():
    assert luminance(np.zeros((1, 1, 3), np.uint8))[0, 0] == pytest.approx(0.0)
    assert luminance(np.full((1, 1, 3), 255, np.uint8))[0, 0] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("name", sorted(RAMPS))
def test_ramp_mapping_is_monotonic(name):
    """Brighter input must never map to an earlier (lighter-ink) ramp glyph."""
    table = ramp_table(name)
    lum = np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(1, -1)
    codes = map_to_ramp(lum, table)[0]
    positions = [int(np.flatnonzero(table == c)[0]) for c in codes]
    assert positions == sorted(positions)


@pytest.mark.parametrize("name", sorted(RAMPS))
def test_ramp_mapping_hits_both_ends(name):
    table = ramp_table(name)
    lum = np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(1, -1)
    codes = map_to_ramp(lum, table)[0]
    assert codes[0] == table[0]
    assert codes[-1] == table[-1]


def test_ramp_mapping_clamps_out_of_range():
    table = ramp_table("standard")
    lum = np.array([[-5.0, 5.0]], dtype=np.float32)
    codes = map_to_ramp(lum, table)[0]
    assert codes[0] == table[0]
    assert codes[1] == table[-1]


def test_adjust_identity_by_default():
    lum = np.linspace(0, 1, 16, dtype=np.float32).reshape(1, -1)
    assert np.allclose(adjust(lum), lum)


def test_adjust_contrast_pushes_away_from_midgrey():
    lum = np.array([[0.25, 0.5, 0.75]], dtype=np.float32)
    out = adjust(lum, contrast=2.0)
    assert out[0, 0] < 0.25
    assert out[0, 1] == pytest.approx(0.5)
    assert out[0, 2] > 0.75


def test_adjust_always_clamps():
    lum = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    out = adjust(lum, brightness=2.0, contrast=4.0, gamma=0.2)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_ramp_table_is_cached_and_immutable():
    a = ramp_table("standard")
    assert a is ramp_table("standard")
    assert not a.flags.writeable
