"""Tests for character_voices.json loading, lookup, and --init scaffolding."""
import json
from pathlib import Path
from textwrap import dedent

import pandas as pd
import pytest

from bitpart.tts.csv_io import is_already_processed_in_output_dir
from bitpart.tts.voices import (
    get_voice_config_for_row,
    init_character_voices,
    load_character_voices,
)


# ---------------------------------------------------------------------------
# load_character_voices
# ---------------------------------------------------------------------------

def _write_voices(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "character_voices.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_returns_inner_project_dict(tmp_path):
    p = _write_voices(tmp_path, {
        "Village": {
            "Townsperson": {
                "character_id": "abc",
                "providers": {"elevenlabs": {"voice_id": "v1"}},
            }
        }
    })
    out = load_character_voices(str(p), project="Village")
    assert "Townsperson" in out
    assert out["Townsperson"]["providers"]["elevenlabs"]["voice_id"] == "v1"


def test_load_missing_file_returns_empty_dict(tmp_path):
    out = load_character_voices(str(tmp_path / "nope.json"), project="Village")
    assert out == {}


def test_load_missing_project_returns_empty_dict(tmp_path):
    p = _write_voices(tmp_path, {"Village": {"x": {}}})
    assert load_character_voices(str(p), project="NotThere") == {}


# ---------------------------------------------------------------------------
# _get_voice_config_for_row
# ---------------------------------------------------------------------------

def _row(**kwargs) -> pd.Series:
    return pd.Series(kwargs)


def test_voice_cfg_returns_cfg_when_all_present():
    voices = {"Townsperson": {"providers": {"elevenlabs": {"voice_id": "v1", "stability": 0.6}}}}
    cfg, reason = get_voice_config_for_row(
        _row(character_name="Townsperson"), voices, "elevenlabs"
    )
    assert reason == ""
    assert cfg == {"voice_id": "v1", "stability": 0.6}


def test_voice_cfg_skips_when_character_name_missing():
    cfg, reason = get_voice_config_for_row(_row(character_name=None), {}, "elevenlabs")
    assert cfg is None
    assert "character_name" in reason


def test_voice_cfg_skips_when_character_not_in_voices():
    voices = {"Other": {"providers": {"elevenlabs": {"voice_id": "v1"}}}}
    cfg, reason = get_voice_config_for_row(
        _row(character_name="Townsperson"), voices, "elevenlabs"
    )
    assert cfg is None
    assert "Townsperson" in reason and "not in" in reason


def test_voice_cfg_skips_when_provider_block_missing():
    voices = {"Townsperson": {"providers": {"inworld": {"voice_id": "v1"}}}}
    cfg, reason = get_voice_config_for_row(
        _row(character_name="Townsperson"), voices, "elevenlabs"
    )
    assert cfg is None
    assert "elevenlabs" in reason


def test_voice_cfg_skips_when_voice_id_empty():
    voices = {"Townsperson": {"providers": {"elevenlabs": {"voice_id": "  "}}}}
    cfg, reason = get_voice_config_for_row(
        _row(character_name="Townsperson"), voices, "elevenlabs"
    )
    assert cfg is None
    assert "empty voice_id" in reason


def test_voice_cfg_strips_bom_from_character_name():
    voices = {"Townsperson": {"providers": {"elevenlabs": {"voice_id": "v1"}}}}
    cfg, reason = get_voice_config_for_row(
        _row(character_name="\ufeffTownsperson"), voices, "elevenlabs"
    )
    assert reason == ""
    assert cfg["voice_id"] == "v1"


# ---------------------------------------------------------------------------
# init_character_voices
# ---------------------------------------------------------------------------

def test_init_scaffolds_unique_character_names_with_only_requested_provider(tmp_path):
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(dedent("""\
        index,utterance_id,character_id,character_name,utterance_text
        0,u1,c1,Townsperson,hi
        1,u2,c2,Blacksmith,bye
        2,u3,c1,Townsperson,hello again
    """), encoding="utf-8")
    voices_path = tmp_path / "character_voices.json"

    init_character_voices(
        str(csv_path),
        project="Village",
        provider="inworld",
        character_voices_path=str(voices_path),
    )

    data = json.loads(voices_path.read_text(encoding="utf-8"))
    assert set(data["Village"].keys()) == {"Blacksmith", "Townsperson"}
    assert data["Village"]["Townsperson"]["character_id"] == "c1"
    assert data["Village"]["Blacksmith"]["character_id"] == "c2"
    # New entries contain ONLY the requested provider — no extra blocks.
    townsperson_providers = data["Village"]["Townsperson"]["providers"]
    assert set(townsperson_providers.keys()) == {"inworld"}
    assert townsperson_providers["inworld"]["voice_id"] == ""
    assert townsperson_providers["inworld"] == {"voice_ids": []}

def test_init_does_not_overwrite_existing_provider_block(tmp_path):
    """Existing provider config (voice_id, tunables) must be preserved verbatim."""
    voices_path = tmp_path / "character_voices.json"
    existing = {
        "Village": {
            "Townsperson": {
                "character_id": "c1",
                "gender": "female",
                "providers": {
                    "elevenlabs": {"voice_id": "PRESET", "stability": 0.7},
                },
            }
        }
    }
    voices_path.write_text(json.dumps(existing), encoding="utf-8")

    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson,hi\n",
        encoding="utf-8",
    )
    init_character_voices(
        str(csv_path),
        project="Village",
        provider="elevenlabs",
        character_voices_path=str(voices_path),
    )

    eleven = json.loads(voices_path.read_text(encoding="utf-8"))["Village"]["Townsperson"]["providers"]["elevenlabs"]
    assert eleven == {"voice_id": "PRESET", "stability": 0.7}


