"""Top-level entry point for the desktop window.

Used by the launcher and by PyInstaller, which cannot start a package that
uses relative imports (`python -m gui`) as its entry script.
"""

from gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
