"""Recovery and cleanup through public commands and controlled native Sessions."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_task_budget_control import BODY, sample_stop
from test_ticket_graph import _change_status, _register, _ticket


@pytest.fixture
def installed_commands(request: pytest.FixtureRequest) -> InstalledCommands:
    """Use the independent candidate installation retained outside pytest scratch."""
    candidate = os.environ.get('TICKET154_CANDIDATE_BIN')
    if candidate is None:
        return request.getfixturevalue('installed_commands')
    directory = Path(candidate)
    return InstalledCommands(directory / 'graphtraj', directory / 'agent-runner')


def events(root: Path) -> list[dict]:
    """Read this controlled project's retained public causal history."""
    return [json.loads(line) for shard in sorted((root / '.graphtraj/state/worldline').glob('*.jsonl'))
            for line in shard.read_text().splitlines()]


def command(commands: InstalledCommands, root: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    """Invoke the public Runner with a bounded lifetime."""
    return run_process([str(commands.runner), *args], cwd=root, env=env, timeout=30)


def prepare(
    commands: InstalledCommands,
    repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: str,
    child: bool = False,
    replacement_child: bool = False,
) -> tuple[Path, dict, dict]:
    """Start one real managed Session whose model work waits for test release."""
    root, _, _, env = configure_harness(commands, repository, fake_codex, tmp_path)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {name: {'runtime': 'codex', 'model': 'selected'}
                  for name in ([role, 'analyst'] if child or replacement_child else [role])},
        'role_tree': {role: {'analyst': {}}} if child or replacement_child else {role: {}},
    }))
    ticket = _ticket('154', 'recovery')
    ticket['body'] = BODY + ticket['body']
    _register(commands, root, ticket)
    _change_status(commands, root, '154', 'ready')
    env['RECOVERY_RELEASE'] = str(tmp_path / 'release')
    env['RECOVERY_STARTED'] = str(tmp_path / 'started')
    if child:
        env['RECOVERY_CHILD'] = '1'
    if replacement_child:
        env['RECOVERY_CHILD'] = 'replacement'
    scenario = Path(__file__).with_name('task_recovery_scenario.py')
    fake_codex.executable.write_text(app_server_peer(
        '#!' + sys.executable + '\nimport runpy\nrunpy.run_path(' + repr(str(scenario)) + ')\n',
        "os.environ['GRAPHTRAJ_PARENT_ALIAS']",
    ))
    result = subprocess.run(
        [str(commands.runner.with_name('graphtraj-mcp'))], cwd=root, env=env,
        input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'swarm', 'arguments': {
                              'tasks': [{'role': role, 'ticket_id': '154'}]}}}) + '\n',
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    task = json.loads(result.stdout)['result']['structuredContent']['tasks'][0]
    wait_for_file(Path(env['RECOVERY_STARTED']))
    return root, env, task


