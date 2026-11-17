from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import uuid

import pytest

import harness_isolation
from graftling.member_processes import ancestor_pids, stop_marked_processes

# Every process this run starts inherits this value; at the end of the session the
# same-user processes carrying exactly it (except pytest and its ancestors) are
# stopped. The name avoids KEY, SECRET and TOKEN, which credential filters drop.
TEST_RUN_ENV = "PYTEST_GRAFTLING_RUN"


def pytest_configure(config: pytest.Config) -> None:
    if not os.environ.get(TEST_RUN_ENV):
        os.environ[TEST_RUN_ENV] = uuid.uuid4().hex
    # Keep tmp_path outside any Harness or agents host configuration.
    harness_isolation.configure(config)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    value = os.environ.get(TEST_RUN_ENV, "")
    report = stop_marked_processes(value, exclude=ancestor_pids(), variable=TEST_RUN_ENV)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter and (report["found"] or report.get("error")):
        reporter.write_line("leftover test processes of {0}={1}: found={2} stopped={3} remaining={4}{5}".format(
            TEST_RUN_ENV, value, len(report["found"]), len(report["stopped"]), len(report["remaining"]),
            " error=" + str(report["error"]) if report.get("error") else ""))
    harness_isolation.report(session)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "src"


def _absolute_pythonpath(configured: str, cwd: Path) -> str:
    """Resolve relative PYTHONPATH entries against the invocation directory.

    pytest's pythonpath covers only this process. Subprocesses (fake Runtimes
    run by sys.executable, installed commands) start in other directories, where
    a relative entry such as ``src`` would name nothing.
    """
    return os.pathsep.join(str(cwd / entry) if entry else entry for entry in configured.split(os.pathsep))


if os.environ.get("PYTHONPATH"):
    os.environ["PYTHONPATH"] = _absolute_pythonpath(os.environ["PYTHONPATH"], Path.cwd())

_ORIGIN = "import importlib.util; print(getattr(importlib.util.find_spec('graftling'), 'origin', None))"


def _checkout_import_problem(cwd: Path, executable: str = sys.executable) -> Optional[str]:
    """Say why subprocesses started from cwd would not import this checkout.

    Fake Runtimes inherit PYTHONPATH; children started with ``-I`` ignore it,
    so only the venv's site-packages can give them this checkout.
    """
    resolved = []
    for form, flags in (("subprocesses", ()), ("-I children", ("-I",))):
        probe = subprocess.run([executable, *flags, "-c", _ORIGIN], cwd=cwd,
                               capture_output=True, text=True, timeout=60)
        origin = probe.stdout.strip() if probe.returncode == 0 else ""
        if origin and origin != "None" and Path(origin).resolve().is_relative_to(SOURCE.resolve()):
            continue
        resolved.append("{0}: graftling -> {1}".format(form, origin or "probe failed: " + probe.stderr.strip()[-300:]))
    if not resolved:
        return None
    return (
        "Test subprocesses would not import this checkout: {0} from a neutral directory resolves {1}; "
        "expected graftling under {2}. Install it editable into the test venv: "
        "{0} -m pip install -e {3}/src/graftling"
    ).format(executable, "; ".join(resolved), SOURCE, PROJECT_ROOT)


def _command_problem(executable: str = sys.executable) -> Optional[str]:
    """Say which console command of the installed distribution is missing."""
    scripts = Path(executable).parent
    missing = [name for name in ("agents", "agents-mcp") if not (scripts / name).exists()]
    if not missing:
        return None
    return "The test interpreter's bin directory {0} lacks {1}; install this checkout: {2} -m pip install -e {3}/src/graftling".format(
        scripts, ", ".join(missing), executable, PROJECT_ROOT)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Stop at once, with one cause, when subprocesses would import another tree."""
    with tempfile.TemporaryDirectory() as neutral:
        problem = _checkout_import_problem(Path(neutral)) or _command_problem()
    if problem:
        pytest.exit(problem, returncode=pytest.ExitCode.USAGE_ERROR)


def unsupported_dsh() -> Optional[str]:
    """Return why the installed DSH cannot back native tests, using the product check."""
    from graftling.dsh import dsh_version_refusal

    dsh = shutil.which("dsh")
    if dsh is None or shutil.which("node") is None:
        return "Installed DSH and Node are required."
    return dsh_version_refusal(Path(dsh).resolve().parent.parent / "package.json")


@pytest.fixture(autouse=True)
def isolated_runner_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not inherit the invoking Agent's Session or a host's own variables."""
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for name in tuple(os.environ):
        if name.startswith("GRAPHTRAJ_"):
            monkeypatch.delenv(name)
