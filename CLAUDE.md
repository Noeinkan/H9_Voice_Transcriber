# H9 Voice Transcriber

Setup, controls, environment variables and troubleshooting: README. Which file
does what: PROJECT_INDEX.md. Here are only the invariants that break **silently** — no test defends them and none of
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

**`gui/` imports the standard library and nothing else** — plus
`meeting_split.py`, which is why that module must stay stdlib-only too.
`tools/build_exe.py` freezes only the window and excludes torch, numpy,
faster_whisper and the rest by name. An import added here (or in
`meeting_split.py`) resolves fine in `venv` and fails only inside the built
`.exe`, in front of a user.

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
only transcript (beside it sits at most the `<name>.meetings.json` sidecar). `should_skip` tells the two apart by matching `[mm:ss] Person N: ` (a bare
`Person N` header line matches too) against the file's **first line**
(`is_labelled`). Change how `write_turns` opens a
turn and nothing raises: every recording just looks unlabelled forever and is
re-transcribed on every run.

**`AUDIO_SUFFIXES`, the 500 MB "model is ready" threshold and
`_LABELLED_FIRST_LINE` are written out twice**, in `transcribe.py` and in
`gui/paths.py`. Change one, change the other, or the queue lists files the
transcriber ignores, or promises to skip files it then redoes (and the Start
button and progress bar size the run wrong).

**Meeting-break suggestions can only fall between turns.** `transcribe_one`
saves the turns (or Whisper segments, without speakers) plus the ranked pauses
to `<name>.meetings.json`; `gui/meeting_review.py` reads that file after the
run and writes the user-named split `.txt` files. That is why `label_speakers`
passes `break_gap_ms=meeting_split.MIN_GAP_MS` to `build_turns`: it cuts a turn
at every 5 s pause even when the speaker stays the same. Drop it and pauses
inside one person's turn vanish from the suggestions — no error, just fewer
breaks offered. Those cuts are for the sidecar only: `write_turns` and
`meeting_split.render` join same-speaker pieces back into one paragraph.
The sidecar is deleted before every re-transcription, so a stale one never
outlives its transcript.

**The silence line and turn layout are written out three times**:
`transcribe.py` (plain transcript), `diarization.silence_note` /
`write_turns` (labelled), and `meeting_split.render` (split files). Change the
`--- N min without speech ---` wording or the `[mm:ss] Person N: ` prefix in
one and the others keep the old look; if the labelled-turn prefix changes,
`_LABELLED_FIRST_LINE` above must follow.

## Verifying

There is no test suite. Without a GPU:

```bat
py -3.12 -c "import gui.app, gui.runner, gui.filelist, gui.preflight, gui.paths, gui.theme, gui.meeting_review, meeting_split"
venv\Scripts\python.exe -m compileall -q transcribe.py diarization.py meeting_split.py voice_id.py enroll_voice.py gui tools
```

The first is the `gui/` rule above: a bare interpreter with none of the
project's dependencies must import the package cleanly. Anything touching the
log format or the pipeline needs a real run — a short file in `input/`, then
`run.bat` (`--speakers` if you touched diarization).
