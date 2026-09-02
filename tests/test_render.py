import numpy as np
import pytest

from tinycinema import render as render_mod
from tinycinema.render import RenderOptions, available_modes, create
from tinycinema.term import DEFAULT

HALFBLOCK = 0x2580


def solid(h, w, rgb):
    return np.broadcast_to(np.array(rgb, np.uint8), (h, w, 3)).copy()


@pytest.mark.parametrize("mode", available_modes())
def test_grid_shape_matches_requested_cells(mode):
    """The contract: pixel_size(cols, rows) in -> exactly (rows, cols) cells out."""
    r = create(mode)
    cols, rows = 37, 11
    w, h = r.pixel_size(cols, rows)
    grid = r.render(solid(h, w, (120, 40, 200)))
    assert grid.shape == (rows, cols)


@pytest.mark.parametrize("mode", available_modes())
def test_colour_planes_have_matching_shape(mode):
    r = create(mode)
    w, h = r.pixel_size(20, 6)
    grid = r.render(solid(h, w, (10, 200, 90)))
    assert grid.fg.shape == (*grid.shape, 3)
    assert grid.bg.shape == (*grid.shape, 3)
    assert grid.chars.dtype == np.uint32


@pytest.mark.parametrize("mode", available_modes())
def test_render_accepts_readonly_input(mode):
    """Frames arrive from np.frombuffer over a pipe, so they are not writeable."""
    r = create(mode)
    w, h = r.pixel_size(12, 4)
    frame = solid(h, w, (200, 30, 30))
    frame.flags.writeable = False
    r.render(frame)  # must not raise


def test_pixel_aspect_is_square_for_subdivided_modes():
    """halfblock and braille subdivide vertically enough to square the pixels."""
    assert create("halfblock").pixel_aspect == pytest.approx(1.0)
    assert create("braille").pixel_aspect == pytest.approx(1.0)
    # one pixel per cell means pixels are twice as tall as they are wide
    assert create("ascii").pixel_aspect == pytest.approx(0.5)


def test_halfblock_maps_rows_to_fg_and_bg():
    """fg is the top pixel, bg the bottom -- two colours in one cell."""
    frame = np.zeros((2, 3, 3), np.uint8)
    frame[0] = (255, 0, 0)
    frame[1] = (0, 0, 255)
    grid = create("halfblock").render(frame)
    assert grid.shape == (1, 3)
    assert (grid.chars == HALFBLOCK).all()
    assert (grid.fg[0] == (255, 0, 0)).all()
    assert (grid.bg[0] == (0, 0, 255)).all()


def test_halfblock_pads_odd_height():
    grid = create("halfblock").render(solid(3, 4, (10, 10, 10)))
    assert grid.shape == (2, 4)
    assert (grid.bg[1] == (0, 0, 0)).all()  # padded row is black


def test_halfblock_mono_falls_back_to_a_ramp():
    """Without colour, solid blocks would be a featureless wall."""
    r = create("halfblock", RenderOptions(color=False))
    frame = np.zeros((4, 4, 3), np.uint8)
    frame[:, 2:] = 255
    grid = r.render(frame)
    assert not (grid.chars == HALFBLOCK).all()
    assert (grid.fg == DEFAULT).all()
    assert grid.chars[0, 0] != grid.chars[0, 3]


def test_ascii_is_monochrome_but_ascii_color_is_not():
    frame = solid(4, 4, (200, 100, 50))
    assert (create("ascii").render(frame).fg == DEFAULT).all()
    assert (create("ascii-color").render(frame).fg == (200, 100, 50)).all()


def test_blocks_paints_the_background():
    grid = create("blocks").render(solid(2, 2, (7, 9, 11)))
    assert (grid.chars == ord(" ")).all()
    assert (grid.bg == (7, 9, 11)).all()
    assert (grid.fg == DEFAULT).all()


def test_braille_all_dark_and_all_bright():
    r = create("braille", RenderOptions(dither="ordered", color=False))
    dark = r.render(np.zeros((4, 2, 3), np.uint8))
    bright = r.render(np.full((4, 2, 3), 255, np.uint8))
    assert dark.chars[0, 0] == 0x2800  # no dots
    assert bright.chars[0, 0] == 0x28FF  # all eight dots


def test_braille_dot_bit_order():
    """Only the top-left pixel lit must set dot 1 (bit 0x01), not some other bit."""
    r = create("braille", RenderOptions(dither="ordered", color=False, threshold=0.5))
    frame = np.zeros((4, 2, 3), np.uint8)
    frame[0, 0] = 255
    assert r.render(frame).chars[0, 0] == 0x2801

    frame = np.zeros((4, 2, 3), np.uint8)
    frame[3, 1] = 255  # bottom-right dot is bit 0x80, the late addition
    assert r.render(frame).chars[0, 0] == 0x2880


def test_braille_pads_to_a_whole_cell():
    grid = create("braille").render(np.zeros((5, 3, 3), np.uint8))
    assert grid.shape == (2, 2)


def test_tone_controls_reach_the_renderer():
    # Compare positions in the ramp, not codepoints -- ramp order is not
    # codepoint order (' .:-=+*#%@' goes ':' 58 -> '%' 37 as it gets brighter).
    ramp = " .:-=+*#%@"
    dim = solid(4, 4, (60, 60, 60))

    def index(opts):
        return ramp.index(chr(create("ascii", opts).render(dim).chars[0, 0]))

    plain = index(RenderOptions(ramp="standard"))
    assert index(RenderOptions(ramp="standard", brightness=0.6)) > plain
    assert index(RenderOptions(ramp="standard", gamma=2.5)) > plain
    assert index(RenderOptions(ramp="standard", brightness=-0.6)) < plain


def test_unknown_mode_lists_the_valid_ones():
    with pytest.raises(ValueError, match="unknown render mode"):
        create("hologram")


def test_registry_names_match_class_attributes():
    """A dataclass field would have let __init__ clobber these back to 'base'."""
    for name in available_modes():
        assert create(name).name == name
    assert "halfblock" in render_mod.available_modes()
