"""Agent Entity binding and immutable direct ownership through Runner entries."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

from test_managed_sessions import launch_document, managed_project, observe


BINDING_FIELDS = (
    "alias",
    "runtime",
    "session",
    "ticket_id",
    "team_generation",
    "role",
    "parent",
)


def _mapping(root: Path, alias: str) -> dict:
    """Read the Runner's own record for one Agent Alias."""
    return yaml.safe_load(
        (
            root / ".graphtraj" / "runner" / "sessions" / alias / "mapping.yml"
        ).read_text(encoding="utf-8")
    )


def _binding(root: Path, alias: str) -> dict:
    """Read the recorded Agent Entity and its direct parent."""
    mapping = _mapping(root, alias)
    return {field: mapping[field] for field in BINDING_FIELDS}


def _session_worker(root: Path, executable: Path, job_file: Path) -> subprocess.CompletedProcess:
    """Run the Runner's own create/resume entry for one durable job document."""
    task = yaml.safe_load(job_file.read_text(encoding="utf-8"))["mapping"]
    environment = {
        **os.environ,
        "PATH": os.pathsep.join((str(executable.parent), os.environ.get("PATH", ""))),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "MANAGED_NATIVE_ROOT": str(executable.parent.parent / "native"),
        "CODEX_HOME": str(executable.parent.parent / "codex-home"),
        "GRAPHTRAJ_TICKET_ID": str(task["ticket_id"]),
        "GRAPHTRAJ_TICKET_NAME": "managed-probe",
        "GRAPHTRAJ_ROLE": str(task["role"]),
        "GRAPHTRAJ_TEAM_GENERATION": str(task["team_generation"]),
        "GRAPHTRAJ_HARNESS_ROOT": str(root),
    }
    return subprocess.run(
        [sys.executable, "-m", "graphtraj.execution.runner_worker", str(job_file)],
        cwd=root,
        env=environment,
        input="Own the mapped Session.\n",
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_resume_keeps_the_entity_and_a_new_native_session_is_a_new_entity(
    managed_project,
) -> None:
    """The recorded entity and parent hold across worker rebuild; new means new."""
    root, cause, call, _ = managed_project
    launched = call("launch", launch_document())["tasks"][0]
    alias, session = launched["alias"], launched["session"]
    observe(call, alias, "running")
    created = _binding(root, alias)
    launch_worker = _mapping(root, alias)["worker_pid"]
    assert created == {
        "alias": alias,
        "runtime": "codex",
        "session": session,
        "ticket_id": "113",
        "team_generation": 1,
        "role": "managed-probe",
        "parent": None,
    }

    # Steering the running turn ends it without changing the entity.
    call("send", [alias, "binding-check", [cause]])
    observe(call, alias, "idle", "completed")
    assert _binding(root, alias) == created

    # A rebuilt Worker resumes the same native Session as the same entity.
    call("send", [alias, "binding-check", [cause]])
    assert observe(call, alias, "running")["session"] == session
    resumed = _mapping(root, alias)
    assert resumed["worker_pid"] != launch_worker
    assert {field: resumed[field] for field in BINDING_FIELDS} == created

    # A new native Session forms a new entity and leaves the first one alone.
    second = call("launch", launch_document("second"))["tasks"][0]
    observe(call, second["alias"], "running")
    assert second["alias"] != alias
    assert second["session"] != session
    assert _binding(root, second["alias"])["session"] == second["session"]
    assert _binding(root, alias) == created


def test_a_launch_input_and_request_parent_cannot_rebind_an_existing_entity(
    managed_project,
) -> None:
    """Re-submitting input or changing a request parent keeps the recorded entity."""
    root, cause, call, executable = managed_project
    launched = call("launch", launch_document())["tasks"][0]
    alias = launched["alias"]
    observe(call, alias, "running")
    recorded = _binding(root, alias)
    call("send", [alias, "binding-check", [cause]])
    observe(call, alias, "idle", "completed")
    session_directory = root / ".graphtraj" / "runner" / "sessions" / alias
    assert _binding(root, alias) == recorded

    # A launch input that asks for another parent cannot re-parent the entity.
    launch_file = session_directory / "launch.yml"
    launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
    launch["mapping"]["parent"] = "other@l1"
    launch_file.write_text(yaml.safe_dump(launch), encoding="utf-8")
    denied = call("send", [alias, "binding-check", [cause]], returncode=1)
    assert denied["error"]["code"] == "operation-failed"
    assert _binding(root, alias) == recorded

    # Re-submitting that launch input is refused with its own retained evidence.
    refused = _session_worker(root, executable, launch_file)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    failure = yaml.safe_load(
        (session_directory / "launch-error.yml").read_text(encoding="utf-8")
    )
    assert failure["code"] == "AGENT_BINDING_CONFLICT"
    assert _binding(root, alias) == recorded

    # The recorded launch input still resumes the entity after that refusal.
    launch["mapping"]["parent"] = recorded["parent"]
    launch_file.write_text(yaml.safe_dump(launch), encoding="utf-8")
    call("send", [alias, "binding-check", [cause]])
    assert observe(call, alias, "running")["session"] == recorded["session"]
    call("interrupt", [alias])
    observe(call, alias, "idle", "interrupted")

    # A modified resume request is refused the same way.
    resume_file = session_directory / "resume.yml"
    resume = yaml.safe_load(resume_file.read_text(encoding="utf-8"))
    resume["mapping"]["parent"] = "other@l1"
    resume_file.write_text(yaml.safe_dump(resume), encoding="utf-8")
    refused = _session_worker(root, executable, resume_file)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    failure = yaml.safe_load(
        (session_directory / "resume-error.yml").read_text(encoding="utf-8")
    )
    assert failure["code"] == "AGENT_BINDING_CONFLICT"
    assert _binding(root, alias) == recorded

    # The refused requests left the entity usable after every refusal.
    call("send", [alias, "binding-check", [cause]])
    assert observe(call, alias, "running")["session"] == recorded["session"]
    assert _binding(root, alias) == recorded
