"""The three things that must be in place before a transcription can start."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass

from . import paths

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    detail: str = ""


def quick_checks() -> list[Check]:
    """Cheap checks, safe to run on the main loop at start-up."""
    ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    interpreter = paths.venv_python()
    model = paths.model_is_ready()

    return [
        Check("ffmpeg", "ffmpeg", ffmpeg,
              "" if ffmpeg else "not on PATH — install with: winget install Gyan.FFmpeg"),
        Check("venv", "Python env", interpreter is not None,
              "" if interpreter else "the venv folder is missing — run 'H9 Transcriber.bat' once"),
        Check("model", "large-v3 model", model,
              "" if model else "not downloaded yet — the first run fetches ~3 GB"),
    ]


def blocking_problem(checks: list[Check]) -> str | None:
    """The one message to show the user, or None when Start is safe to press."""
    for check in checks:
        if check.key in ("ffmpeg", "venv") and not check.ok:
            return f"{check.label}: {check.detail}"
    return None


def probe_gpu(callback) -> None:
    """Ask the project interpreter about CUDA, off the main loop.

    Importing torch takes several seconds, so this never happens inline;
    `callback(Check)` is invoked from a worker thread when the answer arrives.
    """
    def work() -> None:
        interpreter = paths.venv_python()
        if interpreter is None:
            callback(Check("gpu", "GPU", False, "no Python environment"))
            return
        try:
            result = subprocess.run(
                [str(interpreter), "-c",
                 "import torch;"
                 "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"],
                capture_output=True, text=True, timeout=180,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            callback(Check("gpu", "GPU", False, "could not query torch"))
            return

        name = result.stdout.strip()
        if name:
            callback(Check("gpu", name, True))
        else:
            callback(Check("gpu", "CPU only", False, "CUDA unavailable — much slower"))

    threading.Thread(target=work, daemon=True).start()
