"""462: a Codex child's tool processes are stopped after its owner or its service ends.

Codex runs a tool shell in its own session below its app-server. It stops
them when its stdin closes, but not when the service is killed (seen with
codex-cli 0.164 ``command/exec``: after SIGKILL of the app-server the
``/bin/sh`` and its ``sleep`` lived on). The Codex owner now gives its owned
service this execution's own marker, records the service's descendants while
it lives (459's sampler), stops what is left after the service exits, and the
driver records ``tool_marker`` and ``tool_descendants`` so reconciling an
``owner-exited`` execution stops them. Real ``/bin/sh`` and ``/bin/sleep``.

Every test stops only processes it started, after checking pid and start time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import yaml

from graftling import AgentControl, Caller, bind
from graftling.codex.driver import CodexDriver
from graftling.member_processes import MEMBER_RUN_ENV
from graftling.tool_descendants import Identity, _table, identity, read_sidecar

pytestmark = pytest.mark.skipif(not (sys.platform == 'darwin' or sys.platform.startswith('linux')),
                                reason='macOS and Linux process tables')

TOOL = '/bin/sleep 462; :'
CALLER = ('controlled-host', 'actual-parent', 'parent-session', 'codex')
OWNER = r'''
import json, sys, threading
from pathlib import Path
from graftling import AgentControl, Caller, bind
from graftling.codex.driver import CodexDriver
control = AgentControl(Path(sys.argv[1]), {'codex': CodexDriver(json.loads(sys.argv[2]))})
call = bind(control, Caller(*json.loads(sys.argv[3])))
print(json.dumps(call({'action': 'create', 'runtime': 'codex', 'instruction': 'tool-hold'}).document), flush=True)
threading.Event().wait()
'''


@pytest.fixture
def native_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """The controlled app-server peer; it starts the tool shell and never stops it itself."""
    peer = tmp_path / 'codex'
    peer.write_text('#!' + sys.executable + '\n' + Path(__file__).with_name('codex_stdio_peer.py').read_text())
    peer.chmod(0o755)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))
    monkeypatch.setenv('PEER_TOOL_COMMAND', TOOL)
    monkeypatch.delenv(MEMBER_RUN_ENV, raising=False)
    return {'adapter_request': {
        'arguments': [str(peer)], 'worktree_path': str(tmp_path),
        'session_parameters': {'cwd': str(tmp_path), 'model': 'chosen-model', 'developerInstructions': '',
                               'config': {'default_permissions': 'chosen', 'permissions': {
                                   'chosen': {'extends': ':workspace', 'filesystem': {str(tmp_path): 'write'}}}}},
    }}


def argv(pid: int) -> str:
    from graftling.tool_descendants import _argv

    return ' '.join(_argv(pid))


def is_alive(item: Identity) -> bool:
    now = identity(item.pid)
    return now is not None and now.start == item.start


def wait_for(predicate, seconds: float = 20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.1)
    return predicate()


def ours(started_after: int) -> dict[str, list[Identity]]:
    """Processes of this test's commands started after ``started_after``, by command line."""
    found: dict[str, list[Identity]] = {}
    for item in _table().values():
        if item.start >= started_after:
            found.setdefault(argv(item.pid), []).append(item)
    return found


def stop_own(items) -> None:
    """Stop only processes this test started, after checking pid and start time."""
    for item in items:
        if is_alive(item):
            os.kill(item.pid, signal.SIGKILL)
    wait_for(lambda: not any(is_alive(item) for item in items), 5)


def tools(started_after: int) -> dict[str, Identity]:
    seen = ours(started_after)
    named = {'shell': f'/bin/sh -c {TOOL}', 'sleep': '/bin/sleep 462', 'other': '/bin/sleep 303'}
    return {key: seen[command][0] for key, command in named.items() if command in seen}


def record(root: Path, agent: str) -> dict:
    return json.loads((root / 'control/agents' / f'{agent}.json').read_text())['executions'][-1]


