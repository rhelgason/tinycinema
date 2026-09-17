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


def test_one_unplayable_file_does_not_abandon_the_playlist(capsys, monkeypatch, tmp_path):
    """A file can look fine at open time and only fail once ffmpeg decodes it,
    so the per-item guard has to cover playback, not just opening."""
    from tinycinema import cli as cli_mod
    from tinycinema import player as player_mod
    from tinycinema import term as term_mod
    from tinycinema.sources import DecodeError, DemoSource
    from tinycinema.term import Capabilities

    # Pretend to be a terminal: a pipe implies --once, which stops a playlist
    # after the first item by design and would mask the behaviour under test.
    tty_caps = Capabilities(
        is_tty=True, truecolor=True, color256=True, unicode=True,
        kitty=False, iterm=False, term="xterm", term_program="test",
    )
    monkeypatch.setattr(cli_mod, "detect_capabilities", lambda: tty_caps)
    monkeypatch.setattr(term_mod, "detect_capabilities", lambda *a, **k: tty_caps)

    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (tmp_path / name).write_bytes(b"\0")

    opened = []
    monkeypatch.setattr(
        cli_mod, "open_source",
        lambda spec, **kw: (opened.append(spec), DemoSource("bars", fps=30.0))[1],
    )

    class FailsOnTheSecond:
        exit_reason = "eof"

        def __init__(self, source, term, opts, clock=None):
            self.stats = player_mod.Stats()

        def run(self):
            if len(opened) == 2:
                raise DecodeError("moov atom not found")
            return 0

    monkeypatch.setattr(player_mod, "Player", FailsOnTheSecond)

    code = main([str(tmp_path), "--width", "20", "--height", "6", "--no-audio"])
    assert len(opened) == 3, f"stopped after {len(opened)} of 3 files"
    assert code == 1, "a failed file should still show in the exit status"
    assert "decode failed" in capsys.readouterr().err


def test_demo_once_renders_plain_text_to_a_pipe(capsys):
    """Piped output must be plain text: no escapes, exactly one frame."""
    assert main(["--demo", "--width", "20", "--height", "6"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert len(out.rstrip("\n").split("\n")) == 6
    assert all(len(line) == 20 for line in out.rstrip("\n").split("\n"))


def _piped_demo(capsys, *flags: str) -> str:
    assert main(["--demo", "bars", "--width", "20", "--height", "6", *flags]) == 0
    return capsys.readouterr().out


def test_piped_ascii_default_ramp_matches_blocks(capsys):
    """The coincidence tools/verify.py used to treat as a failure."""
    ascii_out = _piped_demo(capsys, "--mode", "ascii")
    blocks_out = _piped_demo(capsys, "--mode", "blocks")
    assert ascii_out == blocks_out


def test_piped_ascii_standard_ramp_differs_from_blocks(capsys):
    """How the verifier tells the two modes apart without a colour tty."""
    ascii_out = _piped_demo(capsys, "--mode", "ascii", "--ramp", "standard")
    blocks_out = _piped_demo(capsys, "--mode", "blocks", "--ramp", "standard")
    assert ascii_out != blocks_out


def test_doctor_runs(capsys):
    code = main(["--doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "tinycinema" in out
    assert "ffmpeg" in out
    assert "Glyph check" in out


def test_doctor_hue_ramp_is_smooth():
    """Regression: green used to be 128+60*(i%3), a sawtooth, not a gradient."""
    from tinycinema.doctor import _hue_ramp

    rgb = _hue_ramp(48)
    assert rgb[0] == (255, 0, 0)
    assert rgb[-1] == (255, 0, 0)  # full circle back to red
    # Adjacent cells must not jump the way the old modulo-3 green did (~60).
    for i in range(1, len(rgb)):
        r0, g0, b0 = rgb[i - 1]
        r1, g1, b1 = rgb[i]
        step = abs(r1 - r0) + abs(g1 - g0) + abs(b1 - b0)
        assert step < 50, f"jump of {step} between {(r0, g0, b0)} and {(r1, g1, b1)}"


def test_doctor_grey_ramp_is_monotonic():
    from tinycinema.doctor import _grey_ramp

    grey = [r for r, g, b in _grey_ramp(48)]
    assert grey[0] == 0 and grey[-1] == 255
    assert grey == sorted(grey)


def test_stats_are_reported(capsys):
    main(["--demo", "--width", "20", "--height", "6", "--stats"])
    assert "rendered" in capsys.readouterr().err
