# Adding a new TTS provider

This is the step-by-step recipe for adding a third TTS provider (or fourth, etc.) to the pipeline. Today we have **ElevenLabs** and **Inworld**; this doc walks through what you'd touch to add a hypothetical **OpenAI TTS** provider as a worked example.

> **Heads up — the if/elif pattern.** The codebase deliberately uses small `if/elif` chains for provider dispatch (in 3 places) instead of a registry. That's fine for two providers and easy to read, but it means **every new provider touches the same 3 functions**. If you find yourself adding a fourth provider, that's the right time to refactor to a registry pattern — see the bottom of this doc.

---

## Prerequisites

Before starting, gather these from your provider's docs:

- **Auth scheme** — Bearer token? `xi-api-key` header? HTTP Basic? Different providers use different conventions.
- **Endpoint URL** for synthesizing speech.
- **Request body shape** — text field name, voice ID field name, audio format options.
- **Response shape** — does it return raw audio bytes (like ElevenLabs), or JSON with base64-encoded audio (like Inworld)?
- **The voice ID format** — what does a "voice ID" look like for this provider? (UUID? Slug like "Alex"? URL?)
- **Tunable knobs** — temperature, stability, speed, etc. that you want exposed in `character_voices.json`.

---

## The checklist

Seven files to touch. Four are required code changes, three are config/docs.

| # | File | Type | What to change |
|---|---|---|---|
| 1 | `bitpart/tts/providers/<name>.py` | **NEW** | Create a `generate(api_key, text, cfg, full_path)` function |
| 2 | `bitpart/tts/providers/__init__.py` | edit | Import the module, add to `SUPPORTED`, add `elif` branch in `generate()` |
| 3 | `bitpart/tts/pipeline.py` | edit | Add an API-key branch in `_resolve_api_key` |
| 4 | `bitpart/tts/pipeline.py` | edit | Add an error-message branch in `_ensure_api_key_or_exit` |
| 5 | `bitpart/tts/config.py` | edit | Add a `PROVIDER_DRIFT_KEYS["<name>"]` entry so drift detection covers the provider's audio-affecting keys |
| 6 | `character_voices.json` | edit | Add `providers.<name>` blocks to characters that should support it |
| 7 | `README.md` | edit | Document the provider and its voice-config keys |

Optional but recommended:

| # | File | What to change |
|---|---|---|
| 8 | `bitpart/tts/config.py` | Add provider-specific defaults (model name, API base URL, passthrough/voice-setting key tuples) |
| 9 | `tests/` | Add a unit test for any provider-specific helper (e.g. text transformation) |

> **Why step 5 matters:** without a `PROVIDER_DRIFT_KEYS` entry, drift detection silently falls back to checking only `voice_id` for your provider — every other config tweak (stability, model_id, temperature, ...) will be missed.

---

## Worked example: adding "OpenAI TTS"

Pretend OpenAI's TTS API:

