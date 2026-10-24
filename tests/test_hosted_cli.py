"""Public CLI calls through a live host with kernel-verified request ownership."""

import os
import json
from pathlib import Path
import subprocess
import sys
import shutil

import yaml
import pytest

from graphtraj.execution.runner_heartbeat import hold_ownership
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import tools
from graphtraj.interfaces.hosted_cli import CONNECTION_ENV, cli_connection
from graphtraj.runtimes.codex.managed_session import native_operation_features
from test_result_submission import result_project
from test_codex_app_server import context, peer


def run_cli(
    module: str,
    root: Path,
    address: str,
    *arguments: str,
    process_timeout: float = 20,
    input_text: str | None = None,
    **claims: str,
) -> subprocess.CompletedProcess:
    """Execute one public entry in a distinct process, retaining real kernel locks."""
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                   CONNECTION_ENV: address, **claims}
    return subprocess.run(
        [sys.executable, '-c', f'from {module} import main; main()', *arguments],
        cwd=root, env=environment, capture_output=True, text=True,
        timeout=process_timeout, input=input_text,
    )


def cli(root: Path, address: str, *arguments: str, **claims: str) -> subprocess.CompletedProcess:
    """Execute the Agent Runner entry in a distinct process, retaining real kernel locks."""
    return run_cli('graphtraj.interfaces.cli.agent_runner', root, address, *arguments, **claims)


def product_cli(root: Path, address: str, *arguments: str, **claims: str) -> subprocess.CompletedProcess:
    """Execute the product entry in a distinct process, retaining real kernel locks."""
    return run_cli('graphtraj.interfaces.cli.graphtraj', root, address, *arguments, **claims)


def own_process(runner: Path) -> Path:
    """Bind the existing fixture's first Session to this live host process."""
    directory = runner / 'sessions/research@x1'
    path = directory / 'mapping.yml'
    mapping = yaml.safe_load(path.read_text())
    mapping.update(worker_pid=os.getpid(), runtime_pid=os.getpid())
    path.write_text(yaml.safe_dump(mapping))
    return directory


def test_cli_host_submits_exact_result_and_preserves_report_authority(tmp_path: Path) -> None:
    """Project reports are readable; forged environment identities cannot change authorship."""
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
        sibling = cli(tmp_path, address, 'reports', 'research@x2')
        assert sibling.returncode == 0, sibling.stdout + sibling.stderr
        assert yaml.safe_load(sibling.stdout)['alias'] == 'research@x2'
        refused = cli(tmp_path, address, 'submit-report', '--name', 'researcher-x2.md', '--text', 'forged')
        assert refused.returncode == 1
    with runtime_caller(runner, None):
        assert tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document['submissions'] == [submission]


def test_cli_host_accepts_the_session_worktree_and_refuses_other_directories(tmp_path: Path) -> None:
    """A restricted Session reaches the bound host from its own Worktree, and only there."""
    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    worktree = tmp_path / 'worktrees/research'
    nested = worktree / 'src'
    nested.mkdir()
    foreign = tmp_path / 'elsewhere'
    foreign.mkdir()
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        report = cli(worktree, address, 'submit-report', '--name', 'researcher-x1.md',
                     '--text', 'Worktree evidence')
        assert report.returncode == 0, report.stdout + report.stderr
        assert yaml.safe_load(report.stdout)['report'].endswith('researcher-x1.md')
        submission = cli(worktree, address, 'submit-result', '--commit', commit,
                         '--result-ref', 'result.md', '--evidence-ref',
                         '.state/teams/1/rounds/1/researcher-x1.md', '--completion', 'Complete')
        assert submission.returncode == 0, submission.stdout + submission.stderr
        assert yaml.safe_load(submission.stdout)['alias'] == 'research@x1'
        graph = product_cli(worktree, address, 'task', 'graph')
        assert graph.returncode == 0, graph.stdout + graph.stderr
        assert [item['task_id'] for item in yaml.safe_load(graph.stdout)['tasks']] == ['148']
        worldline = product_cli(worktree, address, 'worldline', 'read')
        assert worldline.returncode == 0, worldline.stdout + worldline.stderr
        assert any(json.loads(line)['event'] for line in worldline.stdout.splitlines())
        assert cli(nested, address, 'reports', 'research@x1').returncode == 0
        refused = cli(foreign, address, 'reports', 'research@x1')
        assert refused.returncode == 1
        assert yaml.safe_load(refused.stdout)['error']['code'] == 'invalid-config'
        sibling = cli(worktree, address, 'reports', 'research@x2')
        assert sibling.returncode == 0, sibling.stdout + sibling.stderr
        assert yaml.safe_load(sibling.stdout)['alias'] == 'research@x2'


