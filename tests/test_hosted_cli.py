"""Public CLI calls through a live host with kernel-verified request ownership."""

import os
import json
from pathlib import Path
import subprocess
import sys
import shutil

import yaml

from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import tools
from graphtraj.interfaces.hosted_cli import CONNECTION_ENV, cli_connection
from graphtraj.runtimes.codex.managed_session import native_operation_features
from test_result_submission import result_project
from test_codex_app_server import context, peer


def cli(root: Path, address: str, *arguments: str, **claims: str) -> subprocess.CompletedProcess:
    """Execute the public entry in a distinct process, retaining real kernel locks."""
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   CONNECTION_ENV: address, **claims}
    return subprocess.run(
        [sys.executable, '-c', 'from graphtraj.interfaces.cli.agent_runner import main; main()',
         *arguments], cwd=root, env=environment, capture_output=True, text=True, timeout=20,
    )


def own_process(runner: Path) -> Path:
    """Bind the existing fixture's first Session to this live host process."""
    directory = runner / 'sessions/research@x1'
    path = directory / 'mapping.yml'
    mapping = yaml.safe_load(path.read_text())
    mapping.update(worker_pid=os.getpid(), runtime_pid=os.getpid())
    path.write_text(yaml.safe_dump(mapping))
    return directory


def test_cli_host_submits_exact_result_and_preserves_report_authority(tmp_path: Path) -> None:
    """Forged environment identities cannot change the author or read another report."""
    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Retained evidence'}, cwd=tmp_path)
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        result = cli(tmp_path, address, 'submit-result', '--commit', commit,
                     '--result-ref', 'result.md', '--evidence-ref',
                     '.state/teams/1/rounds/1/researcher-x1.md', '--completion', 'Complete',
                     GRAPHTRAJ_CALLER_ALIAS='research@x2', GRAPHTRAJ_ROLE='main',
                     GRAPHTRAJ_CALLER_PID='1', CODEX_THREAD_ID='native-research@x2')
        assert result.returncode == 0, result.stdout + result.stderr
        submission = yaml.safe_load(result.stdout)
        assert submission['alias'] == 'research@x1'
        assert submission['candidate'] == commit
        assert submission['event_id']
        assert (tmp_path / submission['evidence_refs'][0]).read_text() == 'Retained evidence'
        refused = cli(tmp_path, address, 'reports', 'research@x2')
        assert refused.returncode == 1
        assert yaml.safe_load(refused.stdout)['error']['code'] == 'authority-denied'
    with runtime_caller(runner, None):
        assert tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document['submissions'] == [submission]


def test_cli_host_refuses_unowned_wrong_channel_and_unavailable_host(tmp_path: Path) -> None:
    """A channel address, claimed owner PID or a dead owner never supplies authority."""
    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    arguments = ('submit-result', '--commit', commit, '--result-ref', 'result.md', '--completion', 'Done')
    with cli_connection(tmp_path, 'research@x1', native_operation_features()) as address:
        result = cli(tmp_path, address, *arguments, GRAPHTRAJ_CALLER_PID=str(os.getpid()))
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout)['error']['code'] == 'authority-denied'
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x2', native_operation_features(),
    ) as other:
        result = cli(tmp_path, other, *arguments, GRAPHTRAJ_CALLER_ALIAS='research@x2')
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout)['error']['code'] == 'authority-denied'
    result = cli(tmp_path, address, *arguments)
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)['error']['code'] == 'operation-failed'
    assert 'owner did not acknowledge' in result.stderr


def test_cli_host_requires_kernel_lock_and_rejects_request_identity(tmp_path: Path) -> None:
    """A sender cannot replace a kernel owner with a PID or alias in its request."""
    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        for locked in (False, True):
            script = (
                'import sys\n'
                'from graphtraj.execution.runner_connection import connection_operation\n'
                'from graphtraj.execution.runner_models import RunnerError\n'
                'try:\n'
                ' r=connection_operation(sys.argv[1], {"cwd": sys.argv[2], "request": '
                '{"action":"execute","feature":"alias_status","arguments":{},'
                '"pid":1,"alias":"research@x2","role":"main"}}, authenticate=' + str(locked) + ')\n'
                ' print(r)\n'
                'except RunnerError as e: print(e.code)\n'
            )
            result = subprocess.run([sys.executable, '-c', script, address, str(tmp_path)],
                                    env=environment, text=True, capture_output=True, timeout=20)
            assert result.returncode == 0, result.stderr
            if locked:
                assert "'failed': True" in result.stdout
                assert 'unexpected parameter' in result.stdout
            else:
                assert result.stdout.strip() == 'authority-denied'


