"""Keep the suite's temporary directories outside every Harness (482).

Many tests treat ``tmp_path`` as "outside any Harness": they run product entry
points with that directory as cwd and expect no Harness to be found. The
product walks up from cwd to the nearest Harness (``.graphtraj``) or agents
host configuration (``.agents-control/claude-host.json``), which is intended.
When the temporary root lies inside a real Harness (``TMPDIR=<Harness>/tmp/...``)
that walk reaches it, so tests fail falsely and, worse, write its Main records
and sessions.

The guarantee is made once for the whole session rather than per test: when
the temporary root pytest would use lies inside a Harness, the session's
``TMPDIR`` (inherited by every subprocess) and pytest's temporary root are moved
to ``graphtraj-tests-<uid>`` under the first candidate outside every Harness.
An explicit ``--basetemp`` inside a Harness is refused instead, as is a
location with no usable candidate, so no test ever runs there.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import pytest

MARKERS = (Path(".graphtraj"), Path(".agents-control") / "claude-host.json")
# PYTEST_OUTSIDE_HARNESS_TMPDIR names a preferred directory, e.g. where a sandbox allows writes.
CANDIDATES = tuple(filter(None, (os.environ.get("PYTEST_OUTSIDE_HARNESS_TMPDIR"), "/tmp", "/var/tmp")))


def enclosing_harness(path: Path) -> Optional[Path]:
    """Return the nearest directory at or above ``path`` that a product walk-up would take as a Harness."""
    path = Path(os.path.abspath(path))
    try:
        path = path.resolve()
    except OSError:
        pass
    for directory in (path, *path.parents):
        if any(os.path.lexists(directory / marker) for marker in MARKERS):
            return directory
    return None


def _outside_root(candidates: Iterable[str]) -> Optional[Path]:
    for candidate in candidates:
        base = Path(candidate)
        if not base.is_dir() or enclosing_harness(base) is not None:
            continue
        root = base / "graphtraj-tests-{0}".format(os.getuid())
        try:
            root.mkdir(mode=0o700, exist_ok=True)
            probe = tempfile.mkdtemp(dir=root)
            os.rmdir(probe)
        except OSError:
            continue
        if enclosing_harness(root) is None:
            return root.resolve()
    return None


def isolate(config: pytest.Config, candidates: Iterable[str] = CANDIDATES) -> Optional[str]:
    """Move this session's temporary root out of an enclosing Harness; return what was done."""
    if config.option.basetemp:
        harness = enclosing_harness(Path(config.option.basetemp))
        if harness is not None:
            raise pytest.UsageError(
                "--basetemp {0} lies inside the Harness {1}; tests would walk up into it and change its "
                "records. Choose a --basetemp outside every Harness (482).".format(config.option.basetemp, harness))
        return None
    current = os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()
    harness = enclosing_harness(Path(current))
    if harness is None:
        return None
    outside = _outside_root(candidates)
    if outside is None:
        pytest.exit(
            "The pytest temporary root {0} lies inside the Harness {1}, and none of {2} is a writable "
            "directory outside every Harness; no test was run (482). Set TMPDIR outside every Harness."
            .format(current, harness, ", ".join(candidates)), returncode=4)
    os.environ.pop("PYTEST_DEBUG_TEMPROOT", None)
    os.environ["TMPDIR"] = str(outside)
    tempfile.tempdir = str(outside)
    return "pytest temporary root {0} lies inside the Harness {1}; moved TMPDIR and pytest's temporary root to {2} (482)".format(
        current, harness, outside)


_NOTICE_KEY = pytest.StashKey[Optional[str]]()


def configure(config: pytest.Config) -> None:
    """Call first from ``pytest_configure``, before pytest reads ``--basetemp``."""
    config.stash[_NOTICE_KEY] = isolate(config)


def report(session: pytest.Session) -> None:
    """Print the move, also under ``-q``, so a run's log shows where its temporary files went."""
    notice = session.config.stash.get(_NOTICE_KEY, None)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if notice and reporter is not None:
        reporter.write_line(notice)
