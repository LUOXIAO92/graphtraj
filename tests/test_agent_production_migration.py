"""Public stopped cutover/recovery with actual Git worktrees and synthetic identities."""
import json
from pathlib import Path
import subprocess
import tomllib

from click.testing import CliRunner
import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.cli.graphtraj import main
from graphtraj.runtimes.codex.codex_adapter import _toml_value


def project(root: Path) -> tuple[Path, Path]:
    """Retain a stopped native identity and a real linked worktree, without a host."""
    root.mkdir()
    for args in [('init',), ('config', 'user.email', 'test@example.com'), ('config', 'user.name', 'Test')]:
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    (root / 'source.txt').write_text('tracked source\n')
    subprocess.run(['git', 'add', 'source.txt'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-m', 'fixture'], cwd=root, check=True, capture_output=True)
    data = root / '.graphtraj'
    data.mkdir()
    (data / 'config.yml').write_text(default_configuration_content(root, root))
    (data / 'state/tasks').mkdir(parents=True)
    from graphtraj.graph.task_graph import register_task
    from test_task_graph import _task

    register_task(data / 'state', root, _task('1', 'fixture'))
    worktree = data / '.agent-worktrees/member'
    subprocess.run(['git', 'worktree', 'add', '-b', 'member', str(worktree)], cwd=root, check=True, capture_output=True)
    (worktree / '.state').symlink_to('../../state')
    directory = data / 'runner/sessions/old@member'
    directory.mkdir(parents=True)
    mapping = {'alias': 'old@member', 'runtime': 'codex', 'session': 'native-old',
               'parent': 'original-parent', 'worker_pid': 0, 'worktree_path': str(worktree),
               'task_id': '1', 'team_generation': 1, 'role': 'engineer', 'trace_file': str(directory / 'native.jsonl'),
               'runtime_pid': 0, 'retained_batch_file': 'retained-batch.yml'}
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    (directory / 'session.yml').write_text(yaml.safe_dump({'session': 'native-old', 'rollout_path': str(directory / 'native.jsonl')}))
    permissions = {'member': {'filesystem': {str(worktree): 'write', str(data / 'state'): 'read'}}}
    (directory / 'launch.yml').write_text(yaml.safe_dump({'runtime': 'codex', 'mapping': mapping,
        'adapter_request': {'cwd': str(worktree), 'worktree_path': str(worktree), 'approval_policy': 'on-request',
                            'arguments': ['-c', 'permissions=' + _toml_value(permissions)],
                            'session_parameters': {'cwd': str(worktree), 'config': {'permissions': permissions}}},
        'connection': {'model': 'retained-model'}}))
    (directory / 'execution.yml').write_text('outcome: completed\nterminal_confirmed: true\n')
    return worktree, directory


@pytest.mark.parametrize('resume', [False, True])
def test_public_cutover_and_restore_preserve_identity_and_git_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool,
) -> None:
    """Directory authority, same native ID, permission settings and Git paths move back."""
    root = tmp_path / 'project'
    worktree, directory = project(root)
    evidence = b'\x00retained untracked delivery evidence\xff'
    (worktree / 'untracked-evidence.bin').write_bytes(evidence)
    from graphtraj.sessions.storage import SessionStore, session_path
    from test_session_storage import header

    with SessionStore.create(session_path(root / '.graphtraj/state', 'canonical-old'), header('canonical-old')) as archive:
        archive.put_attachment(b'retained legacy attachment')
    original = (directory / 'mapping.yml').read_bytes()
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    new_worktree = root / '.graphtraj/core/worktrees/member'
    assert new_worktree.is_dir() and not worktree.exists()
    assert (new_worktree / 'untracked-evidence.bin').read_bytes() == evidence
    assert (new_worktree / '.state').resolve() == root / '.graphtraj/core/state'
    assert not (root / '.graphtraj/config.yml').exists()
    mapping = yaml.safe_load((root / '.graphtraj/core/runner/sessions/old@member/mapping.yml').read_text())
    assert mapping['session'] == 'native-old' and mapping['parent'] == 'original-parent'
    assert mapping['worktree_path'] == str(new_worktree)
    record = json.loads((root / '.graphtraj/swarm/control/agents/old@member.json').read_text())
    assert record['agent'] == 'old@member' and record['session'] == 'native-old'
    assert record['settings']['adapter_request']['approval_policy'] == 'on-request'
    assert record['settings']['adapter_request']['cwd'] == str(new_worktree)
    request = record['settings']['adapter_request']
    expected = {'member': {'filesystem': {str(new_worktree): 'write', str(root / '.graphtraj/core/state'): 'read'}}}
    assert request['session_parameters']['config']['permissions'] == expected
    assert tomllib.loads(request['arguments'][1])['permissions'] == expected
    # The public control resumes the retained native ID under its original host
    # and parent. This is a driver seam, not a claim of real Runtime execution.
    from agent_swarm import AgentControl, Binding, Caller

    class Driver:
        def start(self, run):
            """Observe the exact restored launch settings and finish this synthetic turn."""
            assert run.session == 'native-old' and run.agent == 'old@member'
            assert run.settings['adapter_request'] == request
            run.events.session(run.session)
            run.events.finished('completed')

    control = AgentControl(root / '.graphtraj/swarm', {'codex': Driver()})
    if resume:
        resumed = control.send('old@member', 'continue', Binding(Caller('graphtraj-tasks', 'original-parent')))
        assert not resumed.failed
    assert str(new_worktree) in subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], text=True)
    restored = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
    if resume:
        assert restored.exit_code != 0 and 'Post-cutover data changed' in restored.output
        assert new_worktree.is_dir() and not worktree.exists()
        return
    assert restored.exit_code == 0, restored.output
    assert worktree.is_dir() and not new_worktree.exists()
    assert (worktree / 'untracked-evidence.bin').read_bytes() == evidence
    assert (directory / 'mapping.yml').read_bytes() == original
    assert (worktree / '.state').readlink() == Path('../../state')
    assert (Path(report['backup']) / 'after-core').is_dir()


