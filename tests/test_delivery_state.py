from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process
from test_ticket_graph import _configure, _register, _ticket, _change_status


def test_delivery_state_request_rolls_back_state_when_its_event_is_invalid(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("74", "complete-team-round"))
    _change_status(installed_commands, project, "74", "ready")
    ticket = state / "tickets" / "74-complete-team-round"
    ticket_before = (ticket / "ticket.yml").read_bytes()
    worldline_before = {
        path: path.read_bytes() for path in (state / "worldline").glob("*.jsonl")
    }
    predecessor = [
        json.loads(line)
        for path in worldline_before
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]["event_id"]
    request = project / "delivery-state-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "phase": "start",
                "ticket_id": "74",
                "caused_by_event_ids": [predecessor],
                "evidence_refs": ["missing-batch.yml"],
                "worktree": ".graphtraj/worktrees/74-complete-team-round",
                "branch": "agent/74-complete-team-round",
                "members": {
                    "team_leader": {"role": "team-leader", "session_ref": "74-complete-team-round@l1"},
                    "engineer": {"role": "engineer-junior", "session_ref": None},
                    "standards_reviewer": {"role": "standards-reviewer", "session_ref": None},
                    "spec_reviewer": {"role": "spec-reviewer", "session_ref": None},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    facts = project / "delivery-state-facts.yml"
    facts.write_bytes(request.read_bytes())

    result = run_process(
        [
            str(installed_commands.product),
            "delivery-state",
            "apply",
            "--request-file",
            str(request),
            "--facts-file",
            str(facts),
        ],
        cwd=project,
    )

    assert result.returncode == 1
    assert (ticket / "ticket.yml").read_bytes() == ticket_before
    assert not (ticket / "teams").exists()
    assert {path: path.read_bytes() for path in worldline_before} == worldline_before
