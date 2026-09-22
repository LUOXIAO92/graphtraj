"""Development checks for native execution plumbing; not real approval acceptance."""

import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from graphtraj.execution import runner_status
from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes import replacement
from graphtraj.teams.coding import team_replacement
from test_direct_control_authority import _record_direct_session


@pytest.mark.parametrize("decision", ["allow", "deny", "cancel", "error"])
def test_native_execution_owns_continuation(tmp_path: Path, monkeypatch, decision: str) -> None:
    """Only an executing wrapper runs the payload; its failure never falls back."""
    wrapper = tmp_path / "wrapper"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os, sys\n"
        + ("os.execv(sys.argv[1], sys.argv[2:])\n" if decision == "allow" else
           f"print({decision!r}, file=sys.stderr); sys.exit(1)\n")
    )
    wrapper.chmod(0o755)
    marker = tmp_path / "executed"
    command = [sys.executable, "-c", (
        f"from pathlib import Path; Path({str(marker)!r}).touch(); "
        "print('replacement_alias: successor')"
    )]
    channel, peer = socket.socketpair()
    with channel, peer:
        monkeypatch.setenv("CODEX_ESCALATE_SOCKET", str(channel.fileno()))
        monkeypatch.setenv("EXEC_WRAPPER", str(wrapper))
        if decision == "allow":
            assert replacement.execute_replacement(command) == {"replacement_alias": "successor"}
        else:
            with pytest.raises(RunnerError, match=decision):
                replacement.execute_replacement(command)
    assert marker.exists() == (decision == "allow")


def test_missing_channel_is_not_no_approval(monkeypatch) -> None:
    """Codex without its inherited channel must not execute locally."""
    monkeypatch.delenv("CODEX_ESCALATE_SOCKET", raising=False)
    with pytest.raises(RunnerError) as error:
        replacement.execute_replacement([sys.executable, "-c", "raise AssertionError"])
    assert error.value.code == "native-approval-unavailable"


@pytest.mark.parametrize("runtime", ["codex", "pi", "unknown"])
def test_recorded_runtime_controls_native_stage(tmp_path: Path, monkeypatch, runtime: str) -> None:
    """The actual caller binding selects capability, even with forged environment."""
    root = tmp_path / "runner"
    parent = "132-ticket-handover0-team_leader@leader"
    caller = "132-ticket-handover0-engineer@caller"
    _record_direct_session(root, parent, "team-leader", None)
    _record_direct_session(root, caller, "engineer", parent)
    path = root / "sessions" / caller / "mapping.yml"
    mapping = yaml.safe_load(path.read_text()); mapping["runtime"] = runtime
    path.write_text(yaml.safe_dump(mapping))
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: caller)
    monkeypatch.setenv("GRAPHTRAJ_RUNTIME", "pi")
    monkeypatch.delenv("CODEX_ESCALATE_SOCKET", raising=False)
    target, _ = runner_status.read_alias_mapping(root, parent)
    if runtime == "pi":
        assert runner_status.require_replacement_authority(root, parent, target, ["unused"]) is None
    else:
        with pytest.raises(RunnerError):
            runner_status.require_replacement_authority(root, parent, target, ["unused"])
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: None)
    assert runner_status.require_replacement_authority(root, parent, target) is None


def test_public_replacement_requires_stopped_descendants(tmp_path: Path, monkeypatch) -> None:
    """An idle direct target with an active descendant cannot be replaced."""
    root = tmp_path / "runner"
    parent = "132-ticket-handover0-team_leader@leader"
    child = "132-ticket-handover0-engineer@child"
    _record_direct_session(root, parent, "team-leader", None)
    _record_direct_session(root, child, "engineer", parent)
    (root / "sessions" / parent / "execution.yml").write_text("outcome: completed\n")
    monkeypatch.setattr(team_replacement, "discover_project", lambda *a, **k: SimpleNamespace(runner_directory=root))
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: None)
    monkeypatch.setattr(runner_status, "session_operation", lambda *a: {"activity": "running"})
    with pytest.raises(RunnerError) as error:
        team_replacement.replace_session(parent, "user", ("cause",), tmp_path)
    assert error.value.code == "replacement-not-stopped"


def test_external_runtime_uses_executable_not_environment(monkeypatch) -> None:
    """Self-reported Runtime and thread variables cannot impersonate pi."""
    monkeypatch.setattr(replacement, "process_ancestors", lambda pid: [pid, 123])
    monkeypatch.setattr(replacement, "process_executable", lambda pid: Path("/opt/bin/codex"))
    monkeypatch.setenv("GRAPHTRAJ_RUNTIME", "pi")
    assert replacement.caller_runtime() == "codex"
    monkeypatch.setattr(replacement, "process_executable", lambda pid: Path("/bin/zsh"))
    assert replacement.caller_runtime() is None