def test_cutover_preserves_accepted_legacy_codex_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The accepted exception preserves native memory and reports the old names."""
    root = tmp_path / 'project'
    worktree, directory = project(root)
    (directory / 'native.jsonl').write_text(json.dumps({'type': 'session_meta', 'payload': {
        'id': 'native-old', 'cwd': str(worktree), 'dynamic_tools': [{'name': 'graphtraj'}]}}) + '\n')
    before = (directory / 'native.jsonl').read_bytes()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    declarations = report['legacy_native_registrations']['sessions']
    assert declarations[0]['tools'] == ['graphtraj']
    assert declarations[0]['session'] == 'native-old'
    assert (root / '.graphtraj/core/runner/sessions/old@member/native.jsonl').read_bytes() == before


def test_cutover_refuses_unconfirmed_writer_before_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator acknowledgement cannot override a retained active execution."""
    root = tmp_path / 'project'
    _, directory = project(root)
    (directory / 'execution.yml').unlink()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code != 0 and 'Stop and confirm' in result.output
    assert not (tmp_path / 'input').exists()
    assert (root / '.graphtraj/config.yml').is_file()


def test_historical_unknown_binding_is_retained_without_fake_activity_or_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup-incompatible historical binding is a gap, not a new cleanup requirement."""
    root = tmp_path / 'project'
    project(root)
    old = root / '.graphtraj/runner/sessions/old-history/mapping.yml'
    old.parent.mkdir()
    old.write_text('alias: old-history\ntask_id: "218"\nsession: retained-native\n')
    before = old.read_bytes()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report['control_missing'][0]['alias'] == 'old-history'
    assert (root / '.graphtraj/core/runner/sessions/old-history/mapping.yml').read_bytes() == before
    assert not (root / '.graphtraj/swarm/control/agents/old-history.json').exists()


@pytest.mark.parametrize('runtime', ['pi', 'dsh'])
def test_cutover_moves_owned_native_files_and_preserves_external_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str,
) -> None:
    """Native continuation bytes leave core; uncaptured user settings remain links."""
    from graphtraj.execution.task_agents import native_directory

    root = tmp_path / 'project'
    _, directory = project(root)
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    mapping['runtime'] = runtime
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    launch = yaml.safe_load((directory / 'launch.yml').read_text())
    launch.update(runtime=runtime, mapping=mapping)
    (directory / 'launch.yml').write_text(yaml.safe_dump(launch))
    external = tmp_path / 'native-user-settings.json'
    external.write_text('{"keep":"original-user-setting"}')
    if runtime == 'pi':
        native = Path(mapping['trace_file']).with_suffix('.pi')
        native.mkdir()
        content = b'{"type":"session","id":"native-old","version":3}\n'
        (native / 'session.jsonl').write_bytes(content)
        (native / 'settings.json').symlink_to(external)
        Path(mapping['trace_file']).symlink_to(native / 'session.jsonl')
        relative = Path('session.jsonl')
    else:
        native = directory / 'dsh-native'
        native.mkdir()
        content = b'{"version":4,"id":"native-old","createdAt":1,"isSeeded":false}\n'
        (native / 'native-old.jsonl').write_bytes(content)
        (directory / 'dsh-home').mkdir()
        (directory / 'dsh-home/settings.json').symlink_to(external)
        Path(mapping['trace_file']).symlink_to(native / 'native-old.jsonl')
        relative = Path('dsh-native/native-old.jsonl')
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    destination = native_directory(root, mapping['alias'], runtime)
    assert (destination / relative).read_bytes() == content
    trace = root / '.graphtraj/core/runner/sessions/old@member/native.jsonl'
    assert trace.is_symlink() and trace.resolve() == destination / relative
    link = destination / ('settings.json' if runtime == 'pi' else 'dsh-home/settings.json')
    assert link.is_symlink() and link.resolve() == external
    assert external.read_text() == '{"keep":"original-user-setting"}'
    record = json.loads((root / '.graphtraj/swarm/control/agents/old@member.json').read_text())
    assert record['settings']['adapter_request']['native_directory'] == str(destination)
    assert yaml.safe_load(result.output)['missing_links']  # Reference retained, bytes not captured.


def test_stopped_settings_update_keeps_identity_and_checks_host(tmp_path: Path) -> None:
    """Migration consumes the independent tool's public API, including its ownership checks."""
    from agent_swarm import AgentControl, Caller, AgentsError, Binding

    control = AgentControl(tmp_path, {})
    owner = Caller('original-host', 'parent')
    record = {'agent': 'retained', 'name': 'retained', 'runtime': 'codex', 'host': owner.host,
              'parent': owner.agent, 'creator': {'host': owner.host, 'agent': owner.agent, 'session': None},
              'session': 'original-native', 'sessions': ['original-native'], 'settings': {'cwd': '/before'},
              'created_at': None, 'retired_at': None, 'executions': []}
    control.import_agent(record)
    with pytest.raises(AgentsError, match='owning host'):
        control.configure_stopped('retained', {'cwd': '/wrong'}, Caller('foreign-host', 'parent'))
    control.configure_stopped('retained', {'cwd': '/after'}, owner)
    status = control.operate('status', {'agent': 'retained'}, Binding(owner)).result
    assert status['session'] == 'original-native' and status['state'] == 'standby'


