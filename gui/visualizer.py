"""The waveform panel that appears while a recording is being transcribed.

It shows the real shape of the file: ffmpeg decodes a loudness envelope in the
background, and the part Whisper has already been through is lit up behind a
travelling playhead. Until the envelope arrives - and if ffmpeg cannot read the
file at all - the same bars run as a synthetic equaliser, so the panel is never
a dead rectangle.

Only one Tk item exists per bar. Each frame moves and recolours them; nothing
is created or deleted, and a colour is only pushed when its quantised index
actually changes, which keeps a full-width panel at about 20 fps for free.
"""

from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path

from . import theme, waveform

BARS = 132
FRAME_MS = 50
BAR_GAP = 3
PANEL_HEIGHT = 96

PLAYED_STEPS = 14
UPCOMING_STEPS = 8
LOADING_STEPS = 10
MORPH_PER_FRAME = 0.05          # synthetic -> real envelope, about a second
POSITION_EASING = 0.10          # how fast the playhead chases the real position


class Visualizer(tk.Canvas):
    def __init__(self, master) -> None:
        super().__init__(master, height=PANEL_HEIGHT, background=theme.SURFACE,
                         highlightthickness=0, borderwidth=0)
        self._played = theme.ramp(theme.ACCENT, theme.GLOW, PLAYED_STEPS)
        self._upcoming = theme.ramp(theme.WAVE_LOW, theme.WAVE_HIGH, UPCOMING_STEPS)
        # Used while ffmpeg is still reading the envelope: a scanning wave, so
        # the panel says "working on it" rather than sitting dark.
        self._loading = theme.ramp(theme.mix(theme.SURFACE, theme.ACCENT, 0.45),
                                   theme.GLOW, LOADING_STEPS)

        self._bars: list[int] = []
        self._colours: list[str] = []
        self._spans: list[tuple[float, float]] = []
        self._width = 1
        self._height = PANEL_HEIGHT
        self._baseline = 0
        self._playhead = 0
        self._glow: list[int] = []

        self._peaks: list[float] | None = None
        self._loader: waveform.Loader | None = None
        self._morph = 0.0
        self._phase = 0
        self._position = 0.0
        self._target = 0.0
        self._active = False
        self._settling = False

        self.bind("<Configure>", lambda _event: self._layout())

    # ==================================================================
    # public API
    # ==================================================================
    def start(self) -> None:
        self._active = True
        self._settling = False
        self._phase = 0
        self._position = self._target = 0.0
        self._layout()
        self._tick()

    def set_file(self, path: Path | None) -> None:
        """Point at the recording now being transcribed and reload its envelope."""
        self._position = self._target = 0.0
        self._peaks = None
        self._morph = 0.0
        self._loader = None
        if path is not None and path.is_file():
            self._loader = waveform.Loader(path, BARS)

    def set_position(self, fraction: float) -> None:
        self._target = max(0.0, min(1.0, fraction))

    def settle(self) -> None:
        """Finish: run the playhead to the end and calm the shimmer down."""
        self._target = 1.0
        self._settling = True

    def stop(self) -> None:
        self._active = False

    # ==================================================================
    # geometry
    # ==================================================================
    def _layout(self) -> None:
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        if width <= 1:
            return

        self.delete("all")
        self._bars = []
        self._colours = []
        self._spans = []
        self._width, self._height = width, height
        self._baseline = height // 2

        span = (width - 24) / BARS
        bar_width = max(2.0, span - BAR_GAP)
        for index in range(BARS):
            x0 = 12 + index * span
            self._spans.append((x0, x0 + bar_width))
            self._bars.append(self.create_rectangle(
                x0, self._baseline - 1, x0 + bar_width, self._baseline + 1,
                fill=self._upcoming[0], outline=""))
            self._colours.append(self._upcoming[0])

        # Three lines of decreasing brightness fake a soft glow; Tk has no alpha.
        self._glow = [
            self.create_line(0, 0, 0, height, fill=theme.mix(theme.SURFACE, theme.GLOW, 0.25), width=7),
            self.create_line(0, 0, 0, height, fill=theme.mix(theme.SURFACE, theme.GLOW, 0.55), width=3),
        ]
        self._playhead = self.create_line(0, 0, 0, height, fill=theme.GLOW, width=1)

    # ==================================================================
    # animation
    # ==================================================================
    def _tick(self) -> None:
        if not self._active:
            return
        self._phase += 1
        self._collect_envelope()
        self._position += (self._target - self._position) * POSITION_EASING
        if self._bars:
            self._draw()
        self.after(FRAME_MS, self._tick)

    def _collect_envelope(self) -> None:
        if self._loader is not None and self._loader.done:
            self._peaks = self._loader.result
            self._loader = None
        if self._peaks is not None and self._morph < 1.0:
            self._morph = min(1.0, self._morph + MORPH_PER_FRAME)

    def _draw(self) -> None:
        limit = self._height * 0.44
        baseline = self._baseline
        phase = self._phase
        edge = self._position * BARS
        calm = 0.35 if self._settling else 1.0
        loading = self._peaks is None

        for index, item in enumerate(self._bars):
            amplitude = self._amplitude(index, phase)

            # Bars right at the playhead breathe, so the eye follows the front.
            distance = abs(index - edge)
            near = math.exp(-(distance * distance) / 42.0)
            amplitude *= 1.0 + 0.45 * near * calm * math.sin(phase * 0.42 + index * 0.7)

            half = max(1.0, min(limit, amplitude * limit))
            x0, x1 = self._spans[index]
            self.coords(item, x0, baseline - half, x1, baseline + half)

            colour = self._colour(index, edge, near, phase, calm, loading)
            if colour != self._colours[index]:
                self.itemconfigure(item, fill=colour)
                self._colours[index] = colour

        x = 12 + (self._width - 24) * self._position
        for item in self._glow + [self._playhead]:
            self.itemconfigure(item, state="hidden" if loading else "normal")
        for item in self._glow:
            self.coords(item, x, 0, x, self._height)
        self.coords(self._playhead, x, 0, x, self._height)

    def _amplitude(self, index: int, phase: int) -> float:
        synthetic = (0.46
                     + 0.26 * math.sin(index * 0.35 + phase * 0.16)
                     + 0.18 * math.sin(index * 0.11 - phase * 0.09)
                     + 0.12 * math.sin(index * 0.71 + phase * 0.23))
        if self._peaks is None or self._morph <= 0.0:
            return max(0.10, synthetic)
        real = self._peaks[index] if index < len(self._peaks) else 0.05
        return max(0.04, synthetic + (real - synthetic) * self._morph)

    def _colour(self, index: int, edge: float, near: float, phase: int,
                calm: float, loading: bool) -> str:
        if loading:
            wave = 0.5 + 0.5 * math.sin(phase * 0.20 - index * 0.20)
            level = 0.18 + 0.82 * wave ** 1.4
            return self._loading[min(LOADING_STEPS - 1, int(level * (LOADING_STEPS - 1)))]
        if index <= edge:
            sweep = 0.5 + 0.5 * math.sin(phase * 0.17 - index * 0.22)
            level = 0.25 + 0.45 * sweep * calm + 0.75 * near
            return self._played[min(PLAYED_STEPS - 1, int(level * (PLAYED_STEPS - 1)))]
        level = 0.15 + 0.85 * near
        return self._upcoming[min(UPCOMING_STEPS - 1, int(level * (UPCOMING_STEPS - 1)))]
