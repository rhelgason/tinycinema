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
    assert a.source == ["clip.mp4"]
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


def test_youtube_url_without_yt_dlp_explains_the_extra(capsys, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_ytdlp(name, *a, **k):
        if name == "yt_dlp":
            raise ImportError("nope")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ytdlp)
    assert main(["https://youtube.com/watch?v=abc"]) == 1
    assert "yt-dlp" in capsys.readouterr().err


def test_a_url_that_cannot_be_resolved_exits_cleanly(capsys, monkeypatch):
    """No traceback on a dead link, an offline machine or a private video."""
    from tinycinema import sources

    def fail(url, **kw):
        raise sources.ResolveError(f"could not resolve {url}")

    monkeypatch.setattr(sources, "resolve_url", fail)
    assert main(["https://youtube.com/watch?v=abc"]) == 1
    assert "could not resolve" in capsys.readouterr().err


def test_quality_is_parsed_from_the_command_line():
    assert build_parser().parse_args(["u", "--quality", "720p"]).quality == 720
    assert build_parser().parse_args(["u"]).quality == 480


def test_no_cache_flag():
    assert build_parser().parse_args(["u"]).cache is True
    assert build_parser().parse_args(["u", "--no-cache"]).cache is False


def test_verbose_explains_what_it_is_doing(capsys):
    """The point of --verbose is being able to debug a run you can't reproduce."""
    main(["--demo", "--width", "20", "--height", "6", "--verbose"])
    err = capsys.readouterr().err
    assert "playing" in err
    assert "mode=" in err and "clock=" in err


def test_verbose_writes_only_to_stderr(capsys):
    """stdout may be a pipe someone is capturing frames from."""
    main(["--demo", "--width", "20", "--height", "6", "--verbose"])
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out
    assert "playing" not in captured.out


def test_quiet_by_default(capsys):
    main(["--demo", "--width", "20", "--height", "6"])
    assert "mode=" not in capsys.readouterr().err


def test_clear_cache_exits_without_playing(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("TINYCINEMA_CACHE", str(tmp_path / "c"))
    assert main(["--clear-cache"]) == 0
    assert "removed" in capsys.readouterr().out


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
