"""The main per-row orchestration loop.

This module is the only place that knows about the *order* of operations:
read CSV row -> resolve voice -> check existing file metadata -> call provider
-> embed metadata -> update CSV. Everything else lives in focused helper
modules under ``tts/``.

The work is split across small per-phase helpers so each step can fail
in isolation and be debugged on its own:

* Setup phase     - ``_build_run_config``, ``_ensure_api_key_or_exit``
* Per-row phase   - ``_process_csv_row`` and the ``_handle_*`` helpers it dispatches to
* Post-loop phase - ``_write_csv_and_summary``, ``_print_*_warning``

Three small dataclasses (``RunConfig``, ``RunStats``, ``CsvRowContext``) bundle
state so we don't have to thread 10+ args through every helper.
"""
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from bitpart.tts import providers
from bitpart.tts.audio_metadata import (
    check_metadata_drift,
    embed_mp3_metadata,
    get_file_provider,
)
from bitpart.shared.color import yellow
from bitpart.tts.config import (
    DEFAULT_PROVIDER,
    DEFAULT_RETRY_COUNT,
    INWORLD_DEFAULT_MODEL_ID,
    RATE_LIMIT_DELAY,
)
from bitpart.tts.csv_io import (
    ensure_output_dir,
    get_audio_filename,
    get_full_audio_path,
    is_already_processed_in_output_dir,
    load_and_validate_dataframe,
)
from bitpart.tts.progress import print_progress
from bitpart.tts.providers.inworld import text_with_optional_emotion
from bitpart.tts.voices import (
    get_voice_config_for_row,
    load_character_voices,
    resolve_voices_path,
)


# ---------------------------------------------------------------------------
# State containers
# ---------------------------------------------------------------------------

@dataclass
class RunConfig:
    """Immutable run-level settings, derived once from CLI args + env."""
    csv_path: str
    output_dir: str
    project: str
    provider: str
    api_key: str
    voices_path: Path
    character_voices: dict
    has_emotion_column: bool  # set after CSV is loaded; built defaults to False
    max_attempts: int
    retry_count: int
    inworld_model_id: str
    skip_existing: bool
    debug: bool
    regenerate_drift: bool
    limit: int | None


@dataclass
class RunStats:
    """Mutable counters and warning lists accumulated during the per-row loop."""
    generated: int = 0
    skipped: int = 0
    errors: int = 0
    regenerated: int = 0
    drift_files: list[tuple[str, list[str]]] = field(default_factory=list)
    provider_mismatch_files: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CsvRowContext:
    """Computed-once values for a single CSV row, passed to per-row helpers."""
    idx: int
    utterance_text: str
    character_name: str
    filename: str
    full_path: str
    already_via_csv: bool


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def convert_utterances_to_speech(
    csv_path: str,
    output_dir: str | None = None,
    character_voices_path: str | None = None,
    project: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    api_key: str | None = None,
    skip_existing: bool = True,
    limit: int | None = None,
    debug: bool = False,
    regenerate_drift: bool = False,
) -> None:
    """Read CSV, generate audio for each row, embed metadata, write CSV back.

    For provider ``inworld``, an optional CSV column ``emotion`` may be present;
    non-empty values are sent as a leading bracket tag (e.g. ``angry`` becomes
    ``[angry]`` prepended to the utterance).

    Args:
        csv_path: Path to the utterances CSV file.
        output_dir: Directory to save audio files (default: same folder as CSV).
        character_voices_path: Override path to ``character_voices.json``.
        project: Top-level key in ``character_voices.json`` (e.g. ``Village``). Required.
        provider: ``"elevenlabs"`` or ``"inworld"``.
        api_key: API key for the provider (default: env ``ELEVENLABS_API_KEY`` / ``INWORLD_API_KEY``).
        skip_existing: If True, don't overwrite rows whose ``file_name`` already exists.
        limit: If set, stop after this many utterances (useful for ``--limit 1`` smoke tests).
        debug: If True, print full message per file; otherwise dot progress.
        regenerate_drift: If True, delete + regenerate audio whose embedded metadata
            no longer matches the CSV / JSON.
    """
    cfg = _build_run_config(
        csv_path=csv_path,
        output_dir=output_dir,
        character_voices_path=character_voices_path,
        project=project,
        provider=provider,
        api_key=api_key,
        skip_existing=skip_existing,
        limit=limit,
        debug=debug,
        regenerate_drift=regenerate_drift,
    )

    _print_info_banner(cfg)
    _ensure_api_key_or_exit(cfg)
    ensure_output_dir(cfg.output_dir)

    df = load_and_validate_dataframe(cfg.csv_path)
    cfg.has_emotion_column = "emotion" in df.columns

    # Generated, skipped, errors, regenerated, drift files, provider mismatch files
    stats = RunStats()
    state: dict = {"need_newline": False}

    for idx, row in df.iterrows():
        if cfg.limit is not None and (stats.generated + stats.errors) >= cfg.limit:
            print_progress(state, cfg.debug, "skip", f"  Reached limit of {cfg.limit} utterance(s), stopping.")
            break
        _process_csv_row(idx, row, df, cfg, stats, state)
        time.sleep(RATE_LIMIT_DELAY)

    if state.get("need_newline"):
        print()
    _write_csv_and_summary(df, cfg, stats)
    _print_drift_warning(stats.drift_files, cfg)
    _print_provider_mismatch_warning(stats.provider_mismatch_files, cfg)


