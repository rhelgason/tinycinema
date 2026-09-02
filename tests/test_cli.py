import argparse

import pytest

from tinycinema.cli import build_parser, main, parse_time


# -- timestamps -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("0", 0.0), ("42", 42.0), ("1:30", 90.0), ("01:02:03", 3723.0), ("2.5", 2.5)],
)
def test_parse_time(text, seconds):
    assert parse_time(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["abc", "1:2:3:4", "1:xx"])
def test_parse_time_rejects_nonsense(text):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_time(text)


# -- argument wiring --------------------------------------------------------


def test_defaults():
    a = build_parser().parse_args(["clip.mp4"])
    assert a.source == "clip.mp4"
    assert a.mode == "auto"
    assert a.color is True
    assert a.hud is True
    assert a.once is False


def test_demo_flag_has_a_default_pattern():
    assert build_parser().parse_args(["--demo"]).demo == "ball"
    assert build_parser().parse_args(["--demo", "bars"]).demo == "bars"


def test_negative_flags():
    a = build_parser().parse_args(["x.mp4", "--no-color", "--no-hud"])
    assert a.color is False
    assert a.hud is False


def test_invalid_mode_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["x.mp4", "--mode", "hologram"])


def test_invalid_ramp_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["x.mp4", "--ramp", "squiggles"])


# -- end to end -------------------------------------------------------------


def test_no_arguments_prints_help(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().out


def test_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_missing_file_exits_nonzero_with_a_message(capsys):
    assert main(["/nope/missing.mp4"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_youtube_url_explains_itself(capsys):
    assert main(["https://youtube.com/watch?v=abc"]) == 1
    assert "yt-dlp" in capsys.readouterr().err


def test_demo_once_renders_plain_text_to_a_pipe(capsys):
    """Piped output must be plain text: no escapes, exactly one frame."""
    assert main(["--demo", "--width", "20", "--height", "6"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert len(out.rstrip("\n").split("\n")) == 6
    assert all(len(line) == 20 for line in out.rstrip("\n").split("\n"))


def test_doctor_runs(capsys):
    code = main(["--doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "tinycinema" in out
    assert "ffmpeg" in out
    assert "Glyph check" in out


def test_stats_are_reported(capsys):
    main(["--demo", "--width", "20", "--height", "6", "--stats"])
    assert "rendered" in capsys.readouterr().err
