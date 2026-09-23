"""Subtree stopping through public control and the common managed Worker boundary."""

import os
import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from test_managed_sessions import ManagedProject, launch_document, managed_project, observe


def mapping(root: Path, alias: str) -> dict:
    """Read identity retained by a managed Worker in the isolated test project."""
    return yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())


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