# ---------------------------------------------------------------------------
# Setup phase
# ---------------------------------------------------------------------------

def _build_run_config(
    *,
    csv_path: str,
    output_dir: str | None,
    character_voices_path: str | None,
    project: str | None,
    provider: str,
    api_key: str | None,
    skip_existing: bool,
    limit: int | None,
    debug: bool,
    regenerate_drift: bool,
) -> RunConfig:
    """Validate CLI args, resolve paths/api_key/retry, and bundle into a RunConfig.

    ``has_emotion_column`` defaults to False here - the caller flips it on after
    the CSV is loaded (which can't happen before this function returns because
    arg validation must run first to give the user good error messages).
    """
    csv_path_resolved = Path(csv_path).resolve()
    csv_parent = csv_path_resolved.parent
    if not project:
        raise SystemExit("Error: --project is required (e.g. --project Village).")

    provider_norm = (provider or DEFAULT_PROVIDER).strip().lower()
    if provider_norm not in providers.SUPPORTED:
        raise SystemExit(f"Error: provider must be one of {providers.SUPPORTED}.")

    resolved_api_key = _resolve_api_key(provider_norm, api_key)
    retry_count = _load_retry_count()

    voices_path = Path(resolve_voices_path(csv_parent, character_voices_path))
    character_voices = load_character_voices(voices_path, project=project)
    inworld_model_id = os.environ.get("INWORLD_MODEL_ID", INWORLD_DEFAULT_MODEL_ID)

    return RunConfig(
        csv_path=str(csv_path_resolved),
        output_dir=output_dir or str(csv_parent),
        project=project,
        provider=provider_norm,
        api_key=resolved_api_key or "",
        voices_path=voices_path,
        character_voices=character_voices,
        has_emotion_column=False,
        max_attempts=retry_count + 1,
        retry_count=retry_count,
        inworld_model_id=inworld_model_id,
        skip_existing=skip_existing,
        debug=debug,
        regenerate_drift=regenerate_drift,
        limit=limit,
    )


def _resolve_api_key(provider: str, api_key: str | None) -> str | None:
    """Return the API key for the chosen provider (explicit > provider-specific env var)."""
    if provider == "inworld":
        return api_key or os.environ.get("INWORLD_API_KEY")
    return api_key or os.environ.get("ELEVENLABS_API_KEY")


def _load_retry_count() -> int:
    """Read ``BITPART_TTS_RETRY_COUNT`` from env (default ``DEFAULT_RETRY_COUNT``); clamp to >= 0."""
    try:
        n = int(os.environ.get("BITPART_TTS_RETRY_COUNT", DEFAULT_RETRY_COUNT))
        return max(0, n)
    except (ValueError, TypeError):
        return DEFAULT_RETRY_COUNT


def _ensure_api_key_or_exit(cfg: RunConfig) -> None:
    """Print a provider-specific error and exit(1) if the api_key is missing."""
    if cfg.api_key:
        return
    if cfg.provider == "inworld":
        print("Error: INWORLD_API_KEY environment variable is required.")
        sys.exit(1)
    print("Error: ELEVENLABS_API_KEY environment variable is required.")
    print("Get your API key from https://elevenlabs.io/app/settings/api-keys")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Per-row phase
