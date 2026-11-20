"""``character_voices.json`` loading, lookup, and ``--init`` scaffolding.

The JSON is the source of truth for every character's per-provider voice
configuration. Shape::

    {
      "<Project>": {
        "<character_name>": {
          "character_id": "...",
          "gender": "...",
          "providers": {
            "elevenlabs": {
              "voice_ids": ["<default voice>", "<extra voice>", { "voice_id": "...", "stability": 0.4 }],
              "stability": 0.6
            },
            "inworld":    { "voice_id": "...", "temperature": 1.1, ... }
          }
        }
      }
    }

``voice_ids`` is optional (a lone ``voice_id`` is still the single-voice form). The
first entry is the ``default`` voice; the rest are named ``v2``, ``v3``, ... Each entry
is a voice id string, or an object that also overrides settings for that voice only.
Every entry is generated once per utterance; the SDK picks one voice per NPC instance.
"""
import json
from pathlib import Path

import pandas as pd

from bitpart.tts.config import CHARACTER_VOICES_FILE
from bitpart.tts.csv_io import load_and_validate_dataframe


def resolve_voices_path(csv_parent: Path, character_voices_path: str | None) -> str:
    """Resolve path to ``character_voices.json``: explicit > CSV dir > repo root."""
    if character_voices_path:
        return character_voices_path
    voices_path = str(csv_parent / CHARACTER_VOICES_FILE)
    if Path(voices_path).exists():
        return voices_path
    # Two levels up: bitpart/tts/voices.py -> bitpart/tts -> bitpart -> repo root.
    fallback = Path(__file__).resolve().parent.parent.parent / CHARACTER_VOICES_FILE
    return str(fallback) if fallback.exists() else voices_path


def load_character_voices(path: str | Path, project: str) -> dict:
    """Return the inner dict (``character_name -> entry``) for ``project``.

    Returns an empty dict if the file is missing/empty, or the project key
    is absent.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"Error: {p} is not valid JSON ({e.msg} at line {e.lineno}, column {e.colno}). "
        ) from e
    if not isinstance(data, dict):
        return {}
    project_section = data.get(project) or {}
    if not isinstance(project_section, dict):
        return {}
    return project_section


VOICE_IDS_KEY = "voice_ids"
# Internal: the effective block handed back by ``_provider_block`` carries the extra
# voices (everything after the first ``voice_ids`` entry) under this key.
VARIANTS_KEY = "variants"
DEFAULT_VOICE_NAME = "default"


def _voice_items(block: dict) -> list[dict]:
    """Normalize ``voice_ids`` (strings or dicts) into per-voice override dicts, dropping duplicates.

    Returns ``[]`` when ``voice_ids`` is absent or has no usable entries (the block's own
    ``voice_id`` is then the single voice).
    """
    raw = block.get(VOICE_IDS_KEY)
    if not isinstance(raw, list):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"voice_id": item}
        if not isinstance(item, dict):
            continue
        voice_id = str(item.get("voice_id", "")).strip()
        if not voice_id or voice_id in seen:
            continue
        seen.add(voice_id)
        items.append({**item, "voice_id": voice_id})
    return items


def validate_voice_ids(character_voices: dict, provider: str) -> list[str]:
    """Human-readable warnings for ``voice_ids`` entries that are ignored (blank, malformed, or repeated)."""
    warnings: list[str] = []
    for name, entry in character_voices.items():
        if not isinstance(entry, dict):
            continue
        block = (entry.get("providers") or {}).get(provider)
        if not isinstance(block, dict) or not isinstance(block.get(VOICE_IDS_KEY), list):
            continue
        ignored = len(block[VOICE_IDS_KEY]) - len(_voice_items(block))
        if ignored:
            warnings.append(
                f"character '{name}' has {ignored} blank, malformed or duplicate entr"
                f"{'y' if ignored == 1 else 'ies'} in providers.{provider}.{VOICE_IDS_KEY}; ignoring"
            )
    return warnings


def count_voices(character_voices: dict, provider: str) -> int:
    """Total voices (each generated once per utterance) configured across characters for ``provider``."""
    total = 0
    for entry in character_voices.values():
        if not isinstance(entry, dict):
            continue
        block = (entry.get("providers") or {}).get(provider)
        if isinstance(block, dict):
            total += max(1, len(_voice_items(block)))
    return total


def _provider_block(
    row: pd.Series, character_voices: dict, provider: str
) -> tuple[dict | None, str]:
    """Return ``(effective_block, reason)`` for a CSV row, or ``(None, reason)``.

    With ``voice_ids``, the first entry is the default voice and the rest become variants named
    ``v2``, ``v3``, ...; each entry may override the block's other settings for that voice only.
    Without it, the block's ``voice_id`` is the single voice.
    """
    if not pd.notna(row.get("character_name")):
        return None, "character_name is empty"
    character_name = str(row["character_name"]).strip().lstrip("\ufeff")
    if not character_name:
        return None, "character_name is empty"
    entry = character_voices.get(character_name)
    if not isinstance(entry, dict):
        return None, f"character_name '{character_name}' not in character_voices.json"
    providers = entry.get("providers") or {}
    block = providers.get(provider)
    if not isinstance(block, dict):
        return None, f"character '{character_name}' has no '{provider}' provider entry"

    base = {k: v for k, v in block.items() if k != VOICE_IDS_KEY}
    items = _voice_items(block)
    if not items:
        return {**base, VARIANTS_KEY: {}}, ""
    effective = {**base, **items[0]}
    # Variants hold complete configs (shared settings + that entry's overrides).
    effective[VARIANTS_KEY] = {
        f"v{i}": {**base, **item} for i, item in enumerate(items[1:], start=2)
    }
    return effective, ""


def get_voice_variant_names(
    row: pd.Series, character_voices: dict, provider: str
) -> list[str]:
    """Names of the extra (non-default) voices configured for a row's character."""
    block, _ = _provider_block(row, character_voices, provider)
    if block is None:
        return []
    return list(block[VARIANTS_KEY])


