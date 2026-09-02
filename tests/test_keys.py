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


def test_truncated_sequence_is_held_for_the_next_poll():
    """A split escape sequence must not be misread as a bare ESC keypress."""
    r = KeyReader()
    assert r._decode(b"ab\x1b[") == ["a", "b"]
    assert r._pending == b"\x1b["


def test_not_a_tty_is_not_usable():
    import io

    assert not KeyReader(io.StringIO()).usable
    assert KeyReader(io.StringIO()).poll() == []
