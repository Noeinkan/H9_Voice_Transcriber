"""The H9 Voice Transcriber window: layout and wiring."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import paths, preflight, theme
from .animated import PulseDot, SmoothBar
from .filelist import FileList
from .runner import Event, Options, Runner
from .visualizer import Visualizer

QUALITY_PRESETS = {"Fast": 1, "Balanced": 5, "Best": 10}
PRECISIONS = {"Low VRAM (int8)": "int8", "Sharper (float16)": "float16"}
# Speaker labelling: how many voices to expect. 0 means let the clustering
# work it out; pinning the real number keeps it from splitting one voice in
# two on a noisy recording.
SPEAKER_MODES = {"Off": None, "Auto": 0, "2 people": 2, "3 people": 3, "4 people": 4}
LOG_LINE_CAP = 1500
# The time-left estimate stays quiet until the run has shown its real pace.
ETA_WARMUP_SECONDS = 20
# Stand-in length for a file ffprobe could not measure.
UNKNOWN_FILE_SECONDS = 600.0


def enable_dpi_awareness() -> None:
    """Tell Windows we scale ourselves, so the window is crisp at 125%/150%.

    Must run before the first Tk window exists.
    """
    if os.name != "nt":
        return
    import ctypes
    for call in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
                 lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            call()
            return
        except (AttributeError, OSError):
            continue


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        scale = self._apply_dpi_scaling()
        self.title("H9 Voice Transcriber")
        self.geometry(f"{int(960 * scale)}x{int(720 * scale)}")
        self.minsize(int(840 * scale), int(620 * scale))
        theme.apply_theme(self)
        self._set_icon()

        self.runner = Runner()
        # Run progress is measured in seconds of audio, not in files: a
        # 55-minute recording and a 1-minute one are not one step each, and
        # up-to-date files cost nothing.
        self._weights: dict[str, float] = {}
        self._uncounted: set[str] = set()
        self._done_weight = 0.0
        self._total_weight = 0.0
        self._eta_clock: tuple[float, float] | None = None
        self._stage_text = "Idle"
        self._eta_text = ""
        self._segment = (0, 0)
        self._file_fraction = 0.0
        self._current_file = ""
        self._download_mode = False
        self._settle_job = None
        self._log_visible = tk.BooleanVar(value=False)
        self._force = tk.BooleanVar(value=False)
        self._timestamps = tk.BooleanVar(value=True)
        self._quality = tk.StringVar(value="Balanced")
        self._precision = tk.StringVar(value="Low VRAM (int8)")
        self._speakers = tk.StringVar(value="Auto")
        self._gpu_check: preflight.Check | None = None
        # Tk is not thread-safe: worker threads post (callable, args)
        # here and _drain runs them on the main loop.
        self._ui_queue: queue.Queue = queue.Queue()

        self._build()
        self._force.trace_add("write", lambda *_: self._on_files_changed())
        self._speakers.trace_add("write", lambda *_: self.files.set_diarize(
            SPEAKER_MODES.get(self._speakers.get()) is not None))
        self.files.refresh()
        self._refresh_checks()
        preflight.probe_gpu(lambda check: self._post(self._set_gpu_chip, check))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain)

    # ==================================================================
    # layout
    # ==================================================================
    def _build(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=(22, 18, 22, 16))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        self._grid_root = root
        self._weigh_rows(log_visible=False)

        self._build_header(root, row=0)
        self._build_list_toolbar(root, row=2)

        self.files = FileList(root, on_change=self._on_files_changed)
        self.files.grid(row=3, column=0, sticky="nsew")
        self.files.tree.bind("<Double-1>", self._open_selected_transcript, add="+")
        self.files.tree.bind("<Button-3>", self._show_context_menu)
        self._build_context_menu()

        self._build_controls(root, row=4)
        self._build_visualizer(root, row=5)
        self._build_progress(root, row=6)
        self._build_log(root, toggle_row=7, log_row=8)
        self._build_footer(root, row=9)

    def _build_header(self, root: ttk.Frame, row: int) -> None:
        header = ttk.Frame(root, style="App.TFrame")
        header.grid(row=row, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        badge = tk.Canvas(header, width=42, height=42, highlightthickness=0,
                          background=theme.BG)
        badge.create_rectangle(0, 0, 42, 42, fill=theme.SURFACE_ALT, outline="")
        badge.create_oval(13, 8, 29, 26, fill=theme.ACCENT, outline="")
        badge.create_rectangle(19, 24, 23, 31, fill=theme.ACCENT, outline="")
        badge.create_rectangle(14, 31, 28, 33, fill=theme.ACCENT, outline="")
        badge.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))

        ttk.Label(header, text="H9 Voice Transcriber", style="H1.TLabel") \
            .grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Offline speech to text with Whisper large-v3",
                  style="Sub.TLabel").grid(row=1, column=1, sticky="w", pady=(1, 0))

        self.chips = ttk.Frame(header, style="App.TFrame")
        self.chips.grid(row=0, column=2, rowspan=2, sticky="e")

        ttk.Frame(root, style="App.TFrame", height=18) \
            .grid(row=row + 1, column=0, sticky="ew")

    def _build_list_toolbar(self, root: ttk.Frame, row: int) -> None:
        bar = ttk.Frame(root, style="App.TFrame")
        bar.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        bar.columnconfigure(0, weight=1)

        ttk.Label(bar, text="AUDIO QUEUE", style="Section.TLabel") \
            .grid(row=0, column=0, sticky="w")

        buttons = ttk.Frame(bar, style="App.TFrame")
        buttons.grid(row=0, column=1, sticky="e")
        self.up_to_date_toggle = self._small_button(
            buttons, "Show up to date", lambda: self.files.toggle_up_to_date())
        self.up_to_date_toggle.pack(side="left", padx=(0, 6))
        self._small_button(buttons, "Add audio...", self._add_files).pack(side="left", padx=(0, 6))
        self._small_button(buttons, "Refresh", self.files_refresh).pack(side="left", padx=(0, 6))
        self._small_button(buttons, "Open input folder",
                           lambda: _open(paths.INPUT_DIR)).pack(side="left")

    def files_refresh(self) -> None:
        self.files.refresh()

    def _build_controls(self, root: ttk.Frame, row: int) -> None:
        card = ttk.Frame(root, style="Card.TFrame", padding=(14, 12))
        card.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        card.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(card, text="Start transcription",
                                       style="Accent.TButton", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="w")

        self.stop_button = ttk.Button(card, text="Stop", style="Danger.TButton",
                                      command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(8, 0))

        # The settings sit on their own row: four of them beside the buttons
        # ran off the right edge on a 960-wide window.
        options = ttk.Frame(card, style="Card.TFrame")
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 2))

        ttk.Checkbutton(options, text="Redo files already transcribed",
                        style="Card.TCheckbutton",
                        variable=self._force).pack(side="right")
        ttk.Checkbutton(options, text="Timestamps",
                        style="Card.TCheckbutton",
                        variable=self._timestamps).pack(side="right", padx=(0, 14))

        self._option_label(options, "Quality").pack(side="left", padx=(0, 6))
        quality = ttk.Combobox(options, textvariable=self._quality, state="readonly",
                               width=10, values=list(QUALITY_PRESETS))
        quality.pack(side="left", padx=(0, 18))

        self._option_label(options, "Precision").pack(side="left", padx=(0, 6))
        precision = ttk.Combobox(options, textvariable=self._precision, state="readonly",
                                 width=16, values=list(PRECISIONS))
        precision.pack(side="left", padx=(0, 18))

        self._option_label(options, "Speakers").pack(side="left", padx=(0, 6))
        speakers = ttk.Combobox(options, textvariable=self._speakers, state="readonly",
                                width=9, values=list(SPEAKER_MODES))
        speakers.pack(side="left", padx=(0, 18))

        self._option_widgets = [quality, precision, speakers]

    def _build_visualizer(self, root: ttk.Frame, row: int) -> None:
        """The waveform panel. It is only gridded while a run is in progress."""
        self._visual_row = row
        self.visual_card = ttk.Frame(root, style="Card.TFrame", padding=(0, 8))
        self.visual_card.columnconfigure(0, weight=1)
        self.visual = Visualizer(self.visual_card)
        self.visual.grid(row=0, column=0, sticky="ew")

    def _build_progress(self, root: ttk.Frame, row: int) -> None:
        area = ttk.Frame(root, style="App.TFrame")
        area.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        area.columnconfigure(0, weight=1)

        self.progress = SmoothBar(area)
        self.progress.grid(row=0, column=0, sticky="ew")

        line = ttk.Frame(area, style="App.TFrame")
        line.grid(row=1, column=0, sticky="ew", pady=(9, 0))
        line.columnconfigure(1, weight=1)

        self.dot = PulseDot(line)
        self.dot.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.stage_label = ttk.Label(line, text="Idle", style="Status.TLabel")
        self.stage_label.grid(row=0, column=1, sticky="w")
        self.count_label = ttk.Label(line, text="", style="Muted.TLabel")
        self.count_label.grid(row=0, column=2, sticky="e")

    def _show_visualizer(self) -> None:
        if self._settle_job is not None:
            self.after_cancel(self._settle_job)
            self._settle_job = None
        self.visual_card.grid(row=self._visual_row, column=0, sticky="ew", pady=(12, 0))
        self.update_idletasks()
        self.visual.start()

    def _hide_visualizer(self) -> None:
        self._settle_job = None
        self.visual.stop()
        self.visual_card.grid_forget()

    def _build_log(self, root: ttk.Frame, toggle_row: int, log_row: int) -> None:
        toggle_bar = ttk.Frame(root, style="App.TFrame")
        toggle_bar.grid(row=toggle_row, column=0, sticky="ew", pady=(14, 6))
        toggle_bar.columnconfigure(1, weight=1)

        self.log_toggle = self._small_button(toggle_bar, "Show details", self._toggle_log)
        self.log_toggle.grid(row=0, column=0, sticky="w")
        self._small_button(toggle_bar, "Open log file",
                           lambda: _open(paths.ROOT / "transcripts.log")) \
            .grid(row=0, column=2, sticky="e")

        self.log_card = ttk.Frame(root, style="Card.TFrame")
        self.log_card.columnconfigure(0, weight=1)
        self.log_card.rowconfigure(0, weight=1)

        self.log = tk.Text(self.log_card, height=9, wrap="none", relief="flat",
                           background=theme.SURFACE, foreground=theme.MUTED,
                           insertbackground=theme.TEXT, font=(theme.MONO, 9),
                           padx=12, pady=10, state="disabled",
                           highlightthickness=0, borderwidth=0)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.log_card, orient="vertical", style="Vert.Vertical.TScrollbar",
                               command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.tag_configure("ok", foreground=theme.SUCCESS)
        self.log.tag_configure("bad", foreground=theme.DANGER)
        self.log.tag_configure("note", foreground=theme.ACCENT)

        self._log_row = log_row

    def _build_footer(self, root: ttk.Frame, row: int) -> None:
        footer = ttk.Frame(root, style="App.TFrame")
        footer.grid(row=row, column=0, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, text="Transcripts are written to  " + str(paths.OUTPUT_DIR),
                  style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Open output folder", style="Ghost.TButton",
                   command=lambda: _open(paths.OUTPUT_DIR)).grid(row=0, column=1, sticky="e")

    def _build_context_menu(self) -> None:
        self.menu = tk.Menu(self, tearoff=0, background=theme.SURFACE_ALT,
                            foreground=theme.TEXT, activebackground=theme.ACCENT,
                            activeforeground="#0f1117", borderwidth=0,
                            font=(theme.FONT, 9))
        self.menu.add_command(label="Open transcript", command=self._open_selected_transcript)
        self.menu.add_command(label="Show audio in Explorer", command=self._reveal_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Remove from input folder", command=self._remove_selected)

    # -- small widget helpers ---------------------------------------------
    def _small_button(self, master, text: str, command) -> ttk.Button:
        button = ttk.Button(master, text=text, style="Ghost.TButton", command=command)
        button.configure(padding=(11, 6))
        return button

    def _option_label(self, master, text: str) -> ttk.Label:
        return ttk.Label(master, text=text, background=theme.SURFACE,
                         foreground=theme.FAINT, font=(theme.FONT, 9))

    # ==================================================================
    # preflight chips
    # ==================================================================
    def _refresh_checks(self) -> None:
        """Redraw the whole chip strip so the order stays stable."""
        for child in self.chips.winfo_children():
            child.destroy()
        for check in preflight.quick_checks():
            self._add_chip(check)
        if self._gpu_check is not None:
            self._add_chip(self._gpu_check)

    def _set_gpu_chip(self, check: preflight.Check) -> None:
        self._gpu_check = check
        self._refresh_checks()

    def _add_chip(self, check: preflight.Check) -> None:
        colour = theme.SUCCESS if check.ok else theme.WARNING
        chip = tk.Frame(self.chips, background=theme.SURFACE)
        chip.chip_key = check.key
        tk.Label(chip, text="●", background=theme.SURFACE, foreground=colour,
                 font=(theme.FONT, 8)).pack(side="left", padx=(8, 4), pady=4)
        tk.Label(chip, text=check.label, background=theme.SURFACE,
                 foreground=theme.MUTED if check.ok else theme.TEXT,
                 font=(theme.FONT, 9)).pack(side="left", padx=(0, 10), pady=4)
        if check.detail:
            _tooltip(chip, check.detail)
        chip.pack(side="left", padx=(6, 0))

    # ==================================================================
    # actions
    # ==================================================================
    def _add_files(self) -> None:
        patterns = " ".join("*" + suffix for suffix in paths.AUDIO_SUFFIXES)
        chosen = filedialog.askopenfilenames(
            title="Choose audio or video files",
            filetypes=[("Audio and video", patterns), ("All files", "*.*")],
        )
        if not chosen:
            return
        paths.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        # During a run the status line belongs to the run.
        if not self.runner.is_running():
            self._set_stage("Copying " + str(len(chosen)) + " file(s) into input...")

        def work() -> None:
            failures: list[str] = []
            for item in chosen:
                source = Path(item)
                try:
                    if source.parent.resolve() != paths.INPUT_DIR.resolve():
                        shutil.copy2(source, paths.INPUT_DIR / source.name)
                except OSError as exc:
                    failures.append(source.name + ": " + str(exc))
            self._post(self._after_add, failures)

        threading.Thread(target=work, daemon=True).start()

    def _after_add(self, failures: list[str]) -> None:
        self.files.refresh()
        if failures:
            messagebox.showerror("Could not copy every file", "\n".join(failures), parent=self)
        if self.runner.is_running():
            return
        self._set_stage("Some files could not be copied" if failures else "Idle")

    def _start(self) -> None:
        if self.runner.is_running():
            return
        checks = preflight.quick_checks()
        problem = preflight.blocking_problem(checks)
        if problem:
            messagebox.showerror("Not ready yet", problem, parent=self)
            return
        self.files.refresh()
        if self.files.is_empty():
            messagebox.showinfo(
                "Nothing to transcribe",
                "Put audio files in\n" + str(paths.INPUT_DIR) + '\n\nor use "Add audio...".',
                parent=self)
            return

        force = self._force.get()
        work = self.files.begin_run(force)
        known = [s for s in map(self.files.seconds, work) if s]
        fallback = sum(known) / len(known) if known else UNKNOWN_FILE_SECONDS
        self._weights = {name: self.files.seconds(name) or fallback for name in work}
        self._uncounted = set(work)
        self._done_weight = 0.0
        self._total_weight = sum(self._weights.values())
        self._eta_clock = None
        self._eta_text = ""
        self._segment = (0, 0)
        self._file_fraction = 0.0
        self._current_file = ""
        self._download_mode = False
        self.progress.reset()

        speakers = SPEAKER_MODES.get(self._speakers.get())
        options = Options(
            beam_size=QUALITY_PRESETS[self._quality.get()],
            compute_type=PRECISIONS[self._precision.get()],
            vad=True,
            force=force,
            diarize=speakers is not None,
            speakers=speakers or 0,
            timestamps=self._timestamps.get(),
        )
        try:
            self.runner.start(options)
        except (OSError, RuntimeError) as exc:
            self.files.end_run()
            self.files.refresh()
            messagebox.showerror("Could not start", str(exc), parent=self)
            return

        self._append_log("-- starting transcription --", "note")
        self._set_running(True)
        self._show_visualizer()
        self.progress.start()
        self.dot.start()
        if paths.model_is_ready():
            self._set_stage("Starting...")
        else:
            self._set_stage("Downloading the model (one time, ~3 GB)...")

    def _stop(self) -> None:
        if not self.runner.is_running():
            return
        self.stop_button.configure(state="disabled")
        self._set_stage("Stopping...")
        self.runner.stop()

    def _set_running(self, running: bool) -> None:
        self.stop_button.configure(state="normal" if running else "disabled")
        for widget in self._option_widgets:
            widget.configure(state="disabled" if running else "readonly")
        if running:
            self.start_button.configure(state="disabled")
        else:
            self._update_start_button()

    def _update_start_button(self) -> None:
        """Say what Start will do: how many files, how much audio."""
        if self.runner.is_running():
            return
        if self.files.is_empty():
            self.start_button.configure(text="Start transcription", state="normal")
            return
        work = self.files.to_do(self._force.get())
        if not work:
            self.start_button.configure(text="Nothing new to transcribe", state="disabled")
            return
        text = "Transcribe %d file%s" % (len(work), "" if len(work) == 1 else "s")
        lengths = [self.files.seconds(name) for name in work]
        if all(lengths):
            text += "  (" + _span(sum(lengths)) + ")"
        self.start_button.configure(text=text, state="normal")

    # ==================================================================
    # event pump
    # ==================================================================
    def _post(self, callback, *args) -> None:
        """Ask the main loop to run `callback(*args)` on its next tick."""
        self._ui_queue.put((callback, args))

    def _drain(self) -> None:
        while True:
            try:
                callback, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
        for event in self.runner.poll():
            self._handle(event)
        self.after(80, self._drain)

    def _handle(self, event: Event) -> None:
        if event.kind == "log":
            tag = ""
            if event.text.startswith("ERROR") or event.text.startswith("WARNING"):
                tag = "bad"
            elif event.text.startswith("DONE") or event.text.startswith("All files"):
                tag = "ok"
            self._append_log(event.text, tag)

        elif event.kind == "file":
            self._download_mode = False
            self.files.set_status(event.name, event.status, event.detail)
            if event.status == "working":
                if event.name not in self._weights:
                    # The transcriber judged this file differently from the
                    # window; count it now rather than let the bar overshoot.
                    weight = self.files.seconds(event.name) or UNKNOWN_FILE_SECONDS
                    self._weights[event.name] = weight
                    self._uncounted.add(event.name)
                    self._total_weight += weight
                self._segment = (0, 0)
                self._file_fraction = 0.0
                self._current_file = event.name
                self.visual.set_file(paths.INPUT_DIR / event.name)
                self._set_stage(self._working_stage())
            elif event.status in ("done", "skipped", "error"):
                if event.name in self._uncounted:
                    self._uncounted.discard(event.name)
                    self._done_weight += self._weights[event.name]
                self._segment = (0, 0)
                self._file_fraction = 0.0
                self._current_file = ""
                self._update_progress()
            if event.status == "error":
                self._set_stage("Failed on " + event.name)

        elif event.kind == "stage":
            percent = event.data.get("download")
            if percent is not None:
                self._download_mode = True
                self.progress.set_fraction(percent / 100.0)
                self.visual.set_position(percent / 100.0)
                self._set_stage(event.text)
                return
            self._download_mode = False
            if "segment" in event.data:
                self._segment = (event.data["segment"], event.data["segments"])
                self._update_progress()
            if self._current_file and ("segment" in event.data
                                       or event.data.get("transcribing")):
                self._set_stage(self._working_stage())
            else:
                self._set_stage(event.text)

        elif event.kind == "progress":
            self._download_mode = False
            self._file_fraction = event.data.get("fraction", 0.0)
            self.visual.set_position(self._file_fraction)
            if self._current_file:
                self.files.set_progress_text(
                    self._current_file,
                    "Transcribing  %d%%" % round(self._file_fraction * 100))
            self._update_progress()

        elif event.kind == "exit":
            self._finish(event.data.get("code", 0), event.data.get("stopped", False))

    def _finish(self, code: int, stopped: bool) -> None:
        self._eta_text = ""
        self.files.end_run()
        self.files.refresh()
        self._set_running(False)
        self._refresh_checks()

        # Let the playhead run out before the panel goes away.
        self.visual.settle()
        self._settle_job = self.after(2200, self._hide_visualizer)
        self.progress.stop()
        if stopped:
            resting = theme.WARNING
        elif code == 0:
            resting = theme.SUCCESS
        else:
            resting = theme.DANGER
        self.dot.stop(resting)

        if stopped:
            self._set_stage("Stopped")
            self._append_log("-- stopped by user --", "bad")
        elif code == 0:
            self.progress.set_fraction(1.0)
            self._set_stage("Finished - transcripts are in the output folder")
            self._append_log("-- finished --", "ok")
        else:
            self._set_stage("Failed (exit code " + str(code) + ") - open the details below")
            self._append_log("-- failed with exit code " + str(code) + " --", "bad")
            if not self._log_visible.get():
                self._toggle_log()

    def _update_progress(self) -> None:
        """Whole-run progress, in seconds of audio: finished files plus how far
        into the current one."""
        if self._download_mode:
            return
        processed = self._done_weight
        if self._current_file in self._uncounted:
            processed += self._weights[self._current_file] * self._file_fraction
        self.progress.set_fraction(min(1.0, processed / max(self._total_weight, 1.0)))
        self._update_eta(processed)

    def _update_eta(self, processed: float) -> None:
        """Time left at the pace seen so far. The clock starts on the first
        real progress, so the model load does not count as slowness."""
        if not self.runner.is_running():
            return
        now = time.monotonic()
        if self._eta_clock is None:
            self._eta_clock = (now, processed)
            return
        since, baseline = self._eta_clock
        elapsed, gained = now - since, processed - baseline
        if elapsed < ETA_WARMUP_SECONDS or gained <= 0:
            return
        left = (self._total_weight - processed) * elapsed / gained
        self._eta_text = _time_left(left)
        self._render_stage()

    def _working_stage(self) -> str:
        text = "Transcribing " + self._current_file
        index, parts = self._segment
        if parts > 1:
            text += f"  -  part {index} of {parts}"
        return text

    def _on_files_changed(self) -> None:
        counts = self.files.counts()
        resting = counts["skipped"]
        if not resting:
            self.up_to_date_toggle.configure(text="Show up to date", state="disabled")
        elif self.files.show_up_to_date:
            self.up_to_date_toggle.configure(text="Hide up to date", state="normal")
        else:
            self.up_to_date_toggle.configure(text=f"Show up to date ({resting})",
                                             state="normal")
        self._update_start_button()

        if counts["total"] == 0:
            self.count_label.configure(text="")
            return
        parts = [str(counts["total"]) + " file(s)"]
        if counts["done"]:
            parts.append(str(counts["done"]) + " done")
        if counts["skipped"]:
            parts.append(str(counts["skipped"]) + " up to date")
        if counts["error"]:
            parts.append(str(counts["error"]) + " failed")
        if counts["later"]:
            parts.append(str(counts["later"]) + " next run")
        self.count_label.configure(text="   .   ".join(parts))

    # ==================================================================
    # log panel
    # ==================================================================
    def _weigh_rows(self, log_visible: bool) -> None:
        """The queue owns the spare height until the log panel is open."""
        self._grid_root.rowconfigure(3, weight=3 if log_visible else 1)
        self._grid_root.rowconfigure(8, weight=2 if log_visible else 0)

    def _toggle_log(self) -> None:
        showing = not self._log_visible.get()
        self._log_visible.set(showing)
        if showing:
            self.log_card.grid(row=self._log_row, column=0, sticky="nsew")
            self.log_toggle.configure(text="Hide details")
        else:
            self.log_card.grid_forget()
            self.log_toggle.configure(text="Show details")
        self._weigh_rows(showing)

    def _append_log(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_LINE_CAP:
            self.log.delete("1.0", str(lines - LOG_LINE_CAP) + ".0")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ==================================================================
    # tree interactions
    # ==================================================================
    def _show_context_menu(self, event) -> None:
        row = self.files.tree.identify_row(event.y)
        if not row or row.startswith("__"):
            return
        if row not in self.files.tree.selection():
            self.files.tree.selection_set(row)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _open_selected_transcript(self, _event=None) -> None:
        for source in self.files.selected_paths():
            transcript = paths.transcript_for(source)
            if transcript.exists():
                _open(transcript)
            else:
                self._set_stage("No transcript yet for " + source.name)

    def _reveal_selected(self) -> None:
        for source in self.files.selected_paths():
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(source)])
            else:
                _open(source.parent)
            break

    def _remove_selected(self) -> None:
        selected = self.files.selected_paths()
        if not selected:
            return
        names = "\n".join(path.name for path in selected)
        question = ("Delete these file(s) from the input folder?\n\n" + names +
                    "\n\nTranscripts already in output are kept.")
        if not messagebox.askyesno("Remove from input folder", question, parent=self):
            return
        for path in selected:
            try:
                path.unlink()
            except OSError as exc:
                messagebox.showerror("Could not delete", path.name + ": " + str(exc),
                                     parent=self)
        self.files.refresh()

    # ==================================================================
    # window plumbing
    # ==================================================================
    def _set_stage(self, text: str) -> None:
        self._stage_text = text
        self._render_stage()

    def _render_stage(self) -> None:
        text = self._stage_text
        if self._eta_text and self.runner.is_running():
            text += "   ·   " + self._eta_text
        self.stage_label.configure(text=text)

    def _apply_dpi_scaling(self) -> float:
        """Match Tk's point-to-pixel ratio to the screen. Returns the factor."""
        if os.name != "nt":
            return 1.0
        try:
            import ctypes
            dpi = float(ctypes.windll.user32.GetDpiForSystem())
        except (AttributeError, OSError, ValueError):
            return 1.0
        if not dpi or abs(dpi - 96.0) < 1:
            return 1.0
        self.tk.call("tk", "scaling", dpi / 72.0)
        return dpi / 96.0

    def _set_icon(self) -> None:
        icon = paths.asset("icon.ico")
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

    def _on_close(self) -> None:
        if self.runner.is_running():
            if not messagebox.askyesno(
                    "Transcription running",
                    "A transcription is still running. Stop it and close?",
                    parent=self):
                return
            self.runner.stop()
        self.destroy()


