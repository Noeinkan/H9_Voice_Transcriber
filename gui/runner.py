"""Runs transcribe.py in a child process and turns its log into UI events.

transcribe.py already prints one timestamped line per meaningful step. Rather
than importing torch into the GUI process (slow to start, and it fights the
Tk main loop), we spawn it with the project interpreter and parse those lines.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_TIMESTAMP = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]\s?")
_START = re.compile(r"^START (?P<name>.+)$")
_DONE = re.compile(r"^DONE\s+(?P<name>.+?) -> .+$")
_SKIP = re.compile(r"^SKIP (?P<name>.+?) \(.*\)$")
_ERROR_FILE = re.compile(r"^ERROR (?P<name>[^:]+\.[A-Za-z0-9]+): (?P<message>.+)$")
_SEGMENT = re.compile(r"^\s+segment (?P<index>\d+)/(?P<total>\d+):")
_DURATION = re.compile(r"^\s+duration: (?P<minutes>[\d.]+) min$")
_PROGRESS = re.compile(r"^@progress (?P<percent>[\d.]+)$")
_DOWNLOAD = re.compile(r"^\s+(?P<done>[\d.]+) / (?P<total>[\d.]+) GB \((?P<percent>\d+)%\)$")


@dataclass
class Options:
    """Everything the window lets the user change before pressing Start."""

    beam_size: int = 5
    compute_type: str = "int8"
    vad: bool = True
    force: bool = False
    diarize: bool = False
    speakers: int = 0              # 0 = let the clustering decide

    def env(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(
            H9_BEAM_SIZE=str(self.beam_size),
            H9_COMPUTE_TYPE=self.compute_type,
            H9_VAD="1" if self.vad else "0",
            H9_FORCE="1" if self.force else "0",
            # Written unconditionally: the child must not inherit a stale
            # H9_DIARIZE from whatever launched the window.
            H9_DIARIZE="1" if self.diarize else "0",
            H9_SPEAKERS=str(self.speakers if self.diarize else 0),
            H9_PROGRESS="1",
            PYTHONUNBUFFERED="1",
            PYTHONIOENCODING="utf-8",
        )
        return environment


@dataclass
class Event:
    kind: str                      # log | file | stage | exit
    text: str = ""
    name: str = ""                 # file this event is about, when relevant
    status: str = ""               # queued | working | done | skipped | error
    detail: str = ""
    data: dict = field(default_factory=dict)


class Runner:
    """Owns the child process and a queue of Events for the Tk main loop."""

    def __init__(self) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False

    # -- lifecycle --------------------------------------------------------
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, options: Options) -> None:
        if self.is_running():
            raise RuntimeError("A transcription is already running")

        interpreter = paths.venv_python() or Path(sys.executable)
        if getattr(sys, "frozen", False) and paths.venv_python() is None:
            raise RuntimeError(
                "The Python environment (venv folder) is missing. "
                "Run 'H9 Transcriber.bat' once to build it."
            )

        self._stopping = False
        self._process = subprocess.Popen(
            [str(interpreter), "-u", str(paths.TRANSCRIBE_SCRIPT)],
            cwd=str(paths.ROOT),
            env=options.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Kill the child and every process it spawned (ffmpeg included)."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._stopping = True
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
        else:
            process.terminate()

    # -- reader thread ----------------------------------------------------
    def _pump(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            for raw in process.stdout:
                line = raw.rstrip("\n").rstrip("\r")
                if line.strip():
                    self._emit(line)
        finally:
            code = process.wait()
            self.events.put(Event(kind="exit", data={"code": code,
                                                     "stopped": self._stopping}))

    def _emit(self, raw: str) -> None:
        line = _TIMESTAMP.sub("", raw)

        # Position updates are frequent and machine-readable; they never reach
        # the log pane, only the visualiser.
        match = _PROGRESS.match(line.strip())
        if match:
            self.events.put(Event(kind="progress",
                                  data={"fraction": float(match["percent"]) / 100.0}))
            return

        self.events.put(Event(kind="log", text=line))

        stripped = line.strip()

        match = _START.match(stripped)
        if match:
            self.events.put(Event(kind="file", name=match["name"],
                                  status="working", detail="starting"))
            return

        match = _DONE.match(stripped)
        if match:
            self.events.put(Event(kind="file", name=match["name"],
                                  status="done", detail="transcribed"))
            return

        match = _SKIP.match(stripped)
        if match:
            self.events.put(Event(kind="file", name=match["name"],
                                  status="skipped", detail="already up to date"))
            return

        match = _ERROR_FILE.match(stripped)
        if match:
            self.events.put(Event(kind="file", name=match["name"],
                                  status="error", detail=match["message"][:120]))
            return

        match = _SEGMENT.match(line)
        if match:
            self.events.put(Event(
                kind="stage",
                text=f"Segment {match['index']} of {match['total']}",
                data={"segment": int(match["index"]), "segments": int(match["total"])},
            ))
            return

        match = _DURATION.match(line)
        if match:
            self.events.put(Event(kind="stage", text=f"{match['minutes']} minutes of audio"))
            return

        match = _DOWNLOAD.match(line)
        if match:
            self.events.put(Event(
                kind="stage",
                text=f"Downloading model  {match['done']} / {match['total']} GB",
                data={"download": int(match["percent"])},
            ))
            return

        if stripped.startswith("Loading model"):
            self.events.put(Event(kind="stage", text="Loading the Whisper model..."))
        elif stripped.startswith("Model loaded"):
            self.events.put(Event(kind="stage", text="Model ready"))
        elif stripped.startswith("Downloading large-v3"):
            self.events.put(Event(kind="stage", text="Downloading the model (one time, ~3 GB)"))
        elif stripped.startswith("transcribing") or stripped.startswith("  transcribing"):
            self.events.put(Event(kind="stage", text="Transcribing..."))
        elif stripped.startswith("identifying speakers"):
            # Runs after the file is already marked Done, so say what it is
            # doing or the window looks stalled for a minute.
            self.events.put(Event(kind="stage", text="Telling the voices apart..."))

    # -- main-loop side ---------------------------------------------------
    def poll(self, limit: int = 200) -> list[Event]:
        drained: list[Event] = []
        for _ in range(limit):
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                break
        return drained
