"""Inline-image protocols: kitty, iTerm2 and sixel.

These emit escape sequences with bitmap payloads, so the tests decode the
payload back out and check it against the pixels that went in. That catches the
things that actually break -- wrong chunking, a bad palette index, an off-by-one
in the sixel bit order -- which eyeballing a terminal would not.
"""

import base64
import re
import struct
import zlib

import numpy as np
import pytest

from tinycinema.png import encode_png
from tinycinema.render import create, image_modes
from tinycinema.render.images import _KITTY_CHUNK, _run_length_encode


def gradient(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    return np.stack(
        [(xx * 7) % 256, (yy * 11) % 256, ((xx + yy) * 5) % 256], axis=-1
    ).astype(np.uint8)


# -- shared contract ---------------------------------------------------------


@pytest.mark.parametrize("mode", image_modes())
def test_image_modes_are_flagged_and_have_square_pixels(mode):
    r = create(mode)
    assert r.is_image
    assert r.pixel_aspect == pytest.approx(1.0)


@pytest.mark.parametrize("mode", image_modes())
def test_image_modes_refuse_the_cell_grid_api(mode):
    """Calling render() on an image mode is a wiring bug; say so loudly."""
    r = create(mode)
    with pytest.raises(TypeError, match="image mode"):
        r.render(gradient(8, 8))


@pytest.mark.parametrize("mode", image_modes())
def test_payload_is_produced_and_bounded(mode):
    r = create(mode)
    w, h = r.pixel_size(40, 12)
    payload = r.encode_image(gradient(h, w), 40, 12)
    assert payload.startswith("\x1b"), "must begin with an escape"
    assert len(payload) > 0


@pytest.mark.parametrize("mode", image_modes())
def test_resolution_is_capped(mode):
    """Uncapped, a full-screen frame is megabytes; no terminal will take it."""
    r = create(mode)
    w, h = r.pixel_size(400, 120)
    assert w * h <= r.MAX_PIXELS
    # the cap must scale uniformly, or the picture stretches
    small_w, small_h = r.pixel_size(40, 12)
    assert (w / h) == pytest.approx(small_w / small_h, rel=0.05)


@pytest.mark.parametrize("mode", image_modes())
def test_small_grids_are_not_scaled_up(mode):
    r = create(mode)
    assert r.pixel_size(10, 4) == (40, 32)


# -- kitty -------------------------------------------------------------------


def test_kitty_header_carries_the_right_geometry():
    r = create("kitty")
    payload = r.encode_image(gradient(16, 32), 8, 2)
    assert "s=32" in payload and "v=16" in payload
    assert "c=8" in payload and "r=2" in payload
    assert "f=24" in payload, "24-bit RGB, not RGBA"
    assert "a=T" in payload, "transmit and display in one go"
    assert "i=1" in payload, "a fixed id means each frame replaces the last"
    assert "q=2" in payload, "unsuppressed replies would land in our key input"


def test_kitty_roundtrips_the_exact_pixels():
    r = create("kitty")
    frame = gradient(12, 20)
    payload = r.encode_image(frame, 20, 3)
    chunks = re.findall(r"\x1b_G[^;]*;([A-Za-z0-9+/=]*)\x1b\\", payload)
    decoded = base64.b64decode("".join(chunks))
    assert np.array_equal(
        np.frombuffer(decoded, np.uint8).reshape(frame.shape), frame
    )


def test_kitty_chunks_are_within_the_protocol_limit():
    """Kitty rejects base64 chunks over 4096 bytes."""
    r = create("kitty")
    w, h = r.pixel_size(80, 24)
    payload = r.encode_image(gradient(h, w), 80, 24)
    chunks = re.findall(r"\x1b_G[^;]*;([A-Za-z0-9+/=]*)\x1b\\", payload)
    assert len(chunks) > 1, "this frame should need chunking"
    assert all(len(c) <= _KITTY_CHUNK for c in chunks)


def test_kitty_marks_continuation_correctly():
    """m=1 on every chunk but the last, which must be m=0."""
    r = create("kitty")
    w, h = r.pixel_size(80, 24)
    payload = r.encode_image(gradient(h, w), 80, 24)
    flags = re.findall(r"\x1b_G([^;]*);", payload)
    assert len(flags) > 1
    assert all("m=1" in f for f in flags[:-1])
    assert "m=0" in flags[-1]
    # control keys belong on the first chunk only
    assert "a=T" in flags[0]
    assert all("a=T" not in f for f in flags[1:])


def test_a_single_chunk_frame_is_one_escape():
    r = create("kitty")
    payload = r.encode_image(gradient(4, 4), 4, 1)
    assert payload.count("\x1b_G") == 1
    assert "m=0" in payload


# -- iTerm2 ------------------------------------------------------------------


def test_iterm_emits_a_valid_png():
    r = create("iterm")
    frame = gradient(12, 20)
    payload = r.encode_image(frame, 20, 3)
    assert payload.startswith("\x1b[H\x1b]1337;File=inline=1;")
    assert payload.endswith("\x07")
    data = payload.split(":", 1)[1].rstrip("\x07")
    png = base64.b64decode(data)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (20, 12)


def test_iterm_declares_its_cell_box():
    r = create("iterm")
    payload = r.encode_image(gradient(8, 8), 33, 7)
    assert "width=33" in payload and "height=7" in payload
    assert "preserveAspectRatio=0" in payload, "we already letterboxed it"


def test_iterm_size_field_matches_the_payload():
    r = create("iterm")
    payload = r.encode_image(gradient(8, 8), 8, 2)
    declared = int(re.search(r"size=(\d+):", payload).group(1))
    data = payload.split(":", 1)[1].rstrip("\x07")
    assert declared == len(base64.b64decode(data))


# -- the PNG encoder ---------------------------------------------------------


def test_png_pixels_round_trip():
    frame = gradient(9, 13)
    png = encode_png(frame)
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (13, 9)

    # pull IDAT back out and undo the per-scanline filter bytes
    idat = b""
    pos = 8
    while pos < len(png):
        length = struct.unpack(">I", png[pos : pos + 4])[0]
        tag = png[pos + 4 : pos + 8]
        if tag == b"IDAT":
            idat += png[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    rows = [raw[i * stride + 1 : (i + 1) * stride] for i in range(height)]
    decoded = np.frombuffer(b"".join(rows), np.uint8).reshape(height, width, 3)
    assert np.array_equal(decoded, frame)


def test_png_rejects_the_wrong_shape():
    with pytest.raises(ValueError, match="RGB"):
        encode_png(np.zeros((4, 4), np.uint8))


def test_png_crcs_are_correct():
    png = encode_png(gradient(4, 4))
    pos = 8
    while pos < len(png):
        length = struct.unpack(">I", png[pos : pos + 4])[0]
        body = png[pos + 4 : pos + 8 + length]
        stored = struct.unpack(">I", png[pos + 8 + length : pos + 12 + length])[0]
        assert stored == zlib.crc32(body), f"bad CRC on {body[:4]!r}"
        pos += 12 + length


# -- sixel -------------------------------------------------------------------


def test_sixel_is_wrapped_in_the_device_control_string():
    r = create("sixel")
    payload = r.encode_image(gradient(12, 12), 12, 2)
    assert "\x1bPq" in payload
    assert payload.endswith("\x1b\\")


def test_sixel_declares_raster_dimensions():
    r = create("sixel")
    payload = r.encode_image(gradient(12, 18), 18, 2)
    assert '"1;1;18;12' in payload


def test_sixel_defines_every_colour_it_uses():
    r = create("sixel")
    payload = r.encode_image(gradient(12, 12), 12, 2)
    defined = {int(m) for m in re.findall(r"#(\d+);2;", payload)}
    used = {int(m) for m in re.findall(r"#(\d+)(?![\d;])", payload)}
    assert used <= defined, "a colour used before definition renders wrong"


def test_sixel_palette_values_are_in_percent():
    """Sixel colour components are 0-100, not 0-255."""
    r = create("sixel")
    payload = r.encode_image(np.full((6, 6, 3), 255, np.uint8), 6, 1)
    for _, comps in re.findall(r"#(\d+);2;([\d;]+)", payload):
        assert all(0 <= int(v) <= 100 for v in comps.split(";"))


def test_sixel_solid_white_uses_the_top_of_the_cube():
    r = create("sixel")
    payload = r.encode_image(np.full((6, 6, 3), 255, np.uint8), 6, 1)
    assert "#215;2;100;100;100" in payload, "6^3-1 is the all-max cube entry"


def test_sixel_solid_black_uses_index_zero():
    r = create("sixel")
    payload = r.encode_image(np.zeros((6, 6, 3), np.uint8), 6, 1)
    assert "#0;2;0;0;0" in payload


def test_sixel_pads_to_whole_bands():
    """Sixel works in 6-row bands; a height that isn't a multiple must pad."""
    r = create("sixel")
    payload = r.encode_image(gradient(8, 6), 6, 1)  # 8 rows -> 2 bands
    assert payload.count("-") >= 1


def test_sixel_bit_order_puts_the_top_row_in_bit_zero():
    """One lit row at the top of a band must be '?'+1, i.e. '@'."""
    frame = np.zeros((6, 1, 3), np.uint8)
    frame[0] = 255  # only the topmost pixel is white
    payload = create("sixel").encode_image(frame, 1, 1)
    white = payload.split("#215")[-1]
    assert white.startswith("@"), f"expected '@' for bit 0, got {white[:4]!r}"


# -- sixel run-length encoding ----------------------------------------------


@pytest.mark.parametrize(
    ("bits", "expected"),
    [
        ([0], "?"),
        ([0, 0], "??"),
        ([0, 0, 0], "???"),
        ([0] * 4, "!4?"),
        ([0] * 10, "!10?"),
        ([1, 1, 1, 1, 2], "!4@A"),
    ],
)
def test_run_length_encoding(bits, expected):
    assert _run_length_encode(np.array(bits)) == expected


def test_run_length_never_grows_the_output():
    """Runs of 3 or fewer must stay literal -- '!3?' is longer than '???'."""
    for n in range(1, 4):
        assert _run_length_encode(np.zeros(n, int)) == "?" * n


def test_run_length_helps_on_letterbox_bars():
    """Flat black bars are the common case and should compress hard."""
    flat = _run_length_encode(np.zeros(500, int))
    assert len(flat) < 10
