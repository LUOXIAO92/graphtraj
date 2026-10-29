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
        "subprocesses: graphtraj -> None, agent_swarm -> None; "
        "-I Workers: graphtraj -> None, agent_swarm -> None; expected both under {1}. "
        "Use a venv whose site-packages resolves this checkout: install it editable "
        "(pip install -e {2}/src/agent_swarm -e {2}) or add a .pth naming {1}. "
        "PYTHONPATH={1} serves only the subprocesses that do not run -I."
    ).format(interpreter, source, PROJECT_ROOT)


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
    output = session.stdout + session.stderr
    assert "subprocesses: graphtraj -> {0}".format(decoy / "graphtraj" / "__init__.py") in output
    assert "PYTHONPATH={0} serves only".format((PROJECT_ROOT / "src").resolve()) in output
    assert "passed" not in session.stdout


def _installation_problem(executable: Path, scripts: Path) -> str:
    """Run the suite's start check for one interpreter and command directory."""
    problem = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import conftest; "
         "print(conftest._installation_problem(sys.argv[1], conftest.Path(sys.argv[2])))",
         str(executable), str(scripts)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert problem.returncode == 0, problem.stderr
    return problem.stdout.strip()


def _metadata_less_venv(tmp_path: Path) -> Path:
    """A venv whose .pth imports this checkout but carries no graphtraj metadata or commands (Task 390)."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(venv)],
                   check=True, timeout=120)
    python = venv / "bin" / "python"
    site = subprocess.run([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                          capture_output=True, text=True, check=True).stdout.strip()
    Path(site, "zz_checkout.pth").write_text(str((PROJECT_ROOT / "src").resolve()) + "\n")
    metadata = subprocess.run([str(python), "-I", "-c", "import importlib.metadata as m; "
                               "print(len(m.entry_points(group='agent_swarm.hosts', name='graphtraj')))"],
                              capture_output=True, text=True, check=True).stdout.strip()
    if metadata != "0":
        pytest.skip("the base interpreter already carries graphtraj metadata")
    return python


def test_a_complete_editable_install_passes_the_installation_check() -> None:
    assert _installation_problem(Path(sys.executable), Path(sys.executable).parent) == "None"


def test_a_missing_graphtraj_session_command_is_named_with_the_fix(tmp_path: Path) -> None:
    assert _installation_problem(Path(sys.executable), tmp_path) == (
        "The test interpreter {0} lacks the graphtraj-session command in {1}. Install this checkout "
        "editable in a dedicated venv: pip install -e {2}/src/agent_swarm -e {2}; a .pth alone gives neither."
    ).format(sys.executable, tmp_path, PROJECT_ROOT)


def test_missing_distribution_metadata_is_named_with_the_fix(tmp_path: Path) -> None:
    python = _metadata_less_venv(tmp_path)
    assert _installation_problem(python, Path(sys.executable).parent) == (
        "The test interpreter {0} lacks the graphtraj distribution metadata (entry point "
        "agent_swarm.hosts: graphtraj under {1}; found no graphtraj entry). Install this checkout "
        "editable in a dedicated venv: pip install -e {2}/src/agent_swarm -e {2}; a .pth alone gives neither."
    ).format(python, (PROJECT_ROOT / "src").resolve(), PROJECT_ROOT)


def test_a_suite_without_installed_metadata_stops_at_start_with_one_message(tmp_path: Path) -> None:
    python = _metadata_less_venv(tmp_path)
    session = subprocess.run(
        [str(python), "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "tests/test_suite_environment.py::test_a_codex_without_the_sandbox_flag_is_refused_as_before"],
        cwd=PROJECT_ROOT, env={name: value for name, value in os.environ.items() if name != "PYTHONPATH"},
        capture_output=True, text=True, timeout=120,
    )
    output = session.stdout + session.stderr
    assert session.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert "lacks the graphtraj distribution metadata" in output
    assert "and the graphtraj-session command in {0}".format(python.parent) in output
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
