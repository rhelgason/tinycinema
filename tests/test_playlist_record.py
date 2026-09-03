"""Playlist expansion, asciinema recording and frame dumping."""

import json

import pytest

from tinycinema.playlist import expand, is_url
from tinycinema.record import CastRecorder, FrameDumper


# -- playlist expansion ------------------------------------------------------


def make_media(directory, *names):
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"\0")
    return directory


def test_explicit_files_pass_straight_through(tmp_path):
    make_media(tmp_path, "a.mp4", "b.mkv")
    got = expand([str(tmp_path / "b.mkv"), str(tmp_path / "a.mp4")])
    assert [p.split("/")[-1] for p in got] == ["b.mkv", "a.mp4"], "given order is kept"


def test_a_directory_expands_to_its_media(tmp_path):
    make_media(tmp_path, "a.mp4", "b.webm", "notes.txt", "cover.jpg")
    got = [p.split("/")[-1] for p in expand([str(tmp_path)])]
    assert got == ["a.mp4", "b.webm"], "non-media files must be skipped"


def test_directory_expansion_sorts_naturally(tmp_path):
    make_media(tmp_path, "ep10.mp4", "ep2.mp4", "ep1.mp4")
    got = [p.split("/")[-1] for p in expand([str(tmp_path)])]
    assert got == ["ep1.mp4", "ep2.mp4", "ep10.mp4"], "ep10 must not sort before ep2"


def test_directory_expansion_recurses(tmp_path):
    make_media(tmp_path, "top.mp4")
    make_media(tmp_path / "season2", "inner.mp4")
    got = [p.split("/")[-1] for p in expand([str(tmp_path)])]
    assert set(got) == {"top.mp4", "inner.mp4"}


def test_hidden_files_are_skipped(tmp_path):
    make_media(tmp_path, "a.mp4", "._a.mp4", ".hidden.mp4")
    assert [p.split("/")[-1] for p in expand([str(tmp_path)])] == ["a.mp4"]


def test_an_explicit_file_is_played_whatever_its_extension(tmp_path):
    """Filtering by suffix is for directory scans, not for what someone typed."""
    odd = tmp_path / "recording.bin"
    odd.write_bytes(b"\0")
    assert expand([str(odd)]) == [str(odd)]


def test_urls_and_stdin_pass_through():
    got = expand(["https://youtu.be/x", "-", "https://example.com/a.mp4"])
    assert got == ["https://youtu.be/x", "-", "https://example.com/a.mp4"]


def test_missing_paths_are_kept_so_the_error_comes_later(tmp_path):
    """open_source produces the 'no such file' message; expand shouldn't guess."""
    assert expand([str(tmp_path / "gone.mp4")]) == [str(tmp_path / "gone.mp4")]


def test_shuffle_is_deterministic_given_a_seed(tmp_path):
    make_media(tmp_path, *[f"{i:02d}.mp4" for i in range(20)])
    a = expand([str(tmp_path)], shuffle=True, seed=7)
    b = expand([str(tmp_path)], shuffle=True, seed=7)
    ordered = expand([str(tmp_path)])
    assert a == b
    assert sorted(a) == sorted(ordered), "shuffle must not lose or add items"
    assert a != ordered


def test_an_empty_directory_yields_nothing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert expand([str(tmp_path / "empty")]) == []


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("https://a.com/b", True), ("http://a", True), ("/tmp/a.mp4", False), ("a.mp4", False)],
)
def test_is_url(spec, expected):
    assert is_url(spec) is expected


# -- asciinema recording -----------------------------------------------------


def read_cast(path):
    lines = path.read_text().splitlines()
    return json.loads(lines[0]), [json.loads(x) for x in lines[1:]]


def test_cast_header_is_valid_v2(tmp_path):
    out = tmp_path / "r.cast"
    with CastRecorder(out, 96, 28, title="hello", timestamp=1700000000):
        pass
    header, _ = read_cast(out)
    assert header["version"] == 2
    assert header["width"] == 96 and header["height"] == 28
    assert header["title"] == "hello"
    assert header["timestamp"] == 1700000000


