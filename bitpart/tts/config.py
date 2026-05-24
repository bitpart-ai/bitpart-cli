"""Constants and tunable defaults for the TTS pipeline.

Most of these can be overridden via environment variables or per-character
fields in ``character_voices.json``.

Bitpart-owned env var naming convention for the ``tts`` subcommand:
   BITPART_TTS_<SUFFIX>   
   - knobs Bitpart itself defines (read inline as string literals 
     in the modules that consume them).
Full list lives in README.md under "Environment variables".
"""


# Pipeline-wide
RATE_LIMIT_DELAY = 0              # seconds between API calls
DEFAULT_RETRY_COUNT = 2           # 2 retries
CHARACTER_VOICES_FILE = "character_voices.json"
DEFAULT_PROVIDER = "elevenlabs" # Default provider when --provider is not passed.

# ElevenLabs defaults
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
ELEVENLABS_TTS_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
# Voice config keys that are forwarded into the ``voice_settings`` request body.
ELEVENLABS_VOICE_SETTING_KEYS = (
    "stability",
    "similarity_boost",
    "style",
    "use_speaker_boost",
)

# Inworld defaults
INWORLD_TTS_URL = "https://api.inworld.ai/tts/v1/voice"
INWORLD_DEFAULT_MODEL_ID = "inworld-tts-1.5-max"
# Voice config keys passed straight through to the Inworld payload.
INWORLD_PASSTHROUGH_KEYS = ("temperature", "speed")


# Per-provider tuple of cfg keys that drift detection compares between the
# embedded MP3 metadata and the current character_voices.json. Change any of
# them in the JSON and the next run flags the audio file as drift.
#
# Built from the per-provider constants the providers themselves use, so
# adding a key in one place automatically wires it into drift detection.
PROVIDER_DRIFT_KEYS: dict[str, tuple[str, ...]] = {
    "elevenlabs": ("voice_id", "model_id", *ELEVENLABS_VOICE_SETTING_KEYS),
    "inworld": ("voice_id", "model_id", *INWORLD_PASSTHROUGH_KEYS),
}
