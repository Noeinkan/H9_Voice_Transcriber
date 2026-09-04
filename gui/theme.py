"""Colour palette and ttk styling for the H9 Transcriber window."""

from __future__ import annotations

from tkinter import ttk

# --- palette -------------------------------------------------------------
BG = "#12141a"
SURFACE = "#191c24"
SURFACE_ALT = "#212633"
BORDER = "#2c3242"
TEXT = "#e7eaf2"
MUTED = "#8b93a7"
FAINT = "#5d6479"
ACCENT = "#6c8cff"
ACCENT_HOVER = "#87a0ff"
ACCENT_PRESS = "#5878e8"
SUCCESS = "#3ecf8e"
WARNING = "#f0a34a"
DANGER = "#ff6b6b"

GLOW = "#aebeff"
WAVE_LOW = "#232838"
WAVE_HIGH = "#39415c"

FONT = "Segoe UI"
MONO = "Consolas"


def rgb(colour: str) -> tuple[int, int, int]:
    value = colour.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def mix(first: str, second: str, amount: float) -> str:
    """Blend two #rrggbb colours; amount 0 gives `first`, 1 gives `second`."""
    amount = max(0.0, min(1.0, amount))
    start, end = rgb(first), rgb(second)
    return "#%02x%02x%02x" % tuple(
        round(start[i] + (end[i] - start[i]) * amount) for i in range(3)
    )


def ramp(first: str, second: str, steps: int) -> list[str]:
    """A precomputed gradient - animation picks an index instead of blending."""
    if steps < 2:
        return [first]
    return [mix(first, second, index / (steps - 1)) for index in range(steps)]


def apply_theme(root) -> ttk.Style:
    """Install the dark theme on `root` and return the configured Style."""
    root.configure(background=BG)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("App.TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Divider.TFrame", background=BORDER)

    style.configure("H1.TLabel", background=BG, foreground=TEXT,
                    font=(FONT, 17, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUTED,
                    font=(FONT, 9))
    style.configure("Body.TLabel", background=BG, foreground=TEXT,
                    font=(FONT, 10))
    style.configure("Muted.TLabel", background=BG, foreground=MUTED,
                    font=(FONT, 9))
    style.configure("Section.TLabel", background=BG, foreground=FAINT,
                    font=(FONT, 8, "bold"))
    style.configure("Status.TLabel", background=BG, foreground=TEXT,
                    font=(FONT, 10))

    _button(style, "Accent.TButton", ACCENT, "#0f1117", ACCENT_HOVER, ACCENT_PRESS)
    _button(style, "Ghost.TButton", SURFACE_ALT, TEXT, "#2b3142", "#191d28")
    _button(style, "Danger.TButton", SURFACE_ALT, DANGER, "#3a2530", "#2a1c24")

    style.configure("Bar.Horizontal.TProgressbar", troughcolor=SURFACE_ALT,
                    background=ACCENT, bordercolor=SURFACE_ALT,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)

    style.configure("Files.Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, bordercolor=SURFACE, borderwidth=0,
                    rowheight=28, font=(FONT, 10))
    style.configure("Files.Treeview.Heading", background=BG, foreground=FAINT,
                    relief="flat", borderwidth=0, font=(FONT, 8, "bold"),
                    padding=(10, 6))
    style.map("Files.Treeview.Heading", background=[("active", BG)])
    style.map("Files.Treeview",
              background=[("selected", SURFACE_ALT)],
              foreground=[("selected", TEXT)])
    style.layout("Files.Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"}),
    ])

    for check_style, surface in (("TCheckbutton", BG), ("Card.TCheckbutton", SURFACE)):
        style.configure(check_style, background=surface, foreground=MUTED,
                        font=(FONT, 9), focuscolor=surface, borderwidth=0,
                        indicatorbackground=SURFACE_ALT, indicatorforeground=ACCENT,
                        indicatormargin=(0, 0, 8, 0), bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, padding=(2, 3))
        style.map(check_style,
                  background=[("active", surface)],
                  foreground=[("active", TEXT)],
                  indicatorbackground=[("active", BORDER), ("selected", SURFACE_ALT)],
                  indicatorforeground=[("selected", ACCENT)])

    style.configure("TCombobox", fieldbackground=SURFACE_ALT, background=SURFACE_ALT,
                    foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT,
                    selectbackground=SURFACE_ALT, selectforeground=TEXT,
                    padding=(8, 4))
    style.map("TCombobox",
              fieldbackground=[("readonly", SURFACE_ALT)],
              foreground=[("disabled", FAINT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#0f1117")
    root.option_add("*TCombobox*Listbox.font", (FONT, 9))

    style.configure("Vert.Vertical.TScrollbar", background=SURFACE_ALT, troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED, darkcolor=SURFACE_ALT,
                    lightcolor=SURFACE_ALT, arrowsize=12)
    style.map("Vert.Vertical.TScrollbar", background=[("active", BORDER)])

    return style


def _button(style: ttk.Style, name: str, bg: str, fg: str, hover: str, press: str) -> None:
    style.configure(name, background=bg, foreground=fg, font=(FONT, 10),
                    relief="flat", borderwidth=0, focuscolor=bg,
                    padding=(16, 9), anchor="center")
    style.map(name,
              background=[("disabled", SURFACE_ALT), ("pressed", press), ("active", hover)],
              foreground=[("disabled", FAINT)])
