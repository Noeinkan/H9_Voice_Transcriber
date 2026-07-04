"""Install all Python dependencies for H9 Voice Transcriber.

Run via:
    python install_deps.py

Streams pip output live and exits with pip's exit code. Keeping this in
Python avoids Windows cmd's `==` and `!VAR!` quoting traps when forwarding
arguments to run_with_log.py.

The torch CUDA wheels are ~3.6 GB and the PyTorch CDN occasionally drops the
connection mid-stream (urllib3.IncompleteRead). Pip does not resume partial
downloads, so we retry the pip step a few times with exponential backoff and
also lower the per-chunk socket timeout so we fail fast and try again rather
than sit for several minutes before bailing.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "run.log"

# pip args that benefit from retry-on-transient-network-error.
HEAVY_PIP_INSTALL = True

# Per-attempt socket timeout (seconds). Default pip timeout is 15s which is
# fine; we just want it predictable.
SOCKET_TIMEOUT = 30


def log(line: str) -> None:
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_pip_once(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "pip", "--timeout", str(SOCKET_TIMEOUT), *args]
    # Force UTF-8 so pip's progress bars / unicode chars render cleanly on
    # Windows where the default code page is often cp1252.
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    result = subprocess.run(cmd, env=env)
    return result.returncode


def run_pip(args: list[str], label: str, retries: int = 1, retry_delay: float = 5.0) -> bool:
    """Run a pip step. On failure, retry up to `retries` extra times."""
    for attempt in range(1, retries + 1):
        if attempt == 1:
            log(f"  > {label}")
        else:
            log(f"  > {label}  (retry {attempt}/{retries} after {retry_delay:.0f}s)")
            time.sleep(retry_delay)

        rc = run_pip_once(args)
        log(f"  {label} returned {rc}")
        if rc == 0:
            return True
        if attempt < retries:
            log(f"  pip failed (rc={rc}); will retry")
            # exponential backoff, capped at 60s
            retry_delay = min(retry_delay * 2, 60.0)

    return False


def main() -> int:
    # pip's HTTP retries are handled internally on most errors, but IncompleteRead
    # (a urllib3.ProtocolError) is treated as a hard failure. Our wrapper loop
    # is the only reliable way to recover from it on Windows.
    heavy_retries = 4 if HEAVY_PIP_INSTALL else 1

    steps: list[tuple[str, list[str], int]] = [
        (
            "pip install -U pip",
            ["install", "-U", "pip"],
            1,
        ),
        (
            "pip install torch + torchaudio (CUDA 12.9 wheels)",
            [
                "install",
                "-U",
                "torch==2.8.0+cu129",
                "torchaudio==2.8.0+cu129",
                "--index-url",
                "https://download.pytorch.org/whl/cu129",
            ],
            heavy_retries,
        ),
        (
            "pip install nvidia-cublas / cuda-cupti / cuda-runtime",
            [
                "install",
                "nvidia-cublas-cu12==12.9.1.4",
                "nvidia-cuda-cupti-cu12==12.9.79",
                "nvidia-cuda-runtime-cu12==12.9.79",
                "--extra-index-url",
                "https://pypi.ngc.nvidia.com",
            ],
            3,
        ),
        (
            "pip install buzz-captions",
            ["install", "buzz-captions"],
            3,
        ),
        (
            "pip install --force-reinstall torch/torchaudio CUDA wheels",
            [
                "install",
                "--force-reinstall",
                "torch==2.8.0+cu129",
                "torchaudio==2.8.0+cu129",
                "--index-url",
                "https://download.pytorch.org/whl/cu129",
            ],
            heavy_retries,
        ),
    ]

    for label, args, retries in steps:
        if not run_pip(args, label, retries=retries):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