def test_init_adds_missing_provider_block_to_existing_entry(tmp_path):
    """Add-only: existing entry with elevenlabs gains an inworld block; elevenlabs untouched."""
    voices_path = tmp_path / "character_voices.json"
    existing = {
        "Village": {
            "Townsperson": {
                "character_id": "c1",
                "gender": "male",
                "providers": {"elevenlabs": {"voice_id": "PRESET"}},
            }
        }
    }
    voices_path.write_text(json.dumps(existing), encoding="utf-8")

    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson,hi\n",
        encoding="utf-8",
    )
    init_character_voices(
        str(csv_path),
        project="Village",
        provider="inworld",
        character_voices_path=str(voices_path),
    )

    providers_block = json.loads(voices_path.read_text(encoding="utf-8"))["Village"]["Townsperson"]["providers"]
    # Both providers present; existing one untouched, new one is the empty skeleton.
    assert set(providers_block.keys()) == {"elevenlabs", "inworld"}
    assert providers_block["elevenlabs"] == {"voice_id": "PRESET"}
    assert providers_block["inworld"] == {"voice_ids": []}
    # And the providers are written back in alphabetical order regardless of insertion order.
    assert list(providers_block.keys()) == ["elevenlabs", "inworld"]


def test_init_sorts_providers_alphabetically_after_successive_inits(tmp_path):
    """Run --init for inworld first, then for elevenlabs. Final order is alphabetical."""
    voices_path = tmp_path / "character_voices.json"
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson,hi\n",
        encoding="utf-8",
    )

    init_character_voices(
        str(csv_path), project="Village",
        provider="inworld", character_voices_path=str(voices_path),
    )
    init_character_voices(
        str(csv_path), project="Village",
        provider="elevenlabs", character_voices_path=str(voices_path),
    )

    providers_block = json.loads(voices_path.read_text(encoding="utf-8"))["Village"]["Townsperson"]["providers"]
    assert list(providers_block.keys()) == ["elevenlabs", "inworld"]


def test_init_normalizes_existing_unsorted_providers(tmp_path):
    """Even when nothing else changes, --init re-sorts an existing unsorted providers block."""
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({
            "Village": {
                "Townsperson": {
                    "character_id": "c1",
                    "gender": "",
                    "providers": {
                        "inworld": {"voice_id": "I"},
                        "elevenlabs": {"voice_id": "E"},
                    },
                }
            }
        }),
        encoding="utf-8",
    )
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson,hi\n",
        encoding="utf-8",
    )

    init_character_voices(
        str(csv_path), project="Village",
        provider="inworld", character_voices_path=str(voices_path),
    )

    providers_block = json.loads(voices_path.read_text(encoding="utf-8"))["Village"]["Townsperson"]["providers"]
    assert list(providers_block.keys()) == ["elevenlabs", "inworld"]
    # And values are not touched.
    assert providers_block["elevenlabs"] == {"voice_id": "E"}
    assert providers_block["inworld"] == {"voice_id": "I"}


