# H9 Voice Transcriber

Offline transcription of long recordings into plain text files, powered by OpenAI Whisper **large-v3** running on your NVIDIA GPU. There is a desktop window for everyday use and a batch file for unattended runs.

![The transcriber window](assets/icon.png)

## Quick start — the desktop app

1. Open the project folder `H9_Voice_Transcriber` in Explorer and double-click **`Create Desktop Shortcut.bat`**. A console opens, prints `Shortcut created: ...`, and waits for a key press. Close it.
2. On your desktop you now have **H9 Voice Transcriber** with a purple microphone icon. Double-click it. The window opens in about a second.
   *If nothing appears the first time:* the shortcut is building the Python environment, which takes 10 minutes or more and shows a console while it works. Leave it alone until the window appears.
3. In the window, click **Add audio…** and pick your recordings, or drop files straight into the `input` folder and click **Refresh**. The queue lists each file with its size, length and status.
4. Click **Start transcription**. The bar under the buttons fills as files complete, and the line beside it says what is happening right now (`Loading the Whisper model…`, `Transcribing <file>`, `Segment 2 of 4`).
   *The very first run downloads the model, about 3 GB.* The status line shows the download in GB; it happens once.
5. When the run finishes, double-click any row marked **Done** to open its transcript, or click **Open output folder** at the bottom right.

Nothing leaves your machine — the model runs locally.

### What the window gives you

