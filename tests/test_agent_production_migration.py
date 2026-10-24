"""Public stopped cutover/recovery with actual Git worktrees and synthetic identities."""
import json
from pathlib import Path
import re
import shutil
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



def test_cutover_keeps_claude_main_continuity_and_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Main claims, queued notices and completion bindings move unchanged and come back."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.main_continuity import current_main, main_sessions, pending_notices, queue_notice
    from graphtraj.graph.task_graph import read_graph

    root = tmp_path / 'project'
    project(root)
    legacy = root / '.graphtraj/runner'
    records = legacy / 'main-sessions'
    records.mkdir()
    connection = {'runtime': 'claude', 'session': 'claude-main', 'runner': str(legacy)}
    (records / 'continuity.jsonl').write_text(json.dumps({
        'at': 1.0, 'connection': connection, 'entry': 'claude:first-control', 'previous': None,
        'runtime': 'claude', 'session': 'claude-main'}, sort_keys=True) + '\n')
    (records / 'continuity.lock').write_bytes(b'')
    queue_notice(legacy, connection, {'kind': 'member-result', 'text': 'queued before cutover'})
    binding = records / 'finalize_codex/session.yml'
    binding.parent.mkdir()
    binding.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'codex-earlier', 'cwd': str(root),
                                       'connection': {'runtime': 'codex', 'session': 'codex-earlier',
                                                      'codex_home': str(tmp_path / 'codex-home')}}))
    (root / '.graphtraj/state/tasks/.claude/.cc-writes').mkdir(parents=True)
    state_grant = str(root / '.graphtraj/state')
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'team': {'engineer': {
        'runtime': 'claude', 'claude': {'read_paths': [str(root / 'docs'), state_grant]}}}}}))
    before = {path.relative_to(records): path.read_bytes() for path in records.rglob('*') if path.is_file()}
    monkeypatch.chdir(root)
    runner = CliRunner()
    arguments = ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped']
    refused = runner.invoke(main, arguments)
    assert refused.exit_code != 0 and '--main-session' in refused.output
    # The refused attempt retains its snapshot as evidence; retry into a new one.
    result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'retry'), '--writes-stopped',
                                  '--main-session', 'claude-main'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report['foreign_entries'] == ['.claude']
    # Authored roles are installed unchanged; the moved grant is named for its owner.
    assert report['role_read_paths_to_update'] == [{'field': 'roles.team.engineer.claude.read_paths',
                                                     'old': state_grant, 'new': str(root / '.graphtraj/core/state')}]
    assert state_grant in (root / '.graphtraj/core/roles.yml').read_text()
    moved = root / '.graphtraj/core/runner/main-sessions'
    assert runner_directory(root) == moved.parent
    assert {path.relative_to(moved): path.read_bytes() for path in moved.rglob('*') if path.is_file()} == before
    assert current_main(moved.parent)['session'] == 'claude-main'
    assert main_sessions(moved.parent) == {'claude-main', 'codex-earlier'}
    notices, _ = pending_notices(moved.parent, 'claude', 'claude-main')
    assert [notice['event']['text'] for notice in notices] == ['queued before cutover']
    # Repetition never imports a second time over the installed layout.
    again = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'again'), '--writes-stopped',
                                 '--main-session', 'claude-main'])
    assert again.exit_code != 0 and 'existing core destination' in again.output
    restored = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
    assert restored.exit_code == 0, restored.output
    assert {path.relative_to(records): path.read_bytes() for path in records.rglob('*') if path.is_file()} == before
    assert runner_directory(root) == legacy
    read_graph(root / '.graphtraj/state')


def test_claude_main_notice_follows_the_installed_core_runner(tmp_path: Path) -> None:
    """A Main connection recorded before cutover queues into the current core Runner."""
    from graphtraj.execution.main_continuity import pending_notices
    from graphtraj.runtimes.claude.adapter import ClaudeRuntimeAdapter

    core = tmp_path / '.graphtraj/core'
    (core / 'runner').mkdir(parents=True)
    (core / 'config.yml').write_text('paths: {}\n')
    connection = {'runtime': 'claude', 'session': 'claude-main', 'runner': str(tmp_path / '.graphtraj/runner')}
    ClaudeRuntimeAdapter().send_host_event(connection, {'kind': 'member-result'})
    notices, _ = pending_notices(core / 'runner', 'claude', 'claude-main')
    assert [notice['event'] for notice in notices] == [{'kind': 'member-result'}]
    assert not (tmp_path / '.graphtraj/runner').exists()


