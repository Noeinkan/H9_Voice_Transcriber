"""Review suggested meeting breaks and name the resulting text files."""

from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import meeting_split


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    return text[:105] + ("..." if len(text) > 105 else "")


def show(parent: tk.Misc, transcript: Path) -> tk.Toplevel | None:
    proposal = meeting_split.proposal_path(transcript)
    try:
        data = json.loads(proposal.read_text(encoding="utf-8"))
        units = data["units"]
        candidates = data["candidates"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        messagebox.showerror("Meeting splits", f"Could not read suggestions: {exc}", parent=parent)
        return
    if not candidates:
        messagebox.showinfo("Meeting splits", "No meeting breaks were suggested.", parent=parent)
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Review meeting splits - " + transcript.stem)
    dialog.geometry("780x680")
    dialog.minsize(620, 480)
    dialog.transient(parent)
    dialog.grab_set()
    frame = ttk.Frame(dialog, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Suggested meeting breaks", style="H1.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Select the pauses that separate meetings. The original full transcript stays in output.",
              wraplength=720).pack(anchor="w", pady=(6, 12))

    canvas = tk.Canvas(frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    list_frame = ttk.Frame(canvas)
    list_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=list_frame, anchor="nw", tags="content")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure("content", width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    selected = []
    for candidate in candidates:
        index = candidate["index"]
        gap = candidate["gap_ms"] // 1000
        reason = f"{gap // 60}m {gap % 60:02d}s pause"
        if candidate["voice_change"]:
            reason += " · voices change"
        variable = tk.BooleanVar(value=candidate.get("default", False))
        selected.append(variable)
        card = ttk.Frame(list_frame, padding=(6, 8))
        card.pack(fill="x")
        ttk.Checkbutton(card, variable=variable,
                        text=f"Start next meeting at {meeting_split.clock(candidate['at_ms'])}   ({reason})").pack(anchor="w")
        ttk.Label(card, text="Before: " + _snippet(units[index - 1]["text"]),
                  wraplength=690).pack(anchor="w", padx=24)
        ttk.Label(card, text="After:   " + _snippet(units[index]["text"]),
                  wraplength=690).pack(anchor="w", padx=24)

    footer = ttk.Frame(dialog, padding=(18, 8, 18, 18))
    footer.pack(fill="x")
    ttk.Label(footer, text="File names (without .txt)").pack(anchor="w")
    names_frame = ttk.Frame(footer)
    names_frame.pack(fill="x", pady=(6, 12))
    entries: list[tk.StringVar] = []

    def rebuild(*_args) -> None:
        previous = [v.get() for v in entries]
        for child in names_frame.winfo_children():
            child.destroy()
        entries.clear()
        count = 1 + sum(v.get() for v in selected)
        for number in range(count):
            ttk.Label(names_frame, text=f"Meeting {number + 1}").grid(row=number, column=0, sticky="w", pady=2)
            name = previous[number] if number < len(previous) else f"{transcript.stem} - Meeting {number + 1}"
            variable = tk.StringVar(value=name)
            entries.append(variable)
            ttk.Entry(names_frame, textvariable=variable, width=65).grid(
                row=number, column=1, sticky="ew", padx=(10, 0), pady=2)
        names_frame.columnconfigure(1, weight=1)

    for variable in selected:
        variable.trace_add("write", rebuild)
    rebuild()

    def save() -> None:
        cuts = [candidate["index"] for candidate, variable in zip(candidates, selected) if variable.get()]
        if not cuts:
            messagebox.showinfo("Meeting splits", "Select at least one break.", parent=dialog)
            return
        names = [variable.get().strip() for variable in entries]
        invalid = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
        if any(not name or name.endswith((".", " ")) or invalid.search(name)
               or name.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}
               for name in names):
            messagebox.showerror("Invalid file name", "Use names without Windows path characters or trailing dots.", parent=dialog)
            return
        if len({name.casefold() for name in names}) != len(names):
            messagebox.showerror("Duplicate file name", "Give each meeting a different name.", parent=dialog)
            return
        destinations = [transcript.parent / (name + ".txt") for name in names]
        if any(path == transcript or path.exists() for path in destinations):
            messagebox.showerror("File already exists", "A named file already exists. Choose another name.", parent=dialog)
            return
        boundaries = [0, *cuts, len(units)]
        try:
            for path, start, end in zip(destinations, boundaries, boundaries[1:]):
                path.write_text(meeting_split.render(units[start:end],
                                data.get("timestamps", True), data.get("silence_note_ms", 60_000)),
                                encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Could not save meeting files", str(exc), parent=dialog)
            return
        messagebox.showinfo("Meeting files saved", "Created:\n" + "\n".join(p.name for p in destinations), parent=dialog)
        dialog.destroy()

    buttons = ttk.Frame(footer)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Save meeting text files", style="Accent.TButton", command=save).pack(side="right")
    ttk.Button(buttons, text="Later", command=dialog.destroy).pack(side="right", padx=(0, 8))
    return dialog
