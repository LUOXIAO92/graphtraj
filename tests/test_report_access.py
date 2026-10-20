"""Report submission is bound to the issuing Session, not a supplied owner."""

from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution import runner_control
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from conftest import FakeCodex, InstalledCommands
from test_result_submission import result_project


def test_report_submission_uses_only_the_issuers_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An assigned filename works; another report or a Main claim cannot write."""
    runner, team, _ = result_project(tmp_path)
    report = team.parent / 'rounds/1/researcher-x1.md'
    with runtime_caller(runner, 'research@x1'):
        result = runner_control.submit_session_report('researcher-x1.md', 'owned report', tmp_path)
        assert result['alias'] == 'research@x1'
        assert report.read_text() == 'owned report'
        with pytest.raises(RunnerError) as denied:
            runner_control.submit_session_report('../leader.md', 'wrong owner', tmp_path)
        assert denied.value.code == 'authority-denied'
    with runtime_caller(runner, None):
        with pytest.raises(RunnerError) as denied:
            runner_control.submit_session_report('researcher-x1.md', 'not its report', tmp_path)
        assert denied.value.code == 'authority-denied'
    assert report.read_text() == 'owned report'


def test_report_reader_rejects_a_redirected_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared report access cannot follow a link to another report."""
    runner, team, _ = result_project(tmp_path)
    report = team.parent / 'rounds/1/researcher-x1.md'
    report.parent.mkdir(parents=True, exist_ok=True)
    private = report.with_name('other.md')
    private.write_text('synthetic other report')
    report.symlink_to(private)
    with runtime_caller(runner, None):
        with pytest.raises(RunnerError) as denied:
            runner_control.read_session_reports('research@x1', tmp_path)
    assert denied.value.code == 'authority-denied'


def test_failed_report_delivery_remains_visible_only_to_its_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retained native delivery errors are readable without sending another notice."""
    runner, _, _ = result_project(tmp_path)
    mapping_path = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(mapping_path.read_text())
    mapping['parent_connection'] = {
        'runtime': 'codex', 'session': 'original-main', 'codex_home': '/private/native-home',
    }
    mapping_path.write_text(yaml.safe_dump(mapping))
    calls = []

    def refuse(address: dict, document: dict, **kwargs: object) -> None:
        """Return the original transport error at the native host boundary."""
        calls.append(document)
        raise RunnerError('RUNTIME_REQUEST_INVALID', 'Owning host is not loaded')

    monkeypatch.setattr(runner_control, 'connection_operation', refuse)
    monkeypatch.setattr(runner_control, 'OPERATION_TIMEOUT_SECONDS', 0)
    with runtime_caller(runner, 'research@x1'):
        submitted = runner_control.submit_session_report(
            'researcher-x1.md', 'Preserved findings', tmp_path, notify_parent=True,
        )
    assert submitted['delivery'] == 'not-delivered'
    assert submitted['delivery_error']['code'] == 'RUNTIME_REQUEST_INVALID'
    with runtime_caller(runner, None):
        observed = runner_control.read_session_reports('research@x1', tmp_path)
    receipt = observed['report_notification']
    assert receipt['delivery'] == 'not-delivered'
    assert receipt['error'] == submitted['delivery_error']
    assert receipt['parent_connection'] == {'runtime': 'codex', 'session': 'original-main'}
    assert observed['reports'][0]['text'] == 'Preserved findings'
    assert len(calls) == 1
    # A non-direct project member reads the same development record.
    with runtime_caller(runner, 'research@x2'):
        assert runner_control.read_session_reports('research@x1', tmp_path)['reports'] == observed['reports']


def test_direct_parent_reads_terminal_message_without_report_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary children expose their completed result to verified project callers."""
    config = tmp_path / '.graphtraj/config.yml'
    directory = config.parent / 'runner/sessions/child@e1'
    directory.mkdir(parents=True)
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    (directory / 'execution.yml').write_text(
        'outcome: completed\nterminal_confirmed: true\nlast_agent_message: synthetic-result\n')
    monkeypatch.setattr(runner_control, 'read_alias_mapping',
                        lambda *args: ({'parent': 'parent@l1'}, directory))
    monkeypatch.setattr(runner_control, '_session_report_paths', lambda *args, **kwargs: ())
    with runtime_caller(config.parent / 'runner', None):
        result = runner_control.read_session_reports('child@e1', tmp_path)
        assert result == {'alias': 'child@e1', 'reports': [], 'last_agent_message': 'synthetic-result',
                          'execution': {'outcome': 'completed', 'terminal_confirmed': True}}
    # An unregistered identity is not a project caller.
    with runtime_caller(config.parent / 'runner', 'sibling@e2'):
        with pytest.raises(RunnerError) as denied:
            runner_control.read_session_reports('child@e1', tmp_path)
        assert denied.value.code == 'authority-denied'


