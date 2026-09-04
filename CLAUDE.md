# H9 Voice Transcriber

Setup, controls, environment variables and troubleshooting: README. Here are
only the invariants that break **silently** — no test defends them and none of
them fails at development time.

**The window reads the transcriber's log lines.** `gui/runner.py` spawns
`transcribe.py` as a child process and rebuilds the UI by matching its stdout
(`_START`, `_DONE`, `_SKIP`, `_ERROR_FILE`, `_SEGMENT`, `_DURATION`,
`_DOWNLOAD`), timestamp prefix stripped. Reword a `log(...)` string, update the
regex: a stale one raises nothing, the progress bar just stops moving.

**A new `H9_*` variable needs a field in `runner.Options.env()`**, or the
window has no way to set it. `runner.Options` always writes every field it
owns, so a default changed only in `transcribe.py` is invisible to the window:
change both, or the two entry points disagree.

**`gui/` imports the standard library and nothing else.**
`tools/build_exe.py` freezes only the window and excludes torch, numpy,
faster_whisper and the rest by name. An import added here resolves fine in
`venv` and fails only inside the built `.exe`, in front of a user.

**Nothing in `transcribe.py` may import from `buzz.transcriber.*` at module
level**, and `from buzz import cuda_setup` stays ahead of every other non-stdlib
import. That subpackage pulls in OpenAI Whisper, which fights faster-whisper's
CUDA init and kills the process with a native `0xC0000005` — no traceback, no
Python error. Use the local `Segment` dataclass and `_write_txt` instead.

**Diarization runs on the whole recording, never on the parts.** Whisper
transcribes files over 30 minutes part by part; the diarizer must not. Cluster
numbers only mean something inside one pass, so labelling per part gives
`Person 1` a different face in each — plausible output, wrong. Word timings are
shifted onto the full recording's clock first (`transcribe_one`).

**The labelled transcript overwrites the plain one**, so `<name>.txt` is the
only output. `should_skip` tells the two apart by matching `Person N: ` against
the file's **first line** (`is_labelled`). Change how `write_turns` opens a
turn and nothing raises: every recording just looks unlabelled forever and is
re-transcribed on every run.

**`AUDIO_SUFFIXES` and the 500 MB "model is ready" threshold are written out
twice**, in `transcribe.py` and in `gui/paths.py`. Change one, change the other,
or the queue lists files the transcriber ignores.

## Verifying

There is no test suite. Without a GPU:

```bat
py -3.12 -c "import gui.app, gui.runner, gui.filelist, gui.preflight, gui.paths, gui.theme"
venv\Scripts\python.exe -m compileall -q transcribe.py diarization.py voice_id.py enroll_voice.py gui tools
```

The first is the `gui/` rule above: a bare interpreter with none of the
project's dependencies must import the package cleanly. Anything touching the
log format or the pipeline needs a real run — a short file in `input/`, then
`run.bat` (`--speakers` if you touched diarization).