def test_init_canonicalizes_entry_key_order(tmp_path):
    """character_id/gender/providers should always be written in that order.

    Reproduces the 'deleted character_id, re-ran --init' case: the re-added key
    must end up at the *front* of the entry, not appended to the end.
    """
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({
            "Kelpie": {
                "Townsperson1": {
                    "gender": "male",
                    "providers": {"elevenlabs": {"voice_id": "ABC"}},
                    # character_id intentionally absent (simulating manual delete)
                }
            }
        }),
        encoding="utf-8",
    )
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n"
        "0,u1,11111111-1111-1111-1111-111111111111,Townsperson1,hi\n",
        encoding="utf-8",
    )

    init_character_voices(
        str(csv_path), project="Kelpie",
        provider="elevenlabs", character_voices_path=str(voices_path),
    )

    entry = json.loads(voices_path.read_text(encoding="utf-8"))["Kelpie"]["Townsperson1"]
    assert list(entry.keys()) == ["character_id", "gender", "providers"]
    assert entry["character_id"] == "11111111-1111-1111-1111-111111111111"


def test_init_preserves_unknown_entry_keys_at_end(tmp_path):
    """Future / hand-authored extra keys are kept; canonical keys lead, the rest follow."""
    voices_path = tmp_path / "character_voices.json"
    voices_path.write_text(
        json.dumps({
            "Kelpie": {
                "Townsperson1": {
                    "notes": "voiced by Alice",
                    "providers": {"elevenlabs": {"voice_id": "X"}},
                    "character_id": "c1",
                    "tags": ["villager"],
                }
            }
        }),
        encoding="utf-8",
    )
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson1,hi\n",
        encoding="utf-8",
    )

    init_character_voices(
        str(csv_path), project="Kelpie",
        provider="elevenlabs", character_voices_path=str(voices_path),
    )

    keys = list(json.loads(voices_path.read_text(encoding="utf-8"))["Kelpie"]["Townsperson1"].keys())
    # Unknown keys preserved.
    assert "notes" in keys and "tags" in keys
    # Canonical keys lead; unknowns follow (their relative order doesn't matter).
    canonical_indices = [keys.index(k) for k in ("character_id", "providers")]
    unknown_indices = [keys.index(k) for k in ("notes", "tags")]
    assert max(canonical_indices) < min(unknown_indices)
    # And character_id is first within the canonical block.
    assert keys[0] == "character_id"


def test_init_requires_provider(tmp_path):
    csv_path = tmp_path / "u.csv"
    csv_path.write_text(
        "index,utterance_id,character_id,character_name,utterance_text\n0,u1,c1,Townsperson,hi\n",
        encoding="utf-8",
    )
    voices_path = tmp_path / "character_voices.json"
    with pytest.raises(SystemExit):
        init_character_voices(
            str(csv_path),
            project="Village",
            provider="",
            character_voices_path=str(voices_path),
        )


# ---------------------------------------------------------------------------
# _is_already_processed_in_output_dir
# ---------------------------------------------------------------------------

def test_is_already_processed_true_when_in_output_dir(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"")
    assert is_already_processed_in_output_dir(
        str(f), str(tmp_path), skip_existing=True
    ) is True


