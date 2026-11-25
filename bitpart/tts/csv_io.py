"""CSV loading + on-disk audio path helpers.

These exist as a thin layer over pandas / pathlib so the pipeline can stay
focused on orchestration and never has to touch raw file paths or column
validation directly.
"""
import os
import re
from pathlib import Path
import pandas as pd


def to_stored_path(full_path: str, root: str | Path) -> str:
    """Path as written to the CSV: relative to ``root`` with forward slashes, so it works on any machine.

    Falls back to the absolute path (forward slashes) if there is no relative form
    (e.g. a different drive on Windows).
    """
    try:
        rel = os.path.relpath(full_path, root)
    except ValueError:
        return Path(full_path).as_posix()
    return Path(rel).as_posix()


def resolve_stored_path(stored: str, root: str | Path) -> str:
    """Inverse of :func:`to_stored_path`. Absolute paths (older CSVs) are returned unchanged."""
    if not stored:
        return ""
    p = Path(stored)
    return str(p if p.is_absolute() else (Path(root) / p).resolve())


def get_audio_filename(character_id: str, utterance_id: str) -> str:
    """Generate filename: ``{character_id}_{utterance_id}.mp3``."""
    return f"{character_id}_{utterance_id}.mp3"


def get_variant_audio_filename(character_id: str, utterance_id: str, variant: str) -> str:
    """Generate filename for a non-default voice: ``{character_id}_{utterance_id}__{variant}.mp3``."""
    return f"{character_id}_{utterance_id}__{variant}.mp3"


_VOICE_SEP = "|"
_VOICE_NAME = re.compile(r"^v(\d+)$")


def parse_voice_files(cell) -> tuple[str, dict[str, str]]:
    """Parse the ``file_name`` cell into ``(default_path, {voice_name: path})``.

    The cell is the voices' paths separated by ``|``, in ``voice_ids`` order: the first is the
    default voice, the second is ``v2``, the third ``v3``, and so on. An empty slot means that
    voice has no audio (so later voices keep their position). A single-voice cell is just a path.
    """
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return "", {}
    slots = [piece.strip() for piece in str(cell).split(_VOICE_SEP)]
    variants = {f"v{i + 1}": path for i, path in enumerate(slots) if i >= 1 and path}
    return slots[0], variants


def format_voice_files(default: str, variants: dict[str, str]) -> str:
    """Inverse of :func:`parse_voice_files`. Trailing empty slots are dropped."""
    slots = [default]
    for name, path in variants.items():
        m = _VOICE_NAME.match(name)
        if not m or int(m.group(1)) < 2:
            raise ValueError(f"voice name must be 'v2', 'v3', ...: {name!r}")
        index = int(m.group(1)) - 1
        slots.extend([""] * (index + 1 - len(slots)))
        slots[index] = path
    while len(slots) > 1 and not slots[-1]:
        slots.pop()
    return _VOICE_SEP.join(slots)


def get_full_audio_path(filename: str, output_dir: str) -> str:
    """Return the absolute path for an audio file inside ``output_dir``."""
    return str(Path(output_dir) / filename)


def csv_row_num(pandas_idx: int) -> int:
    """Spreadsheet line number for log messages (not the Coppola ``index`` column).
    Row 1 is the header; the first data row is row 2. Matches Excel/Sheets.
    """
    return pandas_idx + 2


def ensure_output_dir(output_dir: str) -> None:
    """Create the output directory if it doesn't exist."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)


def load_and_validate_dataframe(csv_path: str) -> pd.DataFrame:
    """Load CSV and validate required columns; ensure ``file_name`` exists and is string-typed."""
    df = pd.read_csv(csv_path)
    required = {"utterance_id", "character_id", "character_name", "utterance_text"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise SystemExit(f"Error: CSV is missing required columns: {missing}")
    if "file_name" not in df.columns:
        df["file_name"] = ""
    df["file_name"] = df["file_name"].apply(lambda x: "" if pd.isna(x) else str(x))
    return df


def is_already_processed_in_output_dir(
    existing_file: str, output_dir: str, skip_existing: bool
) -> bool:
    """True if file_name is set, the file exists, and it lives in the current output_dir."""
    if not skip_existing or not existing_file:
        return False
    p = Path(existing_file)
    return p.exists() and p.parent.resolve() == Path(output_dir).resolve()
