"""TTS provider implementations.

Each provider lives in its own module and exposes a single ``generate`` function
plus any helpers it needs. The pipeline talks to providers exclusively through
``dispatch`` below, so adding a new provider is "create a new file in this
package and add it to the dispatch table".
"""
from typing import Callable

from bitpart.tts.providers import elevenlabs, inworld

SUPPORTED: tuple[str, ...] = ("elevenlabs", "inworld")


def generate(
    provider: str,
    *,
    api_key: str,
    text: str,
    cfg: dict,
    full_path: str,
    inworld_default_model_id: str,
) -> None:
    """Call the chosen provider's REST API and write the resulting MP3 to ``full_path``.

    Raises ``RuntimeError`` (with the provider-specific HTTP detail) on failure.
    """
    if provider == "inworld":
        inworld.generate(
            api_key, text, cfg, full_path, default_model_id=inworld_default_model_id
        )
    elif provider == "elevenlabs":
        elevenlabs.generate(api_key, text, cfg, full_path)
    else:
        raise SystemExit(f"Error: provider must be one of {SUPPORTED}, got '{provider}'.")
