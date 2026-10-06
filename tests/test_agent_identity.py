"""Public host adoption, caller isolation and retained GraphTraj identity."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces.local_tool import HostTool, bind
from test_hosted_cli import cli
from test_role_organization import project, accept, ADD


def call(host: HostTool, feature: str, arguments: dict | None = None) -> dict:
    """Invoke the model-visible gateway through its owning host binding."""
    result = host({'action': 'execute', 'feature': feature, 'arguments': arguments or {}})
    assert not result.failed, result.document
    return result.document


def test_external_main_and_checker_are_distinct_without_native_handles(project: Path) -> None:
    """A non-Codex host adopts its existing Main and registers each checker first."""
    proposals = []

    def approve(proposal: dict) -> dict:
        """Represent the owning host's user decision, outside model arguments."""
        proposals.append(proposal)
        return {'decision': 'accept', 'rationale': 'Authorized by the owning host user.'}

    with bind(project, event_receiver=lambda event: None, recovery_reviewer=approve) as main:
        alias = main.adopt_main('controlled-adapter')
        assert proposals == [{'operation': 'adopt-main', 'project': str(project),
                              'runtime': 'controlled-adapter', 'alias': None,
                              'purpose': 'main', 'parent': None}]
        assert call(main, 'agent_identity') == {
            'access': 'agent', 'alias': alias, 'purpose': 'main', 'parent': None,
        }
        with main.register_checker(lambda event: None) as checker:
            expected = {'access': 'agent', 'alias': checker.alias,
                        'purpose': 'checker', 'parent': alias}
            assert call(checker, 'agent_identity') == expected
            with ThreadPoolExecutor(2) as workers:
                results = list(workers.map(lambda host: call(host, 'agent_identity'), [main, checker] * 5))
            assert [entry['alias'] for entry in results] == [alias, checker.alias] * 5
            with pytest.raises(RunnerError):
                checker.adopt_main('controlled-adapter')
            with pytest.raises(RunnerError):
                checker.register_checker(lambda event: None)
            with pytest.raises(RunnerError):
                call(checker, 'role_organization', ADD)
            from graphtraj.interfaces.desktop_settings import settings_request
            from graphtraj.execution.runner_status import runtime_caller
            with runtime_caller(project / '.graphtraj/runner', alias):
                with pytest.raises(RunnerError):
                    settings_request({'action': 'read'}, project, accept)
            assert call(main, 'role_organization', ADD)['applied']
            tree = call(main, 'alias_status')['agents']
            assert {item['alias']: item['parent'] for item in tree} == {alias: None, checker.alias: alias}


def test_adoption_refusals_and_restore_preserve_identity(project: Path) -> None:
    """Missing approval and changed purpose cannot admit a Main; restore keeps the alias."""
    with bind(project, event_receiver=lambda event: None) as host:
        with pytest.raises(RunnerError):
            host.adopt_main('controlled')
        with pytest.raises(RunnerError):
            call(host, 'agent_identity')
    with bind(project, event_receiver=lambda event: None,
              recovery_reviewer=lambda proposal: {'decision': 'decline'}) as host:
        with pytest.raises(RunnerError):
            host.adopt_main('controlled')
    with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as host:
        alias = host.adopt_main('controlled')
        with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as duplicate:
            with pytest.raises(RunnerError):
                duplicate.adopt_main('controlled', resume=alias)
        with host.register_checker(lambda event: None) as checker:
            child = checker.alias
        assert host({'action': 'execute', 'feature': 'agent_identity',
                     'arguments': {'alias': alias}}).failed
    with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as restored:
        assert restored.adopt_main('controlled', resume=alias) == alias
        assert call(restored, 'agent_identity')['purpose'] == 'main'
    with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as other:
        with pytest.raises(RunnerError):
            other.adopt_main('controlled', resume=child)