def test_normal_end_owner_stops_the_tool_the_service_left(tmp_path: Path, native_settings: dict) -> None:
    """The service exits after its turn without stopping its tool; the owner stops it."""
    root = tmp_path / 'agents'
    since = identity(os.getpid()).start
    user = subprocess.Popen(['/bin/sleep', '461'], start_new_session=True)
    found: dict[str, Identity] = {}
    try:
        call = bind(AgentControl(root, {'codex': CodexDriver(native_settings)}), Caller(*CALLER))
        created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'tool-end'}).document
        found = wait_for(lambda: len(tools(since)) == 3, 10) and tools(since)
        done = call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 20}).document
        assert done['result']['last_result']['outcome'] == 'completed', done
        execution = record(root, created['agent'])
        facts = execution['process']
        assert facts['tool_marker'] and facts['tool_descendants'].endswith('.json')
        entries = read_sidecar(facts['tool_descendants'])
        print('sidecar:', json.dumps(entries))
        assert {found['shell'].pid, found['sleep'].pid} <= {entry['pid'] for entry in entries}
        assert found['other'].pid not in {entry['pid'] for entry in entries}, 'another marker is foreign'
        [termination] = Path(facts['tool_descendants']).parent.glob('codex-termination-*.yml')
        report = yaml.safe_load(termination.read_text())['escaped_processes']
        print('escaped_processes:', json.dumps(report))
        assert sorted(item['pid'] for item in report['stopped']) == sorted([found['shell'].pid, found['sleep'].pid])
        assert report['remaining'] == [] and 'error' not in report
        assert not is_alive(found['shell']) and not is_alive(found['sleep'])
        assert is_alive(found['other']), "another execution's process is untouched"
        assert user.poll() is None, "the user's own /bin/sleep is untouched"
    finally:
        stop_own(list(found.values()) + [i for items in ours(since).values() for i in items
                                          if argv(i.pid).startswith(('/bin/sleep 303', sys.executable + ' -c'))])
        user.kill()
        user.wait(5)


def test_owner_killed_then_reconciliation_stops_the_tool(tmp_path: Path, native_settings: dict) -> None:
    """SIGKILL the owner and its service; one reconciling read stops the recorded tool."""
    root = tmp_path / 'agents'
    since = identity(os.getpid()).start
    owner = subprocess.Popen([sys.executable, '-c', OWNER, str(root), json.dumps(native_settings), json.dumps(CALLER)],
                             stdout=subprocess.PIPE, text=True)
    user = subprocess.Popen(['/bin/sleep', '461'], start_new_session=True)
    found: dict[str, Identity] = {}
    service = None
    try:
        created = json.loads(owner.stdout.readline())
        agent = created['agent']
        facts = record(root, agent)['process']
        assert facts['tool_marker'] and facts['tool_descendants']

        def recorded():
            try:
                commands = {entry['argv'] for entry in read_sidecar(facts['tool_descendants'])}
            except (OSError, ValueError):
                return None
            return {f'/bin/sh -c {TOOL}', '/bin/sleep 462'} <= commands

        assert wait_for(recorded), 'the owner did not record the tool shell'
        found = tools(since)
        service = identity(facts['runtime_pid'])
        assert service is not None and service.start >= since
        owner.send_signal(signal.SIGKILL)
        owner.wait(5)
        os.killpg(service.pgid, signal.SIGKILL)  # the service's own group, checked above
        assert wait_for(lambda: not is_alive(service), 10)

        def reaped() -> bool:
            # A killed service stays a zombie until launchd reaps it; control's kill(pid, 0) still sees it.
            try:
                os.kill(service.pid, 0)
            except ProcessLookupError:
                return True
            return identity(service.pid) is not None  # reused by another process: not ours, gone for us
        assert wait_for(reaped, 10)
        assert is_alive(found['shell']) and is_alive(found['sleep']), 'the tool outlived owner and service'

        call = bind(AgentControl(root, {'codex': CodexDriver(native_settings)}), Caller(*CALLER))
        status = call({'action': 'status', 'agent': agent}).document
        execution = record(root, agent)
        report = execution.get('escaped_processes')
        print('escaped_processes:', json.dumps(report))
        assert status['result'].get('last_result', {}).get('error', {}).get('code') == 'owner-exited', (status, execution)
        assert sorted(item['pid'] for item in report['stopped']) == sorted([found['shell'].pid, found['sleep'].pid])
        assert report['remaining'] == [] and 'error' not in report
        assert not is_alive(found['shell']) and not is_alive(found['sleep'])
        assert is_alive(found['other']), "another execution's process is untouched"
        assert user.poll() is None, "the user's own /bin/sleep is untouched"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(5)
        stop_own(list(found.values()) + ([service] if service else [])
                 + [i for items in ours(since).values() for i in items
                    if argv(i.pid).startswith(('/bin/sleep 303', sys.executable + ' -c'))])
        user.kill()
        user.wait(5)


