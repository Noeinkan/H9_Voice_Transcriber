# H9 Voice Transcriber

Offline transcription of long M4A recordings into plain text files, powered by [Buzz](https://github.com/chidiwilliams/buzz) and OpenAI Whisper **large-v3** on your NVIDIA GPU.

## Quick start

1. **First time only:** double-click `download_model.bat` and wait for the ~3 GB model to finish downloading (5-15 min).
2. Drop `.m4a` files into the `input/` folder.
3. Double-click `run.bat`.
4. Collect `.txt` transcripts from the `output/` folder.

Progress and errors are appended to `transcripts.log` (per-file) and `run.log` (per step in `run.bat`).
You can watch the live log in another terminal with:

```bat
powershell -Command "Get-Content transcripts.log -Wait"
```

## First-time setup

`run.bat` creates a Python 3.12 virtual environment and installs dependencies automatically. Manual setup:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
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
.venv\Scripts\activate
python -c "import torch, buzz; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## How it works

- Uses Buzz's **faster-whisper** backend with the **large-v3** model and reduced GPU memory mode for the RTX 5060 (4 GB VRAM).
- Skips files whose output `.txt` is newer than the source `.m4a`.
- Splits audio longer than 30 minutes into segments before transcribing, then merges the text into one file. This avoids out-of-memory issues on very long recordings.
- The large-v3 model (~3 GB) is downloaded on first run and cached by Buzz.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ffmpeg` not found | `run.bat` will tell you and stop. Install via `winget install Gyan.FFmpeg`, then close the terminal, open a new one, and re-run `run.bat`. |
| CUDA not available | Update NVIDIA drivers, then reinstall the CUDA PyTorch wheels above |
| Out of memory | Close other GPU apps; the script already uses reduced VRAM mode |
| Slow first run | Model download + first GPU compile are one-time costs |
