"""Two small canvas widgets that move while a run is in progress.

`SmoothBar` replaces the ttk progress bar: it eases towards its target instead
of jumping, and a highlight sweeps along the filled part so the bar still reads
as alive during the long stretch where one file is being decoded.

`PulseDot` is the breathing dot beside the status line - the cheapest possible
signal that the app is working rather than stuck.
"""

from __future__ import annotations

import math
import tkinter as tk

from . import theme

BAR_HEIGHT = 10
BAR_FRAME_MS = 45
SHIMMER_BANDS = 20
SHIMMER_WIDTH = 150.0           # pixels covered by one pass of the highlight
BAR_EASING = 0.16

DOT_SIZE = 16
DOT_FRAME_MS = 60


class SmoothBar(tk.Canvas):
    def __init__(self, master, background: str = theme.BG) -> None:
        super().__init__(master, height=BAR_HEIGHT, background=background,
                         highlightthickness=0, borderwidth=0)
        self._ramp = theme.ramp(theme.ACCENT, theme.GLOW, 10)
        self._track = self.create_rectangle(0, 0, 0, 0, fill=theme.SURFACE_ALT, outline="")
        self._fill = self.create_rectangle(0, 0, 0, 0, fill=theme.ACCENT, outline="")
        self._bands = [self.create_rectangle(0, 0, 0, 0, fill=theme.ACCENT, outline="",
                                             state="hidden")
                       for _ in range(SHIMMER_BANDS)]
        self._fraction = 0.0
        self._target = 0.0
        self._phase = 0
        self._active = False
        self.bind("<Configure>", lambda _event: self._draw())

    # -- public ------------------------------------------------------------
    def set_fraction(self, value: float) -> None:
        self._target = max(0.0, min(1.0, value))
        if not self._active:
            self._fraction = self._target
            self._draw()

    def reset(self) -> None:
        self._fraction = self._target = 0.0
        self._draw()

    def start(self) -> None:
        self._active = True
        self._tick()

    def stop(self) -> None:
        self._active = False
        for band in self._bands:
            self.itemconfigure(band, state="hidden")
        self._fraction = self._target
        self._draw()

    # -- animation ---------------------------------------------------------
    def _tick(self) -> None:
        if not self._active:
            return
        self._phase += 1
        self._fraction += (self._target - self._fraction) * BAR_EASING
        self._draw()
        self.after(BAR_FRAME_MS, self._tick)

    def _draw(self) -> None:
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        filled = width * self._fraction

        self.coords(self._track, 0, 0, width, height)
        self.coords(self._fill, 0, 0, filled, height)

        if not self._active or filled < 4:
            return

        # One highlight travelling left to right, drawn as a short gradient.
        head = (self._phase * 7.0) % (filled + SHIMMER_WIDTH) - SHIMMER_WIDTH / 2
        band_width = SHIMMER_WIDTH / SHIMMER_BANDS
        for index, band in enumerate(self._bands):
            x0 = head + index * band_width
            x1 = min(x0 + band_width + 1, filled)
            if x1 <= 0 or x0 >= filled:
                self.itemconfigure(band, state="hidden")
                continue
            # Brightest in the middle of the pass, fading at both ends.
            level = math.sin(math.pi * (index + 0.5) / SHIMMER_BANDS)
            self.itemconfigure(band, state="normal",
                               fill=self._ramp[int(level * (len(self._ramp) - 1))])
            self.coords(band, max(x0, 0.0), 0, x1, height)


class PulseDot(tk.Canvas):
    def __init__(self, master, background: str = theme.BG) -> None:
        super().__init__(master, width=DOT_SIZE, height=DOT_SIZE,
                         background=background, highlightthickness=0, borderwidth=0)
        self._background = background
        self._dot = self.create_oval(0, 0, 0, 0, fill=theme.FAINT, outline="")
        self._phase = 0
        self._active = False
        self._resting = theme.FAINT
        self._draw(0.5, self._resting)

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._tick()

    def stop(self, colour: str = theme.FAINT) -> None:
        self._active = False
        self._resting = colour
        self._draw(0.55, colour)

    def _tick(self) -> None:
        if not self._active:
            return
        self._phase += 1
        wave = 0.5 + 0.5 * math.sin(self._phase * 0.18)
        self._draw(0.42 + 0.35 * wave, theme.mix(theme.ACCENT, theme.GLOW, wave))
        self.after(DOT_FRAME_MS, self._tick)

    def _draw(self, scale: float, colour: str) -> None:
        centre = DOT_SIZE / 2
        radius = centre * max(0.15, min(1.0, scale))
        self.coords(self._dot, centre - radius, centre - radius,
                    centre + radius, centre + radius)
        self.itemconfigure(self._dot, fill=colour)
