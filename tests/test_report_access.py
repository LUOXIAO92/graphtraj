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


def test_direct_parent_reads_terminal_message_without_report_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary children expose their completed result only to their parent."""
    config = tmp_path / '.graphtraj/config.yml'
    directory = config.parent / 'runner/sessions/child@e1'
    directory.mkdir(parents=True)
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    (directory / 'execution.yml').write_text(
        'outcome: completed\nterminal_confirmed: true\nlast_agent_message: synthetic-result\n')
    monkeypatch.setattr(runner_control, 'read_alias_mapping',
                        lambda *args: ({'parent': 'parent@l1'}, directory))
    monkeypatch.setattr(runner_control, '_session_report_paths', lambda *args, **kwargs: ())
    with runtime_caller(config.parent / 'runner', 'parent@l1'):
        result = runner_control.read_session_reports('child@e1', tmp_path)
        assert result == {'alias': 'child@e1', 'reports': [], 'last_agent_message': 'synthetic-result'}
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
    for caller in ('research@x1', 'parent@p1'):
        with runtime_caller(runner, caller):
            result = runner_control.read_session_reports('research@x1', tmp_path)
            assert result['reports'] == [{'path': str(own), 'text': 'Original findings'}]
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError) as denied:
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
    with runtime_caller(runner, 'parent@p1'):
        result = runner_control.read_session_reports('research@x1', tmp_path)
    assert result['reports'] == []
    assert result['missing_reports'] == [str(own)]
    own.symlink_to(sibling)
    with runtime_caller(runner, 'parent@p1'), pytest.raises(RunnerError) as redirected:
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
    from test_ticket_graph import _register, _change_status, _ticket

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected-model'}},
        'role_tree': {'researcher': {}},
    }))
    _register(installed_commands, root, _ticket('166', 'historical-reports'))
    _change_status(installed_commands, root, '166', 'ready')
    batch = root / 'batch.yml'
    batch.write_text('tasks:\n  - role: researcher\n    ticket_id: "166"\n')
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
    evidence = root / '.graphtraj/state/tickets/166-historical-reports'
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
                        '--caused-by-event-id', events[-1]['event_id']], cwd=root, env=env, timeout=20)
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
