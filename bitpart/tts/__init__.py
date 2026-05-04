"""
TTS automation subpackage of ``bitpart``.

Exposed via the ``bitpart tts`` subcommand (or ``python -m bitpart tts``).
Library callers can keep using the public API below directly.

Internal module map (handy reference for refactors):

    bitpart.tts.config          - constants / env-var defaults
    bitpart.tts.csv_io          - CSV load/validate, audio path helpers
    bitpart.tts.voices          - character_voices.json load + lookup + --init
    bitpart.tts.audio_metadata  - ID3 read/write + drift detection
    bitpart.tts.progress        - per-row print helper (dots / debug lines)
    bitpart.tts.providers       - provider-specific REST calls
    bitpart.tts.pipeline        - convert_utterances_to_speech orchestrator
    bitpart.tts.cli             - argparse register()/handle() for the subcommand
"""

from bitpart.tts.pipeline import convert_utterances_to_speech
from bitpart.tts.voices import init_character_voices, load_character_voices

__all__ = [
    "convert_utterances_to_speech",
    "init_character_voices",
    "load_character_voices",
]
