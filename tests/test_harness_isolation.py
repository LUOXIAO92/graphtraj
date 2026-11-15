"""A pytest temporary root inside a Harness is moved out before any test runs (482)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from harness_isolation import enclosing_harness

TESTS = Path(__file__).resolve().parent
CONFTEST = """import pytest, harness_isolation
@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    harness_isolation.configure(config)
def pytest_sessionstart(session):
    harness_isolation.report(session)
"""
INNER = """import os, tempfile
from pathlib import Path
from harness_isolation import enclosing_harness
def test_outside(tmp_path, tmp_path_factory):
    for path in (tmp_path, tmp_path_factory.mktemp("f"), Path(os.environ["TMPDIR"]), Path(tempfile.mkdtemp())):
        assert enclosing_harness(path) is None, path
"""


def _inner_run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    harness = tmp_path / "harness"
    (harness / ".graphtraj").mkdir(parents=True)
    (harness / "tmp" / "t").mkdir(parents=True)
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(CONFTEST)
    (suite / "test_inner.py").write_text(INNER)
    (tmp_path / "outside").mkdir()
    environment = {**os.environ, "TMPDIR": str(harness / "tmp" / "t"),
                   "PYTEST_OUTSIDE_HARNESS_TMPDIR": str(tmp_path / "outside"),
                   "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    environment.pop("PYTEST_DEBUG_TEMPROOT", None)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, str(suite)],
                          cwd=suite, env=environment, capture_output=True, text=True, timeout=120)


def test_temporary_root_inside_a_harness_moves_outside(tmp_path: Path) -> None:
    result = _inner_run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "lies inside the Harness {0}".format((tmp_path / "harness").resolve()) in result.stdout
    assert list((tmp_path / "harness" / "tmp" / "t").iterdir()) == []
    assert sorted(p.name for p in (tmp_path / "harness" / ".graphtraj").iterdir()) == []
    assert any((tmp_path / "outside").iterdir())


def test_explicit_basetemp_inside_a_harness_is_refused(tmp_path: Path) -> None:
    result = _inner_run(tmp_path, "--basetemp", str(tmp_path / "harness" / "bt"))
    assert result.returncode == 4, result.stdout + result.stderr
    assert "lies inside the Harness" in result.stderr
    assert not (tmp_path / "harness" / "bt").exists()


def test_markers_are_the_product_walk_up_targets(tmp_path: Path) -> None:
    assert enclosing_harness(tmp_path / "a" / "b") is None
    (tmp_path / ".agents-control").mkdir()
    (tmp_path / ".agents-control" / "claude-host.json").write_text("{}")
    assert enclosing_harness(tmp_path / "a" / "b") == tmp_path.resolve()
