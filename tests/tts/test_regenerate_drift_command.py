"""Tests for drift rerun command hints."""
from pathlib import Path

from bitpart.tts.pipeline import RunConfig, _regenerate_drift_command


def _minimal_config(**overrides) -> RunConfig:
    base = dict(
        csv_path="/tmp/u.csv",
        output_dir="/tmp",
        project="Tutorial",
        provider="inworld",
        api_key="",
        voices_path=Path("/tmp/character_voices.json"),
        character_voices={},
        has_emotion_column=False,
        max_attempts=1,
        retry_count=0,
        inworld_model_id="",
        skip_existing=True,
        debug=False,
        regenerate_drift=False,
        limit=None,
        cli_argv=None,
    )
    base.update(overrides)
    return RunConfig(**base)


def test_regenerate_drift_command_uses_captured_argv():
    cfg = _minimal_config(
        cli_argv=["bitpart", "tts", "my.csv", "--project", "Tutorial", "--debug"],
    )
    assert _regenerate_drift_command(cfg) == (
        "bitpart tts my.csv --project Tutorial --debug --regenerate-drift"
    )


def test_regenerate_drift_command_does_not_duplicate_flag():
    cfg = _minimal_config(
        cli_argv=["bitpart", "tts", "my.csv", "--regenerate-drift"],
    )
    assert _regenerate_drift_command(cfg) == "bitpart tts my.csv --regenerate-drift"


def test_regenerate_drift_command_without_argv():
    assert _regenerate_drift_command(_minimal_config()) is None


def test_regenerate_drift_command_normalizes_venv_executable():
    cfg = _minimal_config(
        cli_argv=[
            r"C:\Github\bitpart-cli\venv\Scripts\bitpart.exe",
            "tts",
            "my.csv",
            "--project",
            "Tutorial",
            "--provider",
            "inworld",
        ],
    )
    assert _regenerate_drift_command(cfg) == (
        "bitpart tts my.csv --project Tutorial --provider inworld --regenerate-drift"
    )


def test_regenerate_drift_command_normalizes_python_module_invocation():
    cfg = _minimal_config(
        cli_argv=["python", "-m", "bitpart", "tts", "my.csv", "--project", "Tutorial"],
    )
    assert _regenerate_drift_command(cfg) == (
        "bitpart tts my.csv --project Tutorial --regenerate-drift"
    )