def test_public_cli_uses_the_host_verified_channel(project: Path) -> None:
    """Actual subprocess CLI identity agrees with tools and a refused channel stays refused."""
    from graphtraj.execution.runner_process import process_ancestors

    def verify(pid: int) -> None:
        """This controlled host owns the sole CLI subprocess launched by the test."""
        if os.getpid() not in process_ancestors(pid):
            raise RunnerError('authority-denied', 'Not the owned CLI execution.')

    def refuse(pid: int) -> None:
        """Refuse a writer the host did not assign to this Agent."""
        raise RunnerError('authority-denied', 'Not assigned to this Agent.')

    with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as host:
        alias = host.adopt_main('controlled')
        with host.cli_channel(verify) as address:
            result = cli(project, address, 'identity', CODEX_THREAD_ID='not-authority')
            assert result.returncode == 0, result.stdout + result.stderr
            assert yaml.safe_load(result.stdout) == call(host, 'agent_identity')
            import json
            import subprocess
            import sys
            from graphtraj.interfaces.hosted_cli import CONNECTION_ENV

            envelope = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'graphtraj', 'arguments': {'action': 'execute', 'feature': 'agent_identity', 'arguments': {}},
            }}
            response = subprocess.run(
                [sys.executable, '-c', 'from graphtraj.interfaces.mcp import main; main()'],
                input=json.dumps(envelope) + '\n', text=True, capture_output=True, cwd=project,
                env={**os.environ, CONNECTION_ENV: address,
                     'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}, timeout=10,
            )
            assert response.returncode == 0, response.stderr
            assert json.loads(response.stdout)['result']['structuredContent'] == call(host, 'agent_identity')
        with host.register_checker(lambda event: None) as checker:
            with checker.cli_channel(refuse) as address:
                result = cli(project, address, 'identity', GRAPHTRAJ_CALLER_ALIAS=alias)
                assert result.returncode == 1
                assert yaml.safe_load(result.stdout)['error']['code'] == 'authority-denied'


def test_adopted_main_launches_members_and_retires_without_reparenting(
    installed_commands: InstalledCommands, temporary_git_repository: Path,
    fake_codex: FakeCodex, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public host/swarm/status/retirement preserve both stopped identity and evidence."""
    import sys
    import json
    from conftest import app_server_peer, wait_for_file
    from runner_fixtures import configure_harness
    from test_ticket_graph import _ticket, _register, _change_status

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register(installed_commands, root, _ticket('271', 'identity'))
    _change_status(installed_commands, root, '271', 'ready')
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    # The public Runner starts its subprocesses from the tested wheel install.
    monkeypatch.setattr(sys, 'executable', str(installed_commands.runner.parent / 'python'))
    member_result = tmp_path / 'member-public-calls.json'
    script = f"""#!{sys.executable}
import json, os, subprocess, sys, tomllib
from pathlib import Path
if sys.argv[1:] == ['exec', '--help']:
    print('--config --json --sandbox')
    raise SystemExit(0)
settings = {{}}
for index, argument in enumerate(sys.argv[:-1]):
    if argument == '-c':
        settings.update(tomllib.loads(sys.argv[index + 1]))
environment = dict(os.environ)
environment.update(settings['shell_environment_policy']['set'])
results = []
for arguments in [('identity',), ('requests', environment['IDENTITY_MAIN_ALIAS'])]:
    response = subprocess.run([{str(installed_commands.runner)!r}, *arguments],
                              cwd={str(root)!r}, env=environment, text=True, capture_output=True)
    results.append({{'code': response.returncode, 'stdout': response.stdout, 'stderr': response.stderr}})
if environment['GRAPHTRAJ_ROLE'] == 'team-leader':
    child_input = Path(sys.argv[sys.argv.index('-C') + 1]) / 'child-swarm.yml'
    child_input.write_text(json.dumps({{'tasks': [{{'role': 'engineer', 'instruction': 'Read your registered identity.'}}]}}))
    response = subprocess.run([{str(installed_commands.runner)!r}, '--swarm-input', str(child_input)],
                              cwd={str(root)!r}, env=environment, text=True, capture_output=True)
    results.append({{'code': response.returncode, 'stdout': response.stdout, 'stderr': response.stderr}})
output = Path({str(member_result)!r})
if environment['GRAPHTRAJ_ROLE'] != 'team-leader':
    output = output.with_name('child-public-calls.json')
output.write_text(json.dumps(results))
print(json.dumps({{'type': 'turn.completed'}}), flush=True)
"""
    fake_codex.executable.write_text(app_server_peer(script))
    events = []
    with bind(root, event_receiver=events.append, recovery_reviewer=accept) as main:
        alias = main.adopt_main('controlled-adapter')
        monkeypatch.setenv('IDENTITY_MAIN_ALIAS', alias)
        result = call(main, 'swarm', {'tasks': [{
            'ticket_id': '271', 'role': 'team-leader', 'instruction': 'Complete this controlled turn.',
        }]})
        member = result['tasks'][0]['alias']
        wait_for_file(member_result)
        member_calls = json.loads(member_result.read_text())
        assert member_calls[0]['code'] == 0, member_calls
        assert yaml.safe_load(member_calls[0]['stdout']) == {
            'access': 'agent', 'alias': member, 'purpose': 'member', 'parent': alias,
        }
        assert member_calls[2]['code'] == 0, member_calls
        assert yaml.safe_load(member_calls[2]['stdout'])['tasks'][0]['launch_status'] == 'registered'
        child_result = member_result.with_name('child-public-calls.json')
        wait_for_file(child_result, timeout=15)
        nested_calls = json.loads(child_result.read_text())
        assert nested_calls[0]['code'] == 0, nested_calls
        nested_identity = yaml.safe_load(nested_calls[0]['stdout'])
        assert nested_identity['purpose'] == 'member'
        assert nested_identity['parent'] == member
        assert member_calls[1]['code'] == 1, member_calls
        assert yaml.safe_load(member_calls[1]['stdout'])['error']['code'] == 'authority-denied'
        tree = call(main, 'alias_status')['agents']
        assert next(item for item in tree if item['alias'] == member)['parent'] == alias
        with main.register_checker(events.append) as checker:
            child = checker.alias
        # A retained checker cannot be restored as Main.
        with bind(root, event_receiver=events.append, recovery_reviewer=accept) as outsider:
            with pytest.raises(RunnerError):
                outsider.adopt_main('controlled-adapter', resume=child)
        call(main, 'interrupt', {'alias': member})
        call(main, 'retire', {'alias': child})
        assert call(main, 'alias_status', {'aliases': [child]})['aliases'][0]['retired']
        with pytest.raises(RunnerError):
            main.register_checker(events.append, resume=child)
    with bind(root, event_receiver=events.append, recovery_reviewer=accept) as replacement:
        successor = replacement.adopt_main('controlled-adapter', replaces=alias)
        assert successor != alias
        assert call(replacement, 'agent_identity')['alias'] == successor
        old = call(replacement, 'alias_status', {'aliases': [alias]})['aliases'][0]
        assert old['activity'] == 'idle'
        with pytest.raises(RunnerError):
            call(replacement, 'session_reports', {'alias': member})
    with bind(root, event_receiver=events.append, recovery_reviewer=accept) as refused:
        with pytest.raises(RunnerError):
            refused.adopt_main('controlled-adapter', resume=alias)


def test_bound_member_cannot_use_user_adoption_and_missing_channel_does_not_promote(project: Path) -> None:
    """Even an accepting reviewer does not turn an Agent request into human adoption."""
    import subprocess
    import sys
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.hosted_cli import CONNECTION_ENV

    with bind(project, event_receiver=lambda event: None, recovery_reviewer=accept) as host:
        with runtime_caller(project / '.graphtraj/runner', 'member@e1'):
            with pytest.raises(RunnerError):
                host.adopt_main('controlled')
        host.adopt_main('controlled')
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        environment.pop(CONNECTION_ENV, None)
        result = subprocess.run(
            [sys.executable, '-c', 'from graphtraj.interfaces.cli.agent_runner import main; main()', 'identity'],
            cwd=project, env=environment, text=True, capture_output=True, timeout=10,
        )
        assert result.returncode == 1
        assert yaml.safe_load(result.stdout)['error']['code'] == 'authority-denied'
    human = subprocess.run(
        [sys.executable, '-c', 'from graphtraj.interfaces.cli.agent_runner import main; main()', 'identity'],
        cwd=project, env=environment, text=True, capture_output=True, timeout=10,
    )
    assert human.returncode == 0, human.stdout + human.stderr
    assert yaml.safe_load(human.stdout) == {'access': 'human'}
