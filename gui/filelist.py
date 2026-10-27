"""The table of audio files waiting in input/, with a status per row."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from tkinter import ttk

from . import paths, theme

STATUS_LABEL = {
    "queued": "Queued",
    "working": "Transcribing",
    "done": "Done",
    "skipped": "Up to date",
    "error": "Failed",
    "later": "Next run",
}
STATUS_COLOUR = {
    "queued": theme.MUTED,
    "working": theme.ACCENT,
    "done": theme.SUCCESS,
    "skipped": theme.FAINT,
    "error": theme.DANGER,
    "later": theme.FAINT,
}
_EMPTY_ROW = "__empty__"
_HIDDEN_ROW = "__hidden__"


class FileList(ttk.Frame):
    """A Treeview over paths.INPUT_DIR that remembers per-file status."""

    def __init__(self, master, on_change=None) -> None:
        super().__init__(master, style="Card.TFrame")
        self._on_change = on_change
        self._status: dict[str, str] = {}
        self._detail: dict[str, str] = {}
        self._seconds: dict[str, float | None] = {}
        self._paths: dict[str, Path] = {}
        self._probing = False
        self._diarize = True
        # The names transcribe.py listed when the run began. It reads input/
        # once, so anything added after that waits for the next run.
        self._run_names: set[str] | None = None
        self.show_up_to_date = False

        self.tree = ttk.Treeview(
            self,
            style="Files.Treeview",
            columns=("name", "size", "length", "status"),
            show="headings",
            selectmode="extended",
            height=7,
        )
        self.tree.heading("name", text="FILE", anchor="w")
        self.tree.heading("size", text="SIZE", anchor="e")
        self.tree.heading("length", text="LENGTH", anchor="e")
        self.tree.heading("status", text="STATUS", anchor="w")
        self.tree.column("name", anchor="w", width=300, stretch=True)
        self.tree.column("size", anchor="e", width=80, stretch=False)
        self.tree.column("length", anchor="e", width=80, stretch=False)
        self.tree.column("status", anchor="w", width=150, stretch=False)

        for status, colour in STATUS_COLOUR.items():
            self.tree.tag_configure(status, foreground=colour)
        self.tree.tag_configure(_EMPTY_ROW, foreground=theme.FAINT)
        self.tree.tag_configure(_HIDDEN_ROW, foreground=theme.FAINT)
        self.tree.bind("<Double-1>", self._on_hidden_row, add="+")

        scroll = ttk.Scrollbar(self, orient="vertical", style="Vert.Vertical.TScrollbar",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    # -- data -------------------------------------------------------------
    def refresh(self) -> None:
        """Rescan input/ and redraw, keeping the status of files we know."""
        files = paths.audio_files()
        self._paths = {f.name: f for f in files}
        for name in list(self._status):
            if name not in self._paths:
                self._status.pop(name, None)
                self._detail.pop(name, None)
        for name, path in self._paths.items():
            if name in self._status:
                continue
            if self._run_names is not None and name not in self._run_names:
                self._status[name] = "later"
                self._detail[name] = ""
            elif paths.is_up_to_date(path, self._diarize):
                self._status[name] = "skipped"
                self._detail[name] = "already up to date"
            else:
                self._status[name] = "queued"
                self._detail[name] = ""
        self._redraw()
        self._probe_durations(files)
        self._changed()

    def set_diarize(self, diarize: bool) -> None:
        """Speaker labels change what counts as up to date: re-judge idle rows."""
        self._diarize = diarize
        for name in [n for n, s in self._status.items() if s in ("queued", "skipped")]:
            del self._status[name]
        self.refresh()

    def _redraw(self) -> None:
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        if not self._paths:
            self.tree.insert("", "end", iid=_EMPTY_ROW, tags=(_EMPTY_ROW,),
                             values=("No audio yet - use Add audio... or drop files into the input folder",
                                     "", "", ""))
            return
        # Up-to-date files sink to the bottom (or out of sight): on a folder
        # that has been in use a while they are most of the list, and they
        # pushed the file actually being worked on off screen.
        active = [n for n in self._paths if self._status.get(n) != "skipped"]
        resting = [n for n in self._paths if self._status.get(n) == "skipped"]
        for name in active + (resting if self.show_up_to_date else []):
            self._insert(name)
        if resting and not self.show_up_to_date:
            self.tree.insert("", "end", iid=_HIDDEN_ROW, tags=(_HIDDEN_ROW,), values=(
                f"+ {len(resting)} up-to-date file(s) hidden - double-click to show",
                "", "", ""))
        for iid in selection:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def _insert(self, name: str) -> None:
        status = self._status.get(name, "queued")
        label = STATUS_LABEL.get(status, status)
        detail = self._detail.get(name, "")
        if status in ("working", "error") and detail:
            label = f"{label} — {detail}" if status == "error" else detail.capitalize()
        self.tree.insert("", "end", iid=name, tags=(status,), values=(
            name,
            _human_size(self._paths[name]),
            format_duration(self._seconds.get(name)),
            label,
        ))

    def _on_hidden_row(self, event) -> None:
        if self.tree.identify_row(event.y) == _HIDDEN_ROW:
            self.toggle_up_to_date()

    def toggle_up_to_date(self) -> None:
        self.show_up_to_date = not self.show_up_to_date
        self._redraw()
        self._changed()

    def set_status(self, name: str, status: str, detail: str = "") -> None:
        if name not in self._paths:
            return
        self._status[name] = status
        self._detail[name] = detail
        self._redraw()
        if status == "working" and self.tree.exists(name):
            self.tree.see(name)
        self._changed()

    def begin_run(self, force: bool) -> list[str]:
        """Before a run: queue what will be processed and return those names."""
        self._run_names = set(self._paths)
        work: list[str] = []
        for name, path in self._paths.items():
            if force or not paths.is_up_to_date(path, self._diarize):
                self._status[name] = "queued"
                self._detail[name] = ""
                work.append(name)
            else:
                self._status[name] = "skipped"
                self._detail[name] = "already up to date"
        self._redraw()
        self._changed()
        return work

    def end_run(self) -> None:
        """Rows that sat out the run, or were cut off by Stop, get judged again."""
        self._run_names = None
        for name, status in list(self._status.items()):
            if status in ("later", "working"):
                del self._status[name]
                self._detail.pop(name, None)

    def set_progress_text(self, name: str, text: str) -> None:
        """Update just the status cell - a full redraw per progress tick is waste."""
        if self.tree.exists(name):
            self.tree.set(name, "status", text)

    def _changed(self) -> None:
        if self._on_change:
            self._on_change()

    # -- queries ----------------------------------------------------------
    def counts(self) -> dict[str, int]:
        tally = {key: 0 for key in STATUS_LABEL}
        for status in self._status.values():
            tally[status] = tally.get(status, 0) + 1
        tally["total"] = len(self._paths)
        return tally

    def to_do(self, force: bool) -> list[str]:
        """Names the next run would transcribe, in the order it takes them."""
        return [name for name, path in self._paths.items()
                if force or not paths.is_up_to_date(path, self._diarize)]

    def seconds(self, name: str) -> float | None:
        """Audio length in seconds, or None until ffprobe has answered."""
        return self._seconds.get(name)

    def selected_paths(self) -> list[Path]:
        return [self._paths[iid] for iid in self.tree.selection() if iid in self._paths]

    def is_empty(self) -> bool:
        return not self._paths

    # -- durations, probed off the main loop ------------------------------
    def _probe_durations(self, files: list[Path]) -> None:
        pending = [f for f in files if f.name not in self._seconds]
        if not pending or self._probing:
            return

        def work() -> None:
            for path in pending:
                self._seconds[path.name] = _probe(path)
            self._probing = False

        self._probing = True
        threading.Thread(target=work, daemon=True).start()
        self.after(250, self._watch_probe)

    def _watch_probe(self) -> None:
        """Redraw once the worker is done - all Tk calls stay on the main loop."""
        if self._probing:
            self.after(250, self._watch_probe)
            return
        self._redraw()
        # The Start button quotes the total length, so it needs telling too.
        self._changed()


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _human_size(path: Path) -> str:
    try:
        megabytes = path.stat().st_size / (1024 * 1024)
    except OSError:
        return "—"
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB"
    return f"{megabytes:.0f} MB"


def _probe(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=25,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
