"""Golden tests for the diffed writer -- the highest-value code in the project.

No video required: hand-built CellGrids in, exact byte strings out.
"""

import numpy as np

from tinycinema.term import DEFAULT, CellGrid, FrameWriter, PlainWriter, strip_ansi


def grid(rows, cols, char=" ", fg=DEFAULT, bg=DEFAULT):
    g = CellGrid.blank(rows, cols)
    g.chars[:] = ord(char)
    g.fg[:] = fg
    g.bg[:] = bg
    return g


def writer():
    return FrameWriter(synchronized=False)


def test_identical_frames_emit_nothing():
    """The whole point: a static image costs zero bytes after the first paint."""
    w = writer()
    first = w.encode(grid(4, 8, "x"))
    assert first
    assert w.encode(grid(4, 8, "x")) == ""


def test_single_cell_change_touches_only_that_cell():
    w = writer()
    w.encode(grid(4, 8, "x"))
    g = grid(4, 8, "x")
    g.chars[2, 5] = ord("Z")
    out = w.encode(g)
    assert strip_ansi(out) == "Z"
    assert "\x1b[3;6H" in out  # cursor position is 1-indexed


def test_untouched_rows_are_skipped_entirely():
    w = writer()
    w.encode(grid(6, 10, "."))
    g = grid(6, 10, ".")
    g.chars[0, :] = ord("#")
    out = w.encode(g)
    assert strip_ansi(out) == "#" * 10
    assert out.count("H") == 1  # exactly one cursor move


def test_nearby_changes_merge_into_one_run():
    """Bridging a small gap beats paying for another cursor-move escape."""
    w = writer()
    w.encode(grid(1, 20, "."))
    g = grid(1, 20, ".")
    g.chars[0, 2] = ord("A")
    g.chars[0, 5] = ord("B")  # gap of 2 unchanged cells
    out = w.encode(g)
    assert out.count("\x1b[1;3H") == 1
    assert strip_ansi(out) == "A..B"


def test_distant_changes_get_separate_cursor_moves():
    w = writer()
    w.encode(grid(1, 40, "."))
    g = grid(1, 40, ".")
    g.chars[0, 1] = ord("A")
    g.chars[0, 30] = ord("B")
    out = w.encode(g)
    assert out.count("H") == 2
    assert strip_ansi(out) == "AB"


def test_colour_is_emitted_once_per_run_not_per_cell():
    """SGR coalescing: 10 same-coloured cells cost one escape, not ten."""
    w = writer()
    w.encode(grid(1, 10, " "))
    g = grid(1, 10, "#", fg=(255, 0, 0))
    out = w.encode(g)
    assert out.count("38;2;255;0;0") == 1
    assert strip_ansi(out) == "#" * 10


def test_fg_and_bg_combine_into_one_escape():
    w = writer()
    w.encode(grid(1, 4, " "))
    g = grid(1, 4, "▀", fg=(1, 2, 3), bg=(4, 5, 6))
    out = w.encode(g)
    assert "\x1b[38;2;1;2;3;48;2;4;5;6m" in out
    assert out.count("\x1b[") == 2  # one cursor move, one colour change


def test_default_colour_uses_39_and_49():
    w = writer()
    w.encode(grid(1, 3, "#", fg=(9, 9, 9), bg=(8, 8, 8)))
    out = w.encode(grid(1, 3, "#"))
    assert "39" in out and "49" in out


def test_colour_change_alone_repaints_the_cell():
    w = writer()
    w.encode(grid(2, 2, "#", fg=(10, 10, 10)))
    g = grid(2, 2, "#", fg=(20, 20, 20))
    out = w.encode(g)
    assert strip_ansi(out) == "#" * 4


def test_resize_forces_a_full_repaint():
    w = writer()
    w.encode(grid(4, 4, "x"))
    out = w.encode(grid(6, 4, "x"))
    assert strip_ansi(out) == "x" * 24
    assert "\x1b[0m" in out  # pen state is reset, not carried across


def test_invalidate_forces_a_full_repaint():
    w = writer()
    w.encode(grid(3, 3, "x"))
    assert w.encode(grid(3, 3, "x")) == ""
    w.invalidate()
    assert strip_ansi(w.encode(grid(3, 3, "x"))) == "x" * 9


def test_synchronized_output_wraps_the_frame():
    w = FrameWriter(synchronized=True)
    out = w.encode(grid(2, 2, "x"))
    assert out.startswith("\x1b[?2026h")
    assert out.endswith("\x1b[?2026l")


def test_synchronized_wrapper_is_skipped_when_nothing_changed():
    w = FrameWriter(synchronized=True)
    w.encode(grid(2, 2, "x"))
    assert w.encode(grid(2, 2, "x")) == ""


def test_diffing_actually_saves_bytes_on_realistic_motion():
    """Sanity-check the premise: mostly-static content should be far cheaper."""
    rng = np.random.default_rng(0)
    base = CellGrid.blank(50, 200)
    base.fg[:] = rng.integers(0, 256, (50, 200, 3))
    base.chars[:] = 0x2580

    w = writer()
    full = len(w.encode(base))

    moved = CellGrid(base.chars.copy(), base.fg.copy(), base.bg.copy())
    moved.fg[20:24, 40:60] = rng.integers(0, 256, (4, 20, 3))  # ~1.6% of cells
    partial = len(w.encode(moved))

    assert partial < full / 20


def test_plain_writer_emits_no_escapes():
    import io

    buf = io.StringIO()
    PlainWriter(buf).draw(grid(2, 3, "o"))
    assert buf.getvalue() == "ooo\nooo\n"


def test_cell_grid_to_text():
    g = CellGrid.blank(2, 2)
    g.chars[0, 0] = ord("a")
    assert g.to_text() == "a \n  "
