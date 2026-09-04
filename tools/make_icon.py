"""Generate assets/icon.ico for the desktop app.

Run once (or after changing the palette):

    venv\\Scripts\\python.exe tools\\make_icon.py

Needs Pillow, which the project virtual environment already has. The result is
committed so neither the GUI nor the frozen .exe needs Pillow at run time.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "assets" / "icon.ico"

SIZE = 1024                      # drawn large, then downsampled
TOP = (0x7C, 0x8C, 0xFF)         # gradient start
BOTTOM = (0x8A, 0x5C, 0xF6)      # gradient end
GLYPH = (0xFF, 0xFF, 0xFF)
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def gradient_square(size: int) -> Image.Image:
    image = Image.new("RGB", (1, size))
    pixels = image.load()
    for y in range(size):
        ratio = y / (size - 1)
        pixels[0, y] = tuple(
            round(TOP[channel] + (BOTTOM[channel] - TOP[channel]) * ratio)
            for channel in range(3)
        )
    return image.resize((size, size))


def rounded_mask(size: int, radius_ratio: float = 0.23) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1),
                           radius=int(size * radius_ratio), fill=255)
    return mask


def microphone(size: int) -> Image.Image:
    """A flat microphone: capsule, arc, stem and base."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    unit = size / 100.0

    def box(x0, y0, x1, y1):
        return (x0 * unit, y0 * unit, x1 * unit, y1 * unit)

    draw.rounded_rectangle(box(40, 20, 60, 58), radius=10 * unit, fill=GLYPH)
    draw.arc(box(29, 38, 71, 74), start=0, end=180, fill=GLYPH, width=int(6 * unit))
    draw.rounded_rectangle(box(47.5, 68, 52.5, 80), radius=2.5 * unit, fill=GLYPH)
    draw.rounded_rectangle(box(35, 78, 65, 84), radius=3 * unit, fill=GLYPH)
    return layer


def build() -> Path:
    base = gradient_square(SIZE).convert("RGBA")
    base.putalpha(rounded_mask(SIZE))
    base.alpha_composite(microphone(SIZE))

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    base.save(TARGET, format="ICO", sizes=ICO_SIZES)
    base.resize((512, 512), Image.LANCZOS).save(TARGET.with_suffix(".png"))
    return TARGET


if __name__ == "__main__":
    print("wrote", build())
