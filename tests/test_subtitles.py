"""Subtitle parsing, lookup, wrapping and discovery.

Subtitle files in the wild are frequently a bit broken -- stray blank lines,
mixed line endings, a BOM, a truncated final cue, formatting tags a terminal
can't honour. Most of these tests are about surviving that rather than about
the happy path.
"""

import textwrap

import pytest

from tinycinema.subtitles import (
    Cue,
    SubtitleTrack,
    clean_text,
    discover,
    extract_embedded,
    find_sidecar,
    load,
    parse,
    wrap,
)

SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:04,000
    Hello there.

    2
    00:00:05,500 --> 00:00:08,250
    Second line,
    split across two rows.
    """)

VTT = textwrap.dedent("""\
    WEBVTT

    00:01.000 --> 00:04.000
    No hours in this one.

    cue-id-2
    00:00:05.500 --> 00:00:08.250
    And this one has an id.
    """)


# -- parsing -----------------------------------------------------------------


def test_srt_basics():
    cues = parse(SRT)
    assert len(cues) == 2
    assert cues[0] == Cue(1.0, 4.0, "Hello there.")
    assert cues[1].start == pytest.approx(5.5)
    assert cues[1].end == pytest.approx(8.25)
    assert cues[1].text == "Second line,\nsplit across two rows."


def test_vtt_basics():
    cues = parse(VTT)
    assert len(cues) == 2
    assert cues[0].start == pytest.approx(1.0), "hours are optional in WebVTT"
    assert cues[0].end == pytest.approx(4.0)
    assert cues[1].text == "And this one has an id."


def test_two_digit_fractions_are_milliseconds_not_microseconds():
    """'.5' has to mean 500ms. Reading it as 5ms puts every cue in the wrong place."""
    cues = parse("00:00:01.5 --> 00:00:02.25\nx\n")
    assert cues[0].start == pytest.approx(1.5)
    assert cues[0].end == pytest.approx(2.25)


def test_a_byte_order_mark_does_not_break_the_first_cue():
    cues = parse("﻿" + SRT)
    assert len(cues) == 2 and cues[0].text == "Hello there."


def test_crlf_and_cr_line_endings():
    assert len(parse(SRT.replace("\n", "\r\n"))) == 2
    assert len(parse(SRT.replace("\n", "\r"))) == 2


def test_extra_blank_lines_between_cues():
    assert len(parse(SRT.replace("\n\n", "\n\n\n\n"))) == 2


def test_a_malformed_block_is_skipped_not_fatal():
    broken = SRT + "\n3\nthis line has no timing at all\nsome text\n"
    cues = parse(broken)
    assert len(cues) == 2, "one bad cue must not lose the good ones"


def test_a_truncated_final_cue_is_dropped():
    cues = parse(SRT + "\n3\n00:00:09,000 --> 00:00:11,000\n")
    assert len(cues) == 2, "a cue with no text is not worth showing"


def test_zero_length_cues_are_dropped():
    assert parse("1\n00:00:01,000 --> 00:00:01,000\nblink\n") == []


def test_cues_are_sorted_even_when_the_file_is_not():
    out_of_order = (
        "2\n00:00:05,000 --> 00:00:06,000\nsecond\n\n"
        "1\n00:00:01,000 --> 00:00:02,000\nfirst\n"
    )
    assert [c.text for c in parse(out_of_order)] == ["first", "second"]


def test_empty_input():
    assert parse("") == []
    assert parse("WEBVTT\n\n") == []


# -- tag stripping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<i>italic</i>", "italic"),
        ("<b>bold</b> and <u>under</u>", "bold and under"),
        ('<font color="#ff0000">red</font>', "red"),
        (r"{\an8}top-positioned", "top-positioned"),
        ("<v Roger>Roger speaking", "Roger speaking"),
        ("plain", "plain"),
    ],
)
def test_formatting_a_terminal_cannot_honour_is_stripped(raw, expected):
    assert clean_text(raw) == expected


# -- lookup ------------------------------------------------------------------


def track() -> SubtitleTrack:
    return SubtitleTrack(parse(SRT))


def test_active_at_inside_a_cue():
    assert track().active_at(2.0) == "Hello there."


def test_active_at_is_half_open():
    """Start is inclusive, end exclusive -- otherwise adjacent cues both show."""
    t = track()
    assert t.active_at(1.0) == "Hello there."
    assert t.active_at(4.0) == ""


def test_nothing_before_during_gaps_or_after():
    t = track()
    assert t.active_at(0.0) == ""
    assert t.active_at(4.5) == "", "the gap between cues"
    assert t.active_at(99.0) == ""


def test_an_empty_track_never_matches():
    assert SubtitleTrack([]).active_at(5.0) == ""


def test_overlapping_cues_prefer_one_still_on_screen():
    cues = [Cue(0.0, 10.0, "long"), Cue(1.0, 2.0, "short")]
    t = SubtitleTrack(sorted(cues, key=lambda c: c.start))
    assert t.active_at(1.5) == "short"
    assert t.active_at(5.0) == "long", "must look back past the finished cue"


def test_lookup_is_fast_on_a_feature_length_file():
    """This runs once per rendered frame, so a linear scan would show up."""
    import time

    cues = [Cue(i * 2.0, i * 2.0 + 1.5, f"line {i}") for i in range(20_000)]
    t = SubtitleTrack(cues)
    start = time.perf_counter()
    for i in range(2000):
        t.active_at(i * 19.0)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1, f"{elapsed:.3f}s for 2000 lookups is too slow"


# -- wrapping ----------------------------------------------------------------


def test_wrap_breaks_on_words():
    assert wrap("one two three four", 9) == ["one two", "three", "four"]


def test_wrap_keeps_the_cue_s_own_line_breaks():
    assert wrap("first line\nsecond line", 40) == ["first line", "second line"]


def test_a_word_longer_than_the_width_is_truncated_not_lost():
    out = wrap("supercalifragilistic", 8)
    assert out and all(len(line) <= 8 for line in out)


def test_wrap_caps_the_number_of_lines():
    """Subtitles covering half the picture are worse than slightly clipped ones."""
    out = wrap(" ".join(["word"] * 100), 20, max_lines=3)
    assert len(out) == 3


def test_wrap_handles_a_degenerate_width():
    assert wrap("anything", 0) == []


def test_wrap_ignores_blank_paragraphs():
    assert wrap("a\n\n\nb", 20) == ["a", "b"]


# -- discovery ---------------------------------------------------------------


def test_a_sidecar_next_to_the_media_is_found(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    subs = tmp_path / "clip.srt"
    subs.write_text(SRT)
    assert find_sidecar(tmp_path / "clip.mp4") == subs


def test_a_language_tagged_sidecar_is_found(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    subs = tmp_path / "clip.en.vtt"
    subs.write_text(VTT)
    assert find_sidecar(tmp_path / "clip.mp4") == subs


def test_no_sidecar_is_not_an_error(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    assert find_sidecar(tmp_path / "clip.mp4") is None


def test_unrelated_files_are_not_picked_up(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    (tmp_path / "other.srt").write_text(SRT)
    assert find_sidecar(tmp_path / "clip.mp4") is None


def test_special_characters_in_the_stem_do_not_break_the_glob(tmp_path):
    """A '[' in the filename would otherwise be read as a glob character."""
    (tmp_path / "clip [1080p].mp4").write_bytes(b"\0")
    subs = tmp_path / "clip [1080p].srt"
    subs.write_text(SRT)
    assert find_sidecar(tmp_path / "clip [1080p].mp4") == subs


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text(SRT)
    t = load(path)
    assert len(t) == 2 and t.source == str(path)


def test_explicit_subs_win_over_a_sidecar(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    (tmp_path / "clip.srt").write_text(SRT)
    chosen = tmp_path / "other.srt"
    chosen.write_text("1\n00:00:01,000 --> 00:00:02,000\nexplicit\n")
    t = discover(str(tmp_path / "clip.mp4"), str(chosen))
    assert t.active_at(1.5) == "explicit"


def test_discover_returns_none_with_nothing_to_find(tmp_path, monkeypatch):
    monkeypatch.setattr("tinycinema.subtitles.extract_embedded", lambda m, index=0: None)
    (tmp_path / "clip.mp4").write_bytes(b"\0")
    assert discover(str(tmp_path / "clip.mp4")) is None


def test_discover_falls_back_to_an_embedded_track(tmp_path, monkeypatch):
    (tmp_path / "clip.mkv").write_bytes(b"\0")
    monkeypatch.setattr(
        "tinycinema.subtitles.extract_embedded",
        lambda m, index=0: SubtitleTrack(parse(SRT), source="embedded"),
    )
    t = discover(str(tmp_path / "clip.mkv"))
    assert t is not None and len(t) == 2


# -- embedded extraction -----------------------------------------------------


def test_extract_embedded_parses_ffmpeg_output(monkeypatch):
    monkeypatch.setattr("tinycinema.subtitles.ffmpeg_path", lambda: "/bin/ffmpeg")

    class Result:
        returncode = 0
        stdout = SRT.encode()
        stderr = b""

    monkeypatch.setattr("tinycinema.subtitles.subprocess.run", lambda *a, **k: Result())
    t = extract_embedded("clip.mkv")
    assert t is not None and len(t) == 2


def test_no_subtitle_stream_is_not_an_error(monkeypatch):
    """Most files have none; that is not worth reporting."""
    monkeypatch.setattr("tinycinema.subtitles.ffmpeg_path", lambda: "/bin/ffmpeg")

    class Failed:
        returncode = 1
        stdout = b""
        stderr = b"Stream map '0:s:0' matches no streams."

    monkeypatch.setattr("tinycinema.subtitles.subprocess.run", lambda *a, **k: Failed())
    assert extract_embedded("clip.mp4") is None


def test_extraction_without_ffmpeg_returns_none(monkeypatch):
    monkeypatch.setattr("tinycinema.subtitles.ffmpeg_path", lambda: None)
    assert extract_embedded("clip.mkv") is None
