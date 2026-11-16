# Project index

Which file does what. Invariants that break silently: CLAUDE.md. How to use
the app: README.

## Pipeline (runs in `venv`, needs the GPU stack)

| File | Role |
| --- | --- |
| `transcribe.py` | Batch entry point: every audio file in `input/` → `<name>.txt` in `output/`. Whisper (faster-whisper, large-v3), long files in parts, glossary hotwords, skip-if-up-to-date, then speaker labels and meeting-break suggestions. All settings are `H9_*` environment variables. |
| `diarization.py` | "Who said what": NeMo diarizer over the whole recording, words → speaker turns (`build_turns`), labelled transcript writer (`write_turns`, `silence_note`). |
| `voice_id.py` | Stores and matches the user's own voice fingerprint, so they are always Person 1. |
| `enroll_voice.py` / `enroll_voice.bat` | Records that voice sample once. |
| `meeting_split.py` | **Stdlib only** (the window imports it). Ranks pauses ≥ 5 s as possible meeting breaks, saves `<name>.meetings.json`, renders split transcripts. |
| `keep_awake.py` | Stops Windows sleeping during a run. |
| `check_model.py` | Exit 0 if the model is downloaded; used by `run.bat`. |

## Desktop window (`gui/`, standard library only, frozen into the `.exe`)

| File | Role |
| --- | --- |
| `desktop_app.py` | Top-level entry script (PyInstaller cannot start `python -m gui`). |
| `gui/app.py` | Main window: layout, wiring, right-click menu, post-run meeting review. |
| `gui/runner.py` | Spawns `transcribe.py`, parses its log lines into UI events; `Options.env()` owns every `H9_*` the window sets. |
| `gui/filelist.py` | Queue table of files in `input/` with per-row status. |
| `gui/paths.py` | Folder locations (source vs frozen), audio suffixes, up-to-date check — mirrors constants in `transcribe.py`. |
| `gui/preflight.py` | Readiness dots: ffmpeg, Python env, model, GPU. |
| `gui/meeting_review.py` | Dialog to tick suggested meeting breaks, name each meeting and save the split `.txt` files. |
| `gui/visualizer.py`, `gui/waveform.py` | Live waveform panel; ffmpeg loudness envelope. |
| `gui/animated.py`, `gui/theme.py` | Animated progress widgets; colours and ttk styles. |

## Launchers, setup, build

| File | Role |
| --- | --- |
| `H9 Transcriber.bat` | Opens the window (built `.exe` if present, else from source). |
| `run.bat` | Console run of the whole pipeline, logged to `run.log` via `run_with_log.py`. |
| `run_with_ffmpeg.bat` | `run.bat` with a hard-coded local ffmpeg on `PATH`. |
| `download_model.bat` | Fetches the Whisper model. |
| `install_deps.py` | Installs all Python dependencies into `venv`. |
| `Create Desktop Shortcut.bat` → `tools/install_shortcut.ps1` | Desktop shortcut to the `.exe` or the `.bat`. |
| `tools/build_exe.py` | Freezes only the window into `dist/H9 Transcriber.exe`. |
| `tools/make_icon.py` | Regenerates `assets/icon.ico`. |

## Folders and outputs

- `input/` — recordings to transcribe; `<audio>.terms.txt` beside one is its glossary.
- `output/` — `<name>.txt` transcripts, `<name>.meetings.json` break suggestions, user-named split files.
- `models/` — downloaded Whisper model. `venv/`, `build/`, `dist/` — generated.
- `README.md` — user guide and `H9_*` reference. `COMMERCIAL.md` — licensing audit for commercial use.