def claude_member(
    root: Path, worktree: Path, home: Path, session: str = 'claude-native', cwd: str | None = None,
) -> tuple[Path, Path]:
    """Retain a stopped Claude member whose native Session lives under its worktree cwd."""
    directory = root / '.graphtraj/runner/sessions' / (session + '@member')
    directory.mkdir(parents=True)
    cwd = str(worktree) if cwd is None else cwd
    mapping = {'alias': session + '@member', 'runtime': 'claude', 'session': session,
               'parent': 'original-parent', 'worker_pid': 0, 'worktree_path': cwd,
               'task_id': '1', 'team_generation': 1, 'role': 'engineer', 'runtime_pid': 0,
               'trace_file': str(directory / 'stdout.jsonl')}
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    # No recorded runtime_home: the Adapter's CLAUDE_CONFIG_DIR default applies.
    (directory / 'launch.yml').write_text(yaml.safe_dump({'runtime': 'claude', 'adapter_request': {
        'worktree_path': cwd, 'resources': [str(root / '.graphtraj/state')]}}))
    (directory / 'execution.yml').write_text('outcome: completed\nterminal_confirmed: true\n')
    project = home / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', cwd)
    (project / session / 'subagents').mkdir(parents=True)
    (project / (session + '.jsonl')).write_text('{"sessionId": "%s"}\n' % session)
    (project / session / 'subagents/agent.jsonl').write_text('{"sub": true}\n')
    return project, home / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', str(root / '.graphtraj/core/worktrees/member'))


def test_cutover_copies_claude_native_session_for_the_moved_cwd_and_restore_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-ID resume finds the Session under the new cwd; the original is never moved."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    old, new = claude_member(root, worktree, home)
    original = {path: path.read_bytes() for path in old.rglob('*') if path.is_file()}
    monkeypatch.chdir(root)
    runner = CliRunner()
    for attempt in ('first', 'repeat'):
        result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / attempt), '--writes-stopped'])
        assert result.exit_code == 0, result.output
        report = yaml.safe_load(result.output)
        assert report['native_continuations'] == [{'runtime': 'claude', 'session': 'claude-native',
                                                   'old': str(worktree), 'new': str(root / '.graphtraj/core/worktrees/member'),
                                                   'status': 'copied'}]
        assert (new / 'claude-native.jsonl').read_bytes() == original[old / 'claude-native.jsonl']
        assert (new / 'claude-native/subagents/agent.jsonl').is_file()
        assert {path: path.read_bytes() for path in old.rglob('*') if path.is_file()} == original
        if attempt == 'first':
            # A Session continued under the new cwd is new history: recovery refuses.
            (new / 'claude-native.jsonl').write_text('{"resumed": true}\n')
            refused = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
            assert refused.exit_code != 0 and 'continued under its new cwd' in refused.output
            assert (new / 'claude-native.jsonl').read_text() == '{"resumed": true}\n'
            (new / 'claude-native.jsonl').write_bytes(original[old / 'claude-native.jsonl'])
        restored = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
        assert restored.exit_code == 0, restored.output
        assert not new.exists()
        assert {path: path.read_bytes() for path in old.rglob('*') if path.is_file()} == original


def test_cutover_never_replaces_an_existing_native_session_under_the_new_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing native record at the destination is reported and kept, also by restore."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    _, new = claude_member(root, worktree, home)
    new.mkdir(parents=True)
    (new / 'claude-native.jsonl').write_text('already here\n')
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert [item['status'] for item in report['native_continuations']] == ['conflict']
    assert report['native_continuation_gaps'][0]['status'] == 'conflict'
    assert (new / 'claude-native.jsonl').read_text() == 'already here\n'
    assert not (new / 'claude-native').exists()
    restored = CliRunner().invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
    assert restored.exit_code == 0, restored.output
    assert (new / 'claude-native.jsonl').read_text() == 'already here\n'


