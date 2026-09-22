"""Development checks for native execution plumbing; not real approval acceptance."""

import os
import socket
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from graphtraj.execution import runner_status
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_transport import runtime_launch_failure
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


def test_native_tool_continuation_requires_execution(tmp_path: Path, monkeypatch) -> None:
    """Returning a request does not run it; native execution supplies the result."""
    monkeypatch.delenv("CODEX_ESCALATE_SOCKET", raising=False)
    marker = tmp_path / "operation with ' quotes"
    command = [sys.executable, "-c", (
        f"from pathlib import Path; Path({str(marker)!r}).touch(); "
        "print('replacement_alias: successor')"
    )]
    request = replacement.execute_replacement(command)
    assert request["replacement_status"] == "requires-native-approval"
    arguments = request["native_execution"]["arguments"]
    assert arguments["sandbox_permissions"] == "require_escalated"
    assert not marker.exists()  # Refusal/cancel leaves the operation unexecuted.
    result = subprocess.run(shlex.split(arguments["cmd"]), capture_output=True, text=True)
    assert result.returncode == 0
    assert yaml.safe_load(result.stdout) == {"replacement_alias": "successor"}
    assert marker.exists()


def test_invalid_channel_does_not_fall_back(monkeypatch) -> None:
    """A broken existing connection is not absence of approval capability."""
    monkeypatch.setenv("CODEX_ESCALATE_SOCKET", "invalid")
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
    elif runtime == "codex":
        result = runner_status.require_replacement_authority(root, parent, target, ["unused"])
        assert result["replacement_status"] == "requires-native-approval"
    else:
        with pytest.raises(RunnerError):
            runner_status.require_replacement_authority(root, parent, target, ["unused"])
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: None)
    assert runner_status.require_replacement_authority(root, parent, target) is None


@pytest.mark.parametrize("child_activity", ["idle", "running"])
def test_public_replacement_checks_descendants_with_failed_launch_residue(
    tmp_path: Path, monkeypatch, child_activity: str
) -> None:
    """Terminal unrelated startup residue neither blocks nor hides a live descendant."""
    root = tmp_path / "runner"
    parent = "132-ticket-handover0-team_leader@leader"
    child = "132-ticket-handover0-engineer@child"
    _record_direct_session(root, parent, "team-leader", None)
    _record_direct_session(root, child, "engineer", parent)
    (root / "sessions" / parent / "execution.yml").write_text("outcome: completed\n")
    monkeypatch.setattr(team_replacement, "discover_project", lambda *a, **k: SimpleNamespace(runner_directory=root))
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: None)
    if child_activity == "idle":
        (root / "sessions" / child / "execution.yml").write_text("outcome: completed\n")
    failed = root / "sessions" / "132-ticket-handover0-engineer@failed"
    failed.mkdir()
    (failed / "launch.yml").write_text(yaml.safe_dump({
        "operation": "launch",
        "mapping": {"alias": failed.name, "parent": None, "runtime": "codex"},
    }))
    failure = yaml.safe_dump(runtime_launch_failure(
        "RUNTIME_START_FAILED", "Runtime could not create its sqlite directory.", "",
        terminal_confirmed=True,
    ))
    (failed / "launch-error.yml").write_text(failure)
    monkeypatch.setattr(runner_status, "session_operation", lambda *a: {"activity": "running"})
    with pytest.raises(RunnerError) as error:
        # Missing causes deliberately stop at the next public validation step,
        # after the stopped-subtree check, without creating a replacement.
        team_replacement.replace_session(parent, "user", (), tmp_path)
    expected = "invalid-input" if child_activity == "idle" else "replacement-not-stopped"
    assert error.value.code == expected
    assert (failed / "launch-error.yml").read_text() == failure


def test_external_runtime_uses_executable_not_environment(monkeypatch) -> None:
    """Self-reported Runtime and thread variables cannot impersonate pi."""
    monkeypatch.setattr(replacement, "process_ancestors", lambda pid: [pid, 123])
    monkeypatch.setattr(replacement, "process_executable", lambda pid: Path("/opt/bin/codex"))
    monkeypatch.setenv("GRAPHTRAJ_RUNTIME", "pi")
    assert replacement.caller_runtime() == "codex"
    monkeypatch.setattr(replacement, "process_executable", lambda pid: Path("/bin/zsh"))
    assert replacement.caller_runtime() is None


def test_public_non_direct_replacement_returns_native_request(tmp_path: Path, monkeypatch) -> None:
    """The public entry checks ownership and yields without changing the seat."""
    root = tmp_path / "runner"
    parent = "132-ticket-handover0-team_leader@leader"
    child = "132-ticket-handover0-engineer@child"
    _record_direct_session(root, parent, "team-leader", None)
    _record_direct_session(root, child, "engineer", parent)
    monkeypatch.setattr(team_replacement, "discover_project", lambda *a, **k: SimpleNamespace(runner_directory=root))
    monkeypatch.setattr(runner_status, "caller_alias", lambda directory: None)
    monkeypatch.setattr(replacement, "caller_runtime", lambda: "codex")
    monkeypatch.delenv("CODEX_ESCALATE_SOCKET", raising=False)
    def unexpected_execution(*args):
        """Fail if requesting approval executes the operation locally."""
        pytest.fail("replacement ran before native execution")
    monkeypatch.setattr(team_replacement, "_replace_stopped_session", unexpected_execution)
    result = team_replacement.replace_session(child, "main", ("cause",), tmp_path)
    assert result["replacement_status"] == "requires-native-approval"
    assert result["native_execution"]["arguments"]["sandbox_permissions"] == "require_escalated"
