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

_UNSET_META = object()


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


def _voice_id_drift_message(
    embedded_voice_id: str,
    expected_voice_id: str,
    *,
    file_provider: str,
    current_provider: str,
    key_part: str,
    row_part: str,
    cont: str,
) -> str:
    """voice_id is special-cased so the cross-provider message format is preserved.

    (Comparing voice_ids across providers is meaningless because the IDs live
    in different namespaces; the message makes that explicit.)
    """
    if file_provider and current_provider and file_provider != current_provider:
        provider_part = (
            f"provider(previous)={file_provider} provider(current)={current_provider}"
        )
    elif current_provider:
        provider_part = f"provider={current_provider}"
    elif file_provider:
        provider_part = f"provider={file_provider}"
    else:
        provider_part = ""
    head = " ".join(p for p in (key_part, row_part, provider_part) if p)
    return (
        f"voice_id drift ({head}{cont}"
        f"audio_file(previous)='{embedded_voice_id}', json(current)='{expected_voice_id}')"
    )


def _generic_key_drift_message(
    key: str,
    embedded_value: object,
    expected_value: object,
    *,
    current_provider: str,
    key_part: str,
    row_part: str,
    cont: str,
) -> str:
    """Drift message for any audio-affecting key other than voice_id."""
    provider_part = f"provider={current_provider}" if current_provider else ""
    head = " ".join(p for p in (key_part, row_part, provider_part) if p)
    return (
        f"{key} drift ({head}{cont}"
        f"audio_file(previous)={embedded_value!r}, json(current)={expected_value!r})"
    )


def check_metadata_drift(
    path: str,
    expected_utterance_text: str,
    expected_config: dict,
    current_provider: str = "",
    character_name: str = "",
    row_idx: int | None = None,
    *,
    embedded_meta: dict | None | object = _UNSET_META,
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
    if embedded_meta is _UNSET_META:
        meta = read_tts_metadata(path)
    else:
        meta = embedded_meta
    if meta is None:
        return []
    # 8 spaces aligns continuation lines under the bullet in the summary report.
    cont = "\n" + " " * 8
    key_part = f"key={character_name}" if character_name else ""
    row_part = f"csv_row={row_idx}" if row_idx is not None else ""
    file_provider = str(meta.get("provider", ""))
    embedded_audio_cfg = meta.get("config") or {}

    issues: list[str] = []

    # Provider-config drift — iterate over every audio-affecting key for this provider.
    keys_to_check = PROVIDER_DRIFT_KEYS.get(current_provider, ("voice_id",))
    for key in keys_to_check:
        if key not in embedded_audio_cfg or key not in expected_config:
            continue  # intersection rule: skip when either side doesn't define it
        embedded_value = embedded_audio_cfg[key]
        expected_value = expected_config[key]
        if str(embedded_value) == str(expected_value):
            continue
        if key == "voice_id":
            issues.append(_voice_id_drift_message(
                str(embedded_value), str(expected_value),
                file_provider=file_provider, current_provider=current_provider,
                key_part=key_part, row_part=row_part, cont=cont,
            ))
        else:
            issues.append(_generic_key_drift_message(
                key, embedded_value, expected_value,
                current_provider=current_provider,
                key_part=key_part, row_part=row_part, cont=cont,
            ))

    # utterance_text drift (CSV-side, not provider-config).
    embedded_text = str(meta.get("utterance_text", ""))
    if expected_utterance_text and embedded_text and embedded_text != expected_utterance_text:
        head = " ".join(p for p in (key_part, row_part) if p)
        issues.append(
            f"utterance_text drift ({head}{cont}"
            f"audio_file(previous)={embedded_text!r}, csv(current)={expected_utterance_text!r})"
        )
    return issues
