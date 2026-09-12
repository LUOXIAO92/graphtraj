from __future__ import annotations

import json
import os
import shutil
import tomllib
from pathlib import Path

import yaml
import pytest

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness


def _register_ready_inline_ticket(harness_root: Path, product: Path) -> None:
    ticket_input = harness_root / "ticket.yml"
    ticket_input.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "75",
                "ticket_name": "inline-specialist",
                "source": "https://github.com/example/project/issues/75",
                "title": "Run an inline specialist",
                "body": "Investigate the accepted Ticket.",
                "dependencies": [],
            },
            sort_keys=False,
        )
    )
    registered = run_process(
        [str(product), "ticket", "register", "--ticket-file", str(ticket_input)],
        cwd=harness_root,
    )
    assert registered.returncode == 0, registered.stderr
    readiness = harness_root / "readiness.md"
    readiness.write_text("The registered Ticket has no unmet dependencies.\n")
    state_change = harness_root / "state-change.yml"
    state_change.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "75",
                "status": "ready",
                "active_team_ordinal": None,
                "worktree": None,
                "branch": None,
                "current_candidate": None,
                "caused_by_event_ids": [],
                "evidence_refs": ["readiness.md"],
            },
            sort_keys=False,
        )
    )
    ready = run_process(
        [str(product), "ticket", "update", "--state-file", str(state_change)],
        cwd=harness_root,
    )
    assert ready.returncode == 0, ready.stderr


def test_installed_runner_applies_inline_settings_to_an_existing_preset(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)

    roles_file = harness_root / ".graphtraj" / "roles.yml"
    roles_before = roles_file.read_bytes()
    batch = harness_root / "team-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"75\"\n"
        "    ticket_name: inline-specialist\n"
        "    role:\n"
        "      coding-team.team-leader:\n"
        "        runtime: codex\n"
        "        model: gpt-5.6-luna\n"
        "        reasoning_effort: high\n"
        "        allow_runtime_swarm: false\n"
    )
    environment.update(
        {
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_APPEND_LOG": "1",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    leader_records = [record for record in records if record["role"] == "team-leader"]
    assert leader_records
    assert all(
        record["argv"][record["argv"].index("--model") + 1] == "gpt-5.6-luna"
        for record in leader_records
    )
    assert all(
        any(argument.startswith("agents=") and "enabled = false" in argument
            for argument in record["argv"])
        for record in leader_records
    )
    assert "resume" not in leader_records[0]["argv"]
    assert all("resume" in record["argv"] for record in leader_records[1:])
    assert all(
        any(
            argument == "-c"
            and record["argv"][index + 1] == 'model_reasoning_effort="high"'
            for index, argument in enumerate(record["argv"][:-1])
        )
        for record in leader_records
    )
    assert roles_file.read_bytes() == roles_before


@pytest.mark.parametrize(
    ("reasoning_effort", "expected_code"),
    (("unsupported", "invalid-config"), (True, "invalid-input")),
)
def test_installed_runner_rejects_invalid_inline_reasoning_effort(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    reasoning_effort: object,
    expected_code: str,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)
    batch = harness_root / "invalid-reasoning-effort.yml"
    batch.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "ticket_id": "75",
                        "ticket_name": "inline-specialist",
                        "role": {
                            "coding-team.team-leader": {
                                "runtime": "codex",
                                "model": "gpt-5.6-luna",
                                "reasoning_effort": reasoning_effort,
                            }
                        },
                    }
                ]
            },
            sort_keys=False,
        )
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 1
    response = yaml.safe_load(result.stdout)
    error = response.get("error") or response["tasks"][0]["error"]
    assert error["code"] == expected_code
    assert "reasoning_effort" in error["message"]
    assert not fake_codex.log_file.exists()


