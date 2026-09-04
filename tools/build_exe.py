"""Freeze the window into dist/H9 Transcriber.exe.

    venv\\Scripts\\python.exe tools\\build_exe.py

Only the GUI is frozen. Transcription still runs in the project virtual
environment, so the executable stays around 15 MB instead of bundling the
several gigabytes of torch, CUDA and model weights. The exe therefore has to
stay in this project folder - put a shortcut on the desktop, not a copy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "H9 Transcriber"

# None of these are used by the window, but PyInstaller's hooks find them in
# this virtual environment and would add hundreds of megabytes.
EXCLUDES = [
    "torch", "torchaudio", "torchvision", "numpy", "scipy", "faster_whisper",
    "ctranslate2", "transformers", "buzz", "PyQt6", "PySide6", "matplotlib",
    "pandas", "IPython", "pytest", "PIL", "sqlalchemy", "yt_dlp",
]


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller into the virtual environment...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"])


def build() -> int:
    ensure_pyinstaller()
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", str(ROOT / "assets" / "icon.ico") + ";assets",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command.append(str(ROOT / "desktop_app.py"))

    print("Building", NAME + ".exe ...")
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / (NAME + ".exe")
    print("\nBuilt:", exe, f"({exe.stat().st_size / 1e6:.1f} MB)")
    print("Now run 'Create Desktop Shortcut.bat' so the desktop icon points at it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
