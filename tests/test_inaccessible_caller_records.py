"""Public observation must not interpret unreadable ownership as Main authority."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import status_aliases


@pytest.mark.parametrize("denied_operation", ["metadata", "listing"])
def test_status_refuses_inaccessible_caller_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied_operation: str,
) -> None:
    """A native directory denial produces a refusal, not an unknown/Main caller."""
    configuration = tmp_path / ".graphtraj" / "config.yml"
    sessions = configuration.parent / "runner" / "sessions"
    sessions.mkdir(parents=True)
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    original_symlink = Path.is_symlink
    original_listdir = os.listdir

    def is_symlink(path: Path) -> bool:
        """Inject the actual probe's metadata failure only at ownership discovery."""
        if path == sessions and denied_operation == "metadata":
            raise PermissionError("Session metadata is denied")
        return original_symlink(path)

    def listdir(path: str | Path) -> list[str]:
        """Exercise the denial previously treated as an empty ownership set."""
        if Path(path) == sessions and denied_operation == "listing":
            raise PermissionError("Session listing is denied")
        return original_listdir(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    monkeypatch.setattr(os, "listdir", listdir)

    with pytest.raises(RunnerError) as failure:
        status_aliases((), tmp_path)

    assert failure.value.code == "authority-denied"


def test_status_still_allows_a_fresh_harness(tmp_path: Path) -> None:
    """A new Harness with no Session directory still has a valid Main caller."""
    configuration = tmp_path / ".graphtraj" / "config.yml"
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))

    status = status_aliases((), tmp_path)

    assert status.succeeded
    assert status.document == {"aliases": []}
