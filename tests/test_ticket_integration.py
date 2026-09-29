from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from test_existing_repository_setup import run_setup
from runner_fixtures import configure_harness, retained_state
from test_ticket_graph import _change_status, _register, _ticket


@pytest.fixture
def accepted_ticket(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, request
):
    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    from test_execution_budgets import _budget_body

    definition = _ticket("83", "integration")
    definition["body"] = _budget_body(total=60)
    _register(installed_commands, root, definition)
    for identifier, dependencies in (("84", ["83"]), ("85", ["83"]), ("86", ["83", "84"])):
        _register(installed_commands, root, _ticket(identifier, "dependent", dependencies=dependencies))
    _change_status(installed_commands, root, "83", "ready")
    batch = root / "batch.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "83", "ticket_name": "integration", "role": "coding-team.team-leader"}]}))
    selected_axes = getattr(request, "param", None)
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        FAKE_CODEX_REVIEW_AXES=selected_axes or "",
    )
    launched = run_process([str(installed_commands.runner), "--swarm-input", str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stderr
    from runner_fixtures import wait_for_ticket_status

    wait_for_ticket_status(installed_commands, root, '83', 'awaiting-integration')
    state = root / ".graphtraj/state"
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    assert record["status"] == "awaiting-integration"
    candidate = record["current_candidate"]
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 1
    return root, worktrees, state, candidate


def test_main_integrates_an_accepted_candidate_and_unlocks_only_satisfied_dependencies(
    installed_commands, accepted_ticket, fake_codex
):
    root, worktrees, state, candidate = accepted_ticket
    previous_runtime = fake_codex.log_file.read_bytes()
    # Later branch work must not silently replace the Team's fixed candidate.
    worktree = worktrees / "83-integration"
    (worktree / "LATER.txt").write_text("not part of the accepted candidate\n")
    run_process(["git", "add", "LATER.txt"], cwd=worktree).check_returncode()
    run_process(["git", "commit", "-m", "Later branch work"], cwd=worktree).check_returncode()
    validator = root / "validate.py"
    validator.write_text(
        "import pathlib, subprocess, yaml\n"
        f"state = yaml.safe_load(pathlib.Path({str(state / 'tickets/83-integration/ticket.yml')!r}).read_text())\n"
        "assert state['status'] == 'integrating'\n"
        f"assert state['current_candidate'] == {candidate!r}\n"
        "assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'dev'\n"
        "assert pathlib.Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\n'\n"
        "print('integration checks passed')\n"
    )
    result = run_process(
        [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, str(validator)], cwd=root
    )
    assert result.returncode == 0, result.stderr
    output = yaml.safe_load(result.stdout)
    assert output["candidate"] == candidate
    assert output["status"] == "integrated"
    assert fake_codex.log_file.read_bytes() == previous_runtime
    assert not any("@m" in path.name for path in state.rglob("*"))
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 0
    assert not (worktrees / "dev/LATER.txt").exists()
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert [item["ticket_id"] for item in graph["tickets"] if item["ready"]] == ["84", "85"]
    assert [item["status"] for item in graph["tickets"]] == ["integrated", "ready", "ready", "pending"]
    events = [json.loads(line) for shard in (state / "worldline").glob("*.jsonl") for line in shard.read_text().splitlines()]
    accepted = next(event for event in events if event["kind"] == "team-round-accepted")
    started = next(event for event in events if event["kind"] == "ticket-integration-started")
    integrated = next(event for event in events if event["kind"] == "ticket-integrated")
    assert started["caused_by_event_ids"] == [accepted["event_id"]]
    assert integrated["caused_by_event_ids"] == [started["event_id"]]
    assert "integration checks passed" in (root / integrated["evidence_refs"][0]).read_text()
    unlocked = [event for event in events if event["kind"] == "ticket-dependency-unlocked"]
    assert {event["ticket_id"] for event in unlocked} == {"84", "85"}
    assert all(event["caused_by_event_ids"] == [integrated["event_id"]] for event in unlocked)
    assert not any(path.name in {"task-map.yml", "dag.md", "ledger.yml"} for path in state.rglob("*"))


@pytest.mark.parametrize("accepted_ticket", [""], indirect=True)
def test_main_integrates_a_candidate_accepted_without_review_reports(
    installed_commands, accepted_ticket,
):
    """A zero-axis acceptance leaves no report or Session to forge for Main."""
    root, worktrees, state, candidate = accepted_ticket
    ticket = state / "tickets/83-integration"
    round_directory = ticket / "teams/1/rounds/1"
    assert {path.name for path in round_directory.iterdir()} == {
        "engineer.md", "validation.md", "leader.md"
    }
    team = yaml.safe_load((ticket / "teams/1/team.yml").read_text())
    assert "standards_reviewer" not in team["members"]
    assert "spec_reviewer" not in team["members"]

    result = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "integrate",
            "--ticket-id",
            "83",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
        cwd=root,
    )

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)["status"] == "integrated"
    assert run_process(
        ["git", "merge-base", "--is-ancestor", candidate, "HEAD"],
        cwd=worktrees / "dev",
    ).returncode == 0
    assert (worktrees / "dev/TEAM_ROUND_DELIVERED.txt").read_text() == "complete team round\n"


