"""Tests for ID3 metadata embedding, reading, and drift detection."""
import pytest

from bitpart.tts.audio_metadata import (
    check_metadata_drift,
    embed_mp3_metadata,
    get_file_provider,
    read_tts_metadata,
)
from bitpart.tts.providers.inworld import text_with_optional_emotion
from tests.tts.fixtures.silence_mp3 import write_silence_mp3

# Skip the whole file when mutagen isn't installed (it shouldn't happen in dev,
# but the production code degrades gracefully so the tests must too).
pytest.importorskip("mutagen")


# ---------------------------------------------------------------------------
# _embed_mp3_metadata + _read_tts_metadata round-trip
# ---------------------------------------------------------------------------

def test_embed_then_read_round_trip(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)

    embed_mp3_metadata(
        str(p),
        utterance_text="Hello there",
        provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "stability": 0.6},
    )

    meta = read_tts_metadata(str(p))
    assert meta is not None
    assert meta["provider"] == "elevenlabs"
    assert meta["utterance_text"] == "Hello there"
    assert meta["config"]["voice_id"] == "v1"
    assert meta["config"]["stability"] == 0.6


def test_embed_includes_tts_text_sent_only_when_different(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)

    embed_mp3_metadata(
        str(p),
        utterance_text="Hello there",
        provider="inworld",
        provider_cfg={"voice_id": "Alex"},
        tts_text_sent="[angry] Hello there",
    )

    meta = read_tts_metadata(str(p))
    assert meta["tts_text_sent"] == "[angry] Hello there"


def test_embed_omits_tts_text_sent_when_same(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)

    embed_mp3_metadata(
        str(p),
        utterance_text="Hello",
        provider="inworld",
        provider_cfg={"voice_id": "Alex"},
        tts_text_sent="Hello",
    )

    meta = read_tts_metadata(str(p))
    assert "tts_text_sent" not in meta


def test_read_returns_none_for_file_without_tag(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    assert read_tts_metadata(str(p)) is None


# ---------------------------------------------------------------------------
# _get_file_provider
# ---------------------------------------------------------------------------

def test_get_file_provider_returns_embedded_value(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="x", provider="elevenlabs", provider_cfg={"voice_id": "v"}
    )
    assert get_file_provider(str(p)) == "elevenlabs"


def test_get_file_provider_returns_empty_when_no_metadata(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    assert get_file_provider(str(p)) == ""


# ---------------------------------------------------------------------------
# _check_metadata_drift
# ---------------------------------------------------------------------------

def _embed(p, *, text="Hello", provider="elevenlabs", voice_id="v1"):
    embed_mp3_metadata(
        str(p),
        utterance_text=text,
        provider=provider,
        provider_cfg={"voice_id": voice_id},
    )


def test_drift_returns_empty_when_everything_matches(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p)
    assert check_metadata_drift(
        str(p), expected_utterance_text="Hello", expected_config={"voice_id": "v1"},
        current_provider="elevenlabs", character_name="Townsperson",
    ) == []


def test_drift_returns_empty_when_no_metadata_present(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    assert check_metadata_drift(
        str(p), expected_utterance_text="Hello", expected_config={"voice_id": "v1"},
        current_provider="elevenlabs",
    ) == []


def test_drift_detects_voice_id_change(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, voice_id="v1")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hello", expected_config={"voice_id": "v2"},
        current_provider="elevenlabs", character_name="Townsperson",
    )
    assert len(issues) == 1
    assert "voice_id drift" in issues[0]
    assert "v1" in issues[0] and "v2" in issues[0]
    assert "key=Townsperson" in issues[0]


def test_drift_detects_utterance_text_change(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, text="Hello")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Goodbye", expected_config={"voice_id": "v1"},
        current_provider="elevenlabs", character_name="Townsperson",
    )
    assert len(issues) == 1
    assert "utterance_text drift" in issues[0]


def test_drift_detects_both_when_both_changed(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, text="Hi", voice_id="v1")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Bye", expected_config={"voice_id": "v2"},
        current_provider="elevenlabs",
    )
    assert len(issues) == 2


def test_drift_voice_id_message_includes_provider_when_same(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, provider="elevenlabs", voice_id="v1")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hello", expected_config={"voice_id": "v2"},
        current_provider="elevenlabs",
    )
    assert "provider=elevenlabs" in issues[0]


