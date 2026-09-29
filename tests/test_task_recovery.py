"""Recovery and cleanup through public commands and controlled native Sessions."""

import json
import os
import shutil
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
    preflight_failure: bool = False,
    external_inline: bool = False,
) -> tuple[Path, dict, dict]:
    """Start one real managed Session whose model work waits for test release."""
    root, _, _, env = configure_harness(commands, repository, fake_codex, tmp_path)
    roles = {name: {'runtime': 'codex', 'model': 'selected'}
             for name in ([role, 'analyst'] if child or replacement_child else [role])}
    selection = role
    if external_inline:
        # Setup no longer supplies packaged Skills, so this scenario keeps no
        # Harness Skill directory and only the selected external method.
        harness_skills = root / '.agents/skills'
        assert not harness_skills.exists(), harness_skills
        shutil.rmtree(tmp_path / 'operator-home/.agents/skills')
        (root / 'role.txt').write_text('Use the selected external method.\n')
        skill = root / 'external-method'
        skill.mkdir()
        (skill / 'SKILL.md').write_text('---\nname: external-method\ndescription: Research.\n---\n')
        config = root / '.codex/config.toml'
        with config.open('a') as stream:
            stream.write('\n[[skills.config]]\npath = "../external-method"\nenabled = true\n')
        selection = {role: {**roles[role], 'instructions': 'role.txt'}}
    if '.' in role:
        group, _, name = role.rpartition('.')
        roles[group] = {name: roles.pop(role)}
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles,
        'role_tree': {role: {'analyst': {}}} if child or replacement_child else {role: {}},
    }))
    ticket = _ticket('154', 'recovery')
    ticket['body'] = BODY.replace('planned_sessions: {researcher: 1}',
                                 'planned_sessions: {' + role.rpartition('.')[2].replace('-', '_') + ': 1}') + ticket['body']
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
    if preflight_failure:
        invalid = tmp_path / 'invalid-swarm.yml'
        invalid.write_text(yaml.safe_dump({'tasks': [
            {'role': role, 'ticket_id': '154', 'skills': ['implement']},
        ]}))
        failed = command(commands, root, env, '--swarm-input', str(invalid))
        assert failed.returncode == 1, failed.stdout + failed.stderr
        assert 'Runtime native Skill selection' in failed.stdout + failed.stderr
        sessions = root / '.graphtraj/runner/sessions'
        assert not sessions.exists() or not list(sessions.iterdir())
        traces = root / '.graphtraj/state/tickets/154-recovery/teams/1/traces'
        assert not traces.exists() or not list(traces.iterdir())

    result = subprocess.run(
        [str(commands.runner.with_name('graphtraj-mcp'))], cwd=root, env=env,
        input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                          'params': {'name': 'graphtraj', 'arguments': {
                              'action': 'execute', 'feature': 'swarm', 'arguments': {
                                  'tasks': [{'role': selection, 'ticket_id': '154'}]}}}}) + '\n',
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    task = json.loads(result.stdout)['result']['structuredContent']['tasks'][0]
    assert task['launch_status'] in {'launched', 'completed'}, json.dumps(task)
    wait_for_file(Path(env['RECOVERY_STARTED']))
    return root, env, task