@pytest.mark.parametrize('role', ['researcher', 'engineer', 'spec-reviewer'])
@pytest.mark.parametrize('source', ['mapping', 'native-launch', 'cli-launch'])
def test_historical_report_assignments_preserve_ownership(
    tmp_path: Path, role: str, source: str,
) -> None:
    """Retained assignments expose only owned reports, without changing records."""
    runner, team, _ = result_project(tmp_path)
    directory = runner / 'sessions/research@x1'
    mapping_file = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    del mapping['report_files']
    mapping.update(role=role, parent='parent@p1')
    own = team.parents[2] / 'notes/actual-findings.md'
    own.parent.mkdir()
    own.write_text('Original findings')
    sibling = own.with_name('private.md')
    sibling.write_text('Private sibling evidence')
    config = {'default_permissions': 'restricted', 'permissions': {
        'restricted': {'filesystem': {str(own): 'write', str(sibling): 'read'}}}}
    request = {'worktree_path': mapping['worktree_path']}
    if source == 'mapping':
        mapping['report_file'] = '.state/notes/actual-findings.md'
    elif source == 'native-launch':
        request['session_parameters'] = {'config': config}
    else:
        import json
        request['arguments'] = ['codex', '-c', 'default_permissions="restricted"', '-c',
            'permissions={ restricted = { filesystem = { '
            + json.dumps(str(own)) + ' = "write", '
            + json.dumps(str(sibling)) + ' = "read" } } }']
    mapping_file.write_text(yaml.safe_dump(mapping))
    launch_file = directory / 'launch.yml'
    launch_file.write_text(yaml.safe_dump({'runtime': 'codex', 'mapping': mapping,
                                         'connection': {}, 'adapter_request': request}))
    before = (mapping_file.read_bytes(), launch_file.read_bytes())
    # The member itself and a non-direct project member read the report.
    for caller in ('research@x1', 'research@x2'):
        with runtime_caller(runner, caller):
            result = runner_control.read_session_reports('research@x1', tmp_path)
            assert result['reports'] == [{'path': str(own), 'text': 'Original findings'}]
    with runtime_caller(runner, 'native-helper-thread'), pytest.raises(RunnerError) as denied:
        runner_control.read_session_reports('research@x1', tmp_path)
    assert denied.value.code == 'authority-denied'
    with runtime_caller(runner, 'research@x1'):
        runner_control.submit_session_report(own.name, 'Updated findings', tmp_path)
        with pytest.raises(RunnerError) as denied:
            runner_control.submit_session_report(sibling.name, 'Overwrite', tmp_path)
        assert denied.value.code == 'authority-denied'
    assert sibling.read_text() == 'Private sibling evidence'
    assert before == (mapping_file.read_bytes(), launch_file.read_bytes())
    own.unlink()
    with runtime_caller(runner, 'research@x2'):
        result = runner_control.read_session_reports('research@x1', tmp_path)
    assert result['reports'] == []
    assert result['missing_reports'] == [str(own)]
    own.symlink_to(sibling)
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError) as redirected:
        runner_control.read_session_reports('research@x1', tmp_path)
    assert redirected.value.code == 'authority-denied'


def test_missing_historical_assignment_does_not_infer_from_role(
    tmp_path: Path,
) -> None:
    """Readable evidence and a coding role cannot manufacture report ownership."""
    runner, team, _ = result_project(tmp_path)
    directory = runner / 'sessions/research@x1'
    mapping_file = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    del mapping['report_files']
    mapping['role'] = 'engineer'
    mapping_file.write_text(yaml.safe_dump(mapping))
    request = {'worktree_path': mapping['worktree_path'], 'session_parameters': {
        'config': {'default_permissions': 'p', 'permissions': {'p': {'filesystem': {
            str(team.parent / 'rounds/1/engineer.md'): 'read',
            str(team.parent / 'rounds/1'): 'write',
        }}}}}}
    (directory / 'launch.yml').write_text(yaml.safe_dump({
        'runtime': 'codex', 'mapping': mapping, 'connection': {}, 'adapter_request': request,
    }))
    with runtime_caller(runner, None), pytest.raises(RunnerError) as missing:
        runner_control.read_session_reports('research@x1', tmp_path)
    assert missing.value.code == 'session-not-resumable'
    assert 'no retained report assignment' in missing.value.message


