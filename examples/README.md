# Examples

A complete, runnable pair of inputs you can use to try `bitpart tts` without needing to generate in Coppola:

- [`example-utterances.csv`](example-utterances.csv) — 3 rows, all assigned to characters under the `Kelpie` project.
- [`character_voices.json`](character_voices.json) — voice config for those 3 characters.

All commands below assume:
- You're at the repo root (`bitpart-cli/`) with the venv activated.
- You ran `pip install -e .` (so `bitpart` is on `PATH`).
- Your provider API key is set (see [main README](../README.md#setup) step 5).

> **Heads up:** `Townsperson3` in the example JSON has an empty `elevenlabs.voice_id` on purpose. The included `voice_name` field hints at a real ElevenLabs voice ID you can paste in (`goT3UYdM9bhm0n2lmKQx`) — or leave it blank to see the "missing voice" skip path. `Townsperson1` and `Townsperson2` have working ElevenLabs voices and Inworld voices; `Townsperson3` only has Inworld scaffolded once you run recipe #3 below.

---

## 1. Generate one audio file (smallest possible test)

Use `--limit 1` to call the API exactly once. Good first run to confirm your API key works.

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --limit 1
```

Look for the new `.mp3` next to the CSV in `examples/`.

## 2. Generate all audio for the example

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie
```

You should see 2 files generated, 1 row skipped (`Townsperson3` has no `elevenlabs.voice_id`), and the CSV's `file_name` column populated for the 2 generated rows.

## 3. Use Inworld instead of ElevenLabs

A given audio file can only have been produced by one provider, so the first time you switch providers you need to clear out the existing MP3s. Move them somewhere else (or delete them):

```powershell
# Move the existing ElevenLabs MP3s out of the way (or delete them outright):
mkdir examples\_elevenlabs-archive
Move-Item examples\*.mp3 examples\_elevenlabs-archive\
```

`Townsperson3` doesn't have an Inworld block yet — run `--init` with `--provider inworld` to add the missing block additively (existing ElevenLabs entries are left alone):

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --init --provider inworld
```

Open `examples\character_voices.json`, find `Townsperson3.providers.inworld`, and set `voice_id` to `Alex` (or any other Inworld voice). Then drop `--init` to actually generate audio:

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --provider inworld
```

All 3 rows should generate this time.

## 4. Bootstrap `character_voices.json` from scratch

Delete `examples\character_voices.json` (or point at a fresh CSV) and let `--init` build a skeleton:

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --init --provider elevenlabs
```

Open the file, fill in `voice_id` (and optionally `gender`) for each character, then run command #2.

## 5. Regenerate after editing CSV text or voice config

If you change a row's `utterance_text` or a character's `voice_id`, the existing MP3 will drift. By default `bitpart tts` warns you and leaves the files alone:

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie
# → "WARNING: N audio file(s) has metadata that no longer matches..."
```

Add `--regenerate-drift` to delete-and-recreate any drifted files in one pass:

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --regenerate-drift
```

## 6. Verbose / debug output

By default progress is collapsed to one dot per file. Use `--debug` for one line per row, plus the otherwise-suppressed "already processed" / "file exists, updating CSV only" messages:

```powershell
bitpart tts examples\example-utterances.csv --project Kelpie --debug
```

## 7. Inspect embedded TTS metadata of any generated MP3

`bitpart tts` embeds a `TXXX:TTS_METADATA` JSON blob into every MP3 it creates (the provider, the audio config used, and the `utterance_text`). You can read it back with `mutagen`:

```powershell
python -c "from mutagen.mp3 import MP3; a=MP3(r'examples\22222222-2222-2222-2222-222222222222_bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.mp3'); print(a.tags.pprint() if a.tags else 'no tags')"
```

---

## Need more flags?

The full flag reference and env-var table live in the [main README](../README.md#cli-flags-bitpart-tts). `bitpart tts --help` also prints everything inline.
