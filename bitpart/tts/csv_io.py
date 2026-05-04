"""CSV loading + on-disk audio path helpers.

These exist as a thin layer over pandas / pathlib so the pipeline can stay
focused on orchestration and never has to touch raw file paths or column
validation directly.
"""
from pathlib import Path

import pandas as pd


def get_audio_filename(character_id: str, utterance_id: str) -> str:
    """Generate filename: ``{character_id}_{utterance_id}.mp3``."""
    return f"{character_id}_{utterance_id}.mp3"


def get_full_audio_path(filename: str, output_dir: str) -> str:
    """Return the absolute path for an audio file inside ``output_dir``."""
    return str(Path(output_dir) / filename)


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