@pytest.mark.parametrize('role', ['researcher', 'team-leader'])
def test_explicitly_stopped_member_is_replaced_without_executing_old_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: str,
) -> None:
    """Replacement needs a stopped target, retains its evidence and uses no fixed seat."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex, tmp_path, role)
    alias = task['alias']
    runner = root / '.graphtraj/runner/sessions'
    ticket = root / '.graphtraj/state/tickets/154-recovery'
    cause = events(root)[-1]['event_id']
    try:
        refused = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert refused.returncode == 1 and 'replacement-not-stopped' in refused.stdout
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        original = yaml.safe_load((runner / alias / 'mapping.yml').read_text())
        marker = (runner / alias / 'stop.yml').read_bytes()
        trace = Path(original['trace_file']).read_bytes()
        reports = yaml.safe_load(command(installed_commands, root, env, 'reports', alias).stdout)['reports']
        assert reports and 'Retained work' in reports[0]['text']
        Path(env['RECOVERY_RELEASE']).touch()
        replaced = command(installed_commands, root, env, 'replace', alias, '--caused-by-event-id', cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        replacement = yaml.safe_load(replaced.stdout)['replacement_alias']
        wait_for_file(runner / replacement / 'execution.yml')
        current = yaml.safe_load((runner / replacement / 'mapping.yml').read_text())
        assert current['session'] != original['session']
        assert current['parent'] == original['parent'] is None
        assert current['retained_batch_file'] == original['retained_batch_file']
        assert current['report_files'] != original['report_files']
        assert (runner / alias / 'stop.yml').read_bytes() == marker
        assert Path(original['trace_file']).read_bytes() == trace
        assert Path(reports[0]['path']).read_text() == reports[0]['text']
        team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
        assert team['status'] == 'active'
        assert [member['session_ref'] for member in team['members'].values()] == [replacement]
        stale = command(installed_commands, root, env, 'send', alias, '--instruction', 'Work',
                        '--caused-by-event-id', cause)
        assert stale.returncode == 1 and 'seat-replaced' in stale.stdout
        delivered = yaml.safe_load(command(installed_commands, root, env, 'reports', replacement).stdout)
        submission = delivered['submissions'][0]
        accepted = command(
            installed_commands, root, env, 'decide-result',
            '--submission-id', submission['event_id'], '--commit', submission['candidate'],
            '--decision', 'accepted', '--reason', 'Recovered research satisfies the task',
            '--evidence-ref', submission['evidence_refs'][0],
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        integrated = run_process(
            [str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '154', '--',
             sys.executable, '-c', "from pathlib import Path; assert '# Research' in Path('result.md').read_text()"],
            cwd=root, env=env, timeout=20,
        )
        assert integrated.returncode == 0, integrated.stdout + integrated.stderr
        state = root / '.graphtraj/state'
        retained = {path: path.read_bytes() for path in state.rglob('*') if path.is_file()}
        batch = Path(original['retained_batch_file'])
        assert batch in retained and Path(original['trace_file']) in retained
        cleaned = command(installed_commands, root, env, 'cleanup', '--ticket-id', '154')
        assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
        assert yaml.safe_load(cleaned.stdout)['cleanup_status'] == 'cleaned'
        assert not Path(task['worktree_path']).exists()
        assert all(path.read_bytes() == content for path, content in retained.items())
        assert run_process(['git', 'cat-file', '-e', submission['candidate'] + ':result.md'],
                           cwd=temporary_git_repository).returncode == 0
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


@pytest.mark.parametrize('surface', ['cli', 'mcp'])
def test_sampled_stop_continues_original_researcher_with_unchanged_accounting(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """D7's physical stop feeds authorized continuation without another member."""
    from graphtraj.execution import execution_budget as budgets

    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex, tmp_path, 'researcher')
    alias = task['alias']
    directory = root / '.graphtraj/runner/sessions' / alias
    ticket = root / '.graphtraj/state/tickets/154-recovery'
    cause = events(root)[-1]['event_id']
    original = yaml.safe_load((directory / 'mapping.yml').read_text())
    try:
        busy = command(installed_commands, root, env, 'continue', '--ticket-id', '154',
                       '--caused-by-event-id', cause)
        assert busy.returncode == 1
        assert yaml.safe_load((directory / 'mapping.yml').read_text())['execution_id'] == original['execution_id']
        monitor = budgets.execution_budget_monitor(ticket, '154', 'recovery')
        sample_stop(monitor, monkeypatch)
        wait_for_file(directory / 'execution.yml')
        terminal = yaml.safe_load((directory / 'execution.yml').read_text())
        assert terminal['outcome'] == 'interrupted' and terminal['budget_stopped']
        before = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        assert before['stopped']
        trace = Path(original['trace_file']).read_bytes()
        decision = root / 'continue.yml'
        decision.write_text(yaml.safe_dump({
            'kind': 'ticket-continuation-decided', 'ticket_id': '154',
            'caused_by_event_ids': [events(root)[-1]['event_id']],
            'evidence_refs': [str(Path(original['trace_file']).relative_to(root))],
            'decision': 'Continue within the original task allowance',
        }))
        authorized = run_process([str(installed_commands.product), 'worldline', 'append',
                                  '--event-file', str(decision)], cwd=root, env=env)
        assert authorized.returncode == 0, authorized.stdout + authorized.stderr
        decision_id = yaml.safe_load(authorized.stdout)['event_id']
        Path(env['RECOVERY_RELEASE']).touch()
        if surface == 'cli':
            resumed = command(installed_commands, root, env, 'continue', '--ticket-id', '154',
                              '--caused-by-event-id', decision_id)
            assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        else:
            resumed = subprocess.run(
                [str(installed_commands.runner.with_name('graphtraj-mcp'))], cwd=root, env=env,
                input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                  'params': {'name': 'continue', 'arguments': {
                                      'ticket_id': '154', 'caused_by_event_ids': [decision_id]}}}) + '\n',
                text=True, capture_output=True, timeout=20,
            )
            assert resumed.returncode == 0, resumed.stdout + resumed.stderr
            assert not json.loads(resumed.stdout)['result']['isError'], resumed.stdout
        wait_for_file(directory / 'execution.yml')
        current = yaml.safe_load((directory / 'mapping.yml').read_text())
        assert current['session'] == original['session']
        assert current['execution_id'] != original['execution_id']
        assert current['report_files'] == original['report_files']
        assert current['parent'] == original['parent']
        assert current['retained_batch_file'] == original['retained_batch_file']
        assert Path(original['trace_file']).read_bytes().startswith(trace)
        team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
        assert [member['session_ref'] for member in team['members'].values()] == [alias]
        after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        assert not after['stopped']
        for field in ('started_at', 'allowance_minutes', 'sessions', 'stopping_checks', 'notifications'):
            assert after[field] == before[field]
        assert len(after['leader_notices']) == len(before['leader_notices'])
        context = yaml.safe_load((directory / 'resume.yml').read_text())
        assert context['monitor_execution_budget'] and context['drive_children']
        result = yaml.safe_load(command(installed_commands, root, env, 'reports', alias).stdout)
        assert len(result['submissions']) == 1
        continuation = next(event for event in events(root) if event['kind'] == 'team-continuation-started')
        assert continuation['caused_by_event_ids'] == [decision_id]
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


