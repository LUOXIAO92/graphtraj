"""A Task-free Pi child from the generic request; GraphTraj Pi members unchanged."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.models import pi_destination
from agent_swarm.pi import PiDriver, execution
from agent_swarm.pi.execution import PiExecution
from agent_swarm.runtime import RuntimeAdapterError
from pi_parity_scenarios import capture
from test_pi_runtime import pi_environment  # noqa: F401


def generic(tmp_path: Path, environment: dict, **fields) -> dict:
    """Return a request with only the generic fields; no Task, report or project field."""
    worktree = tmp_path / 'worktree'
    worktree.mkdir(exist_ok=True)
    return {'executable': shutil.which('pi'), 'provider': 'deepseek', 'model': 'deepseek-flash',
            'worktree_path': str(worktree), 'agent_dir': environment['agent_dir'], 'instructions': 'Be brief.',
            'sandbox_python': environment['sandbox_python'], 'sandbox_path': environment['sandbox_path'],
            'worktree_access': 'read', **fields}


def test_task_free_child_launches_messages_and_continues(
    tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The host's paths and domains reach the native policy; the destination comes from Pi's catalog."""
    captured = tmp_path / 'native-policy.json'
    monkeypatch.setenv('PI_FIXTURE_POLICY', str(captured))
    shared, secret, locked = tmp_path / 'shared', tmp_path / 'secret', tmp_path / 'locked'
    for path in (shared, secret, locked):
        path.mkdir()
    request = generic(tmp_path, pi_environment, read_paths=[str(shared)], deny_read=[str(secret)],
                      deny_write=[str(locked)], allowed_domains=['mirror.example'])
    data = tmp_path / 'data'
    call = bind(AgentControl(data, {'pi': PiDriver(request)}), Caller('standalone-host', None))

    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'wait-generic'})
    assert not created.failed, created.document
    agent, session = created.document['agent'], created.document['session']
    deadline = time.monotonic() + 5
    while (sent := call({'action': 'send', 'agent': agent, 'message': 'finish'})).failed:
        assert time.monotonic() < deadline, sent.document
        time.sleep(0.02)
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert not done.failed, done.document
    assert done.document['result']['last_result']['last_message'] == 'wait-generic|finish'

    policy = json.loads(captured.read_text())
    filesystem = policy['filesystem']
    assert policy['network'] == {'allowedDomains': ['mirror.example', 'api.deepseek.com'], 'deniedDomains': []}
    assert filesystem['denyRead'] == [str(secret), pi_environment['agent_dir'], str(data.resolve())]
    assert str(shared) in filesystem['allowRead'] and str(Path(request['worktree_path']).resolve()) in filesystem['allowRead']
    assert filesystem['denyWrite'][0] == pi_environment['agent_dir'] and filesystem['denyWrite'][-1] == str(locked)
    assert not any(Path(path).name in {'.graphtraj', '.codex', 'config.yml', 'roles.yml', 'hooks'}
                   for paths in filesystem.values() for path in paths)
    directory = next((data / 'native').iterdir())
    argv = json.loads((directory / 'pi-process.json').read_text())['argv']
    assert argv[:7] == [request['executable'], '--mode', 'rpc', '--provider', 'deepseek', '--model', 'deepseek-flash']
    assert argv[-2:] == ['--extension', str(Path(execution.__file__).with_name('extension.mjs'))]

    continued = call({'action': 'send', 'agent': agent, 'message': 'continue'})
    assert not continued.failed and continued.document['session'] == session, continued.document
    done = call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    assert not done.failed, done.document
    last = done.document['result']['last_result']['last_message']
    # The fixture answers with the Session's retained history, then the new input.
    assert last.startswith('wait-generic|') and 'wait-generic|finish' in last and last.endswith('|continue')


def test_generic_execution_needs_no_graphtraj(tmp_path: Path) -> None:
    """Preparing a generic launch imports nothing from GraphTraj."""
    for name in ('home', 'work'):
        (tmp_path / name).mkdir()
    script = textwrap.dedent(f'''
        import sys
        from pathlib import Path
        from agent_swarm.pi.execution import PiExecution
        root = Path({str(tmp_path)!r})
        request = {{'executable': '/bin/pi', 'provider': 'p', 'model': 'm', 'worktree_path': str(root / 'work'),
                    'agent_dir': str(root / 'home'), 'instructions': '', 'sandbox_python': sys.executable,
                    'sandbox_path': '/usr/bin', 'worktree_access': 'read', 'provider_domain': 'p.example'}}
        turn = PiExecution(request, '', root, None, None, root / 'trace.jsonl', None)
        turn.prepare_launch(None)
        assert not [name for name in sys.modules if name.split('.')[0] == 'graphtraj'], sorted(sys.modules)
        print('ok')
    ''')
    completed = subprocess.run([sys.executable, '-I', '-c', script], capture_output=True, text=True, timeout=60)
    assert completed.stdout.strip() == 'ok', completed.stderr