def get_voice_config_for_row(
    row: pd.Series,
    character_voices: dict,
    provider: str,
    variant: str | None = None,
) -> tuple[dict | None, str]:
    """Resolve the per-provider voice config for a CSV row.

    Returns ``(cfg, reason)`` where ``cfg`` is a dict like
    ``{"voice_id": "...", "stability": 0.6, ...}`` or ``None`` when the row
    should be skipped. The string is a human-readable skip reason
    (or ``""`` on success).

    ``variant=None`` is the default voice (the first ``voice_ids`` entry, or the block's
    ``voice_id``). A variant name (``v2``, ...) returns that voice's config: the block's
    shared settings overlaid with the entry's own. ``voice_ids`` never appears in the result.
    """
    block, reason = _provider_block(row, character_voices, provider)
    if block is None:
        return None, reason
    character_name = str(row["character_name"]).strip().lstrip("\ufeff")
    cfg = {k: v for k, v in block.items() if k != VARIANTS_KEY}
    label = ""
    if variant is not None:
        cfg = block[VARIANTS_KEY].get(variant)
        if not isinstance(cfg, dict):
            return None, f"character '{character_name}' has no voice '{variant}' for provider '{provider}'"
        cfg = dict(cfg)
        label = f" voice '{variant}'"
    voice_id = str(cfg.get("voice_id", "")).strip()
    if not voice_id:
        return None, f"character '{character_name}'{label} has empty voice_id for provider '{provider}'"
    return cfg, ""


# Canonical key order used inside each character entry. Anything outside this
# tuple (future schema additions, hand-authored fields) is preserved at the end
# in its original order.
_CANONICAL_ENTRY_KEY_ORDER = ("character_id", "gender", "voice_count", "providers")


def _canonicalize_entry(entry: dict) -> dict:
    """Return ``entry`` rebuilt with canonical key order; unknown keys appended."""
    canonical: dict = {}
    for key in _CANONICAL_ENTRY_KEY_ORDER:
        if key in entry:
            canonical[key] = entry[key]
    for key, value in entry.items():
        if key not in canonical:
            canonical[key] = value
    return canonical


