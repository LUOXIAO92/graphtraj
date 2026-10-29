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


@pytest.mark.parametrize("configured", ["src", os.path.join(".", "src")])
def test_a_relative_pythonpath_imports_this_checkout_in_subprocesses(tmp_path: Path, configured: str) -> None:
    session = subprocess.run(
        [sys.executable, "-c", _SESSION, str(tmp_path)],
        cwd=PROJECT_ROOT, env={**os.environ, "PYTHONPATH": configured},
        capture_output=True, text=True, timeout=60,
    )
    assert session.returncode == 0, session.stderr
    assert session.stdout.strip() == str(PROJECT_ROOT / "src" / "graphtraj" / "__init__.py")


def test_an_interpreter_without_this_checkout_is_named_with_both_fixes(tmp_path: Path) -> None:
    # The stale or absent install: -S hides every installed graphtraj.
    interpreter = tmp_path / "python"
    interpreter.write_text('#!/bin/sh\nexec "{0}" -S "$@"\n'.format(sys.executable))
    interpreter.chmod(0o755)
    from conftest import _checkout_import_problem

    source = (PROJECT_ROOT / "src").resolve()
    problem = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import conftest; "
         "print(conftest._checkout_import_problem(conftest.Path(sys.argv[1]), sys.argv[2]))",
         str(tmp_path), str(interpreter)],
        cwd=PROJECT_ROOT, env={name: value for name, value in os.environ.items() if name != "PYTHONPATH"},
        capture_output=True, text=True, timeout=60,
    )
    assert problem.returncode == 0, problem.stderr
    assert problem.stdout.strip() == (
        "Test subprocesses would not import this checkout: {0} from a neutral directory resolves "
        "graphtraj -> None, agent_swarm -> None; expected both under {1}. Install this checkout "
        "editable into that venv (pip install -e {2}/src/agent_swarm -e {2}) or set PYTHONPATH={1}."
    ).format(interpreter, source, PROJECT_ROOT)
    assert _checkout_import_problem(tmp_path) is None


def test_a_suite_whose_subprocesses_import_another_tree_stops_at_start(tmp_path: Path) -> None:
    decoy = tmp_path / "decoy"
    (decoy / "graphtraj").mkdir(parents=True)
    (decoy / "graphtraj" / "__init__.py").write_text("")
    session = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_suite_environment.py::test_a_codex_without_the_sandbox_flag_is_refused_as_before"],
        cwd=PROJECT_ROOT, env={**os.environ, "PYTHONPATH": str(decoy)},
        capture_output=True, text=True, timeout=120,
    )
    assert session.returncode == pytest.ExitCode.USAGE_ERROR, session.stdout + session.stderr
    assert "graphtraj -> {0}".format(decoy / "graphtraj" / "__init__.py") in session.stdout + session.stderr
    assert "or set PYTHONPATH={0}.".format((PROJECT_ROOT / "src").resolve()) in session.stdout + session.stderr
    assert "passed" not in session.stdout


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