def test_cancelled_task_is_neither_recoverable_nor_cleanable(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Cancelling an actual task keeps its stopped evidence and never means complete."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex, tmp_path, 'researcher')
    alias = task['alias']
    try:
        stopped = command(installed_commands, root, env, 'interrupt', alias)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        definition = _ticket('154', 'recovery')
        definition.update(body=BODY + definition['body'], active=False, replaced_by=[])
        revision = root / 'cancel.yml'
        revision.write_text(yaml.safe_dump({
            'product_preserving': True, 'tickets': [definition],
            'caused_by_event_ids': [events(root)[-1]['event_id']],
            'evidence_refs': ['delivery-evidence.md'],
        }))
        cancelled = run_process([str(installed_commands.product), 'ticket', 'revise',
                                 '--revision-file', str(revision)], cwd=root, env=env)
        assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
        cause = events(root)[-1]['event_id']
        ticket = root / '.graphtraj/state/tickets/154-recovery'
        retained = {path: path.read_bytes() for path in ticket.rglob('*') if path.is_file()}
        for args in (
            ('continue', '--ticket-id', '154', '--caused-by-event-id', cause),
            ('replace', alias, '--caused-by-event-id', cause),
            ('send', alias, '--instruction', 'Resume', '--caused-by-event-id', cause),
            ('cleanup', '--ticket-id', '154'),
        ):
            refused = command(installed_commands, root, env, *args)
            assert refused.returncode == 1, refused.stdout + refused.stderr
        assert all(path.read_bytes() == content for path, content in retained.items())
        graph = run_process([str(installed_commands.product), 'ticket', 'graph'], cwd=root, env=env)
        record = yaml.safe_load(graph.stdout)['tickets'][0]
        assert record['status'] == 'implementing' and not record['active'] and not record['ready']
        assert Path(task['worktree_path']).exists()
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)
