from __future__ import annotations

import json
from pathlib import Path

import yaml

from conftest import InstalledCommands, run_process


def _configure(project: Path) -> Path:
    state = project / ".graphtraj" / "state"
    config = project / ".graphtraj" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "paths": {
                    "project_root": ".",
                    "docs": "docs",
                    "agent_worktrees": ".graphtraj/worktrees",
                    "state": ".graphtraj/state",
                },
                "agent_runner": {"dispatch_depth": 1, "max_concurrency": 2},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return state


def _write(path: Path, value: object) -> Path:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _ticket(
    ticket_id: str,
    name: str,
    *,
    dependencies: list[str] | None = None,
) -> dict[str, object]:
    return {
        "ticket_id": ticket_id,
        "ticket_name": name,
        "source": f"https://github.com/example/project/issues/{ticket_id}",
        "title": name.replace("-", " ").title(),
        "body": f"Deliver {name}.",
        "dependencies": dependencies or [],
    }


def _non_coding_ticket(
    ticket_id: str,
    name: str,
    *,
    task_type: str,
) -> dict[str, object]:
    return {
        **_ticket(ticket_id, name),
        "body": (
            "---\n"
            "task_type: {0}\n"
            "---\n\n"
            "Investigate {1}."
        ).format(task_type, name),
    }


def _run(
    commands: InstalledCommands, project: Path, *arguments: str
):
    return run_process([str(commands.product), "ticket", *arguments], cwd=project)


def _register(
    commands: InstalledCommands,
    project: Path,
    ticket: dict[str, object],
) -> None:
    path = _write(project / "register.yml", ticket)
    result = _run(commands, project, "register", "--ticket-file", str(path))
    assert result.returncode == 0, result.stderr


def _change_status(
    commands: InstalledCommands,
    project: Path,
    ticket_id: str,
    status: str,
) -> None:
    evidence = project / "delivery-evidence.md"
    evidence.write_text("Main validated the current delivery fact.\n", encoding="utf-8")
    change = _write(
        project / "state-change.yml",
        {
            "ticket_id": ticket_id,
            "status": status,
            "active_team_ordinal": None,
            "worktree": None,
            "branch": None,
            "current_candidate": None,
            "caused_by_event_ids": [],
            "evidence_refs": ["delivery-evidence.md"],
        },
    )
    result = _run(commands, project, "update", "--state-file", str(change))
    assert result.returncode == 0, result.stderr


