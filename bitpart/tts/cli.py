"""``bitpart tts`` subcommand: argparse wiring + handler.

Exposes two functions consumed by ``bitpart.cli``:

    register(subparsers) -> ArgumentParser   # adds the `tts` subparser
    handle(args)         -> None             # runs it

Loading ``.env.local`` happens at import time so any subcommand handler that
needs an API key sees it as soon as ``bitpart`` is invoked.
"""
import argparse
import os
import sys
from pathlib import Path

# Repo / install root (two levels above ``bitpart/tts/cli.py``: bitpart/tts ->
# bitpart -> repo). With ``pip install -e .`` this stays pinned to the source
# checkout, so a ``.env.local`` kept there acts as the single, well-known source
# of API keys no matter where ``bitpart`` is run from. We deliberately do NOT
# load .env.local from the current working directory — that would silently pick
# up unrelated projects' secrets.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env.local")
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from bitpart.tts.config import DEFAULT_PROVIDER
from bitpart.tts.pipeline import convert_utterances_to_speech
from bitpart.tts.providers import SUPPORTED as SUPPORTED_PROVIDERS
from bitpart.tts.voices import init_character_voices


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Add the ``tts`` subparser to ``bitpart``'s top-level parser."""
    p = subparsers.add_parser(
        "tts",
        help="Generate TTS audio from a CSV (ElevenLabs / Inworld)",
        description="Convert utterance text to speech via ElevenLabs or Inworld",
    )
    p.add_argument(
        "csv",
        nargs="?",
        default=None,
        help="Path to the utterances CSV file. Falls back to env $BITPART_TTS_CSV_UTTERANCE when omitted.",
    )
    p.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=list(SUPPORTED_PROVIDERS),
        help=(
            f"Which TTS provider to use. Falls back to env $BITPART_TTS_PROVIDER, "
            f"then defaults to '{DEFAULT_PROVIDER}'."
        ),
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help=(
            "Directory for audio files. Falls back to env $BITPART_TTS_OUTPUT_DIR, "
            "then defaults to the same folder as the CSV."
        ),
    )
    p.add_argument(
        "--character-voices",
        type=str,
        default=None,
        help=(
            "Override path to character_voices.json. Falls back to env "
            "$BITPART_TTS_CHARACTER_VOICES, then alongside the CSV, then repo root."
        ),
    )
    p.add_argument(
        "--project",
        type=str,
        default=None,
        help="Top-level key in character_voices.json (e.g. Village, Kelpie). Required.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process this many utterances (for testing, e.g. --limit 1)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Print full message for each created file; default is a dot per file for progress",
    )
    p.add_argument(
        "--init",
        action="store_true",
        help=(
            "Scaffold character_voices.json from the CSV (one entry per unique character_name) "
            "and exit. Strictly add-only: new entries get just the requested --provider block; "
            "existing entries gain a missing provider block but never lose one."
        ),
    )
    p.add_argument(
        "--regenerate-drift",
        action="store_true",
        help=(
            "Delete and regenerate any existing audio whose embedded TTS_METADATA does not match "
            "the current CSV utterance_text or any audio-affecting key in character_voices.json."
        ),
    )
    return p


def handle(args: argparse.Namespace) -> None:
    """Run the ``tts`` subcommand with parsed args from ``bitpart.cli``.

    Resolution rule for every shared flag/env: ``CLI arg > env var > default``.
    """
    csv_arg = args.csv or os.environ.get("BITPART_TTS_CSV_UTTERANCE") or None
    if not csv_arg:
        print(
            "Error: no CSV provided. Pass it as a positional argument "
            "(e.g. `bitpart tts path/to.csv`) or set $BITPART_TTS_CSV_UTTERANCE."
        )
        sys.exit(1)

    csv_path = Path(csv_arg).resolve()
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    output_dir = args.output_dir or os.environ.get("BITPART_TTS_OUTPUT_DIR") or None
    character_voices_path = (
        args.character_voices or os.environ.get("BITPART_TTS_CHARACTER_VOICES") or None
    )
    provider = args.provider or os.environ.get("BITPART_TTS_PROVIDER") or None
    if provider is not None and provider not in SUPPORTED_PROVIDERS:
        print(
            f"Error: $BITPART_TTS_PROVIDER='{provider}' is not supported. "
            f"Must be one of: {', '.join(SUPPORTED_PROVIDERS)}."
        )
        sys.exit(1)

    if args.init:
        print(f"Processing: {csv_path}")
        init_character_voices(
            str(csv_path),
            project=args.project,
            provider=provider or DEFAULT_PROVIDER,
            character_voices_path=character_voices_path,
        )
        return

    convert_utterances_to_speech(
        str(csv_path),
        output_dir=output_dir,
        character_voices_path=character_voices_path,
        project=args.project,
        provider=provider,
        limit=args.limit,
        debug=args.debug,
        regenerate_drift=args.regenerate_drift,
        cli_argv=sys.argv,
    )