- POSTs to `https://api.openai.com/v1/audio/speech`
- Auth via `Authorization: Bearer <key>`
- JSON body: `{"model": "tts-1", "voice": "alloy", "input": "...", "response_format": "mp3", "speed": 1.0}`
- Returns raw MP3 bytes
- Voice IDs are slugs: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`

### Step 1 — Create `bitpart/tts/providers/openai.py`

Mirror the structure of `bitpart/tts/providers/elevenlabs.py` since both return raw bytes. Use only stdlib + `urllib` — no SDKs (the codebase deliberately avoids them after a bad experience with the `elevenlabs` package).

```python
"""OpenAI TTS REST integration (no SDK, raw urllib)."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bitpart.tts.config import OPENAI_DEFAULT_MODEL  # add this constant in step 7

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


def generate(api_key: str, text: str, cfg: dict, full_path: str) -> None:
    """Call OpenAI TTS and write the MP3 to ``full_path``. Raises on failure.

    ``cfg`` is the per-character ``providers.openai`` dict, e.g.::

        {"voice_id": "alloy", "model_id": "tts-1-hd", "speed": 1.05}

    Optional keys: ``model_id``, ``speed``.
    """
    voice_id = cfg["voice_id"]
    model_id = cfg.get("model_id") or OPENAI_DEFAULT_MODEL

    payload = {
        "model": model_id,
        "voice": voice_id,
        "input": text,
        "response_format": "mp3",
    }
    if "speed" in cfg:
        payload["speed"] = float(cfg["speed"])

    body = json.dumps(payload).encode("utf-8")
    req = Request(
        OPENAI_TTS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
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
        raise RuntimeError(f"OpenAI HTTP {e.code}: {err_body or e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"OpenAI request failed: {e.reason}") from e

    with open(full_path, "wb") as f:
        f.write(audio_bytes)
```

**If your provider returns JSON with base64 audio** (like Inworld), look at `bitpart/tts/providers/inworld.py` instead — copy the response-parsing block from there.

### Step 2 — Wire it into `bitpart/tts/providers/__init__.py`

Three small edits:

```python
from bitpart.tts.providers import elevenlabs, inworld, openai  # add openai

SUPPORTED: tuple[str, ...] = ("elevenlabs", "inworld", "openai")  # add "openai"


def generate(provider: str, *, api_key, text, cfg, full_path, inworld_default_model_id) -> None:
    if provider == "inworld":
        inworld.generate(api_key, text, cfg, full_path, default_model_id=inworld_default_model_id)
    elif provider == "elevenlabs":
        elevenlabs.generate(api_key, text, cfg, full_path)
    elif provider == "openai":                              # add this branch
        openai.generate(api_key, text, cfg, full_path)
    else:
        raise SystemExit(f"Error: provider must be one of {SUPPORTED}, got '{provider}'.")
```

The `--provider` CLI choices are derived from `SUPPORTED`, so you don't need to touch `cli.py`.

### Step 3 — Add an API-key branch in `_resolve_api_key`

In `bitpart/tts/pipeline.py`:

```python
def _resolve_api_key(provider: str, api_key: str | None) -> str | None:
    """Return the API key for the chosen provider (explicit > provider-specific env var)."""
    if provider == "inworld":
        return api_key or os.environ.get("INWORLD_API_KEY")
    if provider == "openai":                                              # add this
        return api_key or os.environ.get("OPENAI_API_KEY")                # add this
    return api_key or os.environ.get("ELEVENLABS_API_KEY")
```

This makes `OPENAI_API_KEY` work the same way as its ElevenLabs / Inworld counterparts.

(Retry count is governed by a single shared `BITPART_TTS_RETRY_COUNT` env var that applies to all providers, so there's no per-provider retry env to wire up.)

### Step 4 — Add an error-message branch in `_ensure_api_key_or_exit`

Same file:

```python
def _ensure_api_key_or_exit(cfg: RunConfig) -> None:
    """Print a provider-specific error and exit(1) if the api_key is missing."""
    if cfg.api_key:
        return
    if cfg.provider == "inworld":
        print("Error: INWORLD_API_KEY environment variable is required.")
        sys.exit(1)
    if cfg.provider == "openai":                                                # add this
        print("Error: OPENAI_API_KEY environment variable is required.")        # add this
        print("Get your API key from https://platform.openai.com/api-keys")     # add this
        sys.exit(1)                                                             # add this
    print("Error: ELEVENLABS_API_KEY environment variable is required.")
    print("Get your API key from https://elevenlabs.io/app/settings/api-keys")
    sys.exit(1)
```

### Step 5 — Register audio-affecting keys in `PROVIDER_DRIFT_KEYS`

In `bitpart/tts/config.py`, add an entry so drift detection knows which keys are meaningful for your provider. Skipping this step means drift will *only* flag `voice_id` changes for OpenAI — `model_id`, `speed`, etc. will silently never trigger regeneration.

```python
PROVIDER_DRIFT_KEYS: dict[str, tuple[str, ...]] = {
    "elevenlabs": ("voice_id", "model_id", *ELEVENLABS_VOICE_SETTING_KEYS),
    "inworld": ("voice_id", "model_id", *INWORLD_PASSTHROUGH_KEYS),
    "openai": ("voice_id", "model_id", "speed"),                # add this
}
```

If your provider has many tunable knobs, mirror what the existing providers do: define an `OPENAI_PASSTHROUGH_KEYS = ("speed", ...)` constant alongside `ELEVENLABS_VOICE_SETTING_KEYS` and splat it in here, so the provider implementation and drift detection share one source of truth.

### Step 6 — Add `providers.openai` blocks in `character_voices.json`

Pick which characters should be voiced via OpenAI and add a block. Other characters can be left without an `openai` block — they'll be skipped at runtime with a clear message ("character 'X' has no 'openai' provider entry").

```json
{
  "Village": {
    "Townsperson": {
      "character_id": "...",
      "gender": "male",
      "providers": {
        "elevenlabs": { "voice_id": "yl2ZDV1MzN4HbQJbMihG" },
        "inworld":    { "voice_id": "Jonah" },
        "openai":     { "voice_id": "onyx", "speed": 1.05 }
      }
    }
  }
}
```

You can also bootstrap or re-bootstrap the JSON with `--init`, which will leave existing entries alone and only add skeleton blocks for newly-discovered character names. (You'd then need to extend `_new_voice_entry` in `bitpart/tts/voices.py` to include an empty `openai` block in the skeleton if you want `--init` to scaffold one going forward.)

### Step 7 — Document it in `README.md`

Add an "**OpenAI** keys" subsection under the existing **Per-character provider overrides** section, listing the optional keys (e.g. `model_id`, `speed`) and their valid ranges. Look at how Inworld and ElevenLabs are documented and follow the same table format.

### Step 8 (optional) — Provider defaults in `bitpart/tts/config.py`

Centralize anything you'd want to tune later:

```python
# OpenAI defaults
OPENAI_DEFAULT_MODEL = "tts-1"     # or "tts-1-hd" for higher quality
```

The provider module imports from here (see step 1). This keeps "magic strings" out of the provider implementation and makes them easy to find when you want to bump a version.

### Step 9 (optional) — Add a test

If your provider needs a text transformation (like Inworld's emotion bracket-tag) or any non-trivial config translation, add a test in `tests/tts/test_audio_metadata.py` (or a new `tests/tts/test_providers_<name>.py`) that exercises that helper without making a real API call.

If your provider is a straight wrapper over the REST API with no logic, you can skip this — the integration is already exercised the first time you run the script against it.

---

## Verifying it works

```powershell
# 1. Set the API key
$env:OPENAI_API_KEY = "sk-..."

# 2. Run the unit tests to confirm nothing broke
python -m pytest tests -q

# 3. Smoke-test against one row only
bitpart tts "path\to\utterances.csv" --project Village --provider openai --limit 1
```

You should see the info banner, one `Created - <filename>.mp3` line, and a summary line with `Generated: 1`.

If you instead see `Skipping - character '<X>' has no 'openai' provider entry`, you forgot step 6 (the JSON block). If you see `Error: OPENAI_API_KEY environment variable is required`, the env var isn't loaded — check that `.env.local` is in the repo root or the env var is set in the shell.

Verify the embedded metadata reflects the new provider:

```powershell
python -c "from mutagen.mp3 import MP3; import json; a=MP3(r'yourfile.mp3'); tx=[f for f in a.tags.getall('TXXX') if f.desc=='TTS_METADATA']; print(json.dumps(json.loads(tx[0].text[0]), indent=2))"
```

You should see `"provider": "openai"` and the right `config` block.

---

## When to refactor to a registry

If you're adding a fourth provider (or you've added a third and the if/elif chains are starting to feel painful), here's the cleaner pattern:

```python
# In each provider module:
API_KEY_ENV = "OPENAI_API_KEY"
API_KEY_HELP = "Get your API key from https://platform.openai.com/api-keys"

def generate(api_key, text, cfg, full_path): ...
```

```python
# bitpart/tts/providers/__init__.py
from bitpart.tts.providers import elevenlabs, inworld, openai

REGISTRY = {
    "elevenlabs": elevenlabs,
    "inworld": inworld,
    "openai": openai,
}
SUPPORTED = tuple(REGISTRY.keys())

def get(name: str):
    if name not in REGISTRY:
        raise SystemExit(f"Error: provider must be one of {SUPPORTED}, got '{name}'.")
    return REGISTRY[name]
```

Then `_resolve_api_key` and `_ensure_api_key_or_exit` collapse from if/elif chains into:

```python
def _resolve_api_key(provider, api_key):
    mod = providers.get(provider)
    return api_key or os.environ.get(mod.API_KEY_ENV)

def _ensure_api_key_or_exit(cfg):
    if cfg.api_key:
        return
    mod = providers.get(cfg.provider)
    print(f"Error: {mod.API_KEY_ENV} environment variable is required.")
    if mod.API_KEY_HELP:
        print(mod.API_KEY_HELP)
    sys.exit(1)
```

After that, adding **provider #5** is **two files**: the new module + one line in `REGISTRY`.

---

## File map (where things live)

| File | Job |
|---|---|
| `bitpart/tts/providers/<name>.py` | The HTTP call to one provider's REST API |
| `bitpart/tts/providers/__init__.py` | Dispatcher that routes `provider="..."` to the right module |
| `bitpart/tts/config.py` | Constants (default model IDs, API URLs, etc.) |
| `bitpart/tts/config.py` — `PROVIDER_DRIFT_KEYS` | Per-provider tuple of cfg keys drift detection compares between embedded MP3 metadata and current JSON |
| `bitpart/tts/pipeline.py` — `_resolve_api_key` | Maps provider name to its API-key env var |
| `bitpart/tts/pipeline.py` — `_ensure_api_key_or_exit` | Provider-specific "missing API key" error message |
| `bitpart/tts/pipeline.py` — `_compute_tts_text` | Provider-specific text transformation (currently only Inworld emotion tags) |
| `bitpart/tts/pipeline.py` — `_generate_audio_with_retry` | The retry loop, calls `providers.generate(...)` and embeds metadata on success |
| `bitpart/tts/audio_metadata.py` | Embeds the provider name + config into the MP3's ID3 `TTS_METADATA` frame; reads it back for drift detection |
| `character_voices.json` | The per-character voice config; includes `providers.<name>` blocks |
