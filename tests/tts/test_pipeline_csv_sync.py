"""Pipeline: restore ``file_name`` from on-disk audio when CSV cells are cleared."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from bitpart.tts.audio_metadata import embed_mp3_metadata
from bitpart.tts.csv_io import get_audio_filename, load_and_validate_dataframe
from bitpart.tts.pipeline import convert_utterances_to_speech

pytest.importorskip("mutagen")

CHAR_ID = "11111111-1111-1111-1111-111111111111"
UTT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CHAR_NAME = "TutorialNpc"


def test_clears_file_name_restores_from_disk(tmp_path, monkeypatch):
    """Clearing file_name must repopulate it when the MP3 already exists."""
    csv_path = tmp_path / "utterances.csv"
    out_dir = tmp_path / "audio"
    out_dir.mkdir()
    mp3_path = out_dir / get_audio_filename(CHAR_ID, UTT_ID)
    mp3_path.write_bytes(b"\xff\xfb")

    pd.DataFrame(
        [
            {
                "index": 0,
                "utterance_id": UTT_ID,
                "character_id": CHAR_ID,
                "character_name": CHAR_NAME,
                "utterance_text": "Hello",
                "file_name": "",
            }
        ]
    ).to_csv(csv_path, index=False)

    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps(
            {
                "Tutorial": {
                    CHAR_NAME: {
                        "character_id": CHAR_ID,
                        "providers": {
                            "inworld": {
                                "voice_id": "test-voice",
                                "model_id": "inworld-tts-1.5-mini",
                            },
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    embed_mp3_metadata(
        str(mp3_path),
        utterance_text="Hello",
        provider="inworld",
        provider_cfg={"voice_id": "test-voice", "model_id": "inworld-tts-1.5-mini"},
    )

    def fail_generate(*_args, **_kwargs):
        raise AssertionError("TTS API should not be called when audio already exists")

    monkeypatch.setenv("INWORLD_API_KEY", "test-key")
    with patch("bitpart.tts.providers.generate", side_effect=fail_generate):
        convert_utterances_to_speech(
            str(csv_path),
            output_dir=str(out_dir),
            character_voices_path=str(voices_path),
            project="Tutorial",
            provider="inworld",
            api_key="test-key",
        )

    result = load_and_validate_dataframe(str(csv_path))
    # Stored relative to the root (here the CSV folder, as there is no .uproject), with forward slashes.
    assert str(result.loc[0, "file_name"]).strip() == f"audio/{mp3_path.name}"


def test_generates_variant_audio_and_records_variant_column(tmp_path, monkeypatch):
    """Each configured variant gets its own file recorded in the single ``file_name`` cell."""
    csv_path = tmp_path / "utterances.csv"
    out_dir = tmp_path / "audio"
    out_dir.mkdir()
    pd.DataFrame(
        [
            {
                "index": 0,
                "utterance_id": UTT_ID,
                "character_id": CHAR_ID,
                "character_name": CHAR_NAME,
                "utterance_text": "Hello",
                "file_name": "",
            }
        ]
    ).to_csv(csv_path, index=False)
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps(
            {
                "Tutorial": {
                    CHAR_NAME: {
                        "providers": {
                            "inworld": {"voice_ids": ["base", "other"]}
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def fake_generate(provider, *, full_path, cfg, **_kwargs):
        calls.append((Path(full_path).name, cfg["voice_id"]))
        Path(full_path).write_bytes(b"\xff\xfb")

    monkeypatch.setenv("INWORLD_API_KEY", "test-key")
    with patch("bitpart.tts.providers.generate", side_effect=fake_generate), patch(
        "bitpart.tts.pipeline.embed_mp3_metadata"
    ):
        convert_utterances_to_speech(
            str(csv_path),
            output_dir=str(out_dir),
            character_voices_path=str(voices_path),
            project="Tutorial",
            provider="inworld",
            api_key="test-key",
        )

    assert calls == [
        (f"{CHAR_ID}_{UTT_ID}.mp3", "base"),
        (f"{CHAR_ID}_{UTT_ID}__v2.mp3", "other"),
    ]
    result = load_and_validate_dataframe(str(csv_path))
    assert str(result.loc[0, "file_name"]) == (
        f"audio/{CHAR_ID}_{UTT_ID}.mp3|audio/{CHAR_ID}_{UTT_ID}__v2.mp3"
    )
    assert "variant_file_names" not in result.columns


def test_absolute_paths_in_old_csv_become_relative_and_skip_regeneration(tmp_path, monkeypatch):
    """A CSV written before relative paths (absolute file_name) is migrated, not regenerated."""
    csv_path = tmp_path / "utterances.csv"
    out_dir = tmp_path / "audio"
    out_dir.mkdir()
    mp3_path = out_dir / get_audio_filename(CHAR_ID, UTT_ID)
    mp3_path.write_bytes(b"\xff\xfb")
    pd.DataFrame(
        [{"index": 0, "utterance_id": UTT_ID, "character_id": CHAR_ID, "character_name": CHAR_NAME,
          "utterance_text": "Hello", "file_name": str(mp3_path.resolve())}]
    ).to_csv(csv_path, index=False)
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({"Tutorial": {CHAR_NAME: {"providers": {"inworld": {"voice_id": "v", "model_id": "m"}}}}}),
        encoding="utf-8",
    )
    embed_mp3_metadata(str(mp3_path), utterance_text="Hello", provider="inworld",
                       provider_cfg={"voice_id": "v", "model_id": "m"})

    def fail_generate(*_a, **_k):
        raise AssertionError("must not regenerate")

    monkeypatch.setenv("INWORLD_API_KEY", "k")
    with patch("bitpart.tts.providers.generate", side_effect=fail_generate):
        convert_utterances_to_speech(
            str(csv_path), output_dir=str(out_dir), character_voices_path=str(voices_path),
            project="Tutorial", provider="inworld", api_key="k",
        )
    result = load_and_validate_dataframe(str(csv_path))
    assert str(result.loc[0, "file_name"]) == f"audio/{mp3_path.name}"


def test_root_defaults_to_nearest_uproject_dir(tmp_path):
    from bitpart.tts.csv_io import find_project_root, resolve_stored_path, to_stored_path

    proj = tmp_path / "Game"
    (proj / "Artifacts").mkdir(parents=True)
    (proj / "Game.uproject").write_text("{}")
    assert find_project_root(proj / "Artifacts") == proj.resolve()
    assert find_project_root(tmp_path) is None
    stored = to_stored_path(str(proj / "Artifacts" / "a.mp3"), proj)
    assert stored == "Artifacts/a.mp3"
    assert resolve_stored_path(stored, proj) == str((proj / "Artifacts" / "a.mp3").resolve())


def test_rerun_with_multi_voice_cell_does_not_regenerate(tmp_path, monkeypatch):
    """Second run over a CSV whose file_name already lists every voice generates nothing."""
    csv_path = tmp_path / "utterances.csv"
    out_dir = tmp_path / "audio"
    out_dir.mkdir()
    pd.DataFrame(
        [{"index": 0, "utterance_id": UTT_ID, "character_id": CHAR_ID, "character_name": CHAR_NAME,
          "utterance_text": "Hello", "file_name": ""}]
    ).to_csv(csv_path, index=False)
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({"Tutorial": {CHAR_NAME: {"providers": {"inworld": {"voice_ids": ["base", "other"]}}}}}),
        encoding="utf-8",
    )
    calls = []

    def fake_generate(provider, *, full_path, cfg, **_k):
        calls.append(Path(full_path).name)
        Path(full_path).write_bytes(b"\xff\xfb")

    monkeypatch.setenv("INWORLD_API_KEY", "k")
    kwargs = dict(output_dir=str(out_dir), character_voices_path=str(voices_path),
                  project="Tutorial", provider="inworld", api_key="k")
    with patch("bitpart.tts.providers.generate", side_effect=fake_generate):
        convert_utterances_to_speech(str(csv_path), **kwargs)
        first = str(load_and_validate_dataframe(str(csv_path)).loc[0, "file_name"])
        convert_utterances_to_speech(str(csv_path), **kwargs)
        second = str(load_and_validate_dataframe(str(csv_path)).loc[0, "file_name"])
    assert len(calls) == 2
    assert first == second


def test_limit_still_fills_file_name_for_existing_audio_after_limit(tmp_path, monkeypatch):
    """--limit stops generation, but later rows with audio on disk still get file_name filled in."""
    csv_path = tmp_path / "utterances.csv"
    out_dir = tmp_path / "audio"
    out_dir.mkdir()
    rows = [
        {"index": i, "utterance_id": f"u{i}", "character_id": CHAR_ID, "character_name": CHAR_NAME,
         "utterance_text": "Hello"}
        for i in range(3)
    ]
    pd.DataFrame(rows).to_csv(csv_path, index=False)  # fresh CSV: no file_name column
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({"Tutorial": {CHAR_NAME: {"providers": {"inworld": {"voice_id": "base"}}}}}),
        encoding="utf-8",
    )
    # Row 0 needs generating; rows 1 and 2 already have audio on disk.
    for i in (1, 2):
        (out_dir / get_audio_filename(CHAR_ID, f"u{i}")).write_bytes(b"\xff\xfb")
    calls = []

    def fake_generate(provider, *, full_path, cfg, **_k):
        calls.append(Path(full_path).name)
        Path(full_path).write_bytes(b"\xff\xfb")

    monkeypatch.setenv("INWORLD_API_KEY", "k")
    with patch("bitpart.tts.providers.generate", side_effect=fake_generate):
        convert_utterances_to_speech(
            str(csv_path), output_dir=str(out_dir), character_voices_path=str(voices_path),
            project="Tutorial", provider="inworld", api_key="k", limit=1,
        )
    df = load_and_validate_dataframe(str(csv_path))
    assert len(calls) == 1
    assert all(str(v).strip() for v in df["file_name"])