def test_events_are_recorded_in_order(tmp_path):
    out = tmp_path / "r.cast"
    rec = CastRecorder(out, 10, 5)
    rec.write("first")
    rec.write("second")
    rec.close()
    _, events = read_cast(out)
    payloads = [e[2] for e in events]
    assert payloads[:2] == ["first", "second"]
    assert all(e[1] == "o" for e in events)
    assert events[0][0] == 0.0, "the clock starts at the first real output"
    assert events[1][0] >= events[0][0], "timestamps must be non-decreasing"


def test_escape_sequences_survive_the_round_trip(tmp_path):
    """The whole point is replaying the exact bytes the terminal received."""
    out = tmp_path / "r.cast"
    payload = "\x1b[38;2;1;2;3m▀\x1b[0m"
    rec = CastRecorder(out, 10, 5)
    rec.write(payload)
    rec.close()
    _, events = read_cast(out)
    assert events[0][2] == payload


def test_empty_writes_are_dropped(tmp_path):
    """A frame that changed nothing emits nothing and shouldn't pad the cast."""
    out = tmp_path / "r.cast"
    rec = CastRecorder(out, 10, 5)
    rec.write("")
    rec.write("x")
    rec.close()
    _, events = read_cast(out)
    assert [e[2] for e in events][:1] == ["x"]


def test_close_restores_the_terminal_for_replay(tmp_path):
    out = tmp_path / "r.cast"
    rec = CastRecorder(out, 10, 5)
    rec.write("x")
    rec.close()
    _, events = read_cast(out)
    assert "\x1b[?25h" in events[-1][2], "a replay must not leave the cursor hidden"


def test_writing_after_close_is_harmless(tmp_path):
    rec = CastRecorder(tmp_path / "r.cast", 10, 5)
    rec.close()
    rec.write("late")  # must not raise


def test_recorder_creates_missing_parent_directories(tmp_path):
    rec = CastRecorder(tmp_path / "deep" / "nested" / "r.cast", 10, 5)
    rec.close()
    assert (tmp_path / "deep" / "nested" / "r.cast").exists()


# -- frame dumping -----------------------------------------------------------


def test_frames_are_numbered_and_zero_padded(tmp_path):
    d = FrameDumper(tmp_path / "frames")
    for _ in range(3):
        d.write("hello")
    names = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert names == ["frame-00001.txt", "frame-00002.txt", "frame-00003.txt"]


def test_frame_contents_round_trip(tmp_path):
    d = FrameDumper(tmp_path / "frames")
    path = d.write("line1\nline2")
    assert path.read_text() == "line1\nline2\n"


def test_image_modes_dump_png_not_text(tmp_path):
    """Dumping 'the frame' should mean whatever that mode actually produced."""
    import numpy as np

    d = FrameDumper(tmp_path / "frames")
    path = d.write_image(np.zeros((4, 6, 3), np.uint8))
    assert path.suffix == ".png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_text_and_image_frames_share_one_counter(tmp_path):
    """Otherwise switching mode mid-playback would overwrite earlier frames."""
    import numpy as np

    d = FrameDumper(tmp_path / "frames")
    d.write("a")
    d.write_image(np.zeros((2, 2, 3), np.uint8))
    d.write("b")
    names = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert names == ["frame-00001.txt", "frame-00002.png", "frame-00003.txt"]


def test_zero_padding_keeps_lexicographic_order_correct(tmp_path):
    """Tools that glob frames rely on name order matching frame order."""
    d = FrameDumper(tmp_path / "frames")
    for _ in range(11):
        d.write("x")
    names = sorted(p.name for p in (tmp_path / "frames").iterdir())
    assert names[1] == "frame-00002.txt" and names[-1] == "frame-00011.txt"
