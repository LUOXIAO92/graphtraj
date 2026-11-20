"""Task 531: caller identity parses only Sessions whose owner lock is held.

Every hosted request without a scoped native caller resolved its caller by parsing every Session's mapping.yml
(about 0.42 CPU-s per request at production's ~510 Sessions), although only a Session whose recorded Worker
holds its ownership lock can own the caller. The decision is unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from graphtraj.execution import runner_status
from graphtraj.execution.runner_heartbeat import hold_ownership
from test_result_submission import result_project


@pytest.fixture
def parsed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Aliases whose mapping the caller lookup parses."""
    aliases: list[str] = []
    original = runner_status.read_alias_mapping

    def counted(runner_directory: Path, alias: str):
        aliases.append(alias)
        return original(runner_directory, alias)

    monkeypatch.setattr(runner_status, 'read_alias_mapping', counted)
    return aliases


def bind(runner: Path, alias: str, pid: int) -> Path:
    directory = runner / 'sessions' / alias
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    mapping.update(worker_pid=pid, runtime_pid=pid)
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    return directory


def test_no_held_lock_parses_no_mapping(tmp_path: Path, parsed: list[str]) -> None:
    runner, _, _ = result_project(tmp_path)
    bind(runner, 'research@x1', os.getpid())  # recorded, but its Worker holds no lock
    (runner / 'sessions/research@x2/owner-1.lock').touch()  # a dead owner's lock file
    assert runner_status.process_caller_alias(runner, os.getpid()) is None
    assert parsed == []


def test_only_the_held_session_is_parsed_and_owns_the_caller(tmp_path: Path, parsed: list[str]) -> None:
    runner, _, _ = result_project(tmp_path)
    directory = bind(runner, 'research@x1', os.getpid())
    with hold_ownership(directory, os.getpid()):
        assert runner_status.process_caller_alias(runner, os.getpid()) == 'research@x1'
    assert parsed == ['research@x1']


def test_a_lock_held_for_another_pid_still_owns_nothing(tmp_path: Path, parsed: list[str]) -> None:
    """The recorded worker_pid's lock decides, as before: a held lock under another pid does not."""
    runner, _, _ = result_project(tmp_path)  # every mapping records worker_pid 1
    with hold_ownership(runner / 'sessions/research@x2', os.getpid()):
        assert runner_status.process_caller_alias(runner, os.getpid()) is None
    assert parsed == ['research@x2']
