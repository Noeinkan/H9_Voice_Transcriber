"""Run a command, streaming its output to console AND to a log file in real time.

Exits with the spawned command's exit code.

Usage:
    python run_with_log.py <log_file> -- <command> [args...]

Used by run.bat so that long-running pip / python steps show progress live
while also being captured to a log file with the right exit code.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if "--" not in args:
        print("usage: run_with_log.py <log_file> -- <command> [args...]", file=sys.stderr)
        return 2
    sep = args.index("--")
    log_path = Path(args[0])
    cmd = args[sep + 1:]

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )

    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        log_handle.write(line)
        log_handle.flush()

    return_code = process.wait()
    log_handle.close()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