@pytest.mark.parametrize(
    ("leader_decision", "expected_status", "round_closed", "runner_succeeds", "swarm"),
    (
        ("accept", "awaiting-integration", True, True, None),
        ("accept", "awaiting-integration", True, True, False),
        ("accept", "awaiting-integration", True, True, True),
        ("reject", "reviewing", False, True, None),
        ("conflict", "reviewing", False, True, None),
        ("tamper", "reviewing", False, False, None),
        ("rework", "awaiting-integration", True, True, None),
        ("process", "reviewing", False, True, None),
        ("main", "reviewing", False, True, None),
        ("product", "reviewing", False, True, None),
        ("invalid-evidence", "reviewing", False, False, None),
        ("mismatched-report", "reviewing", False, False, None),
        ("no-findings", "reviewing", False, False, None),
    ),
)
def test_installed_runner_obeys_the_explicit_leader_decision_for_a_run_free_team_round(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    leader_decision: str,
    expected_status: str,
    round_closed: bool,
    runner_succeeds: bool,
    swarm: bool | None,
) -> None:
    harness_root, worktree_root, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    roles_file = harness_root / '.graphtraj' / 'roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['coding-team']['team-leader'].pop('allow_runtime_swarm', None)
    if swarm is not None:
        roles['roles']['coding-team']['team-leader']['allow_runtime_swarm'] = swarm
    roles_file.write_text(yaml.safe_dump(roles))
    policy_log = tmp_path / 'policy.jsonl'
    environment['FAKE_CODEX_POLICY_LOG'] = str(policy_log)
    main_config = harness_root / '.codex' / 'config.toml'
    main_config.write_text('developer_instructions = "User-owned Main instructions."\n')
    main_before = main_config.read_bytes()
    ticket_input = harness_root / "ticket.yml"
    ticket_input.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "74",
                "ticket_name": "complete-team-round",
                "source": "https://github.com/example/project/issues/74",
                "title": "Complete Team Round",
                "body": "Deliver one complete Team Round.",
                "dependencies": [],
            },
            sort_keys=False,
        )
    )
    registered = run_process(
        [str(installed_commands.product), "ticket", "register", "--ticket-file", str(ticket_input)],
        cwd=harness_root,
    )
    assert registered.returncode == 0, registered.stderr
    ticket_directory = harness_root / ".graphtraj" / "state" / "tickets" / "74-complete-team-round"
    readiness = harness_root / "readiness.md"
    readiness.write_text("The registered Ticket has no unmet dependencies.\n")
    state_change = harness_root / "state-change.yml"
    state_change.write_text(
        yaml.safe_dump(
            {
                "ticket_id": "74",
                "status": "ready",
                "active_team_ordinal": None,
                "worktree": None,
                "branch": None,
                "current_candidate": None,
                "caused_by_event_ids": [],
                "evidence_refs": ["readiness.md"],
            },
            sort_keys=False,
        )
    )
    ready = run_process(
        [str(installed_commands.product), "ticket", "update", "--state-file", str(state_change)],
        cwd=harness_root,
    )
    assert ready.returncode == 0, ready.stderr

    batch = harness_root / "batch.yml"
    batch_bytes = (
        "tasks:\n"
        "  - ticket_id: \"74\"\n"
        "    ticket_name: complete-team-round\n"
        "    role: coding-team.team-leader\n"
        "    instruction: Keep the accepted Ticket exact.\n"
    ).encode()
    batch.write_bytes(batch_bytes)
    environment.update(
        {
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "FAKE_CODEX_LEADER_DECISION": (
                "reject" if leader_decision == "tamper" else
                "rework" if leader_decision in {
                    "process", "main", "product", "invalid-evidence", "mismatched-report", "no-findings"
                } else leader_decision
            ),
            "FAKE_CODEX_REWORK_CASE": leader_decision,
            "FAKE_CODEX_STATE_TAMPER": (
                "accepted" if leader_decision == "tamper" else ""
            ),
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=45,
    )

    assert (launched.returncode == 0) is runner_succeeds, launched.stderr
    assert main_config.read_bytes() == main_before
    assert 'max_concurrent_threads_per_session' not in tomllib.loads(main_before.decode()).get('agents', {})
    calls = [json.loads(line) for line in policy_log.read_text().splitlines()]
    worktree = worktree_root / "74-complete-team-round"
    for call in calls:
        leader = call['role'] == 'team-leader'
        filesystem = call['settings']['permissions'][call['settings']['default_permissions']]['filesystem']
        assert filesystem[':workspace_roots']['.'] == (
            'read' if call['role'] in {'standards-reviewer', 'spec-reviewer'} else 'write'
        )
        assert filesystem[':workspace_roots']['CONTEXT.md'] == 'read'
        assert filesystem[':workspace_roots']['docs'] == 'read'
        required_skills = {
            'team-leader': {'handoff'},
            'engineer-junior': {'implement', 'ponytail', 'tdd'},
            'standards-reviewer': set(), 'spec-reviewer': set(), 'delivery-state': set(),
        }
        assert {
            Path(skill['path']).parent.name
            for skill in call['settings']['skills']['config'] if skill['enabled']
        } == required_skills[call['role']]
        registration = harness_root / '.graphtraj/runner/sessions/74-complete-team-round@l1/child-registration.yml'
        batch_directory = harness_root / '.graphtraj/state/batches'
        assert (filesystem.get(str(registration)) == 'write') is leader
        assert (filesystem.get(str(batch_directory)) == 'write') is leader
        report_names = {
            "engineer-junior": {"engineer.md", "validation.md"},
            "standards-reviewer": {"standards.md"},
            "spec-reviewer": {"spec.md"},
            "team-leader": {"leader.md"},
        }.get(call["role"])
        report_writes = {
            path
            for path, access in filesystem.items()
            if access == "write"
            and (
                path.startswith(str(ticket_directory))
                or path.startswith(str(worktree / ".state"))
            )
        }
        if report_names is None:
            assert not report_writes
        else:
            assert len(report_writes) == len(report_names)
            canonical = {
                Path(path).relative_to(ticket_directory)
                for path in report_writes
                if path.startswith(str(ticket_directory))
            }
            assert not {
                path
                for path in report_writes
                if path.startswith(str(worktree / ".state"))
            }
            assert {path.name for path in canonical} == report_names
            if call["role"] in {"engineer-junior", "team-leader"}:
                assert canonical == {
                    Path("teams") / "1" / "rounds" / call["round"] / name
                    for name in report_names
                }
        assert "hooks" not in call["settings"]
        assert call['settings']['agents']['enabled'] is (leader and swarm is not False)
        assert 'max_concurrent_threads_per_session' not in call['settings']['agents']
        assert 'max_depth' not in call['settings']['agents']
    retained_directory = harness_root / ".graphtraj" / "state" / "batches"
    retained_batches = list(retained_directory.glob("*.yml"))
    assert len(retained_batches) == (5 if leader_decision == "rework" else 3)
    worktree = worktree_root / "74-complete-team-round"
    if runner_succeeds:
        output = yaml.safe_load(launched.stdout)
        assert "run_id" not in output
        retained = Path(output["retained_batch_file"])
        assert retained.parent == retained_directory
        assert retained.read_bytes() == batch_bytes
        assert output["tasks"][0]["worktree_path"] == str(worktree.resolve())
    wait_for_file(ticket_directory / "teams" / "1" / "rounds" / "1" / "leader.md", 15)

    current = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
    team = yaml.safe_load((ticket_directory / "teams" / "1" / "team.yml").read_text())
    assert current["status"] == expected_status
    assert current["active_team_ordinal"] == 1
    assert current["worktree"] == ".graphtraj/.agent-worktrees/74-complete-team-round"
    assert current["branch"] == "agent/74-complete-team-round"
    assert len(current["current_candidate"]) == 40
    assert set(team) == {
        "team_ordinal", "status", "members", "current_round", "started_at"
    }
    assert team["team_ordinal"] == 1
    assert team["status"] == "active"
    assert team["current_round"] == (2 if leader_decision == "rework" else 1)
    assert set(team["members"]) == {
        "team_leader",
        "engineer",
        "standards_reviewer",
        "spec_reviewer",
    }
    assert all(set(member) == {"role", "session_ref"} for member in team["members"].values())
    assert all(member["session_ref"] for member in team["members"].values())
    round_directory = ticket_directory / "teams" / "1" / "rounds" / "1"
    assert {path.name for path in round_directory.iterdir()} == {
        "engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"
    }
    assert (round_directory.stat().st_mode & 0o222 == 0) is round_closed
    assert all((path.stat().st_mode & 0o222 == 0) is round_closed for path in round_directory.iterdir())
    traces = list((ticket_directory / "teams" / "1" / "traces").glob("*/events.jsonl"))
    assert len(traces) == 5
    assert all(
        json.loads(trace.read_text().splitlines()[0])
        == {"type": "runtime", "runtime": "codex"}
        for trace in traces
    )
    mappings = [
        yaml.safe_load(path.read_text())
        for path in (harness_root / ".graphtraj" / "runner" / "sessions").glob("*/mapping.yml")
    ]
    assert len(mappings) == 5
    assert all("run_id" not in mapping and "turn" not in mapping for mapping in mappings)
    leader_alias = next(mapping["alias"] for mapping in mappings if mapping["role"] == "team-leader")
    delivery_state_mappings = [mapping for mapping in mappings if mapping["role"] == "delivery-state"]
    assert len(delivery_state_mappings) == 1
    assert delivery_state_mappings[0]["alias"] not in {
        member["session_ref"] for member in team["members"].values()
    }
    assert all(
        mapping["parent"] == leader_alias
        for mapping in mappings
        if mapping["role"] not in {"team-leader", "delivery-state"}
    )
    assert not list(ticket_directory.rglob("turn-*"))
    assert not (ticket_directory / "metadata.yml").exists()
    assert not (ticket_directory / "handoff.md").exists()
    assert not (ticket_directory / "reviews").exists()
    assert not (harness_root / ".graphtraj" / "state" / "runs").exists()
    assert not any(path.name in {"ledger.yml", "dag.md", "history.jsonl"} for path in ticket_directory.rglob("*"))
    worldline = [
        json.loads(line)
        for shard in (harness_root / ".graphtraj" / "state" / "worldline").glob("*.jsonl")
        for line in shard.read_text().splitlines()
    ]
    if not runner_succeeds:
        assert worldline[-1]["kind"] == "team-member-started"
        assert not any(event["kind"].startswith("team-round-") for event in worldline)
    else:
        assert worldline[-1]["kind"] == (
            "team-round-accepted" if round_closed else "team-round-rejected"
        )
    started = next(event for event in worldline if event["kind"] == "team-started")
    assert team["started_at"] == started["captured_at"]
    assert all(event["caused_by_event_ids"] for event in worldline[2:])
    assert all(path.stat().st_mode & 0o222 == 0 for path in retained_batches)
    if leader_decision == "rework":
        second = round_directory.parent / "2"
        assert {path.name for path in second.iterdir()} == {path.name for path in round_directory.iterdir()}
        assert all(path.stat().st_mode & 0o222 == 0 for path in second.iterdir())
        rejected = next(event for event in worldline if event["kind"] == "team-round-implementation-rejected")
        rework = next(event for event in worldline if event["kind"] == "team-round-rework-started")
        candidates = [event for event in worldline if event["kind"] == "candidate-ready-for-review"]
        assert rework["caused_by_event_ids"] == [rejected["event_id"]]
        assert candidates[1]["caused_by_event_ids"] == [rework["event_id"]]
        assert candidates[0]["candidate"] != candidates[1]["candidate"] == current["current_candidate"]
        assert all(candidates[0]["candidate"] in path.read_text() for path in round_directory.iterdir())
        assert all(candidates[1]["candidate"] in path.read_text() for path in second.iterdir())
        assert worldline[-1]["team_round"] == 2
        assert team["members"]["engineer"]["role"] == "engineer-junior"
        assert len(mappings) == 5
        observed = [
            json.loads(line)
            for trace in traces for line in trace.read_text().splitlines()
            if line.startswith("{") and json.loads(line).get("type") == "report-observed"
        ]
        for name in ("engineer.md", "validation.md", "leader.md"):
            assert any(
                event["path"] == "teams/1/rounds/2/" + name
                and current["current_candidate"] in event["content"]
                for event in observed
            )
        for seat in team["members"].values():
            trace = ticket_directory / "teams" / "1" / "traces" / seat["session_ref"] / "events.jsonl"
            assert trace.read_text().count('"type": "runner-execution-start"') >= 2
    else:
        assert not (round_directory.parent / "2").exists()


def test_installed_runner_rejects_non_run_free_main_batch_fields(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    task = {
        "ticket_id": "74",
        "ticket_name": "complete-team-round",
        "role": "team-leader",
    }
    invalid = [
        {"run_id": None, "tasks": [task]},
        {"tasks": [{**task, "review_round": 1}]},
        {"tasks": [{**task, "report_file": ".state/reviews/report.md"}]},
        {"tasks": [{**task, "skills": ["tdd"]}]},
        {"tasks": [{**task, "ticket_file": "ticket.md"}]},
        {"tasks": [{**task, "unexpected": True}]},
    ]

    for index, document in enumerate(invalid):
        batch = harness_root / "invalid-{0}.yml".format(index)
        batch.write_text(yaml.safe_dump(document, sort_keys=False))
        result = run_process(
            [str(installed_commands.runner), "--batch-input", str(batch)],
            cwd=harness_root,
            env=environment,
        )
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"

    assert not (harness_root / ".graphtraj" / "state" / "batches").exists()


@pytest.mark.parametrize("startup_failure", ["unsupported-runtime", "missing-child-batch"])
def test_installed_runner_retries_an_unregistered_team_and_preserves_history(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, startup_failure,
):
    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)
    batch = harness_root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '75', 'ticket_name': 'inline-specialist', 'role': 'team-leader',
    }]}))
    if startup_failure == 'unsupported-runtime':
        environment['FAKE_CODEX_UNSUPPORTED'] = '1'
    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness_root, env=environment,
    )
    assert result.returncode == 1
    error = yaml.safe_load(result.stdout)['tasks'][0]['error']
    if startup_failure == 'unsupported-runtime':
        assert error['code'] == 'invalid-config'
        assert not fake_codex.log_file.exists()
    else:
        assert 'did not register its required direct child Batch' in error['message']

    state_root = harness_root / '.graphtraj' / 'state'
    ticket_directory = state_root / 'tickets' / '75-inline-specialist'
    team_directory = ticket_directory / 'teams' / '1'
    ticket_before = (ticket_directory / 'ticket.yml').read_bytes()
    current = yaml.safe_load(ticket_before)
    assert current['status'] == 'ready'
    assert current['active_team_ordinal'] is None
    assert current['current_candidate'] is None
    assert not (team_directory / 'team.yml').exists()
    history_roots = [
        state_root / 'batches',
        harness_root / '.graphtraj' / 'runner' / 'sessions',
        team_directory / 'traces',
    ]
    retained = {
        path: path.read_bytes()
        for directory in history_roots for path in directory.rglob('*') if path.is_file()
    }
    assert list((team_directory / 'traces').glob('*/events.jsonl'))

    environment.pop('FAKE_CODEX_UNSUPPORTED', None)
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    retried = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness_root, env=environment, timeout=45,
    )
    assert retried.returncode == 0, retried.stdout + retried.stderr
    current = yaml.safe_load((ticket_directory / 'ticket.yml').read_text())
    assert current['status'] == 'awaiting-integration'
    assert current['active_team_ordinal'] == 1
    assert current['current_candidate']
    team = yaml.safe_load((team_directory / 'team.yml').read_text())
    assert team['members']['team_leader']['session_ref'].endswith('@l2')
    assert all(path.read_bytes() == content for path, content in retained.items())
    accepted_ticket = (ticket_directory / 'ticket.yml').read_bytes()
    accepted_team = (team_directory / 'team.yml').read_bytes()

    reopened = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness_root, env=environment,
    )
    assert reopened.returncode == 1
    assert yaml.safe_load(reopened.stdout)['tasks'][0]['error']['code'] == 'ticket-already-live'
    assert (ticket_directory / 'ticket.yml').read_bytes() == accepted_ticket
    assert (team_directory / 'team.yml').read_bytes() == accepted_team