def test_main_integration_refuses_dirty_dev(
    installed_commands, accepted_ticket,
):
    root, worktrees, state, candidate = accepted_ticket
    dev = worktrees / "dev"
    before = run_process(["git", "rev-parse", "HEAD"], cwd=dev).stdout
    (dev / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n", encoding="utf-8"
    )

    result = run_process(
        [
            str(installed_commands.product),
            "ticket",
            "integrate",
            "--ticket-id",
            "83",
            "--",
            sys.executable,
            "-c",
            "pass",
        ],
        cwd=root,
    )

    assert result.returncode == 1
    assert "must be clean" in yaml.safe_load(result.stdout)["error"]
    assert run_process(["git", "rev-parse", "HEAD"], cwd=dev).stdout == before
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    assert record["status"] == "awaiting-integration"
    assert record["current_candidate"] == candidate


@pytest.mark.parametrize("flat_roles", (False, True))
def test_grouped_presets_apply_operator_settings_and_preserve_existing_history(
    installed_commands, accepted_ticket, fake_codex, flat_roles,
):
    root, _, state, _ = accepted_ticket
    roles_file = root / ".graphtraj/roles.yml"
    document = yaml.safe_load(roles_file.read_text())
    presets = document["roles"]["coding_team"]
    for name, preset in presets.items():
        preset.update(
            model="operator-" + name,
            base_url="https://runtime.example.invalid/" + name,
            reasoning_effort="high",
            codex={"approval": {"model": "review", "base_url": "https://review.example",
                                 "api_key_env": "REVIEW_KEY"}},
        )
    if flat_roles:
        document["roles"] = {**presets, "delivery_state": document["roles"]["delivery_state"]}
    roles_file.write_text(yaml.safe_dump(document))
    roles_before = roles_file.read_bytes()
    retained = {
        path: retained_state(path)
        for directory in (state / "batches", state / "worldline", state / "tickets/83-integration/teams")
        for path in directory.rglob("*") if path.is_file()
    }
    setup = run_setup(installed_commands, root, answers="")
    assert setup.returncode == 0, setup.stderr
    assert roles_file.read_bytes() == roles_before
    assert {path: retained_state(path) for path in retained} == retained

    _register(installed_commands, root, _ticket("89", "grouped-settings"))
    _change_status(installed_commands, root, "89", "ready")
    batch = root / "grouped-settings.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "89", "ticket_name": "grouped-settings", "role": "coding-team.team-leader",
    }]}))
    fake_codex.log_file.write_text("")
    environment = dict(
        os.environ, HOME=str(root / "operator-home"),
        PATH=str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
        FAKE_CODEX_LOG=str(fake_codex.log_file), FAKE_CODEX_CAPTURE_ROLE="1",
        FAKE_CODEX_APPEND_LOG="1", FAKE_CODEX_CAPTURE_CONNECTION="1",
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    launched = run_process([str(installed_commands.runner), "--swarm-input", str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stderr
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    assert {record["role"] for record in records} == {
        "team-leader", "engineer", "standards-reviewer", "spec-reviewer",
    }
    for record in records:
        if record["role"] == "delivery-state":
            continue
        selected = presets[record["role"].replace("-", "_")]
        assert record["argv"][record["argv"].index("--model") + 1] == selected["model"]
        assert record["connection"]["base_url"] == selected["base_url"]
        settings = {
            key: value
            for index, argument in enumerate(record["argv"][:-1])
            if argument == "-c"
            for key, value in tomllib.loads(record["argv"][index + 1]).items()
        }
        assert settings["model_reasoning_effort"] == selected["reasoning_effort"]
    leader_records = [record for record in records if record["role"] == "team-leader"]
    assert "resume" not in leader_records[0]["argv"]
    assert all("resume" in record["argv"] for record in leader_records[1:])
    assert roles_file.read_bytes() == roles_before
    for path, content in retained.items():
        if path.parent == state / "worldline":
            assert path.read_bytes().startswith(content)
        else:
            assert retained_state(path) == content


def test_failed_validation_retains_evidence_without_unlocking_and_main_can_retry(
    installed_commands, accepted_ticket
):
    root, worktrees, state, candidate = accepted_ticket
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--"]
    failed = run_process(command + [sys.executable, "-c", "print('validation failed'); raise SystemExit(1)"], cwd=root)
    assert failed.returncode == 1
    output = yaml.safe_load(failed.stdout)
    assert output["status"] == "integrating"
    evidence = root / output["evidence"]
    retained = evidence.read_bytes()
    assert b"validation failed" in retained
    assert run_process(["git", "merge-base", "--is-ancestor", candidate, "HEAD"], cwd=worktrees / "dev").returncode == 0
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert not any(item["ready"] for item in graph["tickets"])
    # Generic semantic updates must not turn failed validation into integration.
    record = yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())
    change = {key: record[key] for key in ("ticket_id", "active_team_ordinal", "worktree", "branch", "current_candidate")}
    change.update(status="integrated", caused_by_event_ids=[output["event_id"]], evidence_refs=[output["evidence"]])
    request = root / "bypass.yml"
    request.write_text(yaml.safe_dump(change))
    bypass = run_process([str(installed_commands.product), "ticket", "update", "--state-file", str(request)], cwd=root)
    assert bypass.returncode == 1
    assert yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())["status"] == "integrating"
    retried = run_process(command + [sys.executable, "-c", "print('validation passed')"], cwd=root)
    assert retried.returncode == 0, retried.stderr
    assert yaml.safe_load(retried.stdout)["status"] == "integrated"
    assert evidence.read_bytes() == retained


def test_integration_rejects_an_unaccepted_ticket(installed_commands, accepted_ticket):
    """An unaccepted dependent cannot enter the common integration gate."""
    root, worktrees, state, candidate = accepted_ticket
    before = run_process(["git", "rev-parse", "HEAD"], cwd=worktrees / "dev").stdout
    result = run_process([str(installed_commands.product), "ticket", "integrate", "--ticket-id", "84", "--", sys.executable, "-c", "pass"], cwd=root)
    assert result.returncode == 1
    assert "error" in yaml.safe_load(result.stdout)
    assert run_process(["git", "rev-parse", "HEAD"], cwd=worktrees / "dev").stdout == before


def test_failed_merge_retains_conflict_evidence_and_does_not_run_validation(installed_commands, accepted_ticket):
    root, worktrees, state, candidate = accepted_ticket
    dev = worktrees / "dev"
    (dev / "TEAM_ROUND_DELIVERED.txt").write_text("conflicting integration work\n")
    for arguments in (("add", "TEAM_ROUND_DELIVERED.txt"), ("commit", "-m", "Independent dev change")):
        run_process(["git", *arguments], cwd=dev).check_returncode()
    result = run_process([str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, "-c", "print('VALIDATOR RAN')"], cwd=root)
    assert result.returncode == 1
    output = yaml.safe_load(result.stdout)
    evidence = (root / output["evidence"]).read_text()
    assert "CONFLICT" in evidence
    assert "VALIDATOR RAN" not in evidence
    assert output["status"] == "integrating"
    graph = yaml.safe_load(run_process([str(installed_commands.product), "ticket", "graph"], cwd=root).stdout)
    assert not any(item["ready"] for item in graph["tickets"])


@pytest.fixture
def accepted_document(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> tuple[Path, Path, Path, str, dict[str, str]]:
    """Deliver and accept Markdown through an ordinary configured root Session."""
    from test_generic_role_execution import wait_for_idle
    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['editor'] = {'runtime': 'codex', 'model': 'document-model',
                                'reports': ['sources.md']}
    roles['role_tree']['editor'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
    _register(installed_commands, root, _ticket('83', 'integration'))
    _register(installed_commands, root, _ticket('84', 'dependent', dependencies=['83']))
    _change_status(installed_commands, root, '83', 'ready')
    batch = root / 'document.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '83', 'role': 'editor'}]}))
    environment.update(FAKE_CODEX_LIFECYCLE_ACTION='deliver-document',
                       FAKE_CODEX_RESULT_FILE='article.md',
                       GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner))
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    wait_for_idle(installed_commands, root, environment, alias)
    submission = _accept_resolution(installed_commands, root, alias)
    return root, worktrees, root / '.graphtraj/state', submission['candidate'], environment


def _accept_resolution(commands: InstalledCommands, root: Path, alias: str) -> dict:
    """Decide the member's actual public submission from the top-level parent."""
    reports = run_process([str(commands.runner), 'reports', alias], cwd=root)
    assert reports.returncode == 0, reports.stdout + reports.stderr
    document = yaml.safe_load(reports.stdout)
    submission = document['submissions'][-1]
    arguments = [str(commands.runner), 'decide-result', '--submission-id', submission['event_id'],
                 '--commit', submission['candidate'], '--decision', 'accepted', '--reason', 'Both document requirements hold']
    for ref in submission['evidence_refs']:
        arguments.extend(['--evidence-ref', ref])
    decision = run_process(arguments, cwd=root)
    assert decision.returncode == 0, decision.stdout + decision.stderr
    return submission


@pytest.mark.parametrize('conflict', ['textual', 'semantic'])
@pytest.mark.parametrize('outcome', ['resolved', 'invalid-resolution', 'prose-only'])
def test_configured_document_conflict_requires_common_result_and_validation(
    installed_commands: InstalledCommands,
    accepted_document: tuple,
    fake_codex: FakeCodex,
    conflict: str,
    outcome: str,
) -> None:
    """Real member/Session/result/Git facts, not final prose, govern completion."""
    root, worktrees, state, candidate, environment = accepted_document
    dev = worktrees / 'dev'
    if conflict == 'textual':
        (dev / 'article.md').write_text('conflicting integration work\n')
        run_process(['git', 'add', 'article.md'], cwd=dev).check_returncode()
        run_process(['git', 'commit', '-m', 'Existing document requirement'], cwd=dev).check_returncode()
    command = [str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '83']
    validator = [sys.executable, '-c', "from pathlib import Path; assert Path('article.md').read_text() == 'complete team round\\nconflicting integration work\\n'"]
    failed = run_process(command + ['--', *validator], cwd=root)
    assert failed.returncode == 1, failed.stdout
    original_round = {path: path.read_bytes() for path in (state / 'tickets/83-integration/teams/1/rounds/1').glob('*')}
    assert original_round
    environment.update(FAKE_CODEX_LIFECYCLE_ACTION='resolve-integration', FAKE_CODEX_RESOLUTION=outcome,
                       FAKE_CODEX_CAPTURE_STDIN='1')
    selection = 'editor' if conflict == 'textual' else yaml.safe_dump({'editor': {'runtime': 'codex', 'model': 'inline-document-model', 'reports': ['sources.md']}})
    result = run_process(command + ['--resolve-conflict', 'Preserve both document requirements', '--role', selection, '--', *validator], cwd=root, env=environment)
    assert result.returncode == (1 if outcome == 'prose-only' else 0), result.stdout + result.stderr
    output = yaml.safe_load(result.stdout)
    assert output['status'] == ('escalated' if outcome == 'prose-only' else 'resolving-integration'), (root / output['evidence']).read_text()
    alias = output['resolution']['alias']
    mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())
    team = yaml.safe_load((state / 'tickets/83-integration/teams/1/team.yml').read_text())
    assert any(member['session_ref'] == alias for member in team['members'].values())
    assert mapping['parent'] is None and mapping['role_reference'] == 'editor'
    assert mapping['worktree_path'] == str(dev) and team['current_round'] == 2
    assert all(path.read_bytes() == content for path, content in original_round.items())
    native = json.loads(fake_codex.log_file.read_text())
    settings = {}
    for index, argument in enumerate(native['argv'][:-1]):
        if argument == '-c':
            settings.update(tomllib.loads(native['argv'][index + 1]))
    permissions = settings['permissions'][settings['default_permissions']]['filesystem']
    assert native['cwd'] == str(dev)
    assert permissions[':workspace_roots']['.'] == 'write'
    assert permissions[str(state)] == 'none'
    assert permissions[':workspace_roots']['docs'] == 'read'
    assert permissions.get(str(state / 'tickets/83-integration')) is None
    assigned_reports = [Path(path) for path, access in permissions.items()
                        if access == 'read' and path.startswith(str(state / 'tickets/83-integration'))]
    assert len(assigned_reports) == 1 and assigned_reports[0].parent.name == '2'
    assert native['argv'][native['argv'].index('--model') + 1] == ('document-model' if conflict == 'textual' else 'inline-document-model')
    trace = Path(mapping['trace_file']).read_text()
    if outcome == 'prose-only':
        assert 'Decision: RESOLVED' in trace
    else:
        if conflict == 'textual' and outcome == 'resolved':
            from graphtraj.execution.runner_models import RunnerError
            from graphtraj.execution.runner_status import runtime_caller
            from graphtraj.interfaces import tools

            original = team['members']['editor']['session_ref']
            with runtime_caller(root / '.graphtraj/runner', original):
                report = tools.submit_report({'name': 'sources.md', 'text': 'Original scope checked.'}, cwd=root)
                assert '/rounds/2/' in report.document['report']
                with pytest.raises(RunnerError, match='Integration Worktree'):
                    tools.submit_result({'commit': candidate, 'result_refs': ['article.md'],
                                       'completion': 'Original result is not a resolution'}, cwd=root)
                submitted = output['resolution']['submissions'][-1]
                with pytest.raises(RunnerError):
                    tools.decide_result({'submission_id': submitted['event_id'], 'commit': submitted['candidate'],
                                       'decision': 'accepted', 'reason': 'Same role is not the parent',
                                       'evidence_refs': submitted['evidence_refs']}, cwd=root)

        assert 'Decision: RESOLVED' not in trace
        pending = run_process(command + ['--', *validator], cwd=root)
        assert pending.returncode == 1 and 'acceptance' in pending.stdout
        submission = _accept_resolution(installed_commands, root, alias)
        assert submission['candidate'] == run_process(['git', 'rev-parse', 'HEAD'], cwd=dev).stdout.strip()
        if conflict == 'textual' and outcome == 'resolved':
            # A newer rejected submission of the same commit supersedes the old
            # acceptance; version equality alone cannot manufacture acceptance.
            with runtime_caller(root / '.graphtraj/runner', alias):
                newer = tools.submit_result({'commit': submission['candidate'], 'result_refs': ['article.md'],
                                           'evidence_refs': ['article.md'], 'completion': 'Reassessed document'}, cwd=root).document
            tools.decide_result({'submission_id': newer['event_id'], 'commit': newer['candidate'],
                               'decision': 'rejected', 'reason': 'Reconfirm the document evidence',
                               'evidence_refs': newer['evidence_refs']}, cwd=root)
            pending = run_process(command + ['--', *validator], cwd=root)
            assert pending.returncode == 1 and 'acceptance' in pending.stdout
            with runtime_caller(root / '.graphtraj/runner', alias):
                corrected = tools.submit_result({'commit': submission['candidate'], 'result_refs': ['article.md'],
                                               'evidence_refs': ['article.md'], 'completion': 'Evidence reconfirmed'}, cwd=root).document
            assert corrected['round'] == 3
            _accept_resolution(installed_commands, root, alias)
        checked = run_process(command + ['--', *validator], cwd=root)
        assert checked.returncode == (0 if outcome == 'resolved' else 1), checked.stdout + checked.stderr
        assert yaml.safe_load(checked.stdout)['status'] == ('integrated' if outcome == 'resolved' else 'resolving-integration')
        if outcome == 'resolved':
            from graphtraj.execution.runner_models import RunnerError
            from graphtraj.interfaces import tools

            with pytest.raises(RunnerError, match='active conflict assignment'):
                tools.send_session_instruction({'alias': alias, 'instruction': 'More work',
                                             'caused_by_event_ids': [yaml.safe_load(checked.stdout)['event_id']]}, cwd=root)

    graph = yaml.safe_load(run_process([str(installed_commands.product), 'ticket', 'graph'], cwd=root).stdout)
    assert any(item['ready'] for item in graph['tickets']) == (outcome == 'resolved')
    assert run_process(['git', 'merge-base', '--is-ancestor', candidate, 'HEAD'], cwd=dev).returncode == (1 if conflict == 'textual' and outcome == 'prose-only' else 0)


def test_conflict_selection_rejects_missing_role_and_unauthorized_tree(
    installed_commands: InstalledCommands, accepted_document: tuple, fake_codex: FakeCodex,
) -> None:
    """No implicit role or denied tree edge starts integration work."""
    root, _, _, _, environment = accepted_document
    command = [str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '83']
    validator = [sys.executable, '-c', 'raise SystemExit(1)']
    assert run_process(command + ['--', *validator], cwd=root).returncode == 1
    before = fake_codex.log_file.read_bytes()
    for selection in ([], ['--role', 'unconfigured'], ['--role', 'coding-team.engineer']):
        result = run_process(command + ['--resolve-conflict', 'Reconcile document', *selection, '--', *validator], cwd=root, env=environment)
        assert result.returncode == 1, result.stdout
    assert fake_codex.log_file.read_bytes() == before


def test_role_named_merge_resolver_is_an_ordinary_swarm_member(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A name neither grants Integration Worktree access nor needs a conflict."""
    root, worktrees, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    _register(installed_commands, root, _ticket('91', 'ordinary'))
    _change_status(installed_commands, root, '91', 'ready')
    batch = root / 'ordinary.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '91', 'role': 'merge-resolver'}]}))
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root, env=environment)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    member = yaml.safe_load(launched.stdout)['tasks'][0]
    assert member['worktree_path'] == str(worktrees / '91-ordinary')
    from test_generic_role_execution import wait_for_idle
    wait_for_idle(installed_commands, root, environment, member['alias'])
    team = yaml.safe_load((root / '.graphtraj/state/tickets/91-ordinary/teams/1/team.yml').read_text())
    assert any(item['session_ref'] == member['alias'] for item in team['members'].values())


def test_main_integration_is_serialized_until_validation_finishes(installed_commands, accepted_ticket):
    root, worktrees, state, candidate = accepted_ticket
    started = root / "validation-started"
    release = root / "validation-release"
    validator = root / "wait-validation.py"
    validator.write_text(
        "from pathlib import Path\nimport time\n"
        f"Path({str(started)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists():\n    time.sleep(0.01)\n"
    )
    command = [str(installed_commands.product), "ticket", "integrate", "--ticket-id", "83", "--", sys.executable, str(validator)]
    first = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_for_file(started)
        second = run_process(command, cwd=root, timeout=5)
        assert second.returncode == 1
        assert "in progress" in yaml.safe_load(second.stdout)["error"]
        assert yaml.safe_load((state / "tickets/83-integration/ticket.yml").read_text())["status"] == "integrating"
    finally:
        release.touch()
        stdout, stderr = first.communicate(timeout=10)
    assert first.returncode == 0, stderr
    assert yaml.safe_load(stdout)["status"] == "integrated"


@pytest.mark.parametrize("entrypoint", ["python", "cli"])
@pytest.mark.parametrize("validation_exit", [0, 1])
def test_shared_integration_enforces_task_authority_and_returns_retained_outcome(
    installed_commands: InstalledCommands,
    accepted_ticket: tuple[Path, Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    entrypoint: str,
    validation_exit: int,
) -> None:
    """Python integration includes the CLI's authority and serialization guards."""
    from click.testing import CliRunner
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.ticket_graph import read_graph
    from graphtraj.interfaces.cli.graphtraj import main
    from graphtraj.teams.ticket_integration import integrate_ticket

    root, worktrees, state, candidate = accepted_ticket
    configuration = load_project_configuration(root)
    command = (sys.executable, "-c", "assert open('TEAM_ROUND_DELIVERED.txt').read() == 'complete team round\\n'")
    command = (*command[:2], command[2] + f"; raise SystemExit({validation_exit})")
    monkeypatch.chdir(root)
    from graphtraj.execution.runner_status import runtime_caller

    before = read_worldline(state, root)
    with runtime_caller(root / ".graphtraj/runner", "bound-member"):
        from graphtraj.execution.runner_models import RunnerError
        with pytest.raises((ValueError, RunnerError)) as error:
            integrate_ticket(configuration, "83", command)
        denied = CliRunner().invoke(main, ["ticket", "integrate", "--ticket-id", "83", "--", *command])
    assert denied.exit_code == 1
    assert yaml.safe_load(denied.stdout) == {"error": str(error.value)}
    assert read_worldline(state, root) == before
    monkeypatch.setenv("GRAPHTRAJ_ROLE", "engineer")
    with pytest.raises(ValueError):
        integrate_ticket(configuration, "83", ())
    assert read_worldline(state, root) == before

    if entrypoint == "python":
        result = integrate_ticket(configuration, "83", command)
        assert capsys.readouterr() == ("", "")
    else:
        completed = CliRunner().invoke(main, ["ticket", "integrate", "--ticket-id", "83", "--", *command])
        assert completed.exit_code == validation_exit, completed.output
        result = yaml.safe_load(completed.stdout)
    assert result["status"] == ("integrated" if validation_exit == 0 else "integrating")
    assert result["candidate"] == candidate
    assert set(result["unlocked_ticket_ids"]) == ({"84", "85"} if validation_exit == 0 else set())
    event = next(item for item in read_worldline(state, root) if item["event_id"] == result["event_id"])
    assert event["kind"] == ("ticket-integrated" if validation_exit == 0 else "ticket-integration-failed")
    assert event["validation_command"] == list(command)
    assert result["evidence"] in event["evidence_refs"]
    assert (root / result["evidence"]).is_file()
    assert read_graph(state)["tickets"][0]["status"] == result["status"]


@pytest.fixture
def stopped_committed_integration(
    installed_commands: InstalledCommands,
    accepted_ticket: tuple[Path, Path, Path, str],
    fake_codex: FakeCodex,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, str, list[str]]:
    """Retain a public conflict escalation, sampled stop and committed resolution."""
    from graphtraj.execution import execution_budget

    root, worktrees, state, candidate = accepted_ticket
    dev = worktrees / 'dev'
    delivered = dev / 'TEAM_ROUND_DELIVERED.txt'
    delivered.write_text('conflicting integration work\n')
    for args in (('add', delivered.name), ('commit', '-m', 'Independent integration work')):
        run_process(['git', *args], cwd=dev).check_returncode()
    command = [str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '83']
    validator = root / 'validate-recovery.py'
    validator.write_text(
        "from pathlib import Path\n"
        "assert Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\nconflicting integration work\\n'\n"
        f"assert not Path({str(root / 'fail-validation')!r}).exists()\n"
    )
    validation = [sys.executable, str(validator)]
    failed = run_process(command + ['--', *validation], cwd=root)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    escalated = run_process(command + ['--resolve-conflict', 'Preserve both accepted lines', '--role', 'coding_team.merge_resolver', '--', *validation], cwd=root, env={
        **os.environ, 'HOME': str(root / 'operator-home'),
        'PATH': str(fake_codex.executable.parent) + os.pathsep + os.environ['PATH'],
        'FAKE_CODEX_LOG': str(fake_codex.log_file),
        'FAKE_CODEX_LIFECYCLE_ACTION': 'resolve-integration',
        'FAKE_CODEX_RESOLUTION': 'escalated',
    })
    assert yaml.safe_load(escalated.stdout)['status'] == 'escalated', escalated.stdout + escalated.stderr
    ticket = state / 'tickets/83-integration'
    monitor = execution_budget.ExecutionBudgetMonitor(ticket, '83', 'integration')
    usage = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    with monkeypatch.context() as controlled:
        controlled.setattr(execution_budget.time, 'time', lambda: usage['started_at'] + 100000)
        controlled.setattr(execution_budget.random, 'random', lambda: 1.0)
        assert monitor.check('merge-resolver', 'integration')
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text())['stopped']
    delivered.write_text('complete team round\nconflicting integration work\n')
    run_process(['git', 'add', delivered.name], cwd=dev).check_returncode()
    run_process(['git', 'commit', '--no-edit'], cwd=dev).check_returncode()
    confirmed = run_process(['git', 'rev-parse', 'HEAD'], cwd=dev).stdout.strip()
    return root, dev, state, candidate, command + ['--confirm-resolution', confirmed, '--', *validation]


def test_public_recovery_adopts_committed_merge_and_preserves_history(
    installed_commands: InstalledCommands,
    stopped_committed_integration: tuple[Path, Path, Path, str, list[str]],
    fake_codex: FakeCodex,
) -> None:
    """Recovery validates the committed merge without new work, Round or budget."""
    from graphtraj.graph.delivery_worldline import read_worldline

    root, dev, state, candidate, command = stopped_committed_integration
    ticket = state / 'tickets/83-integration'
    before = read_worldline(state, root)
    retained = {path: retained_state(path) for path in ticket.rglob('*')
                if path.is_file() and path.name != 'ticket.yml'}
    runtime = fake_codex.log_file.read_bytes()
    head = run_process(['git', 'rev-parse', 'HEAD'], cwd=dev).stdout
    result = run_process(command, cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = yaml.safe_load(result.stdout)
    assert outcome['status'] == 'integrated' and outcome['candidate'] == candidate
    assert set(outcome['unlocked_ticket_ids']) == {'84', '85'}
    assert run_process(['git', 'rev-parse', 'HEAD'], cwd=dev).stdout == head
    assert fake_codex.log_file.read_bytes() == runtime
    assert all(retained_state(path) == content for path, content in retained.items())
    assert sorted(path.name for path in (ticket / 'teams/1/rounds').iterdir()) == ['1', '2']
    events = read_worldline(state, root)
    assert events[:len(before)] == before
    started = events[len(before)]
    assert started['caused_by_event_ids'] == [before[-1]['event_id']]
    integrated = next(event for event in events if event['event_id'] == outcome['event_id'])
    assert integrated['caused_by_event_ids'] == [started['event_id']]
    assert integrated['validation_command'] == command[command.index('--') + 1:]
    assert set(before[-1]['evidence_refs']) <= set(integrated['evidence_refs'])


@pytest.mark.parametrize('invalid', ['candidate', 'unrelated-head', 'retained-dev', 'validation-command', 'failed-validation', 'caller', 'unconfirmed'])
def test_public_recovery_rejects_invalid_adoption(
    installed_commands: InstalledCommands,
    stopped_committed_integration: tuple[Path, Path, Path, str, list[str]],
    fake_codex: FakeCodex,
    invalid: str,
) -> None:
    """Invalid identity/version/history or failed validation never unlocks work."""
    from graphtraj.execution.runner_heartbeat import hold_ownership
    from graphtraj.graph.delivery_worldline import read_worldline

    root, dev, state, candidate, command = stopped_committed_integration
    before = read_worldline(state, root)
    runtime = fake_codex.log_file.read_bytes()
    ticket = state / 'tickets/83-integration'
    budget = (ticket / 'execution-budget.yml').read_bytes()
    if invalid == 'unconfirmed':
        index = command.index('--confirm-resolution')
        command = command[:index] + command[index + 2:]
    elif invalid == 'candidate':
        # A public state revision cannot reuse acceptance for another version.
        from graphtraj.graph.ticket_graph import update_ticket_state
        record = yaml.safe_load((ticket / 'ticket.yml').read_text())
        other = run_process(['git', 'rev-parse', 'HEAD'], cwd=dev).stdout.strip()
        cause = before[-1]['event_id']
        for status in ('blocked', 'escalated'):
            revised = update_ticket_state(state, root, {
                key: record[key] for key in ('ticket_id', 'active_team_ordinal', 'worktree', 'branch')
            } | {'status': status, 'current_candidate': other, 'caused_by_event_ids': [cause],
                 'evidence_refs': before[-1]['evidence_refs']})
            cause = revised['event_id']
    elif invalid in {'unrelated-head', 'retained-dev'}:
        target = candidate if invalid == 'retained-dev' else candidate + '^'
        run_process(['git', 'reset', '--hard', target], cwd=dev).check_returncode()
    elif invalid == 'validation-command':
        command = command[:command.index('--') + 1] + [sys.executable, '-c', 'pass']
    elif invalid == 'failed-validation':
        (root / 'fail-validation').touch()
    if invalid == 'caller':
        # An installed CLI child is identified from the real owning process,
        # even after its role environment variable has been removed.
        mapping_path = next(path for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml')
                            if yaml.safe_load(path.read_text())['role'] == 'engineer')
        mapping = yaml.safe_load(mapping_path.read_text())
        mapping.update(worker_pid=os.getpid(), runtime_pid=os.getpid())
        mapping_path.write_text(yaml.safe_dump(mapping))
        environment = {key: value for key, value in os.environ.items() if key != 'GRAPHTRAJ_ROLE'}
        with hold_ownership(mapping_path.parent, os.getpid()):
            result = run_process(command, cwd=root, env=environment)
    else:
        result = run_process(command, cwd=root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert yaml.safe_load((ticket / 'ticket.yml').read_text())['status'] == 'escalated'
    assert (ticket / 'execution-budget.yml').read_bytes() == budget
    assert fake_codex.log_file.read_bytes() == runtime
    graph = yaml.safe_load(run_process([str(installed_commands.product), 'ticket', 'graph'], cwd=root).stdout)
    assert not any(item['ready'] for item in graph['tickets'])
    if invalid == 'failed-validation':
        (root / 'fail-validation').unlink()
        retry = run_process(command, cwd=root)
        assert retry.returncode == 0, retry.stdout + retry.stderr


def test_actual_result_parent_can_integrate_without_role_name_authority(
    installed_commands: InstalledCommands, accepted_ticket: tuple,
) -> None:
    """A bound direct parent may integrate the result it actually accepted."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.teams.ticket_integration import integrate_ticket

    root, _, state, candidate = accepted_ticket
    events = read_worldline(state, root)
    accepted = next(event for event in reversed(events) if event['kind'] == 'team-round-accepted')
    submitted = next(event for event in events if event['event_id'] == accepted['submission_id'])
    mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / submitted['alias'] / 'mapping.yml').read_text())
    assert mapping['parent'] is not None
    with runtime_caller(root / '.graphtraj/runner', mapping['parent']):
        result = integrate_ticket(load_project_configuration(root), '83', (sys.executable, '-c', 'pass'))
    assert result['candidate'] == candidate and result['status'] == 'integrated'
