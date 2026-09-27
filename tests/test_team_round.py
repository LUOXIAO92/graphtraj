from __future__ import annotations

import json
import os
import shutil
import tomllib
from pathlib import Path

import yaml
import pytest

from conftest import wait_for_file, FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness, retained_state, wait_for_ticket_status
from test_ticket_graph import _change_status, _register, _ticket


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
        "        instructions: team-leader\n"
        "        worktree_access: read\n"
        "        reports: [leader.md]\n"
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    wait_for_ticket_status(installed_commands, harness_root, "75", "awaiting-integration")
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    leader_records = [record for record in records if record["role"] == "team-leader"]
    assert leader_records
    assert all(
        record["argv"][record["argv"].index("--model") + 1] == "gpt-5.6-luna"
        for record in leader_records
    )
    assert all(
        any(tomllib.loads(argument)["agents"]["enabled"] is False
            for argument in record["argv"] if argument.startswith("agents="))
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


def test_installed_runner_accepts_non_english_engineer_self_review(
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
    fake_codex.executable.write_text(
        fake_codex.executable.read_text().replace(
            "Self-review: passed.", "自审：已完成。"
        ),
        encoding="utf-8",
    )
    batch = harness_root / "team-batch.yml"
    batch.write_text(
        "tasks:\n"
        "  - ticket_id: \"75\"\n"
        "    ticket_name: inline-specialist\n"
        "    role: team-leader\n",
        encoding="utf-8",
    )

    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env={
            **environment,
            "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
            "GRAPHTRAJ_AGENT_RUNNER": str(installed_commands.runner),
        },
        timeout=45,
    )

    assert launched.returncode == 0, launched.stdout + launched.stderr
    wait_for_ticket_status(installed_commands, harness_root, "75", "awaiting-integration")
    ticket = harness_root / ".graphtraj/state/tickets/75-inline-specialist"
    assert yaml.safe_load((ticket / "ticket.yml").read_text())["status"] == "awaiting-integration"
    assert "自审：已完成。" in (
        ticket / "teams/1/rounds/1/engineer.md"
    ).read_text()
    from graphtraj.execution.runner_control import read_session_reports
    from graphtraj.execution.runner_status import runtime_caller

    runner = harness_root / '.graphtraj/runner'
    for path in (runner / 'sessions').glob('*/mapping.yml'):
        mapping = yaml.safe_load(path.read_text())
        if mapping['role'] in {'standards-reviewer', 'spec-reviewer'}:
            with runtime_caller(runner, mapping['parent']):
                reports = read_session_reports(mapping['alias'], harness_root)['reports']
            assert reports and reports[0]['text']
            # Reconstruct the retained format written before per-Session assignments.
            # Its collector moved the source into the Round, without renaming it.
            mapping['report_file'] = mapping.pop('report_files')[0]
            path.write_text(yaml.safe_dump(mapping))
            launch_path = path.with_name('launch.yml')
            launch = yaml.safe_load(launch_path.read_text())
            launch['mapping']['report_file'] = launch['mapping'].pop('report_files')[0]
            launch_path.write_text(yaml.safe_dump(launch))
            with runtime_caller(runner, mapping['parent']):
                historical = read_session_reports(mapping['alias'], harness_root)['reports']
            assert historical[0]['text'] == reports[0]['text']
            assert '/rounds/1/' in historical[0]['path']



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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
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
    ("decision", "swarm"),
    (("accept", None), ("accept", False), ("accept", True), ("rework", None)),
    ids=["accept-awaiting-integration-True-True-None", "accept-awaiting-integration-True-True-False",
         "accept-awaiting-integration-True-True-True", "rework-awaiting-integration-True-True-None"],
)
def test_installed_runner_obeys_the_explicit_leader_decision_for_a_run_free_team_round(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    decision: str,
    swarm: bool | None,
) -> None:
    """Explicit decisions retain generic dispatch, ownership and file isolation."""
    from graphtraj.graph.delivery_worldline import read_worldline

    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    leader = roles['roles']['coding_team']['team_leader']
    leader.pop('allow_runtime_swarm', None)
    if swarm is not None:
        leader['allow_runtime_swarm'] = swarm
    roles_file.write_text(yaml.safe_dump(roles))
    policy_log = tmp_path / 'policy.jsonl'
    main_config = root / '.codex/config.toml'
    main_config.write_text('developer_instructions = "User-owned Main instructions."\n')
    main_before = main_config.read_bytes()
    _register_ready_inline_ticket(root, installed_commands.product)
    batch = root / 'decision.yml'
    batch.write_text('tasks:\n  - ticket_id: "75"\n    role: team-leader\n')
    launched = run_process(
        [str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root,
        env={**environment, 'FAKE_CODEX_LIFECYCLE_ACTION': 'complete-team-round',
             'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
             'FAKE_CODEX_POLICY_LOG': str(policy_log),
             'FAKE_CODEX_REVIEW_AXES': '', 'FAKE_CODEX_LEADER_DECISION': decision},
        timeout=45,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    from runner_fixtures import wait_for_ticket_status

    wait_for_ticket_status(installed_commands, root, '75', 'awaiting-integration' if decision == 'accept' else 'reworking')
    assert main_config.read_bytes() == main_before
    ticket = root / '.graphtraj/state/tickets/75-inline-specialist'
    current = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert current['status'] == ('awaiting-integration' if decision == 'accept' else 'reworking')
    assert team['current_round'] == 1
    assert {member['role'] for member in team['members'].values()} == {'team-leader', 'engineer'}
    assert not (ticket / 'teams/1/rounds/2').exists()
    events = read_worldline(root / '.graphtraj/state', root)
    submitted = next(event for event in events if event['kind'] == 'result-submitted')
    decided = next(event for event in events if event.get('submission_id') == submitted['event_id'])
    assert decided['candidate'] == submitted['candidate'] == current['current_candidate']
    assert decided['decision'] == ('accepted' if decision == 'accept' else 'rejected')
    assert submitted['event_id'] in decided['caused_by_event_ids']
    mappings = [yaml.safe_load(path.read_text()) for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml')]
    parent = next(mapping for mapping in mappings if mapping['role'] == 'team-leader')
    child = next(mapping for mapping in mappings if mapping['role'] == 'engineer')
    assert child['parent'] == parent['alias'] and parent['parent'] is None
    calls = [json.loads(line) for line in policy_log.read_text().splitlines()]
    assert {call['role'] for call in calls} == {'team-leader', 'engineer'}
    for call in calls:
        settings = call['settings']
        filesystem = settings['permissions'][settings['default_permissions']]['filesystem']
        assert filesystem[':workspace_roots']['.'] == ('read' if call['role'] == 'team-leader' else 'write')
        assert filesystem[':workspace_roots']['CONTEXT.md'] == 'read'
        assert filesystem[':workspace_roots']['docs'] == 'read'
        assert filesystem.get(str(root / '.graphtraj/state/worldline/.lock')) != 'write'
        assert not any(access == 'write' and path.startswith(str(ticket)) for path, access in filesystem.items())
        assert settings['agents']['enabled'] is (call['role'] == 'team-leader' and swarm is True)
        reports = {Path(path).name for path, access in filesystem.items()
                   if access == 'read' and path.startswith(str(ticket)) and path.endswith('.md')}
        assert reports == ({'leader.md'} if call['role'] == 'team-leader' else {'engineer.md', 'validation.md'})


@pytest.mark.parametrize(
    ("axes", "reports"),
    (
        ("", {"engineer.md", "validation.md", "leader.md"}),
        (
            "standards-reviewer",
            {"engineer.md", "validation.md", "standards.md", "leader.md"},
        ),
        (
            "standards-reviewer spec-reviewer",
            {"engineer.md", "validation.md", "standards.md", "spec.md", "leader.md"},
        ),
    ),
)
def test_installed_runner_accepts_the_review_axes_the_leader_selects(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    axes: str,
    reports: set[str],
) -> None:
    """The Leader's Review selection closes the Round without a forced axis."""
    harness_root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register(
        installed_commands, harness_root, _ticket("74", "selected-review-axes")
    )
    _change_status(installed_commands, harness_root, "74", "ready")
    batch = harness_root / "batch.yml"
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "74"\n'
        '    ticket_name: selected-review-axes\n'
        '    role: coding-team.team-leader\n'
    )
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        FAKE_CODEX_REVIEW_AXES=axes,
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )

    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=45,
    )

    assert launched.returncode == 0, launched.stderr
    ticket_directory = (
        harness_root / ".graphtraj" / "state" / "tickets" / "74-selected-review-axes"
    )
    wait_for_ticket_status(installed_commands, harness_root, "74", "awaiting-integration")
    current = yaml.safe_load((ticket_directory / "ticket.yml").read_text())
    assert current["status"] == "awaiting-integration"
    candidate = current["current_candidate"]
    round_directory = ticket_directory / "teams" / "1" / "rounds" / "1"
    assert {path.name for path in round_directory.iterdir()} == reports
    assert all(
        candidate in (round_directory / name).read_text() for name in reports
    )
    team = yaml.safe_load((ticket_directory / "teams" / "1" / "team.yml").read_text())
    for seat, role in (
        ("standards_reviewer", "standards-reviewer"),
        ("spec_reviewer", "spec-reviewer"),
    ):
        session_ref = team["members"].get(seat, {}).get("session_ref")
        if role not in axes:
            assert seat not in team["members"]
            continue
        assert session_ref
        records = (
            harness_root / ".graphtraj" / "runner" / "sessions"
            / session_ref / "events.jsonl"
        )
        assert records.read_text().count('"type": "runner-execution-start"') == 1


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
        {"tasks": [{**task, "ticket_file": "ticket.md"}]},
        {"tasks": [{**task, "unexpected": True}]},
    ]

    for index, document in enumerate(invalid):
        batch = harness_root / "invalid-{0}.yml".format(index)
        batch.write_text(yaml.safe_dump(document, sort_keys=False))
        result = run_process(
            [str(installed_commands.runner), "--swarm-input", str(batch)],
            cwd=harness_root,
            env=environment,
        )
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"

    assert not (harness_root / ".graphtraj" / "state" / "batches").exists()




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
from graphtraj.runtimes.codex.codex_adapter import _toml_value

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
# Exact write grants only: the registered Batch, its retention directory, this
# Leader's own report and the Worldline lock direct control opens. No wildcard
# and no shared Runner, state or Session directory.
harness_store = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']) / '.graphtraj'
ticket = harness_store / 'state' / 'tickets' / '75-inline-specialist'
assert set(targets) == {
    registration,
    harness_store / 'state' / 'batches',
    harness_store / 'state' / 'worldline' / '.lock',
    harness_store / 'runner' / 'capacity',
    ticket / 'teams' / '1' / 'rounds' / '1' / 'leader.md',
}
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
        [str(installed_commands.runner), '--swarm-input', str(batch)],
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
    roles = yaml.safe_load(roles_file.read_text())
    roles['role_tree']['investigation-specialist'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
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
        "        worktree_access: read\n"
        "    instruction: Inspect the Ticket in its assigned Worktree.\n"
    ).encode()
    batch.write_bytes(batch_bytes)
    environment.update(
        {
            "FAKE_CODEX_CAPTURE_STDIN": "1",
            "FAKE_CODEX_CAPTURE_CONNECTION": "1",
        }
    )

    launched = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    output = yaml.safe_load(launched.stdout)
    task = output["tasks"][0]
    assert task["role"] == "investigation-specialist"
    assert task["launch_status"] == "launched"
    retained = Path(output["retained_batch_file"])
    assert retained.read_bytes() == batch_bytes
    assert retained.stat().st_mode & 0o222 == 0
    assert roles_file.read_bytes() == roles_before
    wait_for_file(fake_codex.log_file)
    runtime = json.loads(fake_codex.log_file.read_text())
    assert runtime["cwd"] == task["worktree_path"]
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
    assert "Inspect the Ticket in its assigned Worktree." in runtime["stdin"]
    assert runtime["connection"]["base_url"] is None
    assert any(
        tomllib.loads(argument)["agents"]["enabled"] is False
        for argument in runtime["argv"] if argument.startswith("agents=")
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
    assert current["active_team_ordinal"] == 1
    team = yaml.safe_load((ticket_directory / 'teams/1/team.yml').read_text())
    assert [member['session_ref'] for member in team['members'].values()] == [task['alias']]


@pytest.mark.parametrize("role_name", ("dependency-reviewer", "engineer-specialist"))
def test_installed_runner_uses_generic_instructions_for_new_inline_roles(
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

    roles_file = harness_root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['role_tree'][role_name] = {}
    roles_file.write_text(yaml.safe_dump(roles))
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
        timeout=10,
    )

    assert launched.returncode == 0, launched.stderr
    wait_for_file(fake_codex.log_file)
    runtime = json.loads(fake_codex.log_file.read_text())
    assert runtime["role"] == role_name
    assert "Write the fixed candidate" not in runtime["stdin"]
    assert "Review brief:" not in runtime["stdin"]
    assert not any(runtime["environment"].values())

    wait_for_file(policy_log)
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
def test_installed_runner_registers_a_selected_inline_specialist_as_a_child(
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
    roles = yaml.safe_load(roles_file.read_text())
    for parent in ('team-leader', 'coding-team.team-leader', 'coding_team.team_leader'):
        roles['role_tree'][parent][specialist_role] = {}
    roles_file.write_text(yaml.safe_dump(roles))
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
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
    wait_for_ticket_status(installed_commands, harness_root, "75", "awaiting-integration")
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
    assert specialist["alias"] in {
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
    wait_for_ticket_status(installed_commands, harness_root, "75", "awaiting-integration")
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
                "allow_runtime_swarm": "yes",
            },
        },
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
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness_root,
        env=environment,
    )

    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)["error"]["code"] == "invalid-input"
    assert roles_file.read_bytes() == roles_before
    assert not (harness_root / ".graphtraj" / "state" / "batches").exists()
    assert not fake_codex.log_file.exists()


