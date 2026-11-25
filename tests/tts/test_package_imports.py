"""Smoke tests asserting the ``bitpart.tts.*`` modules are importable and wired correctly.

These intentionally use direct module paths so a future change that breaks the
package layout fails loudly at import time.
"""
import pandas as pd
import pytest


def test_top_level_package_exposes_public_api():
    import bitpart.tts as tts

    assert callable(tts.convert_utterances_to_speech)
    assert callable(tts.init_character_voices)
    assert callable(tts.load_character_voices)


def test_voices_module_helpers_importable():
    from bitpart.tts.voices import (
        get_voice_config_for_row,
        load_character_voices,
        resolve_voices_path,
    )
    assert callable(get_voice_config_for_row)
    assert callable(load_character_voices)
    assert callable(resolve_voices_path)


def test_audio_metadata_module_helpers_importable():
    from bitpart.tts.audio_metadata import (
        check_metadata_drift,
        embed_mp3_metadata,
        get_file_provider,
        read_tts_metadata,
    )
    assert callable(check_metadata_drift)
    assert callable(embed_mp3_metadata)
    assert callable(get_file_provider)
    assert callable(read_tts_metadata)


def test_providers_dispatch_table_lists_both_providers():
    from bitpart.tts import providers

    assert "elevenlabs" in providers.SUPPORTED
    assert "inworld" in providers.SUPPORTED


def test_providers_dispatch_rejects_unknown():
    from bitpart.tts import providers

    with pytest.raises(SystemExit):
        providers.generate(
            "nope", api_key="x", text="hi", cfg={"voice_id": "v"},
            full_path="/tmp/x.mp3", inworld_default_model_id="m",
        )


def test_csv_io_helpers_importable():
    from bitpart.tts.csv_io import (
        ensure_output_dir,
        get_audio_filename,
        get_full_audio_path,
        is_already_processed_in_output_dir,
        load_and_validate_dataframe,
    )
    assert callable(ensure_output_dir)
    assert callable(get_audio_filename)
    assert callable(get_full_audio_path)
    assert callable(is_already_processed_in_output_dir)
    assert callable(load_and_validate_dataframe)


def test_inworld_emotion_helper_in_provider_module():
    from bitpart.tts.providers.inworld import text_with_optional_emotion
    assert text_with_optional_emotion("hi", "angry") == "[angry] hi"
    assert text_with_optional_emotion("hi", "") == "hi"


def test_warn_prints_message(monkeypatch, capsys):
    monkeypatch.setattr("bitpart.shared.color._USE_COLOR", True)
    from bitpart.shared.color import warn

    warn("hello")
    out = capsys.readouterr().out
    assert "\033[33m" in out and "hello" in out and "\033[0m" in out

def test_load_character_voices_via_package(tmp_path):
    import json
    from bitpart.tts.voices import load_character_voices

    p = tmp_path / "cv.json"
    p.write_text(json.dumps({"V": {"X": {"providers": {"elevenlabs": {"voice_id": "v"}}}}}),
                 encoding="utf-8")
    out = load_character_voices(str(p), project="V")
    assert out["X"]["providers"]["elevenlabs"]["voice_id"] == "v"


def test_get_voice_config_for_row_via_package():
    from bitpart.tts.voices import get_voice_config_for_row

    voices = {"X": {"providers": {"elevenlabs": {"voice_id": "v1"}}}}
    cfg, reason = get_voice_config_for_row(
        pd.Series({"character_name": "X"}), voices, "elevenlabs"
    )
    assert reason == ""
    assert cfg["voice_id"] == "v1"
