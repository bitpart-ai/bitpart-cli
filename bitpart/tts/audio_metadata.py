"""ID3 metadata read/write + drift detection for generated MP3s.

Every audio file gets a single ``TXXX`` user-text frame named ``TTS_METADATA``
whose payload is JSON describing what produced it::

    {
      "provider": "elevenlabs",
      "config": {"voice_id": "...", "stability": 0.6, ...},
      "utterance_text": "Hello there",
      "tts_text_sent": "[angry] Hello there"   // only when different
    }

This is what powers drift detection (CSV/JSON changed since the audio was generated)
and wrong-provider detection (existing files were made by a different
provider than the current ``--provider`` flag).

Drift checks every key listed in ``PROVIDER_DRIFT_KEYS`` for the active
provider, using an *intersection rule*: a key only fires drift when it is
present in both the embedded metadata and the current JSON. That way,
adding a brand-new key to ``character_voices.json`` later does not retro-
actively flag older audio files that were generated before the key existed.
"""
import json
from pathlib import Path

from bitpart.tts.config import PROVIDER_DRIFT_KEYS


def _provider_cfg_for_metadata(cfg: dict) -> dict:
    """Copy provider config keeping only JSON-friendly values."""
    out: dict = {}
    for k, v in cfg.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, Path):
            out[k] = str(v)
        else:
            out[k] = str(v)
    return out


def embed_mp3_metadata(
    path: str,
    *,
    utterance_text: str,
    provider: str,
    provider_cfg: dict,
    tts_text_sent: str | None = None,
) -> None:
    """Write the ``TTS_METADATA`` ID3 frame to an MP3.

    Fails silently if mutagen is missing or the file can't be tagged — the
    audio file itself is still valid; we just won't get drift detection on it.
    """
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import TXXX
    except ImportError:
        return

    try:
        audio = MP3(path)
        if audio.tags is None:
            audio.add_tags()

        payload = {
            "provider": provider,
            "config": _provider_cfg_for_metadata(provider_cfg),
            "utterance_text": utterance_text,
        }
        if tts_text_sent is not None and tts_text_sent != utterance_text:
            payload["tts_text_sent"] = tts_text_sent

        meta_json = json.dumps(payload, ensure_ascii=False)
        audio.tags.add(TXXX(encoding=3, desc="TTS_METADATA", text=meta_json))
        audio.save()
    except Exception:
        pass


def read_tts_metadata(path: str) -> dict | None:
    """Return the parsed ``TTS_METADATA`` frame, or None if missing/unreadable."""
    try:
        from mutagen.mp3 import MP3
    except ImportError:
        return None
    try:
        audio = MP3(path)
        if not audio.tags:
            return None
        for f in audio.tags.getall("TXXX"):
            if f.desc == "TTS_METADATA":
                try:
                    return json.loads(f.text[0])
                except Exception:
                    return None
        return None
    except Exception:
        return None


def get_file_provider(path: str) -> str:
    """Return the provider string embedded in the MP3, or '' if missing/unreadable."""
    meta = read_tts_metadata(path)
    return str(meta.get("provider", "")) if meta else ""


def _format_drift_issue(
    field_name: str,
    embedded_value: object,
    current_value: object,
    *,
    current_source: str,
) -> str:
    """One line: value embedded in the audio file vs value in CSV/JSON today."""
    return (
        f"{field_name}: audio file has {embedded_value!r}, "
        f"{current_source} has {current_value!r}"
    )


def _voice_id_drift_message(
    embedded_voice_id: str,
    current_voice_id: str,
    *,
    embedded_provider: str,
    current_provider: str,
) -> str:
    """voice_id drift; call out both providers when they differ (IDs aren't comparable)."""
    if embedded_provider and current_provider and embedded_provider != current_provider:
        return (
            f"voice_id: audio file has {embedded_voice_id!r} (provider {embedded_provider}), "
            f"character_voices.json has {current_voice_id!r} (provider {current_provider})"
        )
    return _format_drift_issue(
        "voice_id",
        embedded_voice_id,
        current_voice_id,
        current_source="character_voices.json",
    )


def check_metadata_drift(
    path: str,
    expected_utterance_text: str,
    expected_config: dict,
    current_provider: str = "",
) -> list[str]:
    """Compare the embedded metadata against current CSV / JSON expectations.

    Returns a list of human-readable mismatch reasons (empty when OK).

    Files without a ``TTS_METADATA`` frame are treated as OK to avoid noisy
    false positives on legacy audio.

    For provider-config keys, we use an *intersection rule*: a key is only
    compared when it exists in both the embedded metadata and ``expected_config``.
    This keeps legacy files quiet when you add a new optional key to
    ``character_voices.json`` later.
    """
    meta = read_tts_metadata(path)
    if meta is None:
        return []
    embedded_provider = str(meta.get("provider", ""))
    embedded_config = meta.get("config") or {}

    issues: list[str] = []

    # Provider-config drift — iterate over every audio-affecting key for this provider.
    keys_to_check = PROVIDER_DRIFT_KEYS.get(current_provider, ("voice_id",))
    for key in keys_to_check:
        if key not in embedded_config or key not in expected_config:
            continue  # intersection rule: skip when either side doesn't define it
        embedded_value = embedded_config[key]
        current_value = expected_config[key]
        if str(embedded_value) == str(current_value):
            continue
        if key == "voice_id":
            issues.append(_voice_id_drift_message(
                str(embedded_value),
                str(current_value),
                embedded_provider=embedded_provider,
                current_provider=current_provider,
            ))
        else:
            issues.append(_format_drift_issue(
                key,
                embedded_value,
                current_value,
                current_source="character_voices.json",
            ))

    # utterance_text drift (CSV-side, not provider-config).
    embedded_utterance_text = str(meta.get("utterance_text", ""))
    if (
        expected_utterance_text
        and embedded_utterance_text
        and embedded_utterance_text != expected_utterance_text
    ):
        issues.append(_format_drift_issue(
            "utterance_text",
            embedded_utterance_text,
            expected_utterance_text,
            current_source="CSV",
        ))
    return issues