@pytest.mark.skipif(
    os.environ.get('CODEX_SANDBOX_ACCEPTANCE') != '1' or shutil.which('codex') is None,
    reason='set CODEX_SANDBOX_ACCEPTANCE=1 with a Codex sandbox executable; no model is used',
)
def test_installed_leader_registers_children_inside_the_codex_sandbox(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)
    batch = harness_root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '75', 'ticket_name': 'inline-specialist', 'role': 'team-leader',
    }]}))
    wrapper = tmp_path / 'sandbox-child-runner'
    wrapper.write_text('#!' + str(installed_commands.runner.parent / 'python') + '\n' + '''
import os, subprocess, sys, tomllib
from pathlib import Path
import yaml
from graphtraj.codex_adapter import _toml_value

registration = Path(os.environ['GRAPHTRAJ_PARENT_REGISTRATION'])
launch = yaml.safe_load((registration.parent / 'launch.yml').read_text())
arguments = launch['adapter_request']['arguments']
settings = {}
for index, argument in enumerate(arguments[:-1]):
    if argument == '-c':
        settings.update(tomllib.loads(arguments[index + 1]))
profile = settings['default_permissions']
filesystem = settings['permissions'][profile]['filesystem']
targets = [Path(path) for path, access in filesystem.items() if access == 'write']
assert registration in targets
assert len(targets) == 2
assert registration.parent not in targets
command = [os.environ['TEST_CODEX_SANDBOX'], 'sandbox', '-C', str(Path.cwd()), '-P', profile]
# The test Harness is below the OS temp directory, which :workspace normally
# permits. Match a real separated Harness by making its root read-only first.
filesystem[os.environ['GRAPHTRAJ_HARNESS_ROOT']] = 'read'
allowed_permissions = 'permissions=' + _toml_value(settings['permissions'])
for target in targets:
    filesystem[str(target)] = 'read'
denied_permissions = 'permissions=' + _toml_value(settings['permissions'])
denied = subprocess.run(command + ['-c', denied_permissions, '--', os.environ['TEST_INSTALLED_RUNNER'], *sys.argv[1:]],
                        text=True, capture_output=True)
assert denied.returncode == 1, denied.stdout + denied.stderr
assert denied.stdout, denied.stderr
assert yaml.safe_load(denied.stdout)['error']['code'] == 'operation-failed'
assert not registration.exists()
completed = subprocess.run(command + ['-c', allowed_permissions, '--', os.environ['TEST_INSTALLED_RUNNER'], *sys.argv[1:]],
                           text=True, capture_output=True)
sys.stdout.write(completed.stdout)
sys.stderr.write(completed.stderr)
if completed.returncode == 0:
    result = yaml.safe_load(completed.stdout)
    assert Path(result['retained_batch_file']).read_bytes() == Path(sys.argv[-1]).read_bytes()
    registered = yaml.safe_load(registration.read_text())
    assert registered['tasks'] == result['tasks']
    assert registered['retained_batch_file'] == result['retained_batch_file']
raise SystemExit(completed.returncode)
''')
    wrapper.chmod(0o755)
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
        FAKE_CODEX_POLICY_LOG=str(tmp_path / 'policy.jsonl'),
        GRAPHTRAJ_AGENT_RUNNER=str(wrapper),
        TEST_CODEX_SANDBOX=shutil.which('codex'),
        TEST_INSTALLED_RUNNER=str(installed_commands.runner),
    )
    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness_root, env=environment, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness_root / '.graphtraj/state/tickets/75-inline-specialist/ticket.yml'
    assert yaml.safe_load(ticket.read_text())['status'] == 'awaiting-integration'