def test_drift_voice_id_message_distinguishes_providers_when_different(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, provider="elevenlabs", voice_id="v1")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hello", expected_config={"voice_id": "v2"},
        current_provider="inworld",
    )
    msg = issues[0]
    assert "provider(previous)=elevenlabs" in msg
    assert "provider(current)=inworld" in msg


# ---------------------------------------------------------------------------
# Drift detection — full provider config (stability, model_id, temperature, ...)
# ---------------------------------------------------------------------------

def test_drift_detects_elevenlabs_stability_change(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "stability": 0.6},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi",
        expected_config={"voice_id": "v1", "stability": 0.4},
        current_provider="elevenlabs", character_name="Townsperson",
    )
    assert len(issues) == 1
    assert "stability drift" in issues[0]
    assert "0.6" in issues[0] and "0.4" in issues[0]
    assert "key=Townsperson" in issues[0]
    assert "provider=elevenlabs" in issues[0]


def test_drift_detects_elevenlabs_model_id_change(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "model_id": "eleven_multilingual_v2"},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi",
        expected_config={"voice_id": "v1", "model_id": "eleven_turbo_v2_5"},
        current_provider="elevenlabs",
    )
    assert len(issues) == 1
    assert "model_id drift" in issues[0]


def test_drift_detects_inworld_temperature_change(tmp_path):
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="inworld",
        provider_cfg={"voice_id": "Alex", "temperature": 1.0},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi",
        expected_config={"voice_id": "Alex", "temperature": 1.4},
        current_provider="inworld",
    )
    assert len(issues) == 1
    assert "temperature drift" in issues[0]
    assert "1.0" in issues[0] and "1.4" in issues[0]


def test_drift_intersection_skips_key_missing_from_embedded(tmp_path):
    """If the embedded MP3 doesn't have the key (legacy file), don't flag drift
    when the key was added to the JSON later."""
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1"},  # no stability embedded
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi",
        expected_config={"voice_id": "v1", "stability": 0.4},  # stability newly added
        current_provider="elevenlabs",
    )
    assert issues == []


def test_drift_intersection_skips_key_missing_from_expected(tmp_path):
    """If the JSON no longer specifies the key, treat it as opted-out (no drift)."""
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "stability": 0.6},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi",
        expected_config={"voice_id": "v1"},  # stability removed from JSON
        current_provider="elevenlabs",
    )
    assert issues == []


def test_drift_detects_multiple_keys_at_once(tmp_path):
    """voice_id + stability + utterance_text all changing produces 3 issues."""
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "stability": 0.6, "similarity_boost": 0.8},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Bye",
        expected_config={"voice_id": "v2", "stability": 0.4, "similarity_boost": 0.8},
        current_provider="elevenlabs",
    )
    # voice_id changed, stability changed, utterance_text changed; similarity_boost matches
    assert len(issues) == 3
    joined = "\n".join(issues)
    assert "voice_id drift" in joined
    assert "stability drift" in joined
    assert "utterance_text drift" in joined


def test_drift_messages_include_row_idx_when_provided(tmp_path):
    """row_idx is surfaced in every drift message so users can find the CSV row fast."""
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    embed_mp3_metadata(
        str(p), utterance_text="Hi", provider="elevenlabs",
        provider_cfg={"voice_id": "v1", "stability": 0.6},
    )
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Bye",
        expected_config={"voice_id": "v2", "stability": 0.4},
        current_provider="elevenlabs", character_name="Townsperson6", row_idx=4,
    )
    assert len(issues) == 3
    for msg in issues:
        assert "csv_row=4" in msg
        assert "key=Townsperson6" in msg


def test_drift_messages_omit_row_when_row_idx_not_provided(tmp_path):
    """No row_idx -> no csv_row=... fragment (back-compat for existing callers)."""
    p = tmp_path / "a.mp3"
    write_silence_mp3(p)
    _embed(p, voice_id="v1")
    issues = check_metadata_drift(
        str(p), expected_utterance_text="Hi", expected_config={"voice_id": "v2"},
        current_provider="elevenlabs", character_name="Townsperson",
    )
    assert "csv_row=" not in issues[0]


# ---------------------------------------------------------------------------
# _inworld_text_with_optional_emotion
# ---------------------------------------------------------------------------

def test_inworld_emotion_prepends_bracket_tag():
    assert text_with_optional_emotion("hi", "angry") == "[angry] hi"


def test_inworld_emotion_returns_text_when_emotion_blank():
    import math
    assert text_with_optional_emotion("hi", "") == "hi"
    assert text_with_optional_emotion("hi", "   ") == "hi"
    assert text_with_optional_emotion("hi", math.nan) == "hi"