def test_cli_connection_uses_and_cleans_a_sandbox_visible_channel(tmp_path: Path) -> None:
    """A Runtime may relocate its own channel into a directory its sandbox can write."""
    runner, _, commit = result_project(tmp_path)
    directory = own_process(runner)
    worktree = tmp_path / 'worktrees/research'
    channel = worktree / '.scratch'
    foreign = tmp_path / 'elsewhere'
    foreign.mkdir()
    shared = runner.parent / 'cli'
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(), directory=channel,
    ) as address:
        assert Path(address).parent == channel
        assert cli(worktree, address, 'reports', 'research@x1').returncode == 0
        submission = cli(worktree, address, 'submit-result', '--commit', commit,
                         '--result-ref', 'result.md', '--completion', 'Worktree channel')
        assert submission.returncode == 0, submission.stdout + submission.stderr
        assert yaml.safe_load(submission.stdout)['alias'] == 'research@x1'
        refused = cli(foreign, address, 'reports', 'research@x1')
        assert refused.returncode == 1
        assert yaml.safe_load(refused.stdout)['error']['code'] == 'invalid-config'
    assert not Path(address).exists()
    assert not any(channel.iterdir())
    assert not shared.exists()
    absent = cli(worktree, address, 'reports', 'research@x1')
    assert absent.returncode == 1
    assert yaml.safe_load(absent.stdout)['error']['code'] == 'operation-failed'


def test_cli_connection_removes_a_relocated_channel_after_failure(tmp_path: Path) -> None:
    """A raised Session error still cleans up the relocated channel directory."""
    import pytest

    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    channel = tmp_path / 'worktrees/research/.scratch'
    with hold_ownership(directory, os.getpid()):
        with pytest.raises(RuntimeError):
            with cli_connection(tmp_path, 'research@x1', native_operation_features(), directory=channel) as address:
                observed = Path(address)
                assert observed.parent == channel
                raise RuntimeError('native session failed')
    assert not observed.exists()
    assert not any(channel.iterdir())


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
        assert filesystem[str(tmp_path / '.graphtraj')] == 'read'
        assert filesystem[address] == 'write'
        assert filesystem.get(str(Path(address).parent)) in (None, 'none')
        result = cli(tmp_path, address, 'submit-result', '--commit', commit,
                     '--result-ref', 'result.md', '--completion', 'Native host adopted',
                     GRAPHTRAJ_NATIVE_RUNTIME='codex', CODEX_THREAD_ID=session)
        assert result.returncode == 0, result.stdout + result.stderr
        observed.append(address)

    worker = CodexManagedExecution(resolved.launch_document()['adapter_request'], 'complete',
                                   directory, lambda *_: None, resolved.evidence_document(),
                                   directory / 'native.jsonl', session_created=created)
    with hold_ownership(directory, os.getpid()):
        assert worker.run()['outcome'] == 'completed'
    assert len(observed) == 1
    assert not Path(observed[0]).exists()


def test_native_submission_errors_identify_wrong_and_absent_references(tmp_path: Path) -> None:
    """Wrong report usage is actionable; a path absent at the commit is named, not a Git failure."""
    import pytest

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        with pytest.raises(ValueError, match='evidence_refs'):
            tools.submit_result({'commit': commit, 'result_refs': ['.state/teams/1/rounds/1/researcher-x1.md'],
                                 'completion': 'Done'}, cwd=tmp_path)
        with pytest.raises(ValueError, match=f'absent.md is not a committed file at {commit}'):
            tools.submit_result({'commit': commit, 'result_refs': ['absent.md'],
                                 'completion': 'Done'}, cwd=tmp_path)