def test_cutover_reports_an_identical_existing_session_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A destination identical to the original is ``existing`` and is not a gap."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    old, new = claude_member(root, worktree, home)
    shutil.copytree(old, new)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert [item['status'] for item in report['native_continuations']] == ['existing']
    assert report['native_continuation_gaps'] == []


def test_failed_native_copy_leaves_no_partial_session_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copy failing midway is removed with the rest of the cutover."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    _, new = claude_member(root, worktree, home)
    copytree = shutil.copytree

    def failing(source, destination, *args, **kwargs):
        """Fail after a partial write, only for the native Session copy."""
        if Path(destination).is_relative_to(home):
            Path(destination).mkdir()
            (Path(destination) / 'partial.jsonl').write_text('partial\n')
            raise OSError('disk full')
        return copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(shutil, 'copytree', failing)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code != 0 and 'disk full' in result.output
    assert not new.exists()
    assert worktree.is_dir() and (root / '.graphtraj/config.yml').is_file()


def test_claude_members_are_matched_by_real_path_and_unplannable_ones_are_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symlinked cwd spelling still continues; a record without cwd is listed, not skipped."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    (tmp_path / 'alias').symlink_to(root)
    spelled = str(tmp_path / 'alias/.graphtraj/.agent-worktrees/member')
    claude_member(root, worktree, home, 'claude-alias', spelled)
    missing = root / '.graphtraj/runner/sessions/no-cwd@member'
    missing.mkdir()
    (missing / 'mapping.yml').write_text(yaml.safe_dump({
        'alias': 'no-cwd@member', 'runtime': 'claude', 'session': 'claude-no-cwd', 'task_id': '1',
        'worker_pid': 0, 'execution_id': 'run-1'}))
    (missing / 'execution.yml').write_text('execution_id: run-1\noutcome: completed\nterminal_confirmed: true\n')
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    statuses = {item['session']: item for item in report['native_continuations']}
    assert statuses['claude-alias']['status'] == 'copied'
    assert statuses['claude-alias']['new'] == str(root / '.graphtraj/core/worktrees/member')
    assert statuses['claude-no-cwd']['status'] == 'unplanned'
    assert [gap['session'] for gap in report['native_continuation_gaps']] == ['claude-no-cwd']
    assert 'role_organization' in report['next'] and 'Main host' in report['next']


def test_restore_removes_a_shared_new_project_directory_for_two_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two Sessions copied into one new cwd directory leave nothing behind after restore."""
    root = tmp_path / 'project'
    worktree, _ = project(root)
    home = tmp_path / 'claude-home'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home))
    _, new = claude_member(root, worktree, home, 'claude-first')
    claude_member(root, worktree, home, 'claude-second')
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert sorted(item['status'] for item in report['native_continuations']) == ['copied', 'copied']
    restored = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
    assert restored.exit_code == 0, restored.output
    assert not new.exists() and not (home / 'projects').joinpath(new.name).exists()


def test_main_session_must_be_the_current_continuity_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A superseded Claude Main is refused; the current one is reported as current_main, also after partition."""
    from graphtraj.workspace.agent_migration import migrate_agents

    root = tmp_path / 'project'
    project(root)
    records = root / '.graphtraj/runner/main-sessions'
    records.mkdir()
    lines = [{'at': 1.0, 'runtime': 'claude', 'session': 'claude-earlier', 'entry': 'claude:first-control',
              'connection': {}, 'previous': None},
             {'at': 2.0, 'runtime': 'claude', 'session': 'claude-main', 'entry': 'claude:first-control',
              'connection': {}, 'previous': {'runtime': 'claude', 'session': 'claude-earlier'}}]
    (records / 'continuity.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in lines))
    binding = records / 'finalize_codex/session.yml'
    binding.parent.mkdir()
    binding.write_text(yaml.safe_dump({'runtime': 'codex', 'session': 'codex-earlier', 'cwd': str(root),
                                       'connection': {'runtime': 'codex', 'session': 'codex-earlier'}}))
    monkeypatch.chdir(root)
    runner = CliRunner()
    # A partitioned public snapshot reads the claim from its retained backup Runner.
    snapshot = tmp_path / 'rehearsal'
    assert runner.invoke(main, ['migrate-agents', '--snapshot', str(snapshot)]).exit_code == 0
    monkeypatch.chdir(snapshot)
    imported = runner.invoke(main, ['migrate-agents', '--main-session', 'claude-main'])
    assert imported.exit_code == 0, imported.output
    partitioned = runner.invoke(main, ['migrate-agents', '--partition'])
    assert partitioned.exit_code == 0, partitioned.output
    preview = migrate_agents(snapshot, preview=True, main_session='claude-main')
    assert any(entry['group'] == 'current_main' for entry in preview['legacy_native_registrations']['sessions'])
    monkeypatch.chdir(root)
    refused = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'old'), '--writes-stopped',
                                   '--main-session', 'claude-earlier'])
    assert refused.exit_code != 0 and 'no retained Main binding' in refused.output
    result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped',
                                  '--main-session', 'claude-main'])
    assert result.exit_code == 0, result.output
    registrations = yaml.safe_load(result.output)['legacy_native_registrations']
    current = [entry for entry in registrations['sessions'] if entry['group'] == 'current_main']
    assert [(entry['runtime'], entry['session']) for entry in current] == [('claude', 'claude-main')]


