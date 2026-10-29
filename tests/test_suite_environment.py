"""The suite's subprocesses import the checkout under test (Task 376)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from graphtraj.runtimes.codex.codex_adapter import CodexAdapterError, _require_codex_permissions

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load the suite's conftest the way pytest does at startup, then start a
# subprocess the way fixtures do: inherited environment, another cwd. -S keeps
# the venv's installed graphtraj out, so only PYTHONPATH can supply it.
_SESSION = """
import os, subprocess, sys
sys.path.insert(0, 'tests')
import conftest
probe = subprocess.run(
    [sys.executable, '-S', '-c',
     "import importlib.util; print(importlib.util.find_spec('graphtraj').origin)"],
    cwd=sys.argv[1], capture_output=True, text=True,
)
sys.stdout.write(probe.stdout + probe.stderr)
"""


@pytest.mark.parametrize("configured", ["src", os.path.join(".", "src"), None])
def test_fixture_subprocesses_import_this_checkout(tmp_path: Path, configured: str | None) -> None:
    environment = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    if configured is not None:
        environment["PYTHONPATH"] = configured
    session = subprocess.run(
        [sys.executable, "-c", _SESSION, str(tmp_path)],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert session.returncode == 0, session.stderr
    assert session.stdout.strip() == str(PROJECT_ROOT / "src" / "graphtraj" / "__init__.py")


def _codex(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n" + body)
    executable.chmod(0o755)
    return executable


def test_a_failed_codex_probe_is_not_reported_as_missing_sandboxing(tmp_path: Path) -> None:
    executable = _codex(tmp_path, (
        "echo 'Traceback (most recent call last):' >&2\n"
        "echo \"ModuleNotFoundError: No module named 'graphtraj'\" >&2\n"
        "exit 3\n"
    ))
    with pytest.raises(CodexAdapterError) as refused:
        _require_codex_permissions(executable)
    assert refused.value.code == "ROLE_CONFIG_UNSUPPORTED"
    assert refused.value.message == (
        "Cannot verify Codex permission controls: '{0} exec --help' exited with status 3: "
        "ModuleNotFoundError: No module named 'graphtraj'".format(executable)
    )


def test_a_codex_without_the_sandbox_flag_is_refused_as_before(tmp_path: Path) -> None:
    executable = _codex(tmp_path, "echo '--config --json'\n")
    with pytest.raises(CodexAdapterError) as refused:
        _require_codex_permissions(executable)
    assert refused.value.code == "ROLE_CONFIG_UNSUPPORTED"
    assert refused.value.message == "Codex must support filesystem sandboxing."