def _new_voice_entry(provider: str, character_id: str = "") -> dict:
    """Skeleton voice entry written by ``--init`` for an unknown character.

    Only the requested ``provider`` block is included; users add other provider
    blocks later (either by re-running ``--init`` with a different provider or
    by editing the JSON directly).
    """
    return {
        "character_id": character_id,
        "gender": "",
        "providers": {
            provider: {VOICE_IDS_KEY: []},
        },
    }


def init_character_voices(
    csv_path: str,
    project: str,
    provider: str,
    character_voices_path: str | None = None,
) -> None:
    """Scan a CSV and write/extend ``character_voices.json`` for ``provider``.

    Strictly add-only — never removes anything from existing entries:
      * New ``character_name`` rows in the CSV become new entries with **only**
        the requested ``provider`` block.
      * Existing entries get a missing ``character_id`` filled in from the CSV
        (if present) and/or a missing ``providers.<provider>`` block added.
      * Existing provider blocks are left exactly as they are.
    """
    if not project:
        raise SystemExit("Error: --init requires --project (e.g. --project Village).")
    if not provider:
        raise SystemExit("Error: --init requires a provider (--provider elevenlabs|inworld).")
    csv_path_resolved = Path(csv_path).resolve()
    csv_parent = csv_path_resolved.parent
    voices_path = Path(resolve_voices_path(csv_parent, character_voices_path))

    df = load_and_validate_dataframe(str(csv_path_resolved))

    if voices_path.exists():
        with open(voices_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    else:
        data = {}

    project_section = data.setdefault(project, {})
    if not isinstance(project_section, dict):
        raise SystemExit(
            f"Error: top-level key '{project}' in {voices_path} is not a JSON object."
        )

    seen_names: dict[str, str] = {}
    for _, row in df.iterrows():
        if not pd.notna(row.get("character_name")):
            continue
        name = str(row["character_name"]).strip().lstrip("\ufeff")
        if not name:
            continue
        cid = ""
        if pd.notna(row.get("character_id")):
            cid = str(row["character_id"]).strip()
        if name not in seen_names or (not seen_names[name] and cid):
            seen_names[name] = cid

    added = 0
    updated_id = 0
    added_provider_block = 0
    already_complete = 0
    for name, cid in sorted(seen_names.items()):
        if name not in project_section:
            project_section[name] = _new_voice_entry(provider, cid)
            added += 1
            continue

        entry = project_section[name]
        if not isinstance(entry, dict):
            already_complete += 1
            continue

        changed = False
        if not entry.get("character_id") and cid:
            entry["character_id"] = cid
            updated_id += 1
            changed = True

        providers_dict = entry.get("providers")
        if not isinstance(providers_dict, dict):
            providers_dict = {}
            entry["providers"] = providers_dict
        if provider not in providers_dict:
            providers_dict[provider] = {VOICE_IDS_KEY: []}
            added_provider_block += 1
            changed = True

        if not changed:
            already_complete += 1

    for name, entry in list(project_section.items()):
        if isinstance(entry, dict):
            providers_dict = entry.get("providers")
            if isinstance(providers_dict, dict):
                entry["providers"] = dict(sorted(providers_dict.items()))
            project_section[name] = _canonicalize_entry(entry)
    data[project] = dict(sorted(project_section.items()))

    voices_path.parent.mkdir(parents=True, exist_ok=True)
    with open(voices_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    def _entries(n: int) -> str:
        return f"{n} entr{'y' if n == 1 else 'ies'}"

    print(f"Init complete. {voices_path}")
    print(f"  Project:               {project}")
    print(f"  Provider:              {provider}")
    print(f"  Added new entries:     {_entries(added)}")
    print(f"  Filled in IDs:         {_entries(updated_id)} (existing)")
    print(f"  Added provider block:  {_entries(added_provider_block)} (existing)")
    print(f"  Already complete:      {_entries(already_complete)} (left untouched)")
    if added or added_provider_block:
        print("  Add voice ids to voice_ids (first is the default) and set gender in the JSON before generating audio.")
