"""Identify an external replacement caller from its actual process ancestry."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from graphtraj.execution.runner_process import process_ancestors, process_executable


def caller_runtime() -> str | None:
    """Identify an external caller from its process ancestry, not projected flags.

    Managed callers use their recorded Runtime instead. For external callers,
    recognize Codex's executable and Pi/DSH's actual Node entrypoints. An unknown
    executable is not classified as lacking approval support.
    """
    for pid in process_ancestors(os.getpid())[1:]:
        executable = process_executable(pid)
        if executable is None:
            continue
        if executable.name.lower() in {"codex", "codex-cli"}:
            return "codex"
        if executable.name == "node":
            try:
                if sys.platform.startswith("linux"):
                    argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
                else:
                    argv = shlex.split(subprocess.check_output(
                        ["/bin/ps", "-p", str(pid), "-o", "args="], text=True,
                    ))
                if len(argv) > 1:
                    entrypoint = str(Path(argv[1]).resolve())
                    if entrypoint.endswith("/@mariozechner/pi-coding-agent/dist/cli.js"):
                        return "pi"
                    if entrypoint.endswith("/@deepseek-ai/dsh/lib/bin.js"):
                        return "dsh"
            except (OSError, ValueError, subprocess.CalledProcessError):
                continue
    return None
