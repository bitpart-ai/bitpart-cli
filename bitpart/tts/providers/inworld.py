"""Inworld TTS REST integration (no SDK, raw urllib)."""
import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from bitpart.tts.config import INWORLD_TTS_URL


def text_with_optional_emotion(utterance_text: str, emotion: object) -> str:
    """If ``emotion`` is non-empty, prepend ``[tag]`` per Inworld TTS conventions."""
    if pd.isna(emotion) or str(emotion).strip() == "":
        return utterance_text
    tag = str(emotion).strip()
    return f"[{tag}] {utterance_text}"


def generate(
    api_key: str,
    text: str,
    cfg: dict,
    full_path: str,
    *,
    default_model_id: str,
    audio_encoding: str = "MP3",
    sample_rate_hz: int = 44100,
    bit_rate: int = 128000,
) -> None:
    """Call Inworld TTS and write the MP3 to ``full_path``. Raises on failure.

    ``cfg`` is the per-character ``providers.inworld`` dict, e.g.::

        {"voice_id": "...", "model_id": "inworld-tts-1.5-mini",
         "temperature": 1.1, "speed": 1.05}

    Optional keys: ``model_id``, ``temperature``, ``speed``.
    """
    voice_id = cfg["voice_id"]
    model_id = cfg.get("model_id") or default_model_id
    payload = {
        "text": text,
        "voiceId": voice_id,
        "modelId": model_id,
        "audioConfig": {
            "audioEncoding": audio_encoding,
            "sampleRateHertz": sample_rate_hz,
            "bitRate": bit_rate,
        },
        "temperature": float(cfg.get("temperature", 1.0)),
        "applyTextNormalization": "ON",
    }
    if "speed" in cfg:
        payload["audioConfig"]["speakingRate"] = float(cfg["speed"])
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        INWORLD_TTS_URL,
        data=body,
        headers={
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            resp_body = resp.read()
    except HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"Inworld HTTP {e.code}: {err_body or e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"Inworld request failed: {e.reason}") from e

    try:
        data = json.loads(resp_body.decode("utf-8"))
        audio_b64 = data.get("audioContent")
        if not audio_b64:
            raise KeyError("audioContent")
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as e:
        raise RuntimeError(f"Failed to parse Inworld response: {e}") from e
    with open(full_path, "wb") as f:
        f.write(audio_bytes)