def test_coding_acceptance_consumes_submission_without_report_commit(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Acceptance uses a submitted version and explicit decision without parsing reports."""
    from graphtraj.graph.delivery_worldline import read_worldline

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_inline_ticket(harness, installed_commands.product)
    batch = harness / 'submission-batch.yml'
    batch.write_text('tasks:\n  - ticket_id: "75"\n    role: team-leader\n')
    launched = run_process(
        [str(installed_commands.runner), '--swarm-input', str(batch)], cwd=harness,
        env={**environment, 'FAKE_CODEX_LIFECYCLE_ACTION': 'complete-team-round',
             'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
             'FAKE_CODEX_REVIEW_AXES': '', 'FAKE_CODEX_REPORT_WITHOUT_COMMIT': '1'},
        timeout=45,
    )
    from runner_fixtures import wait_for_ticket_status

    assert launched.returncode == 0, launched.stdout + launched.stderr
    wait_for_ticket_status(installed_commands, harness, '75', 'awaiting-integration')
    events = read_worldline(harness / '.graphtraj/state', harness)
    submitted = [event for event in events if event['kind'] == 'result-submitted']
    assert submitted, launched.stdout + launched.stderr
    assert submitted[0]['role'] == 'engineer'
    assert (harness / submitted[0]['evidence_refs'][0]).read_text().startswith('Candidate commit:')
    accepted = [event for event in events if event['kind'] == 'team-round-accepted']
    assert launched.returncode == 0, launched.stdout + launched.stderr
    assert accepted[-1]['submission_id'] == submitted[-1]['event_id']
    assert accepted[-1]['candidate'] == submitted[-1]['candidate']
