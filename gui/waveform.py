"""Pulls a coarse loudness envelope out of an audio file with ffmpeg.

The visualiser draws roughly two hundred bars, so there is no point decoding at
full rate: 800 samples per second is more than enough shape and keeps a
two-hour recording under two million samples. Everything here is standard
library, because the frozen .exe does not carry numpy.
"""

from __future__ import annotations

import array
import math
import os
import subprocess
import threading
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SAMPLE_RATE = 800
FULL_SCALE = 32768.0


def extract(path: Path, buckets: int = 200, timeout: int = 300) -> list[float] | None:
    """Return `buckets` peak values in 0..1, or None if ffmpeg could not read the file."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
            capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None

    raw = result.stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % samples.itemsize)])
    if len(samples) < buckets:
        return None

    step = len(samples) / buckets
    levels: list[float] = []
    for index in range(buckets):
        low = int(index * step)
        high = max(low + 1, int((index + 1) * step))
        chunk = samples[low:high]
        # max() and min() on an array slice run in C; abs() per sample would not.
        peak = max(max(chunk), -min(chunk)) / FULL_SCALE
        # Peak alone barely moves across speech - every bucket contains some
        # loud syllable. RMS is what makes pauses and quiet passages visible.
        energy = math.sqrt(sum(value * value for value in chunk) / len(chunk)) / FULL_SCALE
        levels.append(0.35 * peak + 0.65 * energy)

    return _normalise(levels)


def _normalise(levels: list[float]) -> list[float]:
    """Stretch the middle of the range so the shape of the talk is readable."""
    ordered = sorted(levels)
    floor = ordered[len(ordered) // 20]                     # 5th percentile
    ceiling = ordered[-max(1, len(ordered) // 40)]          # ~97th percentile
    span = max(ceiling - floor, 1e-6)
    return [0.06 + 0.94 * max(0.0, min(1.0, (level - floor) / span)) ** 0.75
            for level in levels]


class Loader:
    """Runs `extract` on a worker thread.

    The visualiser checks `done` on its animation tick rather than being called
    back, so no Tk call ever happens off the main loop.
    """

    def __init__(self, path: Path, buckets: int) -> None:
        self.path = path
        self.result: list[float] | None = None
        self.done = False
        self._thread = threading.Thread(target=self._work, args=(buckets,), daemon=True)
        self._thread.start()

    def _work(self, buckets: int) -> None:
        try:
            self.result = extract(self.path, buckets)
        finally:
            self.done = True