def test_installed_command_registers_an_accepted_issue_as_a_ticket(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    issue = _write(project / "issue.yml", _ticket("73", "ticket-readiness"))

    result = _run(
        installed_commands, project, "register", "--ticket-file", str(issue)
    )

    assert result.returncode == 0, result.stderr
    directory = state / "tickets" / "73-ticket-readiness"
    assert directory.is_dir()
    snapshot = (directory / "ticket.md").read_text(encoding="utf-8")
    assert "# Ticket 73: Ticket Readiness" in snapshot
    assert "Ticket name: ticket-readiness" in snapshot
    assert "Source: https://github.com/example/project/issues/73" in snapshot
    assert "Dependencies: none" in snapshot
    assert snapshot.endswith("Deliver ticket-readiness.\n")
    assert yaml.safe_load((directory / "ticket.yml").read_text(encoding="utf-8")) == {
        "ticket_id": "73",
        "ticket_name": "ticket-readiness",
        "current_definition": "ticket.md",
        "active": True,
        "replaced_by": [],
        "dependencies": [],
        "status": "pending",
        "active_team_ordinal": None,
        "worktree": None,
        "branch": None,
        "current_candidate": None,
    }
    events = [
        json.loads(line)
        for path in (state / "worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 1
    assert events[0]["kind"] == "ticket-registered"
    assert events[0]["ticket_id"] == "73"
    assert events[0]["evidence_refs"] == [
        ".graphtraj/state/tickets/73-ticket-readiness/ticket.md"
    ]


def test_installed_command_registers_non_coding_ticket_with_front_matter(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    issue = _write(
        project / "research-ticket.yml",
        _non_coding_ticket("74", "research-ticket", task_type="research"),
    )

    result = _run(
        installed_commands, project, "register", "--ticket-file", str(issue)
    )

    assert result.returncode == 0, result.stderr
    snapshot = (state / "tickets" / "74-research-ticket" / "ticket.md").read_text(
        encoding="utf-8"
    )
    assert snapshot.startswith("---\ntask_type: research\n---\n")
    assert snapshot.endswith("Investigate research-ticket.\n")


def test_installed_command_revises_non_coding_ticket_with_front_matter(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(
        installed_commands,
        project,
        _non_coding_ticket("74", "research-ticket", task_type="research"),
    )
    evidence = project / "research-revision.md"
    evidence.write_text("Research scope changed.\n", encoding="utf-8")
    revision = _write(
        project / "research-revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["research-revision.md"],
            "tickets": [
                {
                    **_non_coding_ticket(
                        "74", "research-ticket", task_type="analysis"
                    ),
                    "active": True,
                    "replaced_by": [],
                }
            ],
        },
    )

    result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )

    assert result.returncode == 0, result.stderr
    event = yaml.safe_load(result.stdout)
    state_record = yaml.safe_load(
        (state / "tickets" / "74-research-ticket" / "ticket.yml").read_text(
            encoding="utf-8"
        )
    )
    snapshot = (
        state
        / "tickets"
        / "74-research-ticket"
        / state_record["current_definition"]
    ).read_text(encoding="utf-8")
    assert state_record["current_definition"] == f"definitions/{event['event_id']}.md"
    assert snapshot.startswith("---\ntask_type: analysis\n---\n")


def test_installed_command_corrects_a_dependency_and_generates_current_readiness(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("1", "foundation"))
    _register(
        installed_commands,
        project,
        _ticket("2", "feature", dependencies=["1"]),
    )
    evidence = project / "validation.md"
    evidence.write_text("The feature is independent.\n", encoding="utf-8")
    revision = _write(
        project / "revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["validation.md"],
            "tickets": [
                {
                    **_ticket("2", "feature"),
                    "active": True,
                    "replaced_by": [],
                }
            ],
        },
    )

    result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )

    assert result.returncode == 0, result.stderr
    event = yaml.safe_load(result.stdout)
    ticket_directory = state / "tickets" / "2-feature"
    ticket_state = yaml.safe_load(
        (ticket_directory / "ticket.yml").read_text(encoding="utf-8")
    )
    assert ticket_state["dependencies"] == []
    assert ticket_state["current_definition"] == (
        f"definitions/{event['event_id']}.md"
    )
    assert (ticket_directory / ticket_state["current_definition"]).is_file()
    initial_snapshot = (ticket_directory / "ticket.md").read_text(encoding="utf-8")
    assert "# Ticket 2: Feature" in initial_snapshot
    assert "Dependencies: 1" in initial_snapshot
    assert initial_snapshot.endswith("Deliver feature.\n")
    graph = _run(installed_commands, project, "graph")
    assert graph.returncode == 0, graph.stderr
    assert yaml.safe_load(graph.stdout) == {
        "tickets": [
            {
                "ticket_id": "1",
                "ticket_name": "foundation",
                "status": "pending",
                "active": True,
                "ready": True,
                "dependencies": [],
                "replaced_by": [],
            },
            {
                "ticket_id": "2",
                "ticket_name": "feature",
                "status": "pending",
                "active": True,
                "ready": True,
                "dependencies": [],
                "replaced_by": [],
            },
        ]
    }
    assert not (state / "dag.md").exists()
    assert not (state / "task-map.yml").exists()


def test_installed_command_merges_two_tickets_into_one_new_ticket_atomically(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("1", "first-half"))
    _register(installed_commands, project, _ticket("2", "second-half"))
    evidence = project / "merge-validation.md"
    evidence.write_text(
        "The halves are not independently deliverable.\n", encoding="utf-8"
    )
    revision = _write(
        project / "merge.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["merge-validation.md"],
            "tickets": [
                {
                    **_ticket("1", "first-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_ticket("2", "second-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_ticket("3", "combined-ticket"),
                    "active": True,
                    "replaced_by": [],
                },
            ],
        },
    )

    result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )

    assert result.returncode == 0, result.stderr
    event = yaml.safe_load(result.stdout)
    assert event["affected_ticket_ids"] == ["1", "2", "3"]
    states = {
        path.parent.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (state / "tickets").glob("*/ticket.yml")
    }
    assert states["1-first-half"]["active"] is False
    assert states["1-first-half"]["replaced_by"] == ["3"]
    assert states["2-second-half"]["active"] is False
    assert states["2-second-half"]["replaced_by"] == ["3"]
    assert states["3-combined-ticket"]["active"] is True
    assert states["3-combined-ticket"]["current_definition"] == "ticket.md"
    graph = yaml.safe_load(_run(installed_commands, project, "graph").stdout)
    assert [ticket["ticket_id"] for ticket in graph["tickets"] if ticket["ready"]] == [
        "3"
    ]


