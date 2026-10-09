"""Subtree stopping through public control and the common managed Worker boundary."""

import os
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Awaitable, Callable

import pytest
import yaml

from test_managed_sessions import ManagedProject, launch_document, managed_project, observe


@pytest.mark.parametrize('native_source', ['child', 'main'])
def test_native_owner_retains_control_of_its_recorded_root(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch, native_source: str,
) -> None:
    """Actual external ownership survives native classification without global Main authority."""
    from graphtraj.interfaces.local_tool import bind
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.runtimes import runtime_adapter
    from graphtraj.runtimes.codex import finalize
    from graphtraj.execution.runner_connection import parent_connection
    from graphtraj.execution.runner_batch import parse_batch
    from graphtraj.execution.runner_launch import launch_batch

    root, cause, call, executable = managed_project
    monkeypatch.setenv('PATH', str(executable.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('MANAGED_NATIVE_ROOT', str(executable.parent.parent / 'native'))
    monkeypatch.setenv('CODEX_HOME', str(executable.parent.parent / 'codex-home'))
    connection = {'runtime': 'codex', 'session': 'external-owner',
                  'codex_home': '/native-owner-home'}
    with parent_connection(connection):
        target = launch_batch(parse_batch(launch_document()), root).document['tasks'][0]['alias']
    child = call('child', [target, 'descendant@e1'])['alias']
    before = mapping(root, target)
    assert before['parent'] is None
    assert before['parent_connection'] == connection

    class NativeMetadata:
        """Supply the owning daemon's verified thread response at its public seam."""
        async def __aenter__(self) -> 'NativeMetadata':
            """Open this controlled native metadata connection."""
            return self

        async def __aexit__(self, *args: object) -> None:
            """Close without changing any Session."""

        async def read_thread(self, session: str) -> dict:
            """A delegated source stays delegated even when it owns an old root."""
            if native_source == 'main':
                return {'id': session, 'source': 'vscode', 'parentThreadId': None}
            return {'id': session, 'source': {'subAgent': {'thread_spawn': {
                'parent_thread_id': 'native-parent', 'depth': 1, 'agent_path': '1',
            }}}}

    monkeypatch.setattr(runtime_adapter, 'current_host_connection', lambda: dict(connection))
    monkeypatch.setattr(finalize, 'proxy', lambda value: NativeMetadata())

    def send(alias: str) -> dict:
        """Use the public Tool, not a caller-selected identity parameter."""
        return bind(root)({'action': 'execute', 'feature': 'send_instruction', 'arguments': {
            'alias': alias, 'instruction': 'hold', 'caused_by_event_ids': [cause],
        }}).document

    assert send(target)['send_status'] == 'sent'
    with pytest.raises(RunnerError, match='direct parent'):
        send(child)
    connection['session'] = 'different-native-child'
    with pytest.raises(RunnerError, match='direct parent|association is unavailable'):
        send(target)
    connection['session'] = 'external-owner'
    connection['codex_home'] = '/different-native-home'
    with pytest.raises(RunnerError, match='direct parent|association is unavailable'):
        send(target)
    connection['codex_home'] = '/native-owner-home'
    stopped = bind(root)({'action': 'execute', 'feature': 'interrupt',
                         'arguments': {'alias': child}}).document
    assert stopped['interrupt_status'] == 'interrupted'
    assert mapping(root, target) == before
    assert not (root / '.graphtraj/runner/main-sessions').exists()


def mapping(root: Path, alias: str) -> dict:
    """Read identity retained by a managed Worker in the isolated test project."""
    return yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())


@pytest.mark.parametrize('entry', ['SessionStart', 'Stop'])
def test_native_root_owner_outlives_historical_checker_membership(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    """Native entry, tools and Stop agree without rewriting either ownership record."""
    import json
    import sys
    from graphtraj.execution import main_finalize
    from graphtraj.execution.runner_batch import parse_batch
    from graphtraj.execution.runner_connection import parent_connection
    from graphtraj.execution.runner_launch import launch_batch
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.interfaces.local_tool import bind
    from graphtraj.runtimes import runtime_adapter
    from graphtraj.runtimes.codex import finalize
    from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
    from test_main_finalize import PEER, native_hook, rollout

    root, _, _, executable = managed_project
    monkeypatch.setenv('PATH', str(executable.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('MANAGED_NATIVE_ROOT', str(executable.parent.parent / 'native'))
    monkeypatch.setenv('CODEX_HOME', str(root))
    connection = {'runtime': 'codex', 'session': 'main', 'codex_home': str(root)}
    with parent_connection(connection):
        launched = launch_batch(parse_batch(launch_document()), root).document
        assert 'alias' in launched['tasks'][0], json.dumps(launched)
        target = launched['tasks'][0]['alias']
    original = mapping(root, target)
    historical = main_finalize.bind_checker(
        root / '.graphtraj/runner/main-sessions/old-owner/session.yml',
        {'runtime': 'codex', 'session': 'old-owner', 'connection': {
            **connection, 'session': 'old-owner',
        }, 'summary_issue': ''}, 'main',
    ) / 'session.yml'
    retained = historical.read_bytes()
    peer = root / 'completion-peer.py'
    peer.write_text(PEER)
    (root / 'options.json').write_text(json.dumps({'source': 'vscode'}))
    monkeypatch.setenv('FINALIZE_TEST_ROOT', str(root))

    def connect(
        connection: dict,
        on_request: Callable[[CodexServerRequest], Awaitable[dict]] | None = None,
    ) -> CodexAppServer:
        """Supply native metadata and fork protocol without changing Runner ownership."""
        return CodexAppServer(cwd=root, command=(sys.executable, str(peer)),
                              experimental_api=True, on_request=on_request)

    monkeypatch.setattr(finalize, 'proxy', connect)
    monkeypatch.setattr(runtime_adapter, 'current_host_connection', lambda: dict(connection))
    monkeypatch.setattr(main_finalize, 'current_host_connection', lambda: dict(connection))
    rollout(root, source='vscode')
    if entry == 'SessionStart':
        assert 'associated' in native_hook(root, entry)['systemMessage']
    else:
        # A real host Stop may be the first hook after hot adoption. It creates
        # the association only for the established native owner and checks now.
        binding = main_finalize.session_binding(root, 'codex', 'main')
        assert not binding.exists()
        wrong = native_hook(root, session_id='wrong-native-session')
        assert wrong['continue'] is False and not binding.exists()
        result = native_hook(root)
        assert 'completed' in result['systemMessage'] and 'decision' not in result
        assert binding.is_file()
        (root / 'options.json').write_text(json.dumps({'source': 'vscode', 'child': 'checker-two'}))
    tool = bind(root)
    assert not tool({'action': 'execute', 'feature': 'bind_main_finalize',
                     'arguments': {'summary_issue': 'tracker:current'}}).failed
    result = native_hook(root)
    assert 'completed' in result['systemMessage'] and 'decision' not in result
    assert historical.read_bytes() == retained
    assert mapping(root, target) == original

    # Use public retirement, which is also the last-child cleanup path. The
    # owning Main must still organize roles and dispatch after the active
    # mapping has moved into the Ticket's retained Trace.
    stopped = tool({'action': 'execute', 'feature': 'interrupt',
                    'arguments': {'alias': target}})
    assert not stopped.failed, stopped.document
    retired = tool({'action': 'execute', 'feature': 'retire',
                    'arguments': {'alias': target}})
    assert not retired.failed, retired.document
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))
    retained_mapping = Path(original['trace_file']).parent / 'runner/session.yml'
    assert yaml.safe_load(retained_mapping.read_text())['retirement']['mapping'] == original
    tool = bind(root, recovery_reviewer=lambda proposal: {'decision': 'accept'})
    role_change = {'change': {'set_presets': {
        'next-probe': {'runtime': 'codex', 'model': 'gpt-5.6'},
    }}}
    before_roles = (root / '.graphtraj/roles.yml').read_bytes()
    for source in ('unknown', {'subAgent': {'threadSpawn': {'parentThreadId': 'parent'}}}):
        (root / 'options.json').write_text(json.dumps({'source': source}))
        with pytest.raises(RunnerError):
            tool({'action': 'execute', 'feature': 'role_organization',
                  'arguments': role_change})
        assert (root / '.graphtraj/roles.yml').read_bytes() == before_roles
    (root / 'options.json').write_text(json.dumps({'source': 'vscode'}))
    organized = tool({'action': 'execute', 'feature': 'role_organization',
                      'arguments': role_change})
    assert not organized.failed and organized.document['applied'], organized.document
    with parent_connection(connection):
        dispatched = tool({'action': 'execute', 'feature': 'swarm',
                           'arguments': launch_document(role='other-probe')})
    assert not dispatched.failed, dispatched.document
    next_task = dispatched.document['tasks'][0]
    assert 'alias' in next_task, dispatched.document
    assert mapping(root, next_task['alias'])['parent_connection'] == connection
    assert historical.read_bytes() == retained

    # A real fork has no root owning connection even though its source is root-like.
    rollout(root, session='checker')
    assert 'recorded completion checker' in native_hook(root)['systemMessage']
    assert native_hook(root, 'SessionStart') == {}
    rollout(root, source={'subagent': {'thread_spawn': {'parent_thread_id': 'parent'}}})
    assert 'child Session' in native_hook(root)['systemMessage']
    rollout(root, source='vscode')
    monkeypatch.setenv('CODEX_HOME', str(root / 'other-home'))
    assert 'recorded completion checker' in native_hook(root)['systemMessage']
    assert historical.read_bytes() == retained


def test_stop_descendants_preserves_identity_and_prohibits_later_work(managed_project: ManagedProject) -> None:
    """An ancestor directly stops all generations and leaves another branch alone."""
    root, cause, call, _ = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    child = call('child', [parent, 'descendant@e1'])['alias']
    grandchild = call('child', [child, 'descendant@e2'])['alias']
    peer = call('launch', launch_document(role='other-probe'))['tasks'][0]['alias']
    before = {alias: mapping(root, alias) for alias in (parent, child, grandchild)}
    result = call('interrupt', [parent])
    assert result['interrupt_status'] == 'interrupted'
    assert {item['alias']: item['interrupt_status'] for item in result['members']} == {
        alias: 'interrupted' for alias in before
    }
    for alias in before:
        assert mapping(root, alias) == before[alias]
        observe(call, alias, 'idle', 'interrupted')
    observe(call, peer, 'running')
    denied = call('send', [parent, 'resume stopped entity', [cause]], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'
    denied = call('child', [grandchild, 'descendant@e3'], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'
    assert not (root / '.graphtraj/runner/sessions/descendant@e3/session.yml').exists()
    denied = call('resume-worker', [grandchild, grandchild], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'
    assert mapping(root, grandchild) == before[grandchild]


def test_unresponsive_parent_does_not_prevent_descendant_interrupt(managed_project: ManagedProject) -> None:
    """A live but unresponsive parent remains explicitly unconfirmed after child stops."""
    root, _, call, _ = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    child = call('child', [parent, 'descendant@e1'])['alias']
    owner = mapping(root, parent)
    os.kill(owner['worker_pid'], signal.SIGSTOP)
    try:
        result = call('interrupt', [parent], timeout=30)
        assert result['interrupt_status'] == 'incomplete'
        members = {item['alias']: item for item in result['members']}
        assert members[parent]['interrupt_status'] == 'unconfirmed'
        assert members[child]['interrupt_status'] == 'interrupted'
        observe(call, child, 'idle', 'interrupted')
        denied = call('child', [child, 'descendant@e2'], returncode=1)
        assert denied['error']['code'] == 'subtree-stopped'
    finally:
        os.kill(owner['worker_pid'], signal.SIGCONT)
    result = call('interrupt', [parent])
    assert result['interrupt_status'] == 'interrupted'


@pytest.mark.parametrize('owner', ['unrelated', 'target', 'missing'])
def test_interrupt_scopes_full_mapping_checks_to_descendants(
    managed_project: ManagedProject, owner: str,
) -> None:
    """Historical branches stay intact; real or unresolved descendants block confirmation."""
    root, _, call, _ = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    child = call('child', [parent, 'descendant@e1'])['alias']
    session_root = root / '.graphtraj/runner/sessions'
    retained_parent = 'main_retained@m1'
    retained_child = 'checker_retained@m1'
    child_parent = {'unrelated': retained_parent, 'target': parent,
                    'missing': 'missing_parent@m1'}[owner]
    retained = {}
    for alias, purpose, ancestor in (
        (retained_parent, 'main', None),
        (retained_child, 'checker', child_parent),
    ):
        directory = session_root / alias
        directory.mkdir()
        path = directory / 'mapping.yml'
        path.write_text(yaml.safe_dump({
            'alias': alias, 'purpose': purpose, 'parent': ancestor,
            'runtime': 'codex', 'hosted': True, 'role': purpose,
            'ticket_id': None, 'team_generation': None,
            'worktree_path': str(root), 'session': None,
            'worker_pid': 123, 'runtime_pid': 123,
        }))
        retained[path] = path.read_bytes()

    result = call('interrupt', [parent])
    members = {item['alias']: item['interrupt_status'] for item in result['members']}
    assert members[parent] == members[child] == 'interrupted'
    if owner == 'unrelated':
        assert result['interrupt_status'] == 'interrupted'
        assert set(members) == {parent, child}
    else:
        assert result['interrupt_status'] == 'incomplete'
        assert members[retained_child] == 'unconfirmed'
    assert retained_parent not in members
    assert all(path.read_bytes() == content for path, content in retained.items())
    observe(call, child, 'idle', 'interrupted')


def test_concurrent_resume_cannot_outlive_stop(managed_project: ManagedProject) -> None:
    """Whichever startup wins, the final stop includes it or refuses its launch."""
    root, cause, call, _ = managed_project
    alias = call('launch', launch_document())['tasks'][0]['alias']
    call('send', [alias, 'finish normally', [cause]])
    observe(call, alias, 'idle', 'completed')

    def resume() -> dict:
        """Accept either startup before stopping or an explicit stopped refusal."""
        try:
            return call('send', [alias, 'hold', [cause]])
        except AssertionError as error:
            assert 'subtree-stopped' in str(error)
            return {}

    with ThreadPoolExecutor() as pool:
        continuing = pool.submit(resume)
        stopped = pool.submit(call, 'interrupt', [alias])
        result = stopped.result()
        continuing.result()
    assert result['interrupt_status'] == 'interrupted'
    observe(call, alias, 'idle')
    denied = call('send', [alias, 'hold', [cause]], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'


def test_creation_and_resume_refused_while_stop_waits_for_native_ack(
    managed_project: ManagedProject, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop publication excludes work before the first native acknowledgement."""
    import threading
    from graphtraj.execution import runner_control

    root, cause, call, _ = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    child = call('child', [parent, 'descendant@e1'])['alias']
    published = threading.Event()
    release = threading.Event()
    native_operation = runner_control.session_operation

    def delayed_native_ack(record: dict, operation: str, **arguments: object) -> dict:
        """Pause delivery, then use the actual managed execution control channel."""
        if operation == 'interrupt':
            published.set()
            assert release.wait(15)
        return native_operation(record, operation, **arguments)

    monkeypatch.setattr(runner_control, 'session_operation', delayed_native_ack)
    with ThreadPoolExecutor() as pool:
        stopping = pool.submit(runner_control.interrupt_session, parent, root)
        try:
            assert published.wait(5)
            denied = call('child', [child, 'descendant@e2'], returncode=1)
            assert denied['error']['code'] == 'subtree-stopped'
            denied = call('send', [parent, 'continue despite stop', [cause]], returncode=1)
            assert denied['error']['code'] == 'subtree-stopped'
        finally:
            release.set()
        assert stopping.result()['interrupt_status'] == 'interrupted'
    observe(call, child, 'idle', 'interrupted')


@pytest.mark.skipif(os.environ.get('CODEX_MANAGED_REAL') != '1', reason='explicit real Codex boundary probe')
def test_real_native_subtree_stops_tool_writes(managed_project: ManagedProject) -> None:
    """Both real native Turns must stop writing before subtree confirmation returns."""
    import shutil
    import sys
    import time
    import tomllib
    from conftest import wait_for_file

    root, cause, call, executable = managed_project
    real = shutil.which('codex')
    assert real
    executable.unlink()
    executable.symlink_to(real)
    native_home = root / 'codex-home'
    native_home.mkdir()
    operator = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    for name in ('config.toml', 'auth.json'):
        if (operator / name).is_file():
            shutil.copy2(operator / name, native_home / name)
    config_file = native_home / 'config.toml'
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}

    def instruction(name: str) -> str:
        """Ask for a bounded foreground tool whose writes show real liveness."""
        return (
            'Run this exact shell command with a long tool wait, and keep waiting until it ends. '
            'Do not run other commands or finish early: '
            f'''{sys.executable} -c 'import time; from pathlib import Path; p=Path("{name}"); '''
            '''[(p.write_text(str(i)), time.sleep(0.1)) for i in range(1200)]' '''
        )

    document = launch_document(instruction('parent-writing'))
    preset = document['tasks'][0]['role']['managed-probe']
    preset['model'] = config.get('model', preset['model'])
    preset['reasoning_effort'] = config.get('model_reasoning_effort', preset['reasoning_effort'])
    parent = call('launch', document, timeout=30)['tasks'][0]['alias']
    child = call('child', [parent, 'native-descendant@e1', instruction('child-writing')], timeout=30)['alias']
    worktree = Path(mapping(root, parent)['worktree_path'])
    writes = [worktree / 'parent-writing', worktree / 'child-writing']
    for path in writes:
        wait_for_file(path, timeout=60)
    result = call('interrupt', [parent], timeout=30)
    assert result['interrupt_status'] == 'interrupted', result
    assert {member['alias'] for member in result['members']} == {parent, child}
    snapshot = [path.read_text() for path in writes]
    time.sleep(0.5)
    assert [path.read_text() for path in writes] == snapshot
    for alias in (parent, child):
        observe(call, alias, 'idle', 'interrupted')
    denied = call('send', [parent, 'continue writing', [cause]], returncode=1)
    assert denied['error']['code'] == 'subtree-stopped'


def test_stop_waits_for_child_already_entering_native_startup(
    managed_project: ManagedProject,
) -> None:
    """A child admitted before stopping must be recorded and stopped in the result."""
    import time
    from conftest import wait_for_file
    from graphtraj.execution.runner_control import interrupt_session

    root, _, call, executable = managed_project
    parent = call('launch', launch_document())['tasks'][0]['alias']
    script = executable.read_text()
    script = script.replace(
        "    emit({'id': request['id'], 'result': result})",
        "    if method == 'turn/start' and 'delayed-start' in params['input'][0]['text']:\n"
        "        gate = Path(os.environ['MANAGED_NATIVE_ROOT']) / 'startup-entered'\n"
        "        gate.touch()\n"
        "        while not gate.with_name('startup-release').exists():\n"
        "            time.sleep(0.01)\n"
        "    emit({'id': request['id'], 'result': result})",
    )
    executable.write_text(script)
    with ThreadPoolExecutor() as pool:
        starting = pool.submit(call, 'child', [parent, 'descendant@e1', 'delayed-start'])
        wait_for_file(root / 'native/startup-entered')
        stopping = pool.submit(interrupt_session, parent, root)
        try:
            time.sleep(0.1)
            assert not stopping.done(), 'An admitted child has not yet published its native execution'
        finally:
            (root / 'native/startup-release').touch()
        child = starting.result()['alias']
        result = stopping.result()
    assert result['interrupt_status'] == 'interrupted'
    assert {item['alias']: item['interrupt_status'] for item in result['members']} == {
        parent: 'interrupted', child: 'interrupted',
    }
    observe(call, child, 'idle', 'interrupted')