def test_is_already_processed_false_when_outside_output_dir(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    f = other / "x.mp3"
    f.write_bytes(b"")
    assert is_already_processed_in_output_dir(
        str(f), str(tmp_path), skip_existing=True
    ) is False


def test_is_already_processed_false_when_skip_existing_off(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"")
    assert is_already_processed_in_output_dir(
        str(f), str(tmp_path), skip_existing=False
    ) is False


def test_is_already_processed_false_when_empty_path(tmp_path):
    assert is_already_processed_in_output_dir(
        "", str(tmp_path), skip_existing=True
    ) is False


# ---------------------------------------------------------------------------
# voice_ids (multiple voices per character)
# ---------------------------------------------------------------------------

from bitpart.tts.csv_io import format_voice_files, parse_voice_files
from bitpart.tts.voices import count_voices, get_voice_variant_names, validate_voice_ids


def _ids_voices(ids, **block_extra):
    block = {"voice_ids": ids, "stability": 0.5, **block_extra}
    return {"Tourist": {"providers": {"elevenlabs": block}}}


_ROW = _row(character_name="Tourist")


def test_first_voice_id_is_default_rest_are_variants():
    voices = _ids_voices(["a", "b", "c"])
    assert get_voice_variant_names(_ROW, voices, "elevenlabs") == ["v2", "v3"]
    cfg, reason = get_voice_config_for_row(_ROW, voices, "elevenlabs")
    assert reason == "" and cfg == {"voice_id": "a", "stability": 0.5}
    cfg, _ = get_voice_config_for_row(_ROW, voices, "elevenlabs", variant="v3")
    assert cfg == {"voice_id": "c", "stability": 0.5}


def test_object_entries_override_settings_for_that_voice_only():
    voices = _ids_voices([{"voice_id": "a", "stability": 0.9}, "b", {"voice_id": "c", "stability": 0.2}])
    assert get_voice_config_for_row(_ROW, voices, "elevenlabs")[0] == {"voice_id": "a", "stability": 0.9}
    assert get_voice_config_for_row(_ROW, voices, "elevenlabs", variant="v2")[0] == {"voice_id": "b", "stability": 0.5}
    assert get_voice_config_for_row(_ROW, voices, "elevenlabs", variant="v3")[0] == {"voice_id": "c", "stability": 0.2}


def test_single_voice_id_form_still_works():
    voices = {"Tourist": {"providers": {"elevenlabs": {"voice_id": "solo", "stability": 0.6}}}}
    assert get_voice_variant_names(_ROW, voices, "elevenlabs") == []
    assert get_voice_config_for_row(_ROW, voices, "elevenlabs")[0] == {"voice_id": "solo", "stability": 0.6}


def test_duplicates_and_blanks_are_ignored_with_warning():
    voices = _ids_voices(["a", "a", "", "b"])
    assert get_voice_variant_names(_ROW, voices, "elevenlabs") == ["v2"]
    assert count_voices(voices, "elevenlabs") == 2
    warnings = validate_voice_ids(voices, "elevenlabs")
    assert len(warnings) == 1 and "2" in warnings[0]


def test_empty_voice_ids_falls_back_to_block_voice_id_then_skips():
    voices = _ids_voices([], voice_id="")
    cfg, reason = get_voice_config_for_row(_ROW, voices, "elevenlabs")
    assert cfg is None and "empty voice_id" in reason


def test_voice_ids_and_variants_keys_not_in_cfg():
    cfg, _ = get_voice_config_for_row(_ROW, _ids_voices(["a", "b"]), "elevenlabs")
    assert "voice_ids" not in cfg and "variants" not in cfg


def test_unknown_variant_is_skipped():
    cfg, reason = get_voice_config_for_row(_ROW, _ids_voices(["a", "b"]), "elevenlabs", variant="v9")
    assert cfg is None and "v9" in reason


def test_voice_files_cell_round_trip():
    variants = {"v2": "C:\\a\\x.mp3", "v3": "dir/y.mp3"}
    cell = format_voice_files("dir/base.mp3", variants)
    assert cell == "dir/base.mp3|C:\\a\\x.mp3|dir/y.mp3"
    assert parse_voice_files(cell) == ("dir/base.mp3", variants)


def test_voice_files_single_path_is_just_the_default():
    assert parse_voice_files("audio/a.mp3") == ("audio/a.mp3", {})
    assert format_voice_files("audio/a.mp3", {}) == "audio/a.mp3"
    assert parse_voice_files(float("nan")) == ("", {})
    assert parse_voice_files("") == ("", {})


def test_voice_files_missing_voice_keeps_later_voices_in_place():
    cell = format_voice_files("base.mp3", {"v3": "c.mp3"})
    assert cell == "base.mp3||c.mp3"
    assert parse_voice_files(cell) == ("base.mp3", {"v3": "c.mp3"})


def test_voice_files_trailing_gaps_trimmed_and_missing_default_kept():
    assert format_voice_files("base.mp3", {"v2": ""}) == "base.mp3"
    cell = format_voice_files("", {"v2": "b.mp3"})
    assert cell == "|b.mp3"
    assert parse_voice_files(cell) == ("", {"v2": "b.mp3"})


def test_voice_files_path_with_equals_is_fine():
    assert parse_voice_files("dir/a=b.mp3") == ("dir/a=b.mp3", {})