@pytest.mark.parametrize('field,value,expected', [
    ('executable', None, 'executable must be a nonempty string'),
    ('model', 5, 'model must be a nonempty string'),
    ('worktree_access', 'admin', "worktree_access must be 'read' or 'write'"),
    ('read_paths', 'shared', 'read_paths must be a list of absolute paths'),
    ('deny_read', ['relative/secret'], 'deny_read must be a list of absolute paths'),
    ('write_paths', [None], 'write_paths must be a list of absolute paths'),
    ('allowed_domains', 'mirror.example', 'allowed_domains must be a list of nonempty strings'),
    ('allow_unix_sockets', [3], 'allow_unix_sockets must be a list of nonempty strings'),
    ('allow_local_binding', 'yes', 'allow_local_binding must be a boolean'),
    ('base_url', 7, 'base_url must be a string when given'),
    ('base_url', 'https://models.example/v1', 'provider_api must be given with base_url'),
    ('worktree_access', 'write', 'git_common_directory must be given for write access'),
])
def test_invalid_request_fields_are_named(
    tmp_path: Path, pi_environment: dict, field: str, value: object, expected: str,
) -> None:
    """A wrong field type fails before any file or process is created."""
    request = generic(tmp_path, pi_environment, provider_domain='api.deepseek.com', **{field: value})
    turn = PiExecution(request, '', tmp_path, None, None, tmp_path / 'trace.jsonl', None)
    with pytest.raises(RuntimeAdapterError) as caught:
        turn.prepare_launch(None)
    assert caught.value.code == 'ROLE_CONFIG_INVALID'
    assert caught.value.message == f'Pi request field {expected}.'
    assert not (tmp_path / 'trace.pi').exists()


@pytest.mark.parametrize('base_url', ['ftp://models.example/v1', 'https://user:secret@models.example/v1', None])
def test_destination_refuses_unsupported_or_missing_models(tmp_path: Path, base_url: str | None) -> None:
    """Only a plain http(s) host of the selected model becomes a network grant."""
    peer = tmp_path / 'pi'
    models = [] if base_url is None else [{'provider': 'p', 'id': 'm', 'baseUrl': base_url}]
    peer.write_text(f'#!{sys.executable}\nimport json,sys\nrequest=json.loads(sys.stdin.readline())\n'
                    f"print(json.dumps({{'id': request['id'], 'success': True, 'data': {{'models': {models!r}}}}}))\n")
    peer.chmod(0o755)
    with pytest.raises(RuntimeAdapterError) as caught:
        pi_destination(str(peer), str(tmp_path), 'p', 'm')
    assert caught.value.code == 'ROLE_CONFIG_UNSUPPORTED'
    assert 'secret' not in caught.value.message


def test_graphtraj_resolver_matches_the_agents_resolver(tmp_path: Path, pi_environment: dict) -> None:
    """GraphTraj's destination delegates to agents with the Runner-selected Pi."""
    from graphtraj.runtimes.model_discovery import pi_model_domain

    for provider in ('deepseek', 'openrouter', 'unlisted'):
        assert (pi_model_domain(pi_environment['agent_dir'], provider, 'model')
                == pi_destination(shutil.which('pi'), pi_environment['agent_dir'], provider, 'model'))


def test_graphtraj_member_launch_matches_base() -> None:
    """GraphTraj members launch with the policy, argv, process spec and environment of 33c7adb.

    Path lists of one rule kind hold the same entries; only their order
    differs, because GraphTraj's paths now follow the agents owner's own.
    """
    goldens = json.loads(Path(__file__).with_name('pi_parity_goldens.json').read_text())
    del goldens['_provenance']
    actual = capture()
    for document in (goldens, actual):
        for name, scenario in document.items():
            if name != 'destinations':
                for kind in ('allowRead', 'denyRead', 'denyWrite'):
                    scenario['policy']['filesystem'][kind].sort()
    assert actual == goldens
