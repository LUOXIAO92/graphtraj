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


def _task(
    task_id: str,
    name: str,
    *,
    dependencies: list[str] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_name": name,
        "source": f"https://github.com/example/project/issues/{task_id}", "schema_version": 2, "parent_id": None, "disposition": "active", "replaced_by": [], "retirement_reason": None,
        "title": name.replace("-", " ").title(),
        "body": f"Deliver {name}.",
        "dependencies": dependencies or [],
    }


def _non_coding_task(
    task_id: str,
    name: str,
    *,
    task_type: str,
) -> dict[str, object]:
    return {
        **_task(task_id, name),
        "body": (
            "---\n"
            "task_type: {0}\n"
            "---\n\n"
            "Investigate {1}."
        ).format(task_type, name),
    }


def test_graph_keeps_legacy_parentage_unknown_without_prose_inference(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    """Legacy prose remains readable but cannot establish formal parentage."""
    project = temporary_git_repository
    _configure(project)
    bodies = [
        "## Parent\n\nhttps://github.com/example/project/issues/90\n\n## Scope\nSee #91.",
        "Parent: #91. Prior work #90 is a dependency, not membership.",
        "属于 #90、#91。Shared work.",
        "See #90; depends on #91.\n```\nParent: #92\n```",
        "Part of #91。Source task node. Prior result #90 stays a dependency.",
    ]
    for index, body in enumerate(bodies, 1):
        _register(installed_commands, project, {
            **_task(str(index), f"task-{index}", dependencies=[str(index - 1)] if index > 1 else []),
            "body": body,
        })
    result = _run(installed_commands, project, "graph")
    assert result.returncode == 0, result.stderr
    graph = yaml.safe_load(result.stdout)
    assert all(task["parent_known"] is False and "parent_id" not in task
               and task["schema_version"] == 1 for task in graph["tasks"])
    assert [task["dependencies"] for task in graph["tasks"]] == [[], ["1"], ["2"], ["3"], ["4"]]
    assert all(task["status"] == "pending" for task in graph["tasks"])


def _run(
    commands: InstalledCommands, project: Path, *arguments: str
):
    return run_process([str(commands.product), "task", *arguments], cwd=project)


def _register(
    commands: InstalledCommands,
    project: Path,
    task: dict[str, object],
) -> None:
    path = _write(project / "register.yml", task)
    result = _run(commands, project, "register", "--task-file", str(path))
    assert result.returncode == 0, result.stderr


def _change_status(
    commands: InstalledCommands,
    project: Path,
    task_id: str,
    status: str,
) -> None:
    evidence = project / "delivery-evidence.md"
    evidence.write_text("Main validated the current delivery fact.\n", encoding="utf-8")
    change = _write(
        project / "state-change.yml",
        {
            "task_id": task_id,
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


def test_installed_command_registers_an_accepted_issue_as_a_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    issue = _write(project / "issue.yml", _task("73", "task-readiness"))

    result = _run(
        installed_commands, project, "register", "--task-file", str(issue)
    )

    assert result.returncode == 0, result.stderr
    directory = state / "tasks" / "73-task-readiness"
    assert directory.is_dir()
    snapshot = (directory / "task.md").read_text(encoding="utf-8")
    assert "# Task 73: Task Readiness" in snapshot
    assert "Task name: task-readiness" in snapshot
    assert "Source: https://github.com/example/project/issues/73" in snapshot
    assert "Dependencies: none" in snapshot
    assert snapshot.endswith("Deliver task-readiness.\n")
    assert yaml.safe_load((directory / "task.yml").read_text(encoding="utf-8")) == {
        "task_id": "73",
        "task_name": "task-readiness",
        "current_definition": "task.md",
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
    assert events[0]["event"] == "task-registered"
    assert events[0]["task_id"] == "73"
    assert events[0]["evidence_refs"] == [
        ".graphtraj/state/tasks/73-task-readiness/task.md"
    ]


def test_installed_command_registers_an_accepted_task_without_an_engineer_tier(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    """Registration keeps difficulty and its budget without an Engineer tier."""
    project = temporary_git_repository
    state = _configure(project)
    issue = _write(
        project / "issue.yml",
        {
            **_task("77", "unified-engineer"),
            "body": (
                "---\n"
                "difficulty: medium\n"
                "difficulty_reason: One role source spans setup and dispatch\n"
                "execution_budget:\n"
                "  estimated_minutes:\n"
                "    implementation: 10\n"
                "    validation: 10\n"
                "    review: 5\n"
                "    total: 30\n"
                "  planned_sessions:\n"
                "    team_leader: 1\n"
                "    engineer: 1\n"
                "    standards_reviewer: 1\n"
                "    spec_reviewer: 1\n"
                "    delivery_state: 1\n"
                "  correction_rounds: 1\n"
                "  estimation_note: The accepted budget selects no Engineer role\n"
                "  on_exceed: Notify the caller and preserve the running Session\n"
                "---\n"
                "\n"
                "Deliver unified-engineer.\n"
            ),
        },
    )

    result = _run(
        installed_commands, project, "register", "--task-file", str(issue)
    )

    assert result.returncode == 0, result.stderr
    snapshot = (state / "tasks" / "77-unified-engineer" / "task.md").read_text(
        encoding="utf-8"
    )
    assert snapshot.startswith("---\ndifficulty: medium\n")
    assert "engineer_tier" not in snapshot


def test_installed_command_registers_non_coding_task_with_front_matter(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    issue = _write(
        project / "research-task.yml",
        _non_coding_task("74", "research-task", task_type="research"),
    )

    result = _run(
        installed_commands, project, "register", "--task-file", str(issue)
    )

    assert result.returncode == 0, result.stderr
    snapshot = (state / "tasks" / "74-research-task" / "task.md").read_text(
        encoding="utf-8"
    )
    assert snapshot.startswith("---\ntask_type: research\n---\n")
    assert snapshot.endswith("Investigate research-task.\n")


def test_installed_command_revises_non_coding_task_with_front_matter(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(
        installed_commands,
        project,
        _non_coding_task("74", "research-task", task_type="research"),
    )
    evidence = project / "research-revision.md"
    evidence.write_text("Research scope changed.\n", encoding="utf-8")
    revision = _write(
        project / "research-revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["research-revision.md"],
            "tasks": [
                {
                    **_non_coding_task(
                        "74", "research-task", task_type="analysis"
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
        (state / "tasks" / "74-research-task" / "task.yml").read_text(
            encoding="utf-8"
        )
    )
    snapshot = (
        state
        / "tasks"
        / "74-research-task"
        / state_record["current_definition"]
    ).read_text(encoding="utf-8")
    assert state_record["current_definition"] == f"definitions/{event['event_id']}.md"
    assert snapshot.startswith("---\ntask_type: analysis\n---\n")


def test_installed_command_revises_non_coding_task_with_source_front_matter(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    task = {
        **_non_coding_task("74", "research-task", task_type="research"),
        "body": (
            "---\n"
            "task_type: research\n"
            "Source: field-notes\n"
            "---\n\n"
            "Investigate research-task."
        ),
    }
    _register(installed_commands, project, task)
    directory = state / "tasks" / "74-research-task"
    initial_snapshot = (directory / "task.md").read_text(encoding="utf-8")
    assert initial_snapshot.startswith(
        "---\ntask_type: research\nSource: field-notes\n---\n"
    )
    assert "Source: https://github.com/example/project/issues/74" in initial_snapshot

    evidence = project / "source-revision.md"
    evidence.write_text("Research notes were extended.\n", encoding="utf-8")
    revision = _write(
        project / "source-revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["source-revision.md"],
            "tasks": [
                {
                    **task,
                    "body": task["body"] + "\n\nPreserve field notes.",
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
    state_record = yaml.safe_load((directory / "task.yml").read_text(encoding="utf-8"))
    revised_snapshot = (directory / state_record["current_definition"]).read_text(
        encoding="utf-8"
    )
    assert state_record["current_definition"].startswith("definitions/")
    assert (directory / "task.md").read_text(encoding="utf-8") == initial_snapshot
    assert revised_snapshot.startswith(
        "---\ntask_type: research\nSource: field-notes\n---\n"
    )
    assert "Source: https://github.com/example/project/issues/74" in revised_snapshot


def test_installed_command_corrects_a_dependency_and_generates_current_readiness(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _task("1", "foundation"))
    _register(
        installed_commands,
        project,
        _task("2", "feature", dependencies=["1"]),
    )
    evidence = project / "validation.md"
    evidence.write_text("The feature is independent.\n", encoding="utf-8")
    revision = _write(
        project / "revision.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["validation.md"],
            "tasks": [
                {
                    **_task("2", "feature"),
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
    task_directory = state / "tasks" / "2-feature"
    task_state = yaml.safe_load(
        (task_directory / "task.yml").read_text(encoding="utf-8")
    )
    assert task_state["dependencies"] == []
    assert task_state["current_definition"] == (
        f"definitions/{event['event_id']}.md"
    )
    assert (task_directory / task_state["current_definition"]).is_file()
    initial_snapshot = (task_directory / "task.md").read_text(encoding="utf-8")
    assert "# Task 2: Feature" in initial_snapshot
    assert "Dependencies: 1" in initial_snapshot
    assert initial_snapshot.endswith("Deliver feature.\n")
    graph = _run(installed_commands, project, "graph")
    assert graph.returncode == 0, graph.stderr
    projection = yaml.safe_load(graph.stdout)
    expected = {
        "tasks": [
            {
                "task_id": "1",
                "task_name": "foundation",
                "title": "Foundation",
                "status": "pending",
                "active": True,
                "ready": True,
                "dependencies": [],
                "replaced_by": [],
            },
            {
                "task_id": "2",
                "task_name": "feature",
                "title": "Feature",
                "status": "pending",
                "active": True,
                "ready": True,
                "dependencies": [],
                "replaced_by": [],
            },
        ]
    }
    for actual, wanted in zip(projection["tasks"], expected["tasks"], strict=True):
        assert {key: actual[key] for key in wanted} == wanted
    assert all(node["parent_known"] is False for node in projection["tasks"])
    assert not (state / "dag.md").exists()
    assert not (state / "task-map.yml").exists()


def test_installed_command_merges_two_tasks_into_one_new_task_atomically(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _task("1", "first-half"))
    _register(installed_commands, project, _task("2", "second-half"))
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
            "tasks": [
                {
                    **_task("1", "first-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_task("2", "second-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_task("3", "combined-task"),
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
    assert event["affected_task_ids"] == ["1", "2", "3"]
    states = {
        path.parent.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (state / "tasks").glob("*/task.yml")
    }
    assert states["1-first-half"]["active"] is False
    assert states["1-first-half"]["replaced_by"] == ["3"]
    assert states["2-second-half"]["active"] is False
    assert states["2-second-half"]["replaced_by"] == ["3"]
    assert states["3-combined-task"]["active"] is True
    assert states["3-combined-task"]["current_definition"] == "task.md"
    graph = yaml.safe_load(_run(installed_commands, project, "graph").stdout)
    assert [task["task_id"] for task in graph["tasks"] if task["ready"]] == [
        "3"
    ]


def test_revision_keeps_created_task_evidence_unique_and_worldline_readable(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    _configure(project)
    _register(installed_commands, project, _task("1", "first-half"))
    _register(installed_commands, project, _task("2", "second-half"))
    created_evidence = ".graphtraj/state/tasks/3-combined-task/task.md"
    revision = _write(
        project / "merge-with-created-evidence.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": [created_evidence],
            "tasks": [
                {
                    **_task("1", "first-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_task("2", "second-half"),
                    "active": False,
                    "replaced_by": ["3"],
                },
                {
                    **_task("3", "combined-task"),
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


def test_revision_rejects_an_active_dependency_on_an_inactive_task_without_changes(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _task("1", "foundation"))
    _register(
        installed_commands,
        project,
        _task("2", "feature", dependencies=["1"]),
    )
    task_states = {
        path: path.read_bytes()
        for path in (state / "tasks").glob("*/task.yml")
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
            "tasks": [
                {
                    **_task("1", "foundation"),
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
    assert {path: path.read_bytes() for path in task_states} == task_states
    assert {path: path.read_bytes() for path in worldline} == worldline
    assert not tuple((state / "tasks" / "1-foundation").glob("definitions/*"))


def test_revision_with_missing_evidence_rolls_back_task_and_worldline(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _task("1", "foundation"))
    state_path = state / "tasks" / "1-foundation" / "task.yml"
    before_state = state_path.read_bytes()
    shard = next((state / "worldline").glob("*.jsonl"))
    before_worldline = shard.read_bytes()
    revision = _write(
        project / "missing-evidence.yml",
        {
            "product_preserving": True,
            "caused_by_event_ids": [],
            "evidence_refs": ["missing.md"],
            "tasks": [
                {
                    **_task("1", "foundation", dependencies=[]),
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


def test_installed_command_records_a_validated_task_state_change(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _task("1", "foundation"))
    evidence = project / "readiness.md"
    evidence.write_text("Main confirmed dispatch readiness.\n", encoding="utf-8")
    change = _write(
        project / "state-change.yml",
        {
            "task_id": "1",
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
    assert event["event"] == "task-state-changed"
    assert event["from_status"] == "pending"
    assert event["to_status"] == "ready"
    assert event["active_team_ordinal"] is None
    assert event["current_candidate"] is None
    assert set(event) == {
        "event_id",
        "captured_at",
        "event",
        "caused_by_event_ids",
        "evidence_refs",
        "task_id",
        "from_status",
        "to_status",
        "active_team_ordinal",
        "worktree",
        "branch",
        "current_candidate",
    }
    current = yaml.safe_load(
        (state / "tasks" / "1-foundation" / "task.yml").read_text(
            encoding="utf-8"
        )
    )
    assert current["status"] == "ready"
    assert current["active_team_ordinal"] is None
    assert current["current_candidate"] is None


def test_generic_task_updates_cannot_unlock_dependents_without_integration(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    _configure(project)
    _register(installed_commands, project, _task("1", "foundation"))
    _register(
        installed_commands,
        project,
        _task("2", "feature", dependencies=["1"]),
    )

    before = yaml.safe_load(_run(installed_commands, project, "graph").stdout)
    assert next(item for item in before["tasks"] if item["task_id"] == "2")[
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
    assert next(item for item in after["tasks"] if item["task_id"] == "2")[
        "ready"
    ] is False