def test_revision_keeps_created_ticket_evidence_unique_and_worldline_readable(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    _configure(project)
    _register(installed_commands, project, _ticket("1", "first-half"))
    _register(installed_commands, project, _ticket("2", "second-half"))
    created_evidence = ".graphtraj/state/tickets/3-combined-ticket/ticket.md"
    revision = _write(
        project / "merge-with-created-evidence.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": [created_evidence],
            "tickets": [
                {
                    **_ticket("1", "first-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_ticket("2", "second-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_ticket("3", "combined-ticket"),
                    "active": True,
                    "replaced_by": [],
                },
            ],
        },
    )

    revision_result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )
    worldline_result = run_process(
        [str(installed_commands.product), "worldline", "read"], cwd=project
    )

    assert revision_result.returncode == 0, revision_result.stderr
    assert worldline_result.returncode == 0, worldline_result.stderr
    event = json.loads(worldline_result.stdout.splitlines()[-1])
    assert event["evidence_refs"].count(created_evidence) == 1


def test_revision_rejects_an_active_dependency_on_an_inactive_ticket_without_changes(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("1", "foundation"))
    _register(
        installed_commands,
        project,
        _ticket("2", "feature", dependencies=["1"]),
    )
    ticket_states = {
        path: path.read_bytes()
        for path in (state / "tickets").glob("*/ticket.yml")
    }
    worldline = {
        path: path.read_bytes() for path in (state / "worldline").glob("*.jsonl")
    }
    evidence = project / "invalid-validation.md"
    evidence.write_text("This correction is incomplete.\n", encoding="utf-8")
    revision = _write(
        project / "invalid-revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["invalid-validation.md"],
            "tickets": [
                {
                    **_ticket("1", "foundation"),
                    "active": False,
                    "replaced_by": [],
                }
            ],
        },
    )

    result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )

    assert result.returncode == 1
    assert "inactive" in result.stderr
    assert {path: path.read_bytes() for path in ticket_states} == ticket_states
    assert {path: path.read_bytes() for path in worldline} == worldline
    assert not tuple((state / "tickets" / "1-foundation").glob("definitions/*"))


def test_revision_with_missing_evidence_rolls_back_ticket_and_worldline(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("1", "foundation"))
    state_path = state / "tickets" / "1-foundation" / "ticket.yml"
    before_state = state_path.read_bytes()
    shard = next((state / "worldline").glob("*.jsonl"))
    before_worldline = shard.read_bytes()
    revision = _write(
        project / "missing-evidence.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["missing.md"],
            "tickets": [
                {
                    **_ticket("1", "foundation", dependencies=[]),
                    "title": "Corrected Foundation",
                    "active": True,
                    "replaced_by": [],
                }
            ],
        },
    )

    result = _run(
        installed_commands, project, "revise", "--revision-file", str(revision)
    )

    assert result.returncode == 1
    assert state_path.read_bytes() == before_state
    assert shard.read_bytes() == before_worldline
    assert not tuple((state_path.parent / "definitions").glob("*.md"))


def test_installed_command_records_a_validated_ticket_state_change(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("1", "foundation"))
    evidence = project / "readiness.md"
    evidence.write_text("Main confirmed dispatch readiness.\n", encoding="utf-8")
    change = _write(
        project / "state-change.yml",
        {
            "ticket_id": "1",
            "status": "ready",
            "active_team_ordinal": None,
            "worktree": None,
            "branch": None,
            "current_candidate": None,
            "caused_by_event_ids": [],
            "evidence_refs": ["readiness.md"],
        },
    )

    result = _run(
        installed_commands, project, "update", "--state-file", str(change)
    )

    assert result.returncode == 0, result.stderr
    event = yaml.safe_load(result.stdout)
    assert event["kind"] == "ticket-state-changed"
    assert event["from_status"] == "pending"
    assert event["to_status"] == "ready"
    assert event["active_team_ordinal"] is None
    assert event["current_candidate"] is None
    assert set(event) == {
        "event_id",
        "captured_at",
        "kind",
        "caused_by_event_ids",
        "evidence_refs",
        "ticket_id",
        "from_status",
        "to_status",
        "active_team_ordinal",
        "worktree",
        "branch",
        "current_candidate",
    }
    current = yaml.safe_load(
        (state / "tickets" / "1-foundation" / "ticket.yml").read_text(
            encoding="utf-8"
        )
    )
    assert current["status"] == "ready"
    assert current["active_team_ordinal"] is None
    assert current["current_candidate"] is None


def test_generic_ticket_updates_cannot_unlock_dependents_without_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    _configure(project)
    _register(installed_commands, project, _ticket("1", "foundation"))
    _register(
        installed_commands,
        project,
        _ticket("2", "feature", dependencies=["1"]),
    )

    before = yaml.safe_load(_run(installed_commands, project, "graph").stdout)
    assert next(item for item in before["tickets"] if item["ticket_id"] == "2")[
        "ready"
    ] is False

    for status in (
        "ready",
        "implementing",
        "reviewing",
        "awaiting-integration",
    ):
        _change_status(installed_commands, project, "1", status)

    after = yaml.safe_load(_run(installed_commands, project, "graph").stdout)
    assert next(item for item in after["tickets"] if item["ticket_id"] == "2")[
        "ready"
    ] is False
