from tinycinema.keys import KeyReader


def decode(data: bytes) -> list[str]:
    return KeyReader()._decode(data)


def test_plain_characters():
    assert decode(b"qhr") == ["q", "h", "r"]


def test_named_control_keys():
    assert decode(b" ") == ["space"]
    assert decode(b"\r") == ["enter"]
    assert decode(b"\x03") == ["ctrl-c"]


def test_arrow_keys_both_encodings():
    assert decode(b"\x1b[A\x1b[B\x1b[C\x1b[D") == ["up", "down", "right", "left"]
    assert decode(b"\x1bOA\x1bOD") == ["up", "left"]


def test_arrows_mixed_with_plain_keys():
    assert decode(b"q\x1b[Cx") == ["q", "right", "x"]


def test_lone_escape_decodes_as_escape():
    assert decode(b"\x1b") == ["escape"]


def test_a_burst_keeps_every_key():
    """The player relies on this: three r's must not collapse into one."""
    assert decode(b"rrr") == ["r", "r", "r"]


def test_unknown_csi_does_not_emit_garbage():
    keys = decode(b"\x1b[200~q")
    assert "q" in keys
    assert "\x1b" not in keys


# Terminals answer back on stdin, mixed in with real keystrokes. Every reply
# below used to be torn apart into its individual bytes, and the byte a reply
# happens to end on is a live binding: `c` colour, `R` render mode, `h` HUD,
# `=` volume. The picture rearranged itself whenever the terminal spoke.
def test_a_device_attributes_reply_is_not_keystrokes():
    assert decode(b"\x1b[?62;4;6c") == []


def test_a_cursor_position_report_is_not_keystrokes():
    assert decode(b"\x1b[24;80R") == []


def test_a_kitty_graphics_ack_is_not_keystrokes():
    assert decode(b"\x1b_Gi=1;OK\x1b\\") == []


def test_an_osc_reply_is_not_keystrokes():
    assert decode(b"\x1b]11;rgb:0000/0000/0000\x07") == []


def test_bracketed_paste_markers_are_stripped_but_the_text_survives():
    assert decode(b"\x1b[200~hi\x1b[201~") == ["h", "i"]


def test_a_real_key_behind_a_reply_still_arrives():
    assert decode(b"\x1b[?62;4;6cq") == ["q"]


def test_an_unterminated_sequence_does_not_wedge_the_reader():
    """Held only while it could still complete, or a stray ESC blocks input."""
    r = KeyReader()
    assert r._decode(b"\x1b[" + b"0" * 40) == []
    assert r._pending == b""


def test_truncated_sequence_is_held_for_the_next_poll():
    """A split escape sequence must not be misread as a bare ESC keypress."""
    r = KeyReader()
    assert r._decode(b"ab\x1b[") == ["a", "b"]
    assert r._pending == b"\x1b["


def test_not_a_tty_is_not_usable():
    import io

    assert not KeyReader(io.StringIO()).usable
    assert KeyReader(io.StringIO()).poll() == []
