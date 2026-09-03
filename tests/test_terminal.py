import types

import pytest

from tinycinema import term as term_mod
from tinycinema.term import RESIZE_DEBOUNCE, Capabilities, Terminal, detect_capabilities


class FakeMono:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


@pytest.fixture
def terminal(monkeypatch):
    mono = FakeMono()
    monkeypatch.setattr(term_mod, "time", types.SimpleNamespace(monotonic=mono.monotonic))
    t = Terminal(alt_screen=False, hide_cursor=False)
    t._size = (80, 24)
    monkeypatch.setattr(t, "size", lambda: t._size)
    t._settled_size = t._observed_size = (80, 24)
    return t, mono


# -- resize detection -------------------------------------------------------


def test_no_resize_when_the_size_is_stable(terminal):
    t, _ = terminal
    assert not t.take_resize()
    assert not t.take_resize()


def test_resize_is_reported_once_the_size_settles(terminal):
    t, mono = terminal
    t._size = (100, 30)
    assert not t.take_resize()  # first sighting only arms the debounce
    mono.t += RESIZE_DEBOUNCE + 0.01
    assert t.take_resize()
    assert not t.take_resize()  # and only once


def test_a_drag_storm_collapses_to_a_single_resize(terminal):
    """Restarting the decoder per event during a drag stutters horribly."""
    t, mono = terminal
    for width in range(100, 120):
        t._size = (width, 30)
        mono.t += 0.02
        assert not t.take_resize()
    mono.t += RESIZE_DEBOUNCE + 0.01
    assert t.take_resize()
    assert t._settled_size == (119, 30)


def test_a_size_that_bounces_back_reports_nothing(terminal):
    t, mono = terminal
    t._size = (100, 30)
    t.take_resize()
    mono.t += 0.05
    t._size = (80, 24)  # back where it started before the debounce elapsed
    assert not t.take_resize()
    mono.t += RESIZE_DEBOUNCE + 0.01
    assert not t.take_resize()


def test_the_sigwinch_flag_alone_does_not_force_a_resize(terminal):
    """The signal is a latency hint; the polled size is the source of truth."""
    t, mono = terminal
    t.resized = True
    assert not t.take_resize()
    assert not t.resized


# -- capabilities -----------------------------------------------------------


def caps(**kw):
    base = dict(
        is_tty=True, truecolor=False, color256=False, unicode=True,
        kitty=False, iterm=False, term="xterm", term_program="test",
    )
    return Capabilities(**{**base, **kw})


def test_auto_never_picks_an_image_mode():
    """The tool renders video as characters; auto-selecting a bitmap would
    silently defeat the entire premise. Image modes stay opt-in."""
    from tinycinema.render import image_modes

    for kw in ({}, {"kitty": True}, {"iterm": True}, {"sixel": True}):
        assert caps(truecolor=True, **kw).best_mode() not in image_modes()


def test_image_modes_are_reported_best_first():
    assert caps(kitty=True, iterm=True, sixel=True).image_modes == [
        "kitty",
        "iterm",
        "sixel",
    ]
    assert caps().image_modes == []


def test_sixel_detection_can_be_overridden(monkeypatch):
    from tinycinema.term import detect_sixel

    monkeypatch.setenv("TINYCINEMA_SIXEL", "1")
    assert detect_sixel()
    monkeypatch.setenv("TINYCINEMA_SIXEL", "0")
    assert not detect_sixel()


def test_sixel_query_is_skipped_when_not_a_tty(monkeypatch):
    """The DA query writes to the terminal and reads a reply; on a pipe that
    would emit junk into the output and block for the timeout."""
    from tinycinema.term import detect_sixel

    monkeypatch.delenv("TINYCINEMA_SIXEL", raising=False)
    assert not detect_sixel()


def test_best_mode_ladder():
    assert caps(truecolor=True, color256=True).best_mode() == "halfblock"
    assert caps(color256=True).best_mode() == "halfblock"
    assert caps(color256=True, unicode=False).best_mode() == "ascii-color"
    assert caps().best_mode() == "ascii"
    assert caps(is_tty=False, truecolor=True).best_mode() == "ascii"


def test_color_depth_labels():
    assert caps(truecolor=True).color_depth == "24-bit"
    assert caps(color256=True).color_depth == "256"
    assert caps().color_depth == "none"


def test_no_color_env_is_respected(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setenv("NO_COLOR", "1")
    c = detect_capabilities()
    assert not c.truecolor and not c.color256


def test_truecolor_detected_from_colorterm(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert detect_capabilities().truecolor


def test_kitty_detected_from_env(monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    assert detect_capabilities().kitty


# -- teardown ---------------------------------------------------------------


def test_restore_is_idempotent():
    t = Terminal(alt_screen=False, hide_cursor=False)
    t.restore()
    t.restore()  # must not raise


def test_context_manager_restores(monkeypatch):
    t = Terminal(alt_screen=False, hide_cursor=False)
    with t:
        assert t._entered
    assert not t._entered


def test_non_tty_writes_no_escapes(capsys):
    """Escapes leaking into a pipe would corrupt whatever is downstream."""
    with Terminal():
        pass
    assert capsys.readouterr().out == ""
