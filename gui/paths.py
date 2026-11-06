"""Where things live, whether we run from source or from a frozen .exe."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

AUDIO_SUFFIXES = (".m4a", ".mp3", ".wav", ".mp4", ".aac", ".flac", ".ogg",
                  ".opus", ".wma", ".mov", ".mkv", ".webm")


def project_root() -> Path:
    """The H9_Voice_Transcriber folder holding input/, output/ and venv/.

    Frozen builds sit in the project folder (or in dist/ beside it), so we walk
    upwards looking for transcribe.py before giving up on the exe's directory.
    """
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent.parent

    for candidate in (start, *start.parents):
        if (candidate / "transcribe.py").is_file():
            return candidate
    return start


ROOT = project_root()
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
MODEL_BIN = ROOT / "models" / "large-v3" / "model.bin"
TRANSCRIBE_SCRIPT = ROOT / "transcribe.py"
SETUP_SCRIPT = ROOT / "install_deps.py"


def asset(name: str) -> Path:
    """Path to a bundled asset, inside the PyInstaller bundle when frozen."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    packaged = base / "assets" / name
    if packaged.exists():
        return packaged
    return ROOT / "assets" / name


def venv_python(windowed: bool = False) -> Path | None:
    """The interpreter inside venv/ (or .venv/), or None if not created yet."""
    name = "pythonw.exe" if windowed else "python.exe"
    if os.name != "nt":
        name = "python"
    for folder in ("venv", ".venv"):
        candidate = ROOT / folder / ("Scripts" if os.name == "nt" else "bin") / name
        if candidate.is_file():
            return candidate
    return None


def model_is_ready() -> bool:
    return MODEL_BIN.is_file() and MODEL_BIN.stat().st_size > 500_000_000


def audio_files(folder: Path = INPUT_DIR) -> list[Path]:
    if not folder.is_dir():
        return []
    found = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES]
    return sorted(found, key=lambda p: p.name.lower())


def transcript_for(source: Path) -> Path:
    return OUTPUT_DIR / f"{source.stem}.txt"


def glossary_for(source: Path) -> Path:
    return source.with_name(source.name + ".terms.txt")


# Mirrors transcribe.py's _LABELLED_FIRST_LINE: change one, change the other,
# or the window promises to skip files the transcriber then redoes.
_LABELLED_FIRST_LINE = re.compile(r"^(?:\[\d+:\d{2}(?::\d{2})?\] )?Person \d+: ")


def is_up_to_date(source: Path, diarize: bool) -> bool:
    """The window's copy of transcribe.should_skip, minus H9_FORCE."""
    transcript = transcript_for(source)
    try:
        if transcript.stat().st_mtime < source.stat().st_mtime:
            return False
        glossary = glossary_for(source)
        if glossary.exists() and glossary.stat().st_mtime > transcript.stat().st_mtime:
            return False
        if not diarize:
            return True
        with transcript.open(encoding="utf-8") as handle:
            return bool(_LABELLED_FIRST_LINE.match(handle.readline()))
    except OSError:
        return False