@pytest.mark.parametrize('source', ['mapping', 'launch', 'cli-launch'])
def test_installed_send_recovers_historical_reports(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    source: str,
) -> None:
    """Public send retains identity and projects only actual historical reports."""
    import json
    import tomllib
    from conftest import run_process
    from runner_fixtures import configure_harness
    from test_generic_role_execution import wait_for_idle
    from test_task_graph import _register, _change_status, _task

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected-model'}},
        'role_tree': {'researcher': {}},
    }))
    _register(installed_commands, root, _task('166', 'historical-reports'))
    _change_status(installed_commands, root, '166', 'ready')
    batch = root / 'batch.yml'
    batch.write_text('tasks:\n  - role: researcher\n    task_id: "166"\n')
    env['FAKE_CODEX_APPEND_LOG'] = '1'
    result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                         cwd=root, env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    wait_for_idle(installed_commands, root, env, task['alias'])
    directory = root / '.graphtraj/runner/sessions' / task['alias']
    mapping_file = directory / 'mapping.yml'
    launch_file = directory / 'launch.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    launch = yaml.safe_load(launch_file.read_text())
    report_ref = mapping.pop('report_files')[0]
    launch['mapping'].pop('report_files')
    if source == 'mapping':
        mapping['report_file'] = report_ref
        launch['mapping']['report_file'] = report_ref
    evidence = root / '.graphtraj/state/tasks/166-historical-reports'
    own = evidence.joinpath(*Path(report_ref).parts[1:])
    own.write_text('Retained evidence')
    reference = own.with_name('reference.md')
    reference.write_text('Readable task input')
    private = own.with_name('private.md')
    private.write_text('Private sibling evidence')
    request = launch['adapter_request']
    config = request['session_parameters']['config']
    filesystem = config['permissions'][config['default_permissions']]['filesystem']
    filesystem[str(own)] = 'write'
    filesystem[str(reference)] = 'read'
    # Old direct-write Contexts recorded exact report grants in their launch.
    from graphtraj.runtimes.codex.codex_adapter import _toml_value
    for index, argument in enumerate(request['arguments']):
        if argument.startswith('permissions='):
            request['arguments'][index] = 'permissions=' + _toml_value(config['permissions'])
    if source == 'cli-launch':
        del request['session_parameters']
    mapping_file.write_text(yaml.safe_dump(mapping))
    launch_file.write_text(yaml.safe_dump(launch))
    before = launch_file.read_bytes()
    trace = (directory / 'events.jsonl').read_bytes()
    events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
              for line in shard.read_text().splitlines()]
    sent = run_process([str(installed_commands.runner), 'send', task['alias'],
                        '--instruction', 'Return retained findings.', '--reports-only',
                        '--caused-by-event-ids', json.dumps([events[-1]['event_id']])], cwd=root, env=env, timeout=20)
    assert sent.returncode == 0, sent.stdout + sent.stderr
    status = wait_for_idle(installed_commands, root, env, task['alias'])
    assert status['session'] == task['session']
    assert launch_file.read_bytes() == before
    assert (directory / 'events.jsonl').read_bytes().startswith(trace)
    assert own.read_text() == 'Retained evidence'
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    settings = {}
    for index, argument in enumerate(records[-1]['argv'][:-1]):
        if argument == '-c':
            settings.update(tomllib.loads(records[-1]['argv'][index + 1]))
    filesystem = settings['permissions'][settings['default_permissions']]['filesystem']
    assert filesystem[str(own)] == ('write' if source == 'cli-launch' else 'read')
    assert filesystem[str(reference)] == 'read'
    assert str(private) not in filesystem
    assert filesystem[str(root / '.graphtraj/state')] == 'none'
    assert private.read_text() == 'Private sibling evidence'
    assert filesystem[':workspace_roots']['.'] == 'read'
    reports = run_process([str(installed_commands.runner), 'reports', task['alias']], cwd=root, env=env)
    assert reports.returncode == 0, reports.stdout + reports.stderr
    assert yaml.safe_load(reports.stdout)['reports'] == [{'path': str(own), 'text': 'Retained evidence'}]


def test_parent_reads_follow_up_reports_beside_the_assignment(tmp_path: Path) -> None:
    """A newly added <stem>-<n>.md report is read in order; other siblings are not."""
    runner, team, _ = result_project(tmp_path)
    rounds = team.parent / 'rounds/1'
    rounds.mkdir(parents=True, exist_ok=True)
    for name, text in [('researcher-x1.md', 'first'), ('researcher-x1-10.md', 'tenth'),
                       ('researcher-x1-2.md', '第二份'), ('researcher-x1-private.md', 'other')]:
        (rounds / name).write_text(text)
    with runtime_caller(runner, None):
        reports = runner_control.read_session_reports('research@x1', tmp_path)['reports']
    assert [report['text'] for report in reports] == ['first', '第二份', 'tenth']