def test_imported_task_control_uses_the_retained_parent_binding(tmp_path: Path) -> None:
    """The Worker consumer can observe an imported child of a legacy parent."""
    from agent_swarm import AgentControl
    from graphtraj.execution.task_agents import core_status
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    path = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(path.read_text())
    mapping.update(parent='research@x2', agent='research@x1')
    path.write_text(yaml.safe_dump(mapping))
    control = AgentControl(tmp_path / '.graphtraj/swarm', {})
    control.import_agent({'agent': mapping['agent'], 'name': mapping['alias'], 'runtime': 'codex',
        'host': 'graphtraj-tasks', 'parent': mapping['parent'],
        'creator': {'host': 'graphtraj-tasks', 'agent': mapping['parent'], 'session': None},
        'session': mapping['session'], 'sessions': [mapping['session']], 'settings': {},
        'created_at': None, 'retired_at': None, 'executions': []})
    assert core_status(runner, mapping) == {'agent': mapping['agent'], 'state': 'standby'}


def test_git_move_refusal_restores_original_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Git's own locked-worktree refusal leaves original identity and paths usable."""
    root = tmp_path / 'project'
    worktree, directory = project(root)
    original = (directory / 'mapping.yml').read_bytes()
    subprocess.run(['git', 'worktree', 'lock', str(worktree)], cwd=root, check=True)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code != 0 and 'locked' in result.output
    assert (directory / 'mapping.yml').read_bytes() == original
    assert worktree.is_dir() and (root / '.graphtraj/config.yml').is_file()
    assert (tmp_path / 'input/.graphtraj/migration-snapshot.yml').is_file()
