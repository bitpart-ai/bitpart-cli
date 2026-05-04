"""ElevenLabs TTS REST integration (no SDK, raw urllib)."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from bitpart.tts.config import (
    ELEVENLABS_TTS_BASE,
    ELEVENLABS_VOICE_SETTING_KEYS,
    MODEL_ID,
    OUTPUT_FORMAT,
)


def generate(api_key: str, text: str, cfg: dict, full_path: str) -> None:
    """Call ElevenLabs TTS and write the MP3 to ``full_path``. Raises on failure.

    ``cfg`` is the per-character ``providers.elevenlabs`` dict, e.g.::

        {"voice_id": "...", "model_id": "eleven_turbo_v2_5", "stability": 0.6}

    Optional keys: ``model_id`` and any of ``ELEVENLABS_VOICE_SETTING_KEYS``.
    """
    voice_id = cfg["voice_id"]
    model_id = cfg.get("model_id") or MODEL_ID
    voice_settings = {k: cfg[k] for k in ELEVENLABS_VOICE_SETTING_KEYS if k in cfg}

    payload: dict = {"text": text, "model_id": model_id}
    if voice_settings:
        payload["voice_settings"] = voice_settings

    qs = urlencode({"output_format": OUTPUT_FORMAT})
    url = f"{ELEVENLABS_TTS_BASE}/{quote(voice_id, safe='')}?{qs}"
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            audio_bytes = resp.read()
    except HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {err_body or e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"ElevenLabs request failed: {e.reason}") from e

    with open(full_path, "wb") as f:
        f.write(audio_bytes)