def test_installed_runner_runs_a_main_inline_specialist_without_creating_a_preset(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    harness_root, _, integration, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)

    roles_file = harness_root / ".graphtraj" / "roles.yml"
    roles_before = roles_file.read_bytes()
    batch = harness_root / "inline-specialist.yml"
    batch_bytes = (
        "tasks:\n"
        "  - ticket_id: \"75\"\n"
        "    ticket_name: inline-specialist\n"
        "    role:\n"
        "      investigation-specialist:\n"
        "        runtime: codex\n"
        "        model: gpt-5.6-luna\n"
        "    instruction: Inspect the Ticket without joining its Team.\n"
    ).encode()
    batch.write_bytes(batch_bytes)
    environment.update(
        {
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_CAPTURE_CONNECTION": "1",
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    output = yaml.safe_load(launched.stdout)
    task = output["tasks"][0]
    assert task["role"] == "investigation-specialist"
    assert task["launch_status"] == "completed"
    retained = Path(output["retained_batch_file"])
    assert retained.read_bytes() == batch_bytes
    assert retained.stat().st_mode & 0o222 == 0
    assert roles_file.read_bytes() == roles_before
    runtime = json.loads(fake_codex.log_file.read_text())
    assert runtime["cwd"] == str(integration)
    permissions = tomllib.loads(next(
        argument for argument in runtime['argv'] if argument.startswith('permissions=')
    ))['permissions']
    assert all(
        access != 'write'
        for profile in permissions.values()
        for path, access in profile['filesystem'].items()
        if Path(path).is_absolute()
    )
    assert "Investigate the accepted Ticket." in runtime["stdin"]
    assert "Inspect the Ticket without joining its Team." in runtime["stdin"]
    assert runtime["connection"]["base_url"] is None
    assert any(
        argument.startswith("agents=") and "enabled = false" in argument
        for argument in runtime["argv"]
    )
    session = yaml.safe_load(
        (
            harness_root
            / ".graphtraj"
            / "runner"
            / "sessions"
            / task["alias"]
            / "mapping.yml"
        ).read_text()
    )
    assert session["role"] == "investigation-specialist"
    assert session["parent"] is None
    assert (
        harness_root
        / ".graphtraj"
        / "runner"
        / "sessions"
        / task["alias"]
        / "events.jsonl"
    ).is_file()
    ticket_directory = (
        harness_root
        / ".graphtraj"
        / "state"
        / "tickets"
        / "75-inline-specialist"
    )
    current = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
    assert current["active_team_ordinal"] is None
    assert not (ticket_directory / "teams").exists()


@pytest.mark.parametrize("role_name", ("dependency-reviewer", "engineer-specialist"))
def test_installed_runner_keeps_new_inline_role_names_outside_formal_team_policy(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role_name: str,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)

    batch = harness_root / (role_name + ".yml")
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"75\"\n"
        "    ticket_name: inline-specialist\n"
        "    role:\n"
        "      {0}:\n"
        "        runtime: codex\n"
        "        model: gpt-5.6-luna\n"
        "    instruction: Inspect the Ticket without formal Team work.\n".format(role_name)
    )
    policy_log = tmp_path / "temporary-policy.jsonl"
    environment.update(
        {
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_POLICY_LOG": str(policy_log),
            "FAKE_CODEX_CAPTURE_ENV": (
                "GRAPHTRAJ_REVIEW_CANDIDATE,GRAPHTRAJ_REVIEW_COMPARISON,"
                "GRAPHTRAJ_REVIEW_BRIEF,GRAPHTRAJ_REVIEW_REPORT"
            ),
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    runtime = json.loads(fake_codex.log_file.read_text())
    assert runtime["role"] == role_name
    assert "Write the fixed candidate" not in runtime["stdin"]
    assert "Review brief:" not in runtime["stdin"]
    assert not any(runtime["environment"].values())

    policy = json.loads(policy_log.read_text().splitlines()[0])
    assert policy["settings"]["agents"]["enabled"] is False
    assert "hooks" not in policy["settings"]


@pytest.mark.parametrize(
    ("specialist_environment", "specialist_role", "serial"),
    (
        ("FAKE_CODEX_INLINE_SPECIALIST", "dependency-reviewer", False),
        ("FAKE_CODEX_INLINE_SPECIALIST", "engineer-specialist", False),
        ("FAKE_CODEX_FINAL_INLINE_SPECIALIST", "investigation-specialist", False),
        ("FAKE_CODEX_FINAL_INLINE_SPECIALIST", "investigation-specialist", True),
    ),
)
def test_installed_runner_runs_a_team_leader_inline_specialist_outside_the_team(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    specialist_environment: str,
    specialist_role: str,
    serial: bool,
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    _register_ready_inline_ticket(harness_root, installed_commands.product)

    roles_file = harness_root / ".graphtraj" / "roles.yml"
    roles_before = roles_file.read_bytes()
    batch = harness_root / "team-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"75\"\n"
        "    ticket_name: inline-specialist\n"
        "    role: team-leader\n"
    )
    environment.update(
        {
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            specialist_environment: "1",
            "FAKE_CODEX_INLINE_ROLE": specialist_role,
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
            "FAKE_CODEX_CAPTURE_ROLE": "1",
            "FAKE_CODEX_APPEND_LOG": "1",
        }
    )

    if serial:
        config_file = harness_root / ".graphtraj" / "config.yml"
        config = yaml.safe_load(config_file.read_text())
        config["agent_runner"]["max_concurrency"] = 1
        config_file.write_text(yaml.safe_dump(config))
        environment["FAKE_CODEX_SERIAL_TEAM"] = "1"

    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=45,
    )

    assert launched.returncode == 0, launched.stderr
    ticket_directory = (
        harness_root
        / ".graphtraj"
        / "state"
        / "tickets"
        / "75-inline-specialist"
    )
    team = yaml.safe_load((ticket_directory / "teams" / "1" / "team.yml").read_text())
    mappings = [
        yaml.safe_load(path.read_text())
        for path in (harness_root / ".graphtraj" / "runner" / "sessions").glob(
            "*/mapping.yml"
        )
    ]
    leader = next(mapping for mapping in mappings if mapping["role"] == "team-leader")
    specialist = next(
        mapping
        for mapping in mappings
        if mapping["role"] == specialist_role
    )
    assert specialist["parent"] == leader["alias"]
    assert specialist["alias"] not in {
        member["session_ref"] for member in team["members"].values()
    }
    assert (
        ticket_directory
        / "teams"
        / "1"
        / "traces"
        / specialist["alias"]
        / "events.jsonl"
    ).is_file()
    retained = [
        yaml.safe_load(path.read_text())
        for path in (harness_root / ".graphtraj" / "state" / "batches").glob("*.yml")
    ]
    assert any(
        task["role"]
        == {
            specialist_role: {
                "runtime": "codex",
                "model": "gpt-5.6-luna",
            }
        }
        for retained_batch in retained
        for task in retained_batch["tasks"]
    )
    assert roles_file.read_bytes() == roles_before
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    leader_records = [record for record in records if record["role"] == "team-leader"]
    assert len(leader_records) == (6 if serial else 4)
    assert all("resume" in record["argv"] for record in leader_records[1:])


@pytest.mark.parametrize(
    "role",
    (
        {
            "coding-team.team-leader": {
                "runtime": "codex", "model": "operator-model",
                "developer_instructions": "Replace the fixed policy.",
            },
        },
        {
            "coding-team.spec-reviewer": {
                "runtime": "codex", "model": "operator-model",
                "allow_runtime_swarm": True,
            },
        },
        {"other-team.team-leader": {"runtime": "codex", "model": "operator-model"}},
        {
            "first-specialist": {
                "runtime": "codex",
                "model": "gpt-5.6-luna",
            },
            "second-specialist": {
                "runtime": "codex",
                "model": "gpt-5.6-luna",
            },
        },
        {
            "investigation-specialist": {
                "runtime": "codex",
                "model": "gpt-5.6-luna",
                "dispatch_depth": 2,
                "agents": {"enabled": True},
            }
        },
    ),
)
def test_installed_runner_rejects_malformed_inline_roles_before_retaining_a_batch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: dict[str, object],
) -> None:
    harness_root, _, _, environment = configure_harness(
        installed_commands,
        temporary_git_repository,
        fake_codex,
        tmp_path,
    )
    roles_file = harness_root / ".graphtraj" / "roles.yml"
    roles_before = roles_file.read_bytes()
    batch = harness_root / "invalid-inline-role.yml"
    batch.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "ticket_id": "75",
                        "ticket_name": "inline-specialist",
                        "role": role,
                    }
                ]
            },
            sort_keys=False,
        )
    )

    result = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"
    assert roles_file.read_bytes() == roles_before
    assert not (harness_root / ".graphtraj" / "state" / "batches").exists()
    assert not fake_codex.log_file.exists()