def test_host_does_not_follow_request_or_response_links(tmp_path: Path) -> None:
    """Writable channel entries cannot redirect the privileged host's file access."""
    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    victim = tmp_path / 'private.txt'
    victim.write_text('Retained private data')
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        linked = Path(address) / 'linked-directory'
        linked.symlink_to(tmp_path, target_is_directory=True)
        attack = Path(address) / 'attack'
        attack.mkdir()
        (attack / 'request.json').symlink_to(victim)
        assert cli(tmp_path, address, 'reports', 'research@x1').returncode == 0
        assert victim.read_text() == 'Retained private data'
        (attack / 'request.json').unlink()
        (attack / 'response.tmp').symlink_to(victim)
        (attack / 'request.json').write_text('{}')
        assert cli(tmp_path, address, 'reports', 'research@x1').returncode == 0
        assert victim.read_text() == 'Retained private data'
        linked.unlink()
        shutil.rmtree(attack)


def test_managed_worker_grants_only_its_channel_and_closes_it(tmp_path: Path, peer: Path, monkeypatch) -> None:
    """The actual native launch wire carries a narrow grant and usable CLI address."""
    from graphtraj.runtimes.codex.managed_session import CodexManagedExecution

    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    resolved = context(tmp_path, peer)
    protocol = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(protocol))
    observed = []

    def created(session: str, pid: int) -> None:
        """Use emitted native configuration and publish the actual Runtime process."""
        mapping_file = directory / 'mapping.yml'
        mapping = yaml.safe_load(mapping_file.read_text())
        mapping.update(runtime_pid=pid, session=session)
        mapping_file.write_text(yaml.safe_dump(mapping))
        messages = [json.loads(line) for line in protocol.read_text().splitlines()]
        config = next(item['params']['config'] for item in messages if item.get('method') == 'thread/start')
        address = config['shell_environment_policy']['set'][CONNECTION_ENV]
        filesystem = config['permissions'][config['default_permissions']]['filesystem']
        assert filesystem[str(tmp_path / '.graphtraj')] == 'none'
        assert filesystem[address] == 'write'
        assert str(Path(address).parent) not in filesystem
        result = cli(tmp_path, address, 'submit-result', '--commit', commit,
                     '--result-ref', 'result.md', '--completion', 'Native host adopted')
        assert result.returncode == 0, result.stdout + result.stderr
        observed.append(address)

    worker = CodexManagedExecution(resolved.launch_document()['adapter_request'], 'complete',
                                   directory, lambda *_: None, resolved.evidence_document(),
                                   directory / 'native.jsonl', session_created=created)
    with hold_ownership(directory, os.getpid()):
        assert worker.run()['outcome'] == 'completed'
    assert len(observed) == 1
    assert not Path(observed[0]).exists()


def test_native_submission_errors_identify_wrong_reference_and_git_failure(tmp_path: Path) -> None:
    """Wrong report usage is actionable; a missing committed path retains Git diagnostics."""
    import pytest
    from graphtraj.execution.runner_models import RunnerError

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        with pytest.raises(ValueError, match='evidence_refs'):
            tools.submit_result({'commit': commit, 'result_refs': ['.state/teams/1/rounds/1/researcher-x1.md'],
                                 'completion': 'Done'}, cwd=tmp_path)
        with pytest.raises(RunnerError) as failure:
            tools.submit_result({'commit': commit, 'result_refs': ['absent.md'],
                                 'completion': 'Done'}, cwd=tmp_path)
        assert 'git cat-file -t ' + commit + ':absent.md' in failure.value.message
        assert str(tmp_path / 'worktrees/research') in failure.value.message
        assert 'fatal:' in failure.value.message