| Control | What it does |
|---|---|
| **Add audio…** | Copies the files you pick into `input`. Accepts m4a, mp3, wav, flac, ogg, opus, aac, wma and the common video containers. |
| **Quality** | `Fast` / `Balanced` / `Best` — Whisper's beam size (1 / 5 / 10). Higher is slower and slightly more accurate. |
| **Precision** | `Low VRAM (int8)` is the safe default on a 4 GB card. `Sharper (float16)` is better when you have VRAM to spare. |
| **Speakers** | `Auto` by default: every file also gets a `<name>.speakers.txt` with the turns tagged `Person 1` / `Person 2`, and the clustering counts the voices itself. Pick `2 people` for an interview when you already know the count — it is more reliable than guessing. `Off` skips the labelling and its extra pass over the audio. See [Telling the voices apart](#telling-the-voices-apart) — including how to make yourself Person 1. |
| **Redo files already transcribed** | Off by default: files whose `.txt` is newer than the audio are skipped. Tick it to transcribe them again. |
| **Stop** | Kills the transcription and the ffmpeg processes under it. Files already finished keep their transcripts. |
| **Show details** | Opens the live log — the same lines that go into `transcripts.log`. It opens by itself if a run fails. |
| Right-click a row | Open transcript · Show audio in Explorer · Remove from input folder. |

The three or four dots in the top right are readiness checks: **ffmpeg**, **Python env**, **large-v3 model**, and the **GPU name** once it has been queried (a few seconds after opening). Hover a red one to read what is wrong.

### Watching it work

While a run is going, a waveform panel opens between the buttons and the progress bar. It is not decoration standing in for the real thing — it is the actual recording:

- ffmpeg reads a loudness envelope of the file in the background, so the bars are the shape of that conversation: loud passages tall, pauses flat.
- The bright part behind the playhead is what Whisper has already been through. Because Whisper reports a timestamp for every phrase it produces, the playhead moves continuously rather than jumping between files, and the queue row shows the same figure (`Transcribing 43%`).
- For the second or two before the envelope is ready — and for any file ffmpeg cannot read — the same bars run as a scanning equaliser instead, so the panel is never a dead rectangle.
- The progress bar underneath covers the whole run: finished files plus how far into the current one. A highlight sweeps along it, which is the quickest way to tell a slow file from a hung one.
- The dot beside the status line breathes while work is happening and settles green when the run finishes, amber if you stopped it, red if it failed.

Two seconds after the last file the panel folds away and the window is quiet again.

### Building the standalone .exe (optional)

The desktop shortcut works without this step — it starts `H9 Transcriber.bat`, which opens the same window. If you would rather have a real executable:

1. Open a terminal in the project folder.
2. Run `venv\Scripts\python.exe tools\build_exe.py`. It installs PyInstaller if needed and takes about a minute.
3. You get `dist\H9 Transcriber.exe`, roughly 10 MB.
4. Run **`Create Desktop Shortcut.bat`** again — it now points the desktop icon at the executable instead of the batch file.

Only the window is frozen into the exe. Transcription still runs in `venv`, which is why the file is 10 MB and not several gigabytes — so **keep the exe inside this project folder** and put a shortcut on the desktop rather than a copy of the exe.

## Quick start — the batch file

1. **First time only:** double-click `download_model.bat` and wait for the ~3 GB model (5-15 min).
2. Drop audio files into the `input` folder.
3. Double-click `run.bat`.
4. Collect `.txt` transcripts from the `output` folder.

Progress and errors are appended to `transcripts.log` (per file) and `run.log` (per step in `run.bat`). Watch the live log in another terminal with:

```bat
powershell -Command "Get-Content transcripts.log -Wait"
```

## Telling the voices apart

Every recording is split into `Person 1` and `Person 2` turns instead of one unbroken block of
text. This is **on by default**, in the window and from a terminal alike. It stays fully offline:
the models come from NVIDIA NeMo, download once from NVIDIA's public servers, and need no account,
key or licence.

The window's **Speakers** dropdown starts on `Auto`. From a terminal:

```bat
run.bat                 REM default: work out how many people are talking
run.bat --speakers 2    REM you already know it is a two-person interview
run.bat --no-speakers   REM plain transcript only, skip the labelling pass
```

Pin the number whenever you know it — set **Speakers** to `2 people`, or pass `--speakers 2`. Left
to guess, the clustering sometimes splits one voice into two when the line is noisy or someone
changes tone.

You get a **second** file per recording, `output\<name>.speakers.txt`:

```text
Person 1: So, tell me how the handover went.

Person 2: We closed it two weeks late, but the model was clean by then.
```

The plain `output\<name>.txt` is still written exactly as before, so nothing that already reads
those files breaks.

First run is slower: it downloads about 200 MB of models, and on a four-minute clip labelling took
roughly a minute on top of transcription. A recording that already has a `.txt` but no
`.speakers.txt` is transcribed again — the word-level timings the labeller needs were never saved
to disk.

### Being Person 1 yourself

Out of the box `Person 1` is whoever speaks first, which flips from recording to recording. Record
your own voice once and it stops flipping:

1. In the project folder, double-click **`enroll_voice.bat`**.
2. Wait for the three-second countdown, then talk for 30 seconds — read anything out loud, pauses
   are fine. *If it reports that the audio is silent,* Windows picked the wrong microphone: run
   `enroll_voice.bat --list-devices`, find your microphone's number in the printed list, then run
   `enroll_voice.bat --device 3` with that number.
3. It saves `voice\me.wav` (the sample, so you can play it back and check it) and `voice\me.npy`
   (the fingerprint used for matching). Both stay on this PC and are git-ignored.

From then on, in every recording where you are present, your voice is `Person 1`. Prefer not to use
the microphone? Record a voice memo on your phone and pass the file: `enroll_voice.bat my_voice.m4a`.

When no voice resembles your fingerprint closely enough — you were not in that recording, or the
audio is too poor to judge — `transcripts.log` says so and the labeller falls back to
first-to-speak numbering.

## First-time setup

Both entry points create a Python 3.12 virtual environment and install dependencies automatically. Manual setup:

```bat
py -3.12 -m venv venv
venv\Scripts\activate
python -m pip install -U pip
pip install -U torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
pip install nvidia-cublas-cu12==12.9.1.4 nvidia-cuda-cupti-cu12==12.9.79 nvidia-cuda-runtime-cu12==12.9.79 --extra-index-url https://pypi.ngc.nvidia.com
pip install buzz-captions
pip install --force-reinstall torch==2.8.0+cu129 torchaudio==2.8.0+cu129 --index-url https://download.pytorch.org/whl/cu129
```

Note: `buzz-captions` pulls in the CPU PyTorch build. Reinstall the CUDA wheels afterward (last command above).

**Requirements:** Python 3.12, ffmpeg on PATH, NVIDIA GPU with recent drivers.

Verify GPU support:

```bat
venv\Scripts\activate
python -c "import torch, buzz; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## How it works

- Uses **faster-whisper** with the **large-v3** model and reduced GPU memory mode for the RTX 5060 (4 GB VRAM).
- Skips files whose output `.txt` is newer than the source audio, unless `H9_FORCE=1` (the window's "Redo files already transcribed").
- Splits audio longer than 30 minutes into segments before transcribing, then merges the text into one file. This avoids out-of-memory issues on very long recordings.
- The large-v3 model (~3 GB) is downloaded on first run into `models/large-v3/`.
- The window never imports torch. It starts `transcribe.py` in `venv` as a child process and reads its log, which is why it opens instantly and why **Stop** can kill the work without killing the window.
- With `--speakers`, the audio is diarized **whole**, never in 30-minute pieces: voice clusters only
  mean something inside a single pass, so chunking would make "Person 1" a different person in each
  half. Whisper still transcribes in pieces; only the word timings are stitched back onto the full
  recording's clock. Speaker models are cached in `%USERPROFILE%\.cache\torch\NeMo`.

Environment variables read by `transcribe.py`, all set for you by the window:

| Variable | Default | Meaning |
|---|---|---|
| `H9_BEAM_SIZE` | `5` | Whisper beam size |
| `H9_COMPUTE_TYPE` | `int8` | `int8` or `float16` |
| `H9_VAD` | on | Voice-activity filtering |
| `H9_FORCE` | off | Re-transcribe files that already have an up-to-date `.txt` |
| `H9_DIARIZE` | **on** | Also write `<name>.speakers.txt` with Person 1 / Person 2 turns. Set to `0` (`run.bat --no-speakers`) for the plain transcript only |
| `H9_SPEAKERS` | auto | How many people are in the recording, when you know it |
| `H9_TIMESTAMPS` | off | Prefix every speaker turn with `[mm:ss]` |
| `H9_PROGRESS` | off | Print `@progress <percent>` lines on stdout for the window's playhead. They never reach `transcripts.log`, and `run.bat` leaves this unset so its console output is unchanged. |

## Layout

```
gui/            the desktop window (standard library only)
  app.py        layout and wiring
  runner.py     runs transcribe.py as a child process, parses its output
  visualizer.py the waveform panel with the travelling playhead
  waveform.py   reads a loudness envelope out of a file with ffmpeg
  animated.py   the easing progress bar and the breathing status dot
  filelist.py   the queue table
tools/          make_icon.py, build_exe.py, install_shortcut.ps1
transcribe.py   the transcription pipeline
diarization.py  splitting a transcript into speaker turns
voice_id.py     recognising your own voice among those speakers
enroll_voice.py records your 30-second voice sample (enroll_voice.bat)
run.bat         unattended batch run
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| The desktop icon does nothing | The first launch builds the environment silently for several minutes. If it still does nothing, run `H9 Transcriber.bat` directly from Explorer to see the error. |
| `ffmpeg` chip is red | Install it with `winget install Gyan.FFmpeg`, then close every terminal, open a new one, and start the app again so it picks up the new PATH. |
| CUDA not available | Update NVIDIA drivers, then reinstall the CUDA PyTorch wheels above |
| Out of memory | Set **Precision** to `Low VRAM (int8)` and close other GPU apps |
| Slow first run | Model download plus the first GPU compile are one-time costs |
| One person split across `Person 1` and `Person 3` | Re-run with the count pinned: `run.bat --speakers 2` |
| `Person 1` is the other person, not you | Enroll your voice (`enroll_voice.bat`). If you already did, check `transcripts.log`: it prints the match score per voice, and anything under 0.35 means the sample and the recording sound too different — re-record the sample on the device you actually use for interviews |
| No `.speakers.txt` appeared | Either **Speakers** was set to `Off` (`--no-speakers`), or the diarizer found no speech — `transcripts.log` says which |