def test_the_service_keeps_only_a_fresh_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """450 still holds: the parent's marker never reaches a service; the owner's own does."""
    from graftling.codex.app_server import CodexAppServer

    monkeypatch.setenv(MEMBER_RUN_ENV, 'parent-marker')
    service = lambda **kwargs: CodexAppServer(cwd=Path('.'), command=['codex'], **kwargs)._environment
    assert MEMBER_RUN_ENV not in service()
    assert MEMBER_RUN_ENV not in service(environment={MEMBER_RUN_ENV: 'parent-marker'})
    assert service(environment={MEMBER_RUN_ENV: 'own'})[MEMBER_RUN_ENV] == 'own'


def test_reclaim_runs_when_the_interpreter_refuses_new_threads(
        tmp_path: Path, native_settings: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Correction 2: an owner thread outliving its interpreter's shutdown still stops the tools.

    At shutdown CPython refuses new executor work, so ``asyncio.to_thread`` raises. The real host's child
    then ended RUNTIME_WORKER_FAILED with no reclaim; the reclaim now runs on the owner's own thread.
    """
    import asyncio

    async def refused(*args, **kwargs):
        raise RuntimeError('cannot schedule new futures after interpreter shutdown')

    monkeypatch.setattr(asyncio, 'to_thread', refused)
    root = tmp_path / 'agents'
    since = identity(os.getpid()).start
    user = subprocess.Popen(['/bin/sleep', '461'], start_new_session=True)
    found: dict[str, Identity] = {}
    try:
        call = bind(AgentControl(root, {'codex': CodexDriver(native_settings)}), Caller(*CALLER))
        created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'tool-end'}).document
        found = wait_for(lambda: len(tools(since)) == 3, 10) and tools(since)
        assert found, 'the peer did not start the tool'
        facts = record(root, created['agent'])['process']
        directory = Path(facts['tool_descendants']).parent
        termination = wait_for(lambda: next(directory.glob('codex-termination-*.yml'), None), 20)
        assert termination is not None, 'the owner-side reclaim did not run'
        report = yaml.safe_load(termination.read_text())['escaped_processes']
        print('escaped_processes:', json.dumps(report))
        assert sorted(item['pid'] for item in report['stopped']) == sorted([found['shell'].pid, found['sleep'].pid])
        assert report['remaining'] == [] and 'error' not in report
        assert not is_alive(found['shell']) and not is_alive(found['sleep'])
        assert is_alive(found['other']) and user.poll() is None
        done = call({'action': 'wait', 'agent': created['agent'], 'timeout_seconds': 20}).document
        print('outcome:', json.dumps(done['result'].get('last_result')))
    finally:
        stop_own(list(found.values()) + [i for items in ours(since).values() for i in items
                                          if argv(i.pid).startswith(('/bin/sleep 303', sys.executable + ' -c'))])
        user.kill()
        user.wait(5)
