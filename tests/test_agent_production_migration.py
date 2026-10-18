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
    worktree = data / '.agent-worktrees/member'
    subprocess.run(['git', 'worktree', 'add', '-b', 'member', str(worktree)], cwd=root, check=True, capture_output=True)
    (worktree / '.state').symlink_to('../../state')
    directory = data / 'runner/sessions/old@member'
    directory.mkdir(parents=True)
    mapping = {'alias': 'old@member', 'runtime': 'codex', 'session': 'native-old',
               'parent': 'original-parent', 'worker_pid': 0, 'worktree_path': str(worktree),
               'task_id': '1', 'team_generation': 1, 'role': 'engineer', 'trace_file': str(directory / 'native.jsonl')}
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


def test_public_cutover_and_restore_preserve_identity_and_git_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Directory authority, same native ID, permission settings and Git paths move back."""
    root = tmp_path / 'project'
    worktree, directory = project(root)
    original = (directory / 'mapping.yml').read_bytes()
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(main, ['migrate-agents', '--cutover', str(tmp_path / 'input'), '--writes-stopped'])
    assert result.exit_code == 0, result.output
    report = yaml.safe_load(result.output)
    new_worktree = root / '.graphtraj/core/worktrees/member'
    assert new_worktree.is_dir() and not worktree.exists()
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
    resumed = control.send('old@member', 'continue', Binding(Caller('graphtraj-tasks', 'original-parent')))
    assert not resumed.failed
    assert str(new_worktree) in subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], text=True)
    restored = runner.invoke(main, ['migrate-agents', '--restore', report['backup'], '--writes-stopped'])
    assert restored.exit_code == 0, restored.output
    assert worktree.is_dir() and not new_worktree.exists()
    assert (directory / 'mapping.yml').read_bytes() == original
    assert (worktree / '.state').readlink() == Path('../../state')
    assert (Path(report['backup']) / 'after-core').is_dir()


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