def _open(target: Path) -> None:
    """Open a file or folder with the system default handler."""
    target = Path(target)
    if not target.exists():
        if target.suffix:
            return
        target.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def _span(seconds: float) -> str:
    """Audio length for the Start button: '45 min', '1 h 46 min'."""
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _time_left(seconds: float) -> str:
    if seconds < 60:
        return "under a minute left"
    return "about " + _span(seconds) + " left"


def _tooltip(widget, text: str) -> None:
    """A minimal hover tooltip - enough for the preflight chips."""
    state = {"window": None}

    def show(_event=None) -> None:
        if state["window"] is not None:
            return
        window = tk.Toplevel(widget)
        window.wm_overrideredirect(True)
        window.configure(background=theme.BORDER)
        tk.Label(window, text=text, background=theme.SURFACE_ALT, foreground=theme.TEXT,
                 font=(theme.FONT, 9), padx=10, pady=6, justify="left",
                 wraplength=320).pack(padx=1, pady=1)
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 6
        window.wm_geometry("+" + str(x) + "+" + str(y))
        state["window"] = window

    def hide(_event=None) -> None:
        window = state["window"]
        if window is not None:
            window.destroy()
            state["window"] = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)
    for child in widget.winfo_children():
        child.bind("<Enter>", show)
        child.bind("<Leave>", hide)


def main() -> int:
    enable_dpi_awareness()
    App().mainloop()
    return 0