@pytest.mark.parametrize('operation', ['send', 'replace'])
@pytest.mark.parametrize('historical', [False, True])
def test_external_inline_resources_survive_recovery(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    operation: str,
    historical: bool,
) -> None:
    """Recovery uses captured resources; replacement selects current native config."""
    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher', external_inline=True)
    alias = task['alias']
    sessions = root / '.graphtraj/runner/sessions'
    directory = sessions / alias
    ticket = root / '.graphtraj/state/tickets/154-recovery'
    try:
        if operation == 'send':
            Path(env['RECOVERY_RELEASE']).touch()
            wait_for_file(directory / 'execution.yml')
        else:
            stopped = command(installed_commands, root, env, 'interrupt', alias)
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        original = yaml.safe_load((directory / 'mapping.yml').read_text())
        batch_file = Path(original['retained_batch_file'])
        if historical:
            batch = yaml.safe_load(batch_file.read_text())
            batch['tasks'][0]['skills'] = ['uninstalled-old-method']
            preset = batch['tasks'][0]['role']['researcher']
            for field in ('skills', 'harness_skills', 'required_skills'):
                preset[field] = ['uninstalled-old-method']
            batch_file.chmod(0o644)
            batch_file.write_text(yaml.safe_dump(batch))
            batch_file.chmod(0o444)
            launch = yaml.safe_load((directory / 'launch.yml').read_text())
            launch['context_evidence']['effective_skills'] = [{
                'name': 'captured-method', 'path': str(root / 'external-method'),
            }]
            (directory / 'launch.yml').write_text(yaml.safe_dump(launch))
        batch_before = batch_file.read_bytes()
        launch_before = (directory / 'launch.yml').read_bytes()
        launch = yaml.safe_load(launch_before)
        before = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        captured = launch['adapter_request']['session_parameters']
        assert captured['config']['skills']['config'] == [
            {'path': str(root / 'external-method'), 'enabled': True},
        ]
        config = root / '.codex/config.toml'
        config.write_text(config.read_text().replace('enabled = true', 'enabled = false'))
        if operation == 'send':
            # Resume must not reload the role body or recreate captured resources.
            (root / 'role.txt').unlink()
        Path(env['RECOVERY_RELEASE']).touch()
        args = (['send', alias, '--instruction', 'Continue the retained work.']
                if operation == 'send' else ['replace', alias])
        result = command(installed_commands, root, env, *args,
                         '--caused-by-event-id', events(root)[-1]['event_id'])
        assert result.returncode == 0, result.stdout + result.stderr
        current_alias = alias if operation == 'send' else yaml.safe_load(result.stdout)['replacement_alias']
        current_directory = sessions / current_alias
        wait_for_file(current_directory / 'execution.yml')
        assert yaml.safe_load((current_directory / 'execution.yml').read_text())['outcome'] == 'completed'
        current = yaml.safe_load((current_directory / 'mapping.yml').read_text())
        record = yaml.safe_load((current_directory / ('resume.yml' if operation == 'send' else 'launch.yml')).read_text())
        params = record['adapter_request']['session_parameters']
        assert current['parent'] == original['parent']
        assert current['role_reference'] == original['role_reference'] == 'researcher'
        assert batch_file.read_bytes() == batch_before
        assert (directory / 'launch.yml').read_bytes() == launch_before
        assert current['retained_batch_file'] == str(batch_file)
        if operation == 'send':
            assert current['session'] == original['session']
            assert current['report_files'] == original['report_files']
            assert params == captured
            assert record['context_evidence'] == launch['context_evidence']
        else:
            assert current['session'] != original['session']
            assert current['report_files'] != original['report_files']
            assert params['config']['skills']['config'] == [
                {'path': str(root / 'external-method'), 'enabled': False},
            ]
        after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        for field in ('started_at', 'allowance_minutes'):
            assert after[field] == before[field]
        assert after['sessions']['researcher'] == (1 if operation == 'send' else 2)
        assert not (root / '.agents/skills').exists()
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)


@pytest.mark.parametrize('role, historical', [
    ('researcher', False), ('team-leader', False), ('engineer-expert', False),
    ('coding-team.engineer', True),
])
def test_explicitly_stopped_member_is_replaced_without_executing_old_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: str,
    historical: bool,
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
        if historical:
            # Reproduce an old Batch whose actual registered identity was engineer.
            batch_file = Path(original['retained_batch_file'])
            batch = yaml.safe_load(batch_file.read_text())
            batch['tasks'][0]['role'] = 'coding-team.engineer-expert'
            batch['tasks'][0]['skills'] = ['uninstalled-old-method']
            batch_file.chmod(0o644)
            batch_file.write_text(yaml.safe_dump(batch))
            batch_file.chmod(0o444)
            original['role_reference'] = 'coding-team.engineer-expert'
            (runner / alias / 'mapping.yml').write_text(yaml.safe_dump(original))
            roles_file = root / '.graphtraj/roles.yml'
            roles = yaml.safe_load(roles_file.read_text())
            roles['roles']['coding-team']['engineer-expert'] = dict(roles['roles']['coding-team']['engineer'])
            roles_file.write_text(yaml.safe_dump(roles))

        retained_batch = Path(original['retained_batch_file']).read_bytes()

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
        usage = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        actual_role = role.rpartition('.')[2]
        key = actual_role.replace('-', '_')
        assert usage['sessions'] == {key: 2}
        assert usage['notifications'].count('planned_sessions.' + key + ':1') == 1
        assert current['role'] == original['role'] == actual_role
        assert Path(original['retained_batch_file']).read_bytes() == retained_batch
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

    root, env, task = prepare(installed_commands, temporary_git_repository, fake_codex,
                              tmp_path, 'researcher', external_inline=True)
    alias = task['alias']
    directory = root / '.graphtraj/runner/sessions' / alias
    ticket = root / '.graphtraj/state/tickets/154-recovery'
    cause = events(root)[-1]['event_id']
    original = yaml.safe_load((directory / 'mapping.yml').read_text())
    original_launch = (directory / 'launch.yml').read_bytes()
    original_batch = Path(original['retained_batch_file']).read_bytes()
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
        (root / 'role.txt').unlink()
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
                                  'params': {'name': 'graphtraj', 'arguments': {
                                      'action': 'execute', 'feature': 'continue',
                                      'arguments': {
                                          'ticket_id': '154',
                                          'caused_by_event_ids': [decision_id]}}}}) + '\n',
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
        assert len(after['parent_notices']) == len(before['parent_notices'])
        context = yaml.safe_load((directory / 'resume.yml').read_text())
        assert context['monitor_execution_budget'] and context['drive_children']
        assert (directory / 'launch.yml').read_bytes() == original_launch
        assert Path(original['retained_batch_file']).read_bytes() == original_batch
        assert context['adapter_request']['session_parameters'] == yaml.safe_load(
            original_launch)['adapter_request']['session_parameters']
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