@pytest.mark.parametrize('receipt', ['valid', 'absent', 'stale'])
def test_unconfirmed_failure_passes_cutover_only_with_a_valid_confirmation_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt: str,
) -> None:
    """The original failure stays unconfirmed; only the Runner's matching receipt confirms its end."""
    import hashlib

    root = tmp_path / 'project'
    _, fixture = project(root)
    # The Runner resolves receipts by its real alias form.
    alias = '1-fixture-handover0-engineer@engineer_4'
    directory = fixture.rename(fixture.with_name(alias))
    mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
    mapping.update(alias=alias, execution_id='run-1', worker_pid=41, runtime_pid=42)
    (directory / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    execution = directory / 'execution.yml'
    execution.write_text(yaml.safe_dump({'execution_id': 'run-1', 'outcome': 'runtime-error',
                                         'terminal_confirmed': False, 'error': {'code': 'owner-exited'}}))
    original = execution.read_bytes()
    if receipt != 'absent':
        digest = hashlib.sha256(original if receipt == 'valid' else b'another execution').hexdigest()
        (directory / 'terminal-confirmation-run-1.yml').write_text(yaml.safe_dump({
            **{key: mapping[key] for key in ('session', 'execution_id', 'worker_pid', 'runtime_pid')},
            'execution_sha256': digest, 'terminal_confirmed': True}))
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    if receipt == 'valid':
        assert result.exit_code == 0, result.output
        moved = root / '.graphtraj/core/runner/sessions' / alias / 'execution.yml'
        assert moved.read_bytes() == original
        return
    assert result.exit_code != 0 and 'Stop and confirm' in result.output and 'agents interrupt' in result.output
    assert not (tmp_path / 'input').exists() and (root / '.graphtraj/config.yml').is_file()


def swarm_agent(
    root: Path, worktree: Path, agent: str, *, worker_pid: int, code: str = 'owner-exited',
    runtime_pid: int | None = -1,
) -> Path:
    """Retain an independent Agent whose last execution agent_swarm ended as unconfirmed."""
    from agent_swarm import AgentControl

    settings = {'cwd': str(worktree), 'adapter_request': {'cwd': str(worktree), 'approval_policy': 'on-request'}}
    execution = {'id': agent + '-run', 'state': 'ended', 'outcome': 'failed', 'terminal_confirmed': False,
                 'last_message': None, 'ended_at': 1.0,
                 'error': {'code': code, 'message': 'The process owning this execution exited before reporting its end.'},
                 'process': {'worker_pid': worker_pid,
                             'runtime_pid': worker_pid + 1 if runtime_pid == -1 else runtime_pid}}
    AgentControl(root / '.graphtraj/swarm', {}).import_agent({
        'agent': agent, 'name': agent, 'runtime': 'codex', 'host': 'agents-cli', 'parent': None,
        'creator': {'host': 'agents-cli', 'agent': None, 'session': None}, 'session': agent + '-native',
        'sessions': [agent + '-native'], 'settings': settings, 'created_at': 1.0, 'retired_at': None,
        'executions': [execution]})
    return root / '.graphtraj/swarm/control/agents' / (agent + '.json')


# The largest pid_t is above every platform PID limit; this test process certainly exists.
GONE_PID = 2**31 - 2


def test_owner_exited_swarm_execution_moves_with_relocated_settings_and_unchanged_executions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cutover carries an owner-exited execution whose processes are gone, still unconfirmed."""
    from agent_swarm import AgentControl, AgentsError, Caller

    root = tmp_path / 'project'
    worktree, _ = project(root)
    path = swarm_agent(root, worktree, 'exited', worker_pid=GONE_PID)
    before = json.loads(path.read_text())['executions']
    # The public control keeps refusing to configure an unconfirmed execution.
    shutil.copytree(root / '.graphtraj/swarm', tmp_path / 'public-swarm')
    with pytest.raises(AgentsError) as refused:
        AgentControl(tmp_path / 'public-swarm', {}).configure_stopped('exited', {}, Caller('agents-cli', None))
    assert refused.value.code == 'turn-running'
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    assert report['unconfirmed_swarm_executions'] == [{
        'agent': 'exited', 'execution': 'exited-run', 'error_code': 'owner-exited', 'worker_pid': GONE_PID,
        'runtime_pid': GONE_PID + 1, 'worker_alive': False, 'runtime_alive': False,
        'terminal_confirmed': 'retained false; not confirmed by cutover'}]
    installed = json.loads(path.read_text())
    new = str(root / '.graphtraj/core/worktrees/member')
    assert installed['settings'] == {'cwd': new, 'adapter_request': {'cwd': new, 'approval_policy': 'on-request'}}
    assert json.dumps(installed['executions'], sort_keys=True) == json.dumps(before, sort_keys=True)
    assert installed['executions'][0]['terminal_confirmed'] is False


@pytest.mark.parametrize('case', ['alive', 'not-owner-exited', 'worker-failed'])
def test_other_unconfirmed_swarm_executions_still_block_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    """A live owner or any other unconfirmed end is refused before any snapshot."""
    import os

    root = tmp_path / 'project'
    worktree, _ = project(root)
    # worker-failed is the production shape outside scheme B: dead worker, runtime_pid never recorded.
    swarm_agent(root, worktree, 'blocked', worker_pid=os.getpid() if case == 'alive' else GONE_PID,
                code={'alive': 'owner-exited', 'not-owner-exited': 'runtime-error',
                      'worker-failed': 'RUNTIME_WORKER_FAILED'}[case],
                runtime_pid=None if case == 'worker-failed' else -1)
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code != 0 and 'Stop and confirm the Agent before cutover: blocked' in result.output
    assert not (tmp_path / 'input').exists() and (root / '.graphtraj/config.yml').is_file()


def test_check_stopped_lists_every_blocker_and_accepted_gap_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read-only precheck uses the cutover stop facts and reports all of them."""
    import os

    root = tmp_path / 'project'
    worktree, directory = project(root)
    swarm_agent(root, worktree, 'exited', worker_pid=GONE_PID)
    swarm_agent(root, worktree, 'live', worker_pid=os.getpid())
    swarm_agent(root, worktree, 'worker-failed', worker_pid=GONE_PID, code='RUNTIME_WORKER_FAILED', runtime_pid=None)
    (directory / 'execution.yml').unlink()
    tree = lambda: {str(path): (path.read_bytes() if path.is_file() and not path.is_symlink() else None)
                    for path in tmp_path.rglob('*')}
    before = tree()
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ['migrate-agents', '--check-stopped'])
    assert result.exit_code == 0, result.output
    facts = yaml.safe_load(result.output)
    assert [item.get('runner') or item.get('swarm') for item in facts['blocking']] == ['old@member', 'live', 'worker-failed']
    assert [item['agent'] for item in facts['unconfirmed_swarm_executions']] == ['exited']
    assert tree() == before
    refused = CliRunner().invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert refused.exit_code != 0 and '2 more; list them with migrate-agents --check-stopped' in refused.output
