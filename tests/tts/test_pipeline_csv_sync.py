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
    assert str(result.loc[0, "file_name"]).strip() == str(mp3_path.resolve())