# ---------------------------------------------------------------------------

def _process_csv_row(
    idx: int,
    row: pd.Series,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> None:
    """Dispatch a single row to the right branch (empty / existing / generate)."""
    ctx = _csv_row_context_from(idx, row, cfg)

    if not ctx.utterance_text:
        _ensure_file_name_if_exists(df, ctx)
        print_progress(state, cfg.debug, "skip", f"  Row {ctx.idx}: Skipping - empty utterance_text")
        stats.skipped += 1
        return

    voice_cfg, skip_reason = get_voice_config_for_row(row, cfg.character_voices, cfg.provider)

    if Path(ctx.full_path).exists():
        if _handle_existing_audio_file(ctx, voice_cfg, df, cfg, stats, state):
            return  # row was fully handled (skipped or drift)
        # else: file was deleted for regeneration, fall through to generation

    if voice_cfg is None:
        _ensure_file_name_if_exists(df, ctx)
        print_progress(
            state, cfg.debug, "skip",
            f"  Row {ctx.idx}: Skipping - {skip_reason}. Update {cfg.voices_path} with a voice_id for the character.",
        )
        stats.skipped += 1
        return

    tts_text = _compute_tts_text(ctx.utterance_text, row, cfg)
    _generate_audio_with_retry(ctx, voice_cfg, tts_text, df, cfg, stats, state)


def _csv_row_context_from(idx: int, row: pd.Series, cfg: RunConfig) -> CsvRowContext:
    """Pull per-row values (text, ids, paths) into a CsvRowContext."""
    utterance_text = str(row["utterance_text"]).strip() if pd.notna(row["utterance_text"]) else ""
    character_id = str(row["character_id"]).strip()
    utterance_id = str(row["utterance_id"]).strip()
    character_name = (
        str(row["character_name"]).strip().lstrip("\ufeff")
        if pd.notna(row.get("character_name"))
        else ""
    )
    filename = get_audio_filename(character_id, utterance_id)
    full_path = get_full_audio_path(filename, cfg.output_dir)
    existing_file = str(row.get("file_name", "")).strip()
    already_via_csv = is_already_processed_in_output_dir(
        existing_file, cfg.output_dir, cfg.skip_existing
    )
    return CsvRowContext(
        idx=idx,
        utterance_text=utterance_text,
        character_name=character_name,
        filename=filename,
        full_path=full_path,
        already_via_csv=already_via_csv,
    )


def _handle_existing_audio_file(
    ctx: CsvRowContext,
    voice_cfg: dict | None,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> bool:
    """Handle a row whose audio file already exists.

    Returns True if the row is fully handled (caller should move on to the next
    row); False if the file was deleted for regeneration and the caller should
    fall through to the generation step.
    """
    file_provider = get_file_provider(ctx.full_path)
    if file_provider and file_provider != cfg.provider:
        _handle_provider_mismatch(ctx, file_provider, df, cfg, stats, state)
        return True

    issues = check_metadata_drift(
        ctx.full_path,
        ctx.utterance_text,
        voice_cfg or {},
        current_provider=cfg.provider,
        character_name=ctx.character_name,
        row_idx=ctx.idx,
    )
    if issues:
        return _handle_audio_drift(ctx, issues, voice_cfg, df, cfg, stats, state)

    _handle_audio_no_drift(ctx, df, cfg, stats, state)
    return True


def _handle_provider_mismatch(
    ctx: CsvRowContext,
    file_provider: str,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> None:
    """Record a cross-provider audio file and skip it.

    Cross-provider drift is meaningless (voice_ids live in different namespaces),
    so we bypass the drift check entirely and just remember the file for the
    end-of-run WARNING block.

    Note: we deliberately do NOT bump ``stats.skipped`` here — wrong-provider
    files get their own counter so the summary line doesn't double-count them.
    """
    stats.provider_mismatch_files.append((ctx.full_path, file_provider))
    df.at[ctx.idx, "file_name"] = ctx.full_path
    print_progress(
        state, cfg.debug, "file_exists",
        f"  Row {ctx.idx}: Skipping - already processed ({ctx.filename}); "
        f"generated by '{file_provider}', not the current provider '{cfg.provider}'",
    )


def _handle_audio_drift(
    ctx: CsvRowContext,
    issues: list[str],
    voice_cfg: dict | None,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> bool:
    """Handle audio with metadata drift detected.

    Returns True if the row was skipped (file left in place); False if the file
    was deleted and the caller should regenerate.
    """
    if cfg.regenerate_drift and voice_cfg is not None:
        try:
            Path(ctx.full_path).unlink()
            issues_block = "\n        " + "\n        ".join(issues)
            print_progress(
                state, cfg.debug, "skip",
                f"  Row {ctx.idx}: Audio metadata drift - deleted {ctx.filename} for regeneration"
                f"{issues_block}",
            )
            stats.regenerated += 1
            return False
        except OSError as e:
            stats.drift_files.append((ctx.full_path, issues))
            df.at[ctx.idx, "file_name"] = ctx.full_path
            print_progress(
                state, cfg.debug, "skip",
                f"  Row {ctx.idx}: Audio metadata drift - cannot delete ({e}); leaving in place",
            )
            return True

    stats.drift_files.append((ctx.full_path, issues))
    df.at[ctx.idx, "file_name"] = ctx.full_path
    print_progress(
        state, cfg.debug, "skip",
        f"  Row {ctx.idx}: Skipping - audio metadata drift ({ctx.filename})",
    )
    return True


def _handle_audio_no_drift(
    ctx: CsvRowContext,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> None:
    """Existing file matches current config; just sync the CSV's file_name column."""
    df.at[ctx.idx, "file_name"] = ctx.full_path
    stats.skipped += 1
    if ctx.already_via_csv:
        msg = f"  Row {ctx.idx}: Skipping - already processed ({ctx.filename})"
    else:
        msg = f"  Row {ctx.idx}: Skipping - file exists, updating CSV only ({ctx.filename})"
    print_progress(state, cfg.debug, "file_exists", msg)


def _compute_tts_text(utterance_text: str, row: pd.Series, cfg: RunConfig) -> str:
    """Apply Inworld bracket-tag emotion if applicable; otherwise return text as-is."""
    if cfg.provider == "inworld" and cfg.has_emotion_column:
        return text_with_optional_emotion(utterance_text, row.get("emotion"))
    return utterance_text


def _generate_audio_with_retry(
    ctx: CsvRowContext,
    voice_cfg: dict,
    tts_text: str,
    df: pd.DataFrame,
    cfg: RunConfig,
    stats: RunStats,
    state: dict,
) -> None:
    """Call the provider with retry, embed metadata on success, record stats."""
    api_text = tts_text if cfg.provider == "inworld" else ctx.utterance_text
    for attempt in range(cfg.max_attempts):
        try:
            providers.generate(
                cfg.provider,
                api_key=cfg.api_key,
                text=api_text,
                cfg=voice_cfg,
                full_path=ctx.full_path,
                inworld_default_model_id=cfg.inworld_model_id,
            )
            embed_mp3_metadata(
                ctx.full_path,
                utterance_text=ctx.utterance_text,
                provider=cfg.provider,
                provider_cfg=dict(voice_cfg),
                tts_text_sent=tts_text if tts_text != ctx.utterance_text else None,
            )
            df.at[ctx.idx, "file_name"] = ctx.full_path
            stats.generated += 1
            print_progress(
                state, cfg.debug, "created",
                f"  Row {ctx.idx}: Created - {ctx.filename}",
                filename_for_milestone=ctx.filename,
                success_count=stats.generated,
            )
            return
        except Exception as e:
            if attempt < cfg.max_attempts - 1:
                print_progress(state, cfg.debug, "skip", f"  Row {ctx.idx}: Retrying after error - {e}")
                time.sleep(RATE_LIMIT_DELAY)
            else:
                msg = (
                    f"ERROR (after {cfg.retry_count} retry(s)) - {e}"
                    if cfg.retry_count else f"ERROR - {e}"
                )
                print_progress(state, cfg.debug, "error", f"  Row {ctx.idx}: {msg}")
                stats.errors += 1


def _ensure_file_name_if_exists(df: pd.DataFrame, ctx: CsvRowContext) -> None:
    """Sync df.file_name with disk: only set it if the audio file actually exists."""
    if Path(ctx.full_path).exists():
        df.at[ctx.idx, "file_name"] = ctx.full_path


# ---------------------------------------------------------------------------
# Post-loop phase - print summary and warnings
# ---------------------------------------------------------------------------

def _write_csv_and_summary(df: pd.DataFrame, cfg: RunConfig, stats: RunStats) -> None:
    """Persist the updated CSV and print the one-line numeric summary."""
    output_csv = Path(cfg.csv_path).resolve()
    df.to_csv(output_csv, index=False)
    rows_with_files = (df["file_name"].astype(str).str.strip() != "").sum()

    summary = (
        f"\nDone. Generated: {stats.generated}, "
        f"Skipped: {stats.skipped}, Errors: {stats.errors}"
    )
    if cfg.regenerate_drift and stats.regenerated:
        summary += f", Regenerated (drift): {stats.regenerated}"
    if stats.drift_files:
        summary += f", Drift (not regenerated): {len(stats.drift_files)}"
    if stats.provider_mismatch_files:
        summary += f", Wrong-provider audio: {len(stats.provider_mismatch_files)}"
    print(summary)
    print(f"CSV saved to: {output_csv}")
    print(f"Rows with file_name set: {rows_with_files} of {len(df)}")


def _print_info_banner(cfg: RunConfig) -> None:
    """The hash-banner block printed at the start of every run."""
    banner_width = 60
    header_label = " Info "
    side = (banner_width - len(header_label)) // 2
    print("#" * side + header_label + "#" * (banner_width - side - len(header_label)))
    print(f"Processing: {cfg.csv_path}")
    if cfg.limit is not None:
        print(f"Limit: {cfg.limit} utterance(s)")
    print(f"Output audio directory: {cfg.output_dir}")
    if cfg.character_voices:
        print(
            f"Character voices config: {cfg.voices_path} "
            f"(project '{cfg.project}', provider '{cfg.provider}')"
        )
    else:
        print(
            f"Warning: no entries found in {cfg.voices_path} for project '{cfg.project}'. "
            f"Run with --init to scaffold one from this CSV."
        )
    print("#" * banner_width)


def _print_drift_warning(
    drift_files: list[tuple[str, list[str]]],
    cfg: RunConfig,
) -> None:
    """Emit the yellow WARNING block + --regenerate-drift suggestion."""
    if not drift_files:
        return
    n = len(drift_files)
    files_word = "file" if n == 1 else "files"
    verb_word = "has" if n == 1 else "have"
    print()
    print(yellow(
        f"WARNING: {n} audio {files_word} {verb_word} metadata that no longer matches "
        f"the CSV ({Path(cfg.csv_path).name}) or '{cfg.voices_path.name}'. "
        f"This means the audio file no longer matches what you currently have configured."
    ))
    max_show = 25
    for fp, issues in drift_files[:max_show]:
        print(yellow(f"  - {fp}"))
        for iss in issues:
            print(yellow(f"        {iss}"))
    if len(drift_files) > max_show:
        print(yellow(f"  ... and {len(drift_files) - max_show} more"))
    print()
    print("To delete these files and regenerate them in one step, re-run with --regenerate-drift:")
    cmd_parts = [
        "bitpart tts",
        f"\"{cfg.csv_path}\"",
        f"--project {cfg.project}",
        f"--provider {cfg.provider}",
        "--regenerate-drift",
    ]
    print("  " + " ".join(cmd_parts))


def _print_provider_mismatch_warning(
    provider_mismatch_files: list[tuple[str, str]],
    cfg: RunConfig,
) -> None:
    """Emit the yellow WARNING for cross-provider audio left on disk."""
    if not provider_mismatch_files:
        return
    by_prov: dict[str, int] = {}
    for _, prov in provider_mismatch_files:
        by_prov[prov] = by_prov.get(prov, 0) + 1
    n = len(provider_mismatch_files)
    files_word = "file" if n == 1 else "files"
    verb_word = "was" if n == 1 else "were"
    per_prov = ", ".join(f"{c} from '{p}'" for p, c in sorted(by_prov.items()))
    print()
    print(yellow(
        f"WARNING: {n} existing audio {files_word} {verb_word} generated by a different "
        f"provider than the current run (--provider {cfg.provider}): {per_prov}. "
        f"They were left as-is."
    ))
    print(yellow("  Suggestion: move these files aside and re-run your previous command."))
