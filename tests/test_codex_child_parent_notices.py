"""A Codex child that is itself a parent gets its children's ends and requests (403).

Codex children run the controlled stdio peer, Claude grandchildren the controlled
CLI, under a real CodexHost. The peer ends a held turn with the text steered into
it, so a steered notice shows as that turn's last message. No network, no real model.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.driver import CodexDriver
from agent_swarm.codex.host import CodexHost
from agent_swarm.codex.managed_session import CodexManagedExecution
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_codex_host_cross_runtime import Running, host_settings, until  # noqa: F401
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture

APPROVAL = 'request:item/commandExecution/requestApproval'


class Tree:
    """A host, its Codex child acting as parent, and that child's own tool."""

    def __init__(self, tmp_path: Path, settings: dict, instruction: str = 'hold') -> None:
        self.running = Running(CodexHost(settings, tmp_path / 'host', 'hold'))
        created = self.running.call('create', runtime='codex', instruction=instruction)
        self.child, session = created['agent'], created['session']
        self.call = bind(self.running.host.control, Caller('codex', self.child, session, 'codex'))

    def create(self, runtime: str, instruction: str) -> str:
        """Create one grandchild through the child's own identity."""
        created = self.call({'action': 'create', 'runtime': runtime, 'instruction': instruction})
        assert not created.failed, created.document
        return created.document['agent']

    def status(self, agent: str) -> dict:
        return self.running.call('status', agent=agent)['result']

    def standby(self, agent: str) -> dict:
        return until(lambda: (lambda result: result if result['state'] == 'standby' else None)(self.status(agent)))

    def executions(self) -> list[dict]:
        with self.running.host.control._locked(self.child) as record:
            return list(record['executions'])


@pytest.mark.parametrize('runtime', ['codex', 'claude'])
def test_a_running_codex_parent_takes_its_childs_end_into_the_turn(
        tmp_path: Path, host_settings: dict, runtime: str) -> None:
    """Steered with the Claude child's framing, once; the root parent hears only of its own child."""
    tree = Tree(tmp_path, host_settings)
    try:
        grandchild = tree.create(runtime, 'hello')
        parent = tree.standby(tree.child)
        assert len(tree.executions()) == 1
        assert tree.executions()[0]['last_message'] == f'[agents · {grandchild} → {tree.child}]\nhello'
        assert tree.status(grandchild)['last_result']['notification'] == 'delivered'
        assert parent['state'] == 'standby'
    finally:
        tree.running.stop()


def test_a_standby_codex_parent_is_continued_with_its_childs_answer(tmp_path: Path, host_settings: dict) -> None:
    """Closed input falls through to one continued turn in the same Session, with the notice as its prompt."""
    tree = Tree(tmp_path, host_settings)
    try:
        grandchild = tree.create('codex', 'hold')
        assert not tree.running.call('send', agent=tree.child, message='first answer')['result'].get('error')
        tree.standby(tree.child)
        assert not tree.running.call('send', agent=grandchild, message='late answer')['result'].get('error')
        until(lambda: len(tree.executions()) == 2 and tree.executions()[1]['state'] == 'ended')
        first, second = tree.executions()
        assert second['last_message'] == f'[agents · {grandchild} → {tree.child}]\nlate answer'
        assert second['session'] == first['session'] and second['operation'] == 'receive'
        assert tree.status(grandchild)['last_result']['notification'] == 'delivered'
        tree.standby(tree.child)
        assert len(tree.executions()) == 2
    finally:
        tree.running.stop()


@pytest.mark.parametrize('runtime', ['codex', 'claude'])
def test_a_running_codex_parent_is_told_of_a_childs_request_once(
        tmp_path: Path, host_settings: dict, runtime: str) -> None:
    """The notice names the request and asks for reply; it answers nothing."""
    tree = Tree(tmp_path, host_settings)
    instruction = APPROVAL if runtime == 'codex' else 'permission'
    try:
        grandchild = tree.create(runtime, instruction)
        tree.standby(tree.child)
        [first] = tree.executions()
        assert first['last_message'].startswith(f'[agents · {grandchild} → {tree.child}]\nPermission request ')
        assert first['last_message'].endswith('answer once with reply.')
        assert tree.status(grandchild)['pending_requests'] == 1
    finally:
        tree.running.stop()


def test_a_standby_codex_parents_request_is_held_and_arrives_when_it_resumes(
        tmp_path: Path, host_settings: dict) -> None:
    """Not started for it; taken into the resumed turn once, and not again after that."""
    tree = Tree(tmp_path, host_settings)
    try:
        assert not tree.running.call('send', agent=tree.child, message='done for now')['result'].get('error')
        tree.standby(tree.child)
        grandchild = tree.create('codex', APPROVAL)
        until(lambda: tree.status(grandchild).get('pending_requests'))
        with tree.running.host.control._locked(grandchild) as record:
            [state] = record['executions'][-1]['request_notices'].values()
        assert state == 'held' and len(tree.executions()) == 1

        tree.running.call('resume', agent=tree.child, message='hold')
        tree.standby(tree.child)
        steered = tree.executions()[1]['last_message']
        assert steered.startswith(f'[agents · {grandchild} → {tree.child}]\nPermission request ')
        with tree.running.host.control._locked(grandchild) as record:
            assert list(record['executions'][-1]['request_notices'].values()) == ['delivered']

        tree.running.call('resume', agent=tree.child, message='ordinary work')
        tree.standby(tree.child)
        assert tree.executions()[2]['last_message'] == 'ordinary work'
    finally:
        tree.running.stop()


def test_a_codex_parents_held_end_is_delivered_across_a_host_restart(tmp_path: Path, host_settings: dict) -> None:
    """Parent and child stop with the host; the end reaches the parent when it next runs, once."""
    tree = Tree(tmp_path, host_settings)
    grandchild = tree.create('codex', 'hold')
    tree.running.stop()
    control_before = tree.running.host.control
    with control_before._locked(grandchild) as record:
        assert record['executions'][-1]['notification'] == 'held'

    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    try:
        running.call('resume', agent=tree.child, message='hold')
        def steered() -> str | None:
            with running.host.control._locked(tree.child) as record:
                last = record['executions'][-1]
                return last.get('last_message') if last['state'] == 'ended' else None
        assert until(steered) == f'[agents · {grandchild} → {tree.child}]\ninterrupted'
        with running.host.control._locked(grandchild) as record:
            assert record['executions'][-1]['notification'] == 'delivered'
        running.call('resume', agent=tree.child, message='ordinary work')
        assert until(lambda: steered() == 'ordinary work')
    finally:
        running.stop()


def test_a_consumers_execution_keeps_its_own_route(tmp_path: Path, native_settings: dict) -> None:
    """GraphTraj's Codex members bring a subclass: no receiver is registered for them."""
    class Member(CodexManagedExecution):
        def __init__(self, *arguments, independent: bool, **options) -> None:
            super().__init__(*arguments, **options)

    control = AgentControl(tmp_path / 'agents', {'codex': CodexDriver(native_settings, execution=Member)})
    call = bind(control, Caller('host', None, 'parent-session', 'codex'))
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hold'})
    assert not created.failed, created.document
    try:
        assert control._receivers == {}
    finally:
        control.interrupt_owned()