@pytest.mark.parametrize('budget_only', [False, True])
def test_failed_first_creation_can_continue_budget_before_ordinary_launch(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget_only: bool,
) -> None:
    """Task continuation clears permission without inventing a Team or Session."""
    from graphtraj.execution import execution_budget as budgets
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.teams.team_round import continue_stopped_ticket

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': {'researcher': {}},
    }))
    definition = _ticket('160', 'first-session')
    definition['body'] = BODY + definition['body']
    _register(installed_commands, root, definition)
    _change_status(installed_commands, root, '160', 'ready')
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': 'researcher', 'ticket_id': '160'}]}))
    ticket = root / '.graphtraj/state/tickets/160-first-session'
    runner = root / '.graphtraj/runner'
    env['FAKE_CODEX_EVENTS'] = '[]'
    failed = command(installed_commands, root, env, '--swarm-input', str(batch))
    assert failed.returncode == 1, failed.stdout + failed.stderr
    failures = {path: path.read_bytes() for path in (runner / 'sessions').glob('*/launch-error.yml')}
    assert failures
    assert not list((runner / 'sessions').glob('*/mapping.yml'))
    assert yaml.safe_load((ticket / 'ticket.yml').read_text())['active_team_ordinal'] is None
    monitor = budgets.execution_budget_monitor(ticket, '160', 'first-session')
    cause = events(root)[-1]['event_id']
    refused = command(installed_commands, root, env, 'continue', '--ticket-id', '160',
                      '--caused-by-event-id', cause)
    assert refused.returncode == 1 and 'sampled stopped Ticket' in refused.stdout
    sample_stop(monitor, monkeypatch)
    before = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    assert before['stopped'] and sum(before['sessions'].values()) == 0

    definition.update(active=True, replaced_by=[])
    definition['body'] = definition['body'].replace('total: 10', 'total: 35').replace(
        'execution_budget:\n',
        'execution_budget:\n  revision_reason: Authorized recovery after failed creation\n',
    )
    revision = root / 'revision.yml'
    revision.write_text(yaml.safe_dump({
        'product_preserving': True, 'tickets': [definition],
        'caused_by_event_ids': [cause], 'evidence_refs': ['delivery-evidence.md'],
    }))
    revised = run_process([str(installed_commands.product), 'ticket', 'revise',
                           '--revision-file', str(revision)], cwd=root, env=env)
    assert revised.returncode == 0, revised.stdout + revised.stderr
    cause = yaml.safe_load(revised.stdout)['event_id']
    blocked = command(installed_commands, root, env, '--swarm-input', str(batch))
    assert blocked.returncode == 1
    assert yaml.safe_load(blocked.stdout)['tasks'][0]['launch_status'] == 'stopped', blocked.stdout
    assert monitor.is_stopped()
    revised_budget = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    assert revised_budget['budget']['execution_budget']['estimated_minutes']['total'] == 35
    for field in ('started_at', 'allowance_minutes', 'stopping_checks', 'sessions', 'notifications'):
        assert revised_budget[field] == before[field]
    retained = (ticket / 'execution-budget.yml').read_bytes()
    history = events(root)
    with runtime_caller(runner, 'unrelated-native-session'):
        with pytest.raises(RunnerError, match='Only the root caller'):
            continue_stopped_ticket('160', (cause,), root)
    for causes in ((), ('missing-event',), (cause, cause)):
        with pytest.raises(RunnerError):
            continue_stopped_ticket('160', causes, root)
    assert (ticket / 'execution-budget.yml').read_bytes() == retained
    assert events(root) == history

    continued = command(installed_commands, root, env, 'continue', '--ticket-id', '160',
                        '--caused-by-event-id', cause, *(['--budget-only'] if budget_only else []))
    assert continued.returncode == 0, continued.stdout + continued.stderr
    result = yaml.safe_load(continued.stdout)
    assert result['tasks'] == []
    after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    assert after == dict(revised_budget, stopped=False)
    assert yaml.safe_load((ticket / 'ticket.yml').read_text())['active_team_ordinal'] is None
    assert not list(ticket.glob('teams/*/team.yml'))
    continuation = next(e for e in events(root) if e['event_id'] == result['continuation_event_id'])
    assert continuation['caused_by_event_ids'] == [cause]
    assert 'team_ordinal' not in continuation and 'team_round' not in continuation

    del env['FAKE_CODEX_EVENTS']
    launched = command(installed_commands, root, env, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    task = yaml.safe_load(launched.stdout)['tasks'][0]
    directory = runner / 'sessions' / task['alias']
    wait_for_file(directory / 'execution.yml')
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    assert mapping['session'] == task['session'] and mapping['parent'] is None
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert [member['session_ref'] for member in team['members'].values()] == [task['alias']]
    final_budget = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    for field in ('started_at', 'allowance_minutes', 'stopping_checks', 'notifications'):
        assert final_budget[field] == after[field]
    assert final_budget['sessions'] == {'researcher': 1}
    assert all(path.read_bytes() == content for path, content in failures.items())


@pytest.mark.parametrize('cancelled', [False, True])
def test_task_continuation_requires_active_ready_task_before_first_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancelled: bool,
) -> None:
    """Neither pending nor cancelled work gains permission from a budget stop."""
    from graphtraj.execution import execution_budget as budgets

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    definition = _ticket('160', 'first-session')
    definition['body'] = BODY + definition['body']
    _register(installed_commands, root, definition)
    if cancelled:
        _change_status(installed_commands, root, '160', 'ready')
        definition.update(active=False, replaced_by=[])
        revision = root / 'cancel.yml'
        revision.write_text(yaml.safe_dump({
            'product_preserving': True, 'tickets': [definition],
            'caused_by_event_ids': [events(root)[-1]['event_id']],
            'evidence_refs': ['delivery-evidence.md'],
        }))
        result = run_process([str(installed_commands.product), 'ticket', 'revise',
                              '--revision-file', str(revision)], cwd=root, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
    ticket = root / '.graphtraj/state/tickets/160-first-session'
    monitor = budgets.execution_budget_monitor(ticket, '160', 'first-session')
    assert not monitor.is_stopped()
    sample_stop(monitor, monkeypatch)
    retained = (ticket / 'execution-budget.yml').read_bytes()
    history = events(root)
    result = command(installed_commands, root, env, 'continue', '--ticket-id', '160',
                     '--caused-by-event-id', history[-1]['event_id'])
    assert result.returncode == 1 and 'invalid-input' in result.stdout
    assert (ticket / 'execution-budget.yml').read_bytes() == retained
    assert events(root) == history


@pytest.mark.parametrize('surface', ['cli', 'mcp'])
def test_budget_only_continuation_leaves_old_subtree_for_new_configured_root(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """Restore permission without running old entities, then dispatch a new root."""
    from graphtraj.execution import execution_budget as budgets
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.teams.team_round import continue_stopped_ticket

    root, env, task = prepare(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
        'researcher', child=True,
    )
    alias = task['alias']
    runner = root / '.graphtraj/runner'
    ticket = root / '.graphtraj/state/tickets/154-recovery'
    child = json.loads((Path(task['worktree_path']) / 'child.json').read_text())['alias']
    directories = [runner / 'sessions' / member for member in (alias, child)]
    cause = events(root)[-1]['event_id']
    try:
        # The child is really executing; budget-only must not bypass subtree checks.
        busy = command(installed_commands, root, env, 'continue', '--ticket-id', '154',
                       '--budget-only', '--caused-by-event-id', cause)
        assert busy.returncode == 1 and 'replacement-not-stopped' in busy.stdout
        monitor = budgets.execution_budget_monitor(ticket, '154', 'recovery')
        sample_stop(monitor, monkeypatch)
        for directory in directories:
            wait_for_file(directory / 'execution.yml')
        before = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        assert before['stopped']
        originals = [yaml.safe_load((directory / 'mapping.yml').read_text())
                     for directory in directories]
        assert originals[1]['parent'] == alias
        retained = {
            path: path.read_bytes()
            for directory, mapping in zip(directories, originals)
            for path in (directory / 'mapping.yml', directory / 'execution.yml',
                         Path(mapping['trace_file']))
        }
        history = events(root)
        with runtime_caller(runner, originals[1]['session']):
            with pytest.raises(RunnerError) as refused:
                continue_stopped_ticket('154', (cause,), root, budget_only=True)
            assert refused.value.code == 'authority-denied'
        for causes in ((), ('missing-event',), (cause, cause)):
            with pytest.raises(RunnerError):
                continue_stopped_ticket('154', causes, root, budget_only=True)

        # A resolved member from another Team must fail before permission changes.
        from graphtraj.teams import team_round
        read_mapping = team_round.read_alias_mapping

        def mismatched_member(directory: Path, member: str) -> tuple[dict, Path]:
            """Supply a mismatched resolved mapping at the storage boundary."""
            mapping, location = read_mapping(directory, member)
            return dict(mapping, team_generation=mapping['team_generation'] + 1), location

        with monkeypatch.context() as patch:
            patch.setattr(team_round, 'read_alias_mapping', mismatched_member)
            with pytest.raises(RunnerError, match='retained lifecycle'):
                continue_stopped_ticket('154', (cause,), root, budget_only=True)
        assert yaml.safe_load((ticket / 'execution-budget.yml').read_text()) == before
        assert events(root) == history

        if surface == 'cli':
            continued = command(installed_commands, root, env, 'continue', '--ticket-id', '154',
                                '--budget-only', '--caused-by-event-id', cause)
            assert continued.returncode == 0, continued.stdout + continued.stderr
            result = yaml.safe_load(continued.stdout)
        else:
            continued = subprocess.run(
                [str(installed_commands.runner.with_name('graphtraj-mcp'))], cwd=root, env=env,
                input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                  'params': {'name': 'graphtraj', 'arguments': {
                                      'action': 'execute', 'feature': 'continue',
                                      'arguments': {
                                          'ticket_id': '154',
                                          'caused_by_event_ids': [cause],
                                          'budget_only': True}}}}) + '\n',
                text=True, capture_output=True, timeout=20,
            )
            assert continued.returncode == 0, continued.stdout + continued.stderr
            document = json.loads(continued.stdout)['result']
            assert not document['isError'], document
            result = document['structuredContent']
        assert result['tasks'] == []
        after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        assert after == dict(before, stopped=False)
        assert all(path.read_bytes() == content for path, content in retained.items())
        continuation = next(e for e in events(root) if e['event_id'] == result['continuation_event_id'])
        assert continuation['caused_by_event_ids'] == [cause]
        repeated = command(installed_commands, root, env, 'continue', '--ticket-id', '154',
                           '--budget-only', '--caused-by-event-id', cause)
        assert repeated.returncode == 1 and 'sampled stopped Ticket' in repeated.stdout

        roles_path = root / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_path.read_text())
        roles['roles']['expert'] = {'runtime': 'codex', 'model': 'expert-selected'}
        roles['role_tree']['expert'] = {}
        roles_path.write_text(yaml.safe_dump(roles))
        batch = root / 'expert.yml'
        batch.write_text(yaml.safe_dump({'tasks': [{'role': 'expert', 'ticket_id': '154'}]}))
        Path(env['RECOVERY_RELEASE']).touch()
        launched = command(installed_commands, root, env, '--swarm-input', str(batch))
        assert launched.returncode == 0, launched.stdout + launched.stderr
        new = yaml.safe_load(launched.stdout)['tasks'][0]
        directory = runner / 'sessions' / new['alias']
        wait_for_file(directory / 'execution.yml')
        mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        assert mapping['session'] == new['session']
        assert mapping['session'] not in {old['session'] for old in originals}
        assert mapping['parent'] is None and mapping['role'] == 'expert'
        assert Path(mapping['trace_file']).is_file()
        team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
        assert {member['session_ref'] for member in team['members'].values()} == {
            alias, child, new['alias'],
        }
        assert all(path.read_bytes() == content for path, content in retained.items())
        final = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
        for field in ('started_at', 'allowance_minutes', 'stopping_checks', 'notifications'):
            assert final[field] == after[field]
        assert final['sessions'] == dict(after['sessions'], expert=1)
    finally:
        Path(env['RECOVERY_RELEASE']).touch()
        command(installed_commands, root, env, 'interrupt', alias)
