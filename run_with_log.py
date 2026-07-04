"""Run a command, streaming its output to console AND to a log file in real time.

Exits with the spawned command's exit code.

Usage:
    python run_with_log.py <log_file> -- "<command string>"

The command is passed as a single string and split via shlex so that
arguments with spaces (URLs, quoted values, etc.) survive intact.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if "--" not in args:
        print("usage: run_with_log.py <log_file> -- <command string>", file=sys.stderr)
        return 2
    sep = args.index("--")
    log_path = Path(args[0])
    cmd = shlex.split(args[sep + 1])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

    if cmd and cmd[0] == "python":
        cmd[0] = sys.executable

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