def test_shared_mcp_command_consumes_bound_graphtraj_dsh_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same MCP command preserves the existing Task caller and native Session check."""
    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    monkeypatch.delenv('AGENT_SWARM_CONNECTION', raising=False)
    expected = {'runtime': 'dsh', 'session': 'owned-dsh-session', 'source': 'main', 'cwd': str(tmp_path)}
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'agents',
        'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}}}}
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(), native_context=lambda: expected,
    ) as address:
        listed = run_cli('graphtraj.interfaces.mcp', tmp_path, address,
                         input_text=json.dumps({'jsonrpc': '2.0', 'id': 0, 'method': 'tools/list'})+'\n',
                         DSH_SESSION_ID=expected['session'], DSH_AGENT_SOURCE='main')
        assert [tool['name'] for tool in json.loads(listed.stdout)['result']['tools']] == ['agents', 'tasks']
        discovery = run_cli('graphtraj.interfaces.mcp', tmp_path, address,
                            input_text=json.dumps({**request, 'params': {'name': 'tasks',
                                'arguments': {'action': 'discover'}}})+'\n',
                            DSH_SESSION_ID=expected['session'], DSH_AGENT_SOURCE='main')
        service = json.loads(discovery.stdout)['result']['structuredContent']['service']
        import hashlib
        from graphtraj.configuration import project_configuration

        for component in ('mcp', 'host'):
            assert service[component]['executable'] == sys.executable
            assert service[component]['sha256'] == hashlib.sha256(
                Path(service[component]['module']).read_bytes()).hexdigest()
            assert service[component]['configuration_sha256'] == hashlib.sha256(
                Path(project_configuration.__file__).read_bytes()).hexdigest()
        assert service['mcp']['module'] != service['host']['module']
        for session, source in ((expected['session'], 'main'), ('other', 'main'), (expected['session'], 'child')):
            result = run_cli('graphtraj.interfaces.mcp', tmp_path, address,
                             input_text=json.dumps(request)+'\n',
                             DSH_SESSION_ID=session, DSH_AGENT_SOURCE=source)
            assert result.returncode == 0, result.stderr
            response = json.loads(result.stdout)['result']
            if (session, source) == (expected['session'], 'main'):
                assert not response['isError'], response
                assert 'research@x1' in json.dumps(response['structuredContent'])
            else:
                assert response['isError']
                assert 'do not match' in response['content'][0]['text']


def test_managed_channel_discovers_and_describes_task_members(tmp_path: Path) -> None:
    """Every managed Agent channel's allowlist exposes the read-only task_members feature."""
    from graphtraj.interfaces.gateway import handle_request

    allowed = native_operation_features()
    found = handle_request({'action': 'discover', 'query': 'members'}, cwd=tmp_path, allowed_features=allowed)
    assert 'task_members' in [item['feature'] for item in found.document['features']]
    described = handle_request({'action': 'describe', 'feature': 'task_members', 'schema': True},
                               cwd=tmp_path, allowed_features=allowed)
    assert not described.failed
    assert described.document['input_schema'] == tools.TOOLS['task_members'].input_schema
    report = handle_request({'action': 'describe', 'feature': 'submit_report', 'schema': True},
                            cwd=tmp_path, allowed_features=allowed)
    assert 'notify_parent' in report.document['input_schema']['properties']


def test_cli_host_returns_a_slow_write_receipt_instead_of_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report the host persists after the ordinary deadline still returns its receipt once."""
    import time
    from dataclasses import replace

    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    original = tools.TOOLS['submit_report']
    calls = []

    def slow(arguments: dict, *, cwd: Path | None = None) -> tools.ToolResult:
        """Persist the report only after the ordinary ten-second control deadline."""
        calls.append(arguments)
        time.sleep(10.5)
        return original.handler(arguments, cwd=cwd)

    monkeypatch.setitem(tools.TOOLS, 'submit_report', replace(original, handler=slow))
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        result = run_cli('graphtraj.interfaces.cli.agent_runner', tmp_path, address,
                         'submit-report', '--name', 'researcher-x1.md', '--text', 'Slow evidence',
                         process_timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 1
    receipt = yaml.safe_load(result.stdout)
    assert Path(receipt['report']).read_text() == 'Slow evidence'
    assert 'did not acknowledge' not in result.stdout + result.stderr


def test_cli_host_returns_a_slow_read_result_instead_of_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An accepted read that outlasts the ordinary deadline returns the owner's real result."""
    import time
    from dataclasses import replace

    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    original = tools.TOOLS['task_members']

    def slow(arguments: dict, *, cwd: Path | None = None) -> tools.ToolResult:
        """Answer only after the ordinary ten-second control deadline."""
        time.sleep(10.5)
        return tools.ToolResult({'members': ['slow-but-answered']})

    monkeypatch.setitem(tools.TOOLS, 'task_members', replace(original, handler=slow))
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        result = run_cli('graphtraj.interfaces.cli.graphtraj', tmp_path, address,
                         'task', 'members', process_timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(result.stdout) == {'members': ['slow-but-answered']}


def test_agents_cli_uses_the_bound_task_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The independent agents CLI reaches a member's host through the MCP agents dispatch."""
    from agent_swarm.connection import CONNECTION_ENV as AGENTS_CONNECTION

    runner, _, _ = result_project(tmp_path)
    directory = own_process(runner)
    monkeypatch.delenv(AGENTS_CONNECTION, raising=False)
    status = json.dumps({'action': 'execute', 'feature': 'status', 'arguments': {}})
    with cli_connection(tmp_path, 'research@x1', native_operation_features()) as address:
        refused = run_cli('agent_swarm.cli', tmp_path, address, status)
        assert refused.returncode == 1  # the channel locates, it never authorizes
        assert json.loads(refused.stdout)['error']['code'] == 'authority-denied'
    with hold_ownership(directory, os.getpid()), cli_connection(
        tmp_path, 'research@x1', native_operation_features(),
    ) as address:
        found = run_cli('agent_swarm.cli', tmp_path, address, json.dumps({'action': 'discover'}))
        assert found.returncode == 0 and 'status' in found.stdout
        result = run_cli('agent_swarm.cli', tmp_path, address, status)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'research@x1' in result.stdout
        both = run_cli('agent_swarm.cli', tmp_path, address, status, **{AGENTS_CONNECTION: address})
        assert json.loads(both.stdout)['error']['code'] == 'authority-denied'
