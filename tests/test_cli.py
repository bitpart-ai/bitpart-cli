"""Top-level dispatcher smoke tests for ``bitpart.cli``.

Verifies that the multi-command CLI is wired correctly: the ``tts`` subparser
is registered, ``--help`` works at both levels, and running ``bitpart`` with no
subcommand fails loudly instead of silently doing nothing.
"""
import os
import subprocess
import sys

import pytest


def _run(args: list[str], env_extra: dict | None = None):
    """Run ``python -m bitpart ...`` and return the CompletedProcess."""
    env = os.environ.copy()
    # Strip any env vars under test so the parent shell can't leak them in.
    for key in (
        "BITPART_TTS_CSV_UTTERANCE",
        "BITPART_TTS_OUTPUT_DIR",
        "BITPART_TTS_CHARACTER_VOICES",
        "BITPART_TTS_PROVIDER",
    ):
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "bitpart", *args],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def test_dispatcher_module_importable():
    import bitpart.cli

    assert callable(bitpart.cli.main)
    # tts must be in the SUBCOMMANDS tuple so it shows up in --help.
    names = [m.__name__ for m in bitpart.cli.SUBCOMMANDS]
    assert any(n.endswith(".tts.cli") or n == "bitpart.tts.cli" for n in names)


def test_tts_subcommand_registers_and_shows_help():
    """`python -m bitpart tts --help` must exit 0 and mention CSV + project."""
    proc = subprocess.run(
        [sys.executable, "-m", "bitpart", "tts", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "csv" in out.lower()
    assert "--project" in out
    assert "--provider" in out


def test_bitpart_no_subcommand_exits_nonzero_with_help():
    """`python -m bitpart` (no args) prints help to stderr and exits non-zero."""
    proc = subprocess.run(
        [sys.executable, "-m", "bitpart"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0
    # Help text appears on stderr (parser.print_help(sys.stderr)).
    combined = (proc.stdout + proc.stderr).lower()
    assert "tts" in combined  # subcommand listed in help


def test_bitpart_help_lists_tts():
    """`python -m bitpart --help` must mention the tts subcommand."""
    proc = subprocess.run(
        [sys.executable, "-m", "bitpart", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert "tts" in proc.stdout.lower()


def test_bitpart_version_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "bitpart", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert "bitpart" in proc.stdout.lower()


def test_tts_help_mentions_env_vars():
    """All BITPART_TTS_* env vars surfaced via --help should be listed there."""
    proc = _run(["tts", "--help"])
    assert proc.returncode == 0, proc.stderr
    for var in (
        "BITPART_TTS_CSV_UTTERANCE",
        "BITPART_TTS_OUTPUT_DIR",
        "BITPART_TTS_CHARACTER_VOICES",
        "BITPART_TTS_PROVIDER",
    ):
        assert var in proc.stdout, f"{var} missing from --help"


def test_provider_precedence_cli_beats_env_beats_default(monkeypatch, tmp_path):
    """Precedence: CLI argument > env var > built-in default.

    Uses ``handle()`` directly with a stubbed pipeline so we can capture exactly
    what value reaches ``convert_utterances_to_speech`` for each layer.
    """
    import argparse

    from bitpart.tts import cli as tts_cli

    csv = tmp_path / "fake.csv"
    csv.write_text("character_name,utterance_id,utterance_text\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_convert(*_args, **kwargs):
        captured["provider"] = kwargs.get("provider")

    monkeypatch.setattr(tts_cli, "convert_utterances_to_speech", fake_convert)

    def make_args(cli_provider):
        return argparse.Namespace(
            csv=str(csv),
            provider=cli_provider,
            output_dir=None,
            character_voices=None,
            project="Whatever",
            limit=None,
            debug=False,
            init=False,
            regenerate_drift=False,
        )

    # 1. Built-in default wins when neither CLI nor env is set.
    monkeypatch.delenv("BITPART_TTS_PROVIDER", raising=False)
    captured.clear()
    tts_cli.handle(make_args(cli_provider=None))
    assert captured["provider"] is None  # passed as None; pipeline applies DEFAULT_PROVIDER

    # 2. Env beats default.
    monkeypatch.setenv("BITPART_TTS_PROVIDER", "inworld")
    captured.clear()
    tts_cli.handle(make_args(cli_provider=None))
    assert captured["provider"] == "inworld"

    # 3. CLI beats env (the rule we most care about getting right).
    monkeypatch.setenv("BITPART_TTS_PROVIDER", "inworld")
    captured.clear()
    tts_cli.handle(make_args(cli_provider="elevenlabs"))
    assert captured["provider"] == "elevenlabs"


def test_tts_invalid_provider_env_exits_with_clear_error(tmp_path):
    """An unsupported BITPART_TTS_PROVIDER must exit 1 with a helpful message."""
    csv = tmp_path / "fake.csv"
    csv.write_text("character_name,utterance_id,utterance_text\n", encoding="utf-8")
    proc = _run(
        ["tts", str(csv)],
        env_extra={"BITPART_TTS_PROVIDER": "totally_made_up"},
    )
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "BITPART_TTS_PROVIDER" in combined
    assert "totally_made_up" in combined


def test_tts_no_csv_and_no_env_exits_with_helpful_error():
    """Running `bitpart tts` with no CSV and no env should exit 1 and name the env var."""
    proc = _run(["tts"])
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "BITPART_TTS_CSV_UTTERANCE" in combined
    assert "no CSV provided" in combined or "no csv provided" in combined.lower()


def test_tts_csv_env_resolves_path(tmp_path):
    """`BITPART_TTS_CSV_UTTERANCE` should make the positional CSV optional.

    With no --project we expect the *next* validation error from the pipeline
    (project required) — i.e. CSV resolution succeeded.
    """
    csv = tmp_path / "fake.csv"
    csv.write_text("character_name,utterance_id,utterance_text\n", encoding="utf-8")
    proc = _run(
        ["tts"],
        env_extra={"BITPART_TTS_CSV_UTTERANCE": str(csv)},
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    # Must NOT be the "no CSV provided" path; must be a downstream error.
    assert "no CSV provided" not in combined
    assert "no csv provided" not in combined.lower()