def test_installed_report_collection_reaches_a_stopped_member(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """After a stop only a report collection resumes; the stop itself stays in force."""
    import json
    from conftest import run_process
    from runner_fixtures import configure_harness
    from test_generic_role_execution import wait_for_idle
    from test_task_graph import _register, _change_status, _task

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected-model'}},
        'role_tree': {'researcher': {}},
    }))
    _register(installed_commands, root, _task('166', 'stopped-reports'))
    _change_status(installed_commands, root, '166', 'ready')
    batch = root / 'batch.yml'
    batch.write_text('tasks:\n  - role: researcher\n    task_id: "166"\n')
    result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                         cwd=root, env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    wait_for_idle(installed_commands, root, env, task['alias'])
    stopped = run_process([str(installed_commands.runner), 'interrupt', task['alias']],
                          cwd=root, env=env, timeout=30)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    directory = root / '.graphtraj/runner/sessions' / task['alias']
    stop = (directory / 'stop.yml').read_bytes()
    budget_file = root / '.graphtraj/state/tasks/166-stopped-reports/execution-budget.yml'
    budget = budget_file.read_bytes() if budget_file.exists() else None
    events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
              for line in shard.read_text().splitlines()]

    def send(*extra: str):
        """Send one instruction to the stopped member through the installed Runner."""
        return run_process([str(installed_commands.runner), 'send', task['alias'],
                            '--instruction', 'Return retained findings.', *extra,
                            '--caused-by-event-ids', json.dumps([events[-1]['event_id']])], cwd=root, env=env, timeout=20)

    # Ordinary work stays refused in the stopped subtree.
    refused = send()
    assert refused.returncode != 0
    assert 'subtree-stopped' in refused.stdout + refused.stderr

    collected = send('--reports-only')
    assert collected.returncode == 0, collected.stdout + collected.stderr
    status = wait_for_idle(installed_commands, root, env, task['alias'])
    assert status['session'] == task['session']
    assert status['execution_id'] != task['execution_id']
    job = yaml.safe_load((directory / 'resume.yml').read_text())
    assert job['reports_only'] is True and job['drive_children'] is False
    assert 'monitor_execution_budget' not in job
    # The stop is not lifted and the budget is not reset.
    assert (directory / 'stop.yml').read_bytes() == stop
    assert (budget_file.read_bytes() if budget_file.exists() else None) == budget
    assert 'subtree-stopped' in send().stdout + send().stderr


@pytest.mark.parametrize(('reports_only', 'collection', 'admitted'), [
    (True, True, True), (True, False, False), (True, None, False), (False, True, False),
])
def test_follow_up_reaches_only_a_running_report_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    reports_only: bool, collection: bool | None, admitted: bool,
) -> None:
    """A retried report collection steers the running one; ordinary input stays refused."""
    directory = tmp_path / 'runner' / 'sessions' / 'member'
    directory.mkdir(parents=True)
    (directory / 'stop.yml').write_text('alias: member\n')
    if collection is not None:
        (directory / 'resume.yml').write_text(yaml.safe_dump({'reports_only': collection}))
    mapping = {'parent': None, 'session': 's', 'execution_id': 'e'}
    sent = []
    monkeypatch.setattr(runner_control, 'owning_execution', lambda *_: {'activity': 'running'})
    monkeypatch.setattr(runner_control, 'session_operation', lambda *args, **kwargs: sent.append(kwargs))
    send = lambda: runner_control._send_session_locked(  # noqa: E731
        'member', 'Report retained findings.', directory, mapping, (), tmp_path, reports_only=reports_only)
    if admitted:
        assert send()['send_status'] == 'sent'
        assert sent == [{'instruction': 'Report retained findings.'}]
    else:
        with pytest.raises(RunnerError, match='stopped subtree'):
            send()
        assert sent == []
    # The stop record is never lifted.
    assert (directory / 'stop.yml').read_text() == 'alias: member\n'


def test_project_read_grants_no_control_to_a_non_parent(tmp_path: Path) -> None:
    """A non-direct member reads reports but cannot query native requests or interrupt."""
    runner, _, _ = result_project(tmp_path)
    with runtime_caller(runner, 'research@x2'):
        assert runner_control.read_session_reports('research@x1', tmp_path)['alias'] == 'research@x1'
        for control in (
            lambda: runner_control.pending_requests('research@x1', tmp_path),
            lambda: runner_control.interrupt_session('research@x1', tmp_path),
        ):
            with pytest.raises(RunnerError) as denied:
                control()
            assert denied.value.code == 'authority-denied'
