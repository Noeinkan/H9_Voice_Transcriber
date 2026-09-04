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
}
STATUS_COLOUR = {
    "queued": theme.MUTED,
    "working": theme.ACCENT,
    "done": theme.SUCCESS,
    "skipped": theme.FAINT,
    "error": theme.DANGER,
}
_EMPTY_ROW = "__empty__"


class FileList(ttk.Frame):
    """A Treeview over paths.INPUT_DIR that remembers per-file status."""

    def __init__(self, master, on_change=None) -> None:
        super().__init__(master, style="Card.TFrame")
        self._on_change = on_change
        self._status: dict[str, str] = {}
        self._detail: dict[str, str] = {}
        self._durations: dict[str, str] = {}
        self._paths: dict[str, Path] = {}
        self._probing = False

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
            if name not in self._status:
                up_to_date = paths.transcript_for(path).exists() and \
                    paths.transcript_for(path).stat().st_mtime >= path.stat().st_mtime
                self._status[name] = "skipped" if up_to_date else "queued"
                self._detail[name] = "already up to date" if up_to_date else ""
        self._redraw()
        self._probe_durations(files)
        if self._on_change:
            self._on_change()

    def _redraw(self) -> None:
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        if not self._paths:
            self.tree.insert("", "end", iid=_EMPTY_ROW, tags=(_EMPTY_ROW,),
                             values=("No audio yet - use Add audio... or drop files into the input folder",
                                     "", "", ""))
            return
        for name, path in self._paths.items():
            status = self._status.get(name, "queued")
            label = STATUS_LABEL.get(status, status)
            detail = self._detail.get(name, "")
            if status in ("working", "error") and detail:
                label = f"{label} — {detail}" if status == "error" else detail.capitalize()
            self.tree.insert("", "end", iid=name, tags=(status,), values=(
                name,
                _human_size(path),
                self._durations.get(name, "—"),
                label,
            ))
        for iid in selection:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def set_status(self, name: str, status: str, detail: str = "") -> None:
        if name not in self._paths:
            return
        self._status[name] = status
        self._detail[name] = detail
        self._redraw()
        if self._on_change:
            self._on_change()

    def reset_pending(self, force: bool) -> None:
        """Before a run: everything that will be processed goes back to queued."""
        for name, path in self._paths.items():
            transcript = paths.transcript_for(path)
            up_to_date = transcript.exists() and \
                transcript.stat().st_mtime >= path.stat().st_mtime
            if force or not up_to_date:
                self._status[name] = "queued"
                self._detail[name] = ""
        self._redraw()
        if self._on_change:
            self._on_change()

    def clear_working(self) -> None:
        """After a stop, a half-finished row must not stay stuck on a percentage."""
        changed = False
        for name, status in list(self._status.items()):
            if status == "working":
                self._status[name] = "queued"
                self._detail[name] = ""
                changed = True
        if changed:
            self._redraw()

    def set_progress_text(self, name: str, text: str) -> None:
        """Update just the status cell - a full redraw per progress tick is waste."""
        if self.tree.exists(name):
            self.tree.set(name, "status", text)

    # -- queries ----------------------------------------------------------
    def counts(self) -> dict[str, int]:
        tally = {key: 0 for key in STATUS_LABEL}
        for status in self._status.values():
            tally[status] = tally.get(status, 0) + 1
        tally["total"] = len(self._paths)
        return tally

    def selected_paths(self) -> list[Path]:
        return [self._paths[iid] for iid in self.tree.selection() if iid in self._paths]

    def is_empty(self) -> bool:
        return not self._paths

    # -- durations, probed off the main loop ------------------------------
    def _probe_durations(self, files: list[Path]) -> None:
        pending = [f for f in files if f.name not in self._durations]
        if not pending or self._probing:
            return

        def work() -> None:
            for path in pending:
                self._durations[path.name] = _probe(path)
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


def _human_size(path: Path) -> str:
    try:
        megabytes = path.stat().st_size / (1024 * 1024)
    except OSError:
        return "—"
    if megabytes >= 1024:
        return f"{megabytes / 1024:.1f} GB"
    return f"{megabytes:.0f} MB"


def _probe(path: Path) -> str:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=25,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        seconds = float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return "—"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
