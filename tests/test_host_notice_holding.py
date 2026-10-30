"""A notice its parent cannot receive now is held and arrives once at its next run (403).

Fake drivers report through the public ``ExecutionEvents``; the Claude and Codex
sections below use the controlled Runtimes. No network, no real model.
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable
from uuid import uuid4

import pytest

from agent_swarm import AgentControl, Caller, ExecutionEvents, Run, bind
from agent_swarm.calls import Call, current_call, on_discard, stop_requested
from agent_swarm.claude.host import IndependentCalls
from agent_swarm.codex.app_server import CodexAdapterError, CodexAppServer
from agent_swarm.codex.host import CodexHost
from agent_swarm.mcp import result_response, serve_concurrent
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_codex_host_cross_runtime import Running, events, host_settings, until  # noqa: F401
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture


MAIN = Caller('test-host', None, 'main-session', 'claude')


class Turn:
    """One running execution with a binding like the Claude and DSH ones."""

    def __init__(self, run: Run) -> None:
        """Start accepting input for ``run``."""
        self.run       = run
        self.accepting = True
        self.inbox: list[dict] = []

    def receive(self, event: dict) -> bool:
        """Take the notice into the turn, or continue the retained Session."""
        if self.accepting:
            self.inbox.append(event)
            return True
        return self.run.events.continue_from_child(event, self.run.archive)


class Driver:
    """Keeps every execution running until the test ends it."""

    def __init__(self) -> None:
        """Start with no execution."""
        self.turns: list[Turn] = []
        self.pending: dict[str, list[dict]] = {}

    def prepare(self, runtime: str, caller: Caller, **options: object) -> dict:
        """Nothing to retain."""
        return {}

    def start(self, run: Run) -> None:
        """Bind a receiver the way a Runtime binding does."""
        run.events.session('native-' + run.agent[-6:])
        turn = Turn(run)
        self.turns.append(turn)
        run.events.receive_children(turn.receive)

    def deliver(self, run: Run, message: str) -> None:
        """Accept input; these tests do not read it."""

    def interrupt(self, run: Run) -> bool:
        """End at once, as an interrupted turn eventually does."""
        self.of(run.agent).run.events.finished('interrupted', error={'code': 'stopped', 'message': 'stopped by host'})
        return True

    def requests(self, run: Run) -> list[dict]:
        """Return the native requests the test reported."""
        return self.pending.get(run.execution, [])

    def reply(self, run: Run, request: dict, response: dict) -> dict:
        """Acknowledge one answer."""
        return {'request_id': request.get('request_id'), 'reply_status': 'submitted'}

    def report(self, agent: str, details: dict) -> None:
        """Report one native request as pending."""
        run = self.of(agent).run
        self.pending.setdefault(run.execution, []).append(details)
        run.events.request(details)

    def of(self, agent: str) -> Turn:
        """Return the Agent's latest execution."""
        return self.all_of(agent)[-1]

    def all_of(self, agent: str) -> list[Turn]:
        """Return every execution of the Agent, oldest first."""
        return [turn for turn in self.turns if turn.run.agent == agent]


def control_over(root: Path, receiver: Callable | None = None) -> tuple[AgentControl, Driver]:
    """Build a holding control over ``root``; a new one stands for a new process."""
    driver = Driver()
    return AgentControl(root, {'fake': driver}, event_receiver=receiver, request_notices=True,
                        hold_notices=True), driver


def create(call: Callable, instruction: str = 'work') -> str:
    """Create one Agent and return its reference."""
    created = call({'action': 'create', 'runtime': 'fake', 'instruction': instruction})
    assert not created.failed, created.document
    return created.document['agent']


def last(call: Callable, agent: str) -> dict:
    """Return the Agent's public ``last_result``."""
    return call({'action': 'status', 'agent': agent}).document['result']['last_result']


def record(root: Path, agent: str) -> dict:
    """Read the Agent's durable record, as a new process would."""
    return json.loads((root / 'control' / 'agents' / f'{agent}.json').read_text())


def request_details(token: str = 'tok-1') -> dict:
    """Return one native request whose input must never reach a notice."""
    return {'request_token': token, 'request_id': 1, 'method': 'claude/can_use_tool',
            'params': {'tool_name': 'Bash', 'input': {'command': 'secret'}}}


@pytest.mark.parametrize('result', [False, 'held', 'raises'])
def test_a_root_end_the_host_cannot_take_is_held_and_survives_a_new_process(
        tmp_path: Path, result: object) -> None:
    """Refused, 'held' or raising: held, readable, and listed for the same caller once."""
    def receiver(notice: dict) -> object:
        """Answer as this case's host does."""
        if result == 'raises':
            raise OSError('host gone')
        return result

    control, driver = control_over(tmp_path, receiver)
    call = bind(control, MAIN)
    agent = create(call)
    driver.of(agent).run.events.finished('completed', last_message='answer')
    assert last(call, agent)['notification'] == 'held'
    assert last(call, agent)['last_message'] == 'answer'

    # Nothing in memory is needed: a new control over the same root sees it.
    again, _ = control_over(tmp_path)
    [notice] = again.held_notices(MAIN)
    execution = driver.of(agent).run.execution
    assert notice == {'parent': None, 'agent': agent, 'session': 'native-' + agent[-6:], 'execution': execution,
                      'body': 'answer', 'outcome': 'completed', 'error': None,
                      'creator': {'host': 'test-host', 'agent': None, 'session': 'main-session'}}
    assert again.held_notices(Caller('test-host', None, 'other-session', 'claude')) == []
    assert again.settle_notice(notice, 'delivered') is True
    assert again.held_notices(MAIN) == []
    assert again.settle_notice(notice, 'delivered') is False
    assert last(bind(again, MAIN), agent)['last_message'] is None


def test_default_control_writes_nothing_new(tmp_path: Path) -> None:
    """Without hold_notices a refused end is unavailable and no new field or value appears."""
    driver = Driver()
    control = AgentControl(tmp_path, {'fake': driver}, event_receiver=lambda notice: False, request_notices=True)
    call = bind(control, MAIN)
    agent = create(call)
    driver.of(agent).run.events.request(request_details())
    driver.of(agent).run.events.finished('completed', last_message='answer')
    [execution] = record(tmp_path, agent)['executions']
    assert execution['notification'] == 'unavailable'
    assert 'request_notices' not in execution
    assert control.held_notices(MAIN) == []
    # Children of an Agent reach the host's receiver as before, and an owner's death stays silent.
    assert set(execution) == {'id', 'operation', 'state', 'started_at', 'resumed_session', 'session', 'process',
                              'inputs', 'requests', 'replies', 'started', 'archive', 'ended_at', 'outcome',
                              'last_message', 'terminal_confirmed', 'error', 'notification'}


def test_a_receiver_can_still_deliver_while_holding_is_on(tmp_path: Path) -> None:
    """Holding changes only what cannot be delivered; a repeated end notifies nobody."""
    seen: list[dict] = []
    control, driver = control_over(tmp_path, lambda notice: seen.append(notice) or True)
    call = bind(control, MAIN)
    agent = create(call)
    events = driver.of(agent).run.events
    events.request(request_details())
    events.request(request_details())
    events.finished('completed', last_message='answer')
    events.finished('completed', last_message='answer')
    assert [notice['outcome'] for notice in seen] == ['request', 'completed']
    assert control.held_notices(MAIN) == []
    assert record(tmp_path, agent)['executions'][0]['request_notices'] == {'tok-1': 'delivered'}


def test_queueing_left_by_a_dead_process_is_listed_but_not_one_in_flight(tmp_path: Path) -> None:
    """A delivery in this process is not replayed; the same state from a dead one is."""
    entered, release = threading.Event(), threading.Event()

    def receiver(notice: dict) -> str:
        """Stay in flight until the test lets go."""
        entered.set()
        assert release.wait(5)
        return 'held'

    control, driver = control_over(tmp_path, receiver)
    call = bind(control, MAIN)
    agent = create(call)
    thread = threading.Thread(target=lambda: driver.of(agent).run.events.finished('completed', last_message='a'))
    thread.start()
    assert entered.wait(5)
    assert record(tmp_path, agent)['executions'][0]['notification'] == 'queueing'
    assert control.held_notices(MAIN) == []
    release.set()
    thread.join(5)

    document = record(tmp_path, agent)
    document['executions'][0]['notification'] = 'queueing'
    document['executions'][0]['process']['worker_pid'] = 2 ** 22 + 1
    (tmp_path / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps(document))
    assert [notice['agent'] for notice in control.held_notices(MAIN)] == [agent]


@pytest.mark.parametrize('legacy', ['queued', 'unavailable'])
def test_legacy_records_are_never_replayed(tmp_path: Path, legacy: str) -> None:
    """A record from before holding stays readable and is not pushed after an upgrade."""
    driver = Driver()
    old = AgentControl(tmp_path, {'fake': driver}, event_receiver=lambda notice: legacy)
    agent = create(bind(old, MAIN))
    driver.of(agent).run.events.finished('completed', last_message='answer')
    control, _ = control_over(tmp_path)
    assert record(tmp_path, agent)['executions'][0]['notification'] == ('queued' if legacy == 'queued' else 'unavailable')
    assert control.held_notices(MAIN) == []


def test_a_retired_agents_notices_are_excluded(tmp_path: Path) -> None:
    """A retired Agent neither lists nor keeps a notice open."""
    control, driver = control_over(tmp_path, lambda notice: False)
    call = bind(control, MAIN)
    agent = create(call)
    driver.of(agent).run.events.finished('completed', last_message='answer')
    [notice] = control.held_notices(MAIN)
    assert not call({'action': 'retire', 'agent': agent}).failed
    assert control.held_notices(MAIN) == []
    assert control.notice_open(notice) is False


def test_a_held_request_is_listed_only_while_it_waits(tmp_path: Path) -> None:
    """Answered or with its execution ended, a held request is withdrawn; the end covers it."""
    control, driver = control_over(tmp_path, lambda notice: False)
    call = bind(control, MAIN)
    agent = create(call)
    events = driver.of(agent).run.events
    driver.report(agent, request_details('tok-1'))
    driver.report(agent, request_details('tok-2'))
    held = control.held_notices(MAIN)
    assert [notice['request'] for notice in held] == ['tok-1', 'tok-2']
    assert held[0]['outcome'] == 'request' and 'secret' not in str(held[0])
    assert 'claude/can_use_tool for Bash' in held[0]['body'] and held[0]['error'] is None

    answer = {'action': 'reply', 'agent': agent, 'request': request_details('tok-1'), 'response': {'behavior': 'deny'}}
    assert not call(answer).failed
    assert [notice['request'] for notice in control.held_notices(MAIN)] == ['tok-2']
    assert control.notice_open(held[0]) is False and control.notice_open(held[1]) is True

    events.finished('completed', last_message='answer')
    assert [notice['outcome'] for notice in control.held_notices(MAIN)] == ['completed']
    assert control.notice_open(held[1]) is False


def test_settling_is_final_unless_reopened(tmp_path: Path) -> None:
    """Delivered or unconfirmed stays so; only a discarded result takes it back."""
    control, driver = control_over(tmp_path, lambda notice: False)
    call = bind(control, MAIN)
    agent = create(call)
    driver.of(agent).run.events.finished('completed', last_message='answer')
    [notice] = control.held_notices(MAIN)
    assert control.settle_notice(notice, 'held') is True
    assert control.settle_notice(notice, 'unconfirmed') is True
    assert control.settle_notice(notice, 'delivered') is False
    assert control.held_notices(MAIN) == []
    assert control.settle_notice(notice, 'held', reopen=True) is True
    assert control.held_notices(MAIN) == [notice]
    with pytest.raises(ValueError):
        control.settle_notice(notice, 'queued')


@pytest.mark.parametrize('form', ['direct', 'execute'])
def test_a_body_shown_by_status_or_wait_is_not_pushed_again(tmp_path: Path, form: str) -> None:
    """Either request form settles it; other features and failed lookups settle nothing."""
    def request(feature: str, **arguments: object) -> dict:
        """Spell one call in this case's request form."""
        return ({'action': feature, **arguments} if form == 'direct'
                else {'action': 'execute', 'feature': feature, 'arguments': arguments})

    control, driver = control_over(tmp_path, lambda notice: False)
    call = bind(control, MAIN)
    agent = create(call)
    driver.of(agent).run.events.finished('completed', last_message='answer')
    document = call({'action': 'status', 'agent': agent}).document
    assert control.settle_shown(request('resume', agent=agent), document) == []
    assert control.settle_shown(request('wait', agent=agent), {'error': {'code': 'not-found'}}) == []
    assert len(control.held_notices(MAIN)) == 1

    [settled] = control.settle_shown(request('wait', agent=agent), document)
    assert (settled['agent'], settled['body']) == (agent, 'answer')
    assert control.held_notices(MAIN) == []
    assert control.settle_shown(request('status', agent=agent), call({'action': 'status', 'agent': agent}).document) == []
    # A discarded result gives it back.
    assert control.settle_notice(settled, 'held', reopen=True) is True
    assert [notice['agent'] for notice in control.held_notices(MAIN)] == [agent]


def test_the_hierarchy_form_settles_only_what_is_addressed_to_the_reader(tmp_path: Path) -> None:
    """A Main reading a grandchild does not consume the notice its parent still needs."""
    control, driver = control_over(tmp_path, lambda notice: False)
    main = bind(control, MAIN)
    first, second = create(main), create(main)
    grandchild = create(driver.of(first).run.call)
    # The parent stopped taking input, so its child's end stays held for it.
    driver.of(first).accepting = False
    for agent in (second, grandchild):
        driver.of(agent).run.events.finished('completed', last_message='answer of ' + agent)
    assert last(main, grandchild)['notification'] == 'held'

    hierarchy = main({'action': 'status'}).document
    [settled] = control.settle_shown({'action': 'status'}, hierarchy)
    assert settled['agent'] == second
    assert record(tmp_path, grandchild)['executions'][-1]['notification'] == 'held'

    # Its true parent reading the same body does consume it, through its own call.
    assert not driver.of(first).run.call({'action': 'status', 'agent': grandchild}).failed
    assert record(tmp_path, grandchild)['executions'][-1]['notification'] == 'delivered'


def test_a_standby_parents_request_is_held_without_starting_it(tmp_path: Path) -> None:
    """Delivered once on its next run, not lost and not a reason to start."""
    host: list[dict] = []
    control, driver = control_over(tmp_path, lambda notice: host.append(notice) or False)
    main = bind(control, MAIN)
    parent = create(main)
    grandchild = create(driver.of(parent).run.call)
    driver.of(parent).accepting = False
    driver.of(parent).run.events.finished('completed', last_message='standing by')
    assert len(driver.all_of(parent)) == 1

    driver.of(grandchild).run.events.request(request_details())
    assert len(driver.all_of(parent)) == 1
    assert record(tmp_path, grandchild)['executions'][-1]['request_notices'] == {'tok-1': 'held'}

    assert not main({'action': 'resume', 'agent': parent, 'message': 'go on'}).failed
    [notice] = driver.of(parent).inbox
    assert (notice['agent'], notice['outcome'], notice['request']) == (grandchild, 'request', 'tok-1')
    assert record(tmp_path, grandchild)['executions'][-1]['request_notices'] == {'tok-1': 'delivered'}

    # The next run has nothing left to hand over.
    driver.of(parent).run.events.finished('completed', last_message='done')
    assert not main({'action': 'send', 'agent': parent, 'message': 'again'}).failed
    assert driver.of(parent).inbox == []
    assert [notice for notice in host if notice['parent'] is not None] == []


def test_a_parent_with_no_receiver_gets_its_childrens_notices_at_its_next_run(tmp_path: Path) -> None:
    """After a host restart ends and requests stay in core, away from the host's root receiver."""
    host: list[dict] = []
    control, driver = control_over(tmp_path, lambda notice: host.append(notice) or True)
    main = bind(control, MAIN)
    parent = create(main)
    done, asking = create(driver.of(parent).run.call), create(driver.of(parent).run.call)
    driver.of(parent).run.events.finished('completed', last_message='standing by')
    host.clear()

    # A new process over the same root: no receiver is bound for the parent.
    restarted, _ = control_over(tmp_path, lambda notice: host.append(notice) or True)
    restarted.drivers['fake'] = driver
    ExecutionEvents(restarted, done, driver.of(done).run.execution).finished('completed', last_message='child answer')
    ExecutionEvents(restarted, asking, driver.of(asking).run.execution).request(request_details())
    assert host == []
    assert record(tmp_path, done)['executions'][-1]['notification'] == 'held'
    assert last(bind(restarted, MAIN), done)['last_message'] == 'child answer'

    assert not bind(restarted, MAIN)({'action': 'resume', 'agent': parent, 'message': 'go on'}).failed
    received = driver.of(parent).inbox
    assert sorted(notice['outcome'] for notice in received) == ['completed', 'request']
    assert [notice['body'] for notice in received if notice['agent'] == done] == ['child answer']
    assert record(tmp_path, done)['executions'][-1]['notification'] == 'delivered'
    assert host == []
    assert restarted.held_notices(Caller('test', parent)) == []


def test_an_end_reaching_a_stopping_parent_continues_it_once(tmp_path: Path) -> None:
    """Accepting no input but still running: held, then one continuation when it finishes."""
    control, driver = control_over(tmp_path, lambda notice: True)
    main = bind(control, MAIN)
    parent = create(main)
    turn = driver.of(parent)
    grandchild = create(turn.run.call)
    other = create(turn.run.call)

    turn.accepting = False
    driver.of(grandchild).run.events.finished('completed', last_message='late answer')
    assert record(tmp_path, grandchild)['executions'][-1]['notification'] == 'held'
    assert len(driver.all_of(parent)) == 1

    # The other child still runs, so this completed round is recorded, not pushed.
    turn.run.events.finished('completed', last_message='my own answer')
    [_, continued] = driver.all_of(parent)
    assert continued.run.settings['completion_message']['body'] == 'late answer'
    assert record(tmp_path, grandchild)['executions'][-1]['notification'] == 'delivered'
    assert continued.inbox == []

    # Ending again finds nothing held, so nothing continues it a second time.
    driver.of(other).run.events.finished('completed', last_message='other answer')
    assert [notice['body'] for notice in continued.inbox] == ['other answer']
    continued.run.events.finished('completed', last_message='final')
    assert len(driver.all_of(parent)) == 2


@pytest.mark.parametrize('reason', ['retired', 'failed', 'bodyless'])
def test_no_continuation_when_the_parent_has_reasons_not_to(tmp_path: Path, reason: str) -> None:
    """A retired or failed parent, or an end without a reply, is not continued; it stays held."""
    control, driver = control_over(tmp_path, lambda notice: True)
    main = bind(control, MAIN)
    parent = create(main)
    turn = driver.of(parent)
    grandchild = create(turn.run.call)
    turn.accepting = False
    ending = driver.of(grandchild).run.events
    if reason == 'retired':
        turn.run.events.finished('completed', last_message='own')
        assert not main({'action': 'retire', 'agent': parent}).failed
    ending.finished('interrupted' if reason == 'bodyless' else 'completed',
                    last_message=None if reason == 'bodyless' else 'answer')
    if reason != 'retired':
        turn.run.events.finished('failed' if reason == 'failed' else 'completed', last_message='own')
    assert len(driver.all_of(parent)) == 1
    assert record(tmp_path, grandchild)['executions'][-1]['notification'] == 'held'

    if reason != 'retired':
        assert not main({'action': 'resume', 'agent': parent, 'message': 'go on'}).failed
        [notice] = driver.of(parent).inbox
        assert notice['body'] == ('interrupted' if reason == 'bodyless' else 'answer')


def test_host_shutdown_holds_the_ends_it_causes_in_one_write(tmp_path: Path) -> None:
    """Interrupted at shutdown: no receiver runs, no parent restarts, and nothing is in flight."""
    seen: list[dict] = []
    control, driver = control_over(tmp_path, lambda notice: seen.append(notice) or True)
    main = bind(control, MAIN)
    parent = create(main)
    grandchild = create(driver.of(parent).run.call)
    driver.of(parent).run.events.finished('completed', last_message='standing by')
    seen.clear()
    assert sorted(control.interrupt_owned()) == sorted([grandchild])
    assert seen == [] and len(driver.all_of(parent)) == 1
    [execution] = record(tmp_path, grandchild)['executions']
    assert (execution['state'], execution['notification']) == ('ended', 'held')


def test_an_owner_that_died_leaves_a_held_end(tmp_path: Path) -> None:
    """A process killed before any report: the reconciled failure still reaches the parent."""
    control, driver = control_over(tmp_path)
    agent = create(bind(control, MAIN))
    document = record(tmp_path, agent)
    document['executions'][0]['process'] = {'worker_pid': 2 ** 22 + 1}
    (tmp_path / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps(document))
    [notice] = control_over(tmp_path)[0].held_notices(MAIN)
    assert (notice['outcome'], notice['error']['code']) == ('failed', 'owner-exited')


# -- Claude Code host: a real IndependentCalls per "process", a controlled Codex child ------


def stop_host(host) -> None:
    """Do what the Claude host's ``main`` does on its way out."""
    for agent in host.control.interrupt_owned():
        deadline = time.monotonic() + 10
        while host.control.owns_running(agent):
            assert time.monotonic() < deadline
            time.sleep(0.01)


def claude_main(tmp_path: Path, native_settings: dict, session: str | None = None) -> tuple:
    """One host process serving one verified Main Session: host, its tool and the Session."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'codex': native_settings})
    session = session or str(uuid4())
    run = host.make_call(session, tmp_path)

    def invoke(feature: str | None = None, **arguments: object) -> dict:
        """Call the tool as the Main does; no feature means ``discover``."""
        request = ({'action': 'discover'} if feature is None
                   else {'action': 'execute', 'feature': feature, 'arguments': arguments})
        result = run('agents', request)
        assert not result.failed, result.document
        return result.document

    return host, invoke, session


def interrupted_child(tmp_path: Path, native_settings: dict) -> tuple[str, str, str]:
    """A Main creates a long child and exits, which interrupts it. Returns agent, session, notice id."""
    host, invoke, session = claude_main(tmp_path, native_settings)
    created = invoke('create', runtime='codex', instruction='hold')
    stop_host(host)
    # Written before the host could exit: the wait above ends at the same write.
    [execution] = record(tmp_path / 'agents', created['agent'])['executions']
    assert (execution['outcome'], execution['notification']) == ('interrupted', 'held')
    return created['agent'], session, f"{execution['id']}:interrupted"


def test_claude_a_child_stopped_with_the_host_reaches_the_next_run_once(tmp_path: Path, native_settings: dict) -> None:
    """Print mode's claim: the next result of the same Session carries it, then nothing does."""
    agent, session, identity = interrupted_child(tmp_path, native_settings)
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    [notice] = invoke()['main_notices']
    assert notice['id'] == identity
    assert (notice['event']['alias'], notice['event']['event']) == (agent, 'interrupted')
    assert 'main_notices' not in invoke()
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []

    # Another run of the Session, in another process, finds nothing to repeat.
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    assert 'main_notices' not in invoke()
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    assert invoke('status', agent=agent)['result']['last_result']['notification'] == 'delivered'


def test_claude_another_session_does_not_receive_it(tmp_path: Path, native_settings: dict) -> None:
    """Held for the Session that created the child, not for the next one that binds."""
    _, session, _ = interrupted_child(tmp_path, native_settings)
    host, invoke, other = claude_main(tmp_path, native_settings)
    assert 'main_notices' not in invoke()
    assert host.context({'operation': 'notices', 'session': other})['notices'] == []


def test_claude_the_mods_push_settles_on_acknowledge_only(tmp_path: Path, native_settings: dict) -> None:
    """Claimed and submitted but not acknowledged is a duplicate at worst, never a loss."""
    agent, session, identity = interrupted_child(tmp_path, native_settings)
    host, _, _ = claude_main(tmp_path, native_settings, session)
    [notice] = host.context({'operation': 'notices', 'session': session})['notices']
    assert notice['id'] == identity
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []

    # The process died between submit and acknowledge: the next one offers it again.
    host, _, _ = claude_main(tmp_path, native_settings, session)
    [again] = host.context({'operation': 'notices', 'session': session})['notices']
    assert again['id'] == identity
    assert host.context({'operation': 'acknowledge', 'session': session, 'position': 0,
                         'ids': [identity, 'unknown:completed']}) == {'acknowledged': True}
    assert record(tmp_path / 'agents', agent)['executions'][-1]['notification'] == 'delivered'

    host, _, _ = claude_main(tmp_path, native_settings, session)
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []


def test_claude_requeue_after_a_failed_submit_keeps_it_for_the_next_claim(tmp_path: Path, native_settings: dict) -> None:
    """A failed submission gives it back, still held."""
    agent, session, identity = interrupted_child(tmp_path, native_settings)
    host, _, _ = claude_main(tmp_path, native_settings, session)
    host.context({'operation': 'notices', 'session': session})
    host.context({'operation': 'requeue', 'session': session, 'ids': [identity]})
    assert record(tmp_path / 'agents', agent)['executions'][-1]['notification'] == 'held'
    [again] = host.context({'operation': 'notices', 'session': session})['notices']
    assert again['id'] == identity


def test_claude_a_body_read_by_status_is_not_pushed(tmp_path: Path, native_settings: dict) -> None:
    """Single and hierarchy forms alike; a later run has nothing either."""
    agent, session, _ = interrupted_child(tmp_path, native_settings)
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    shown = invoke('status')
    assert [node['last_result']['notification'] for node in shown['result']['agents']] == ['held']
    assert 'main_notices' not in shown
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    assert record(tmp_path / 'agents', agent)['executions'][-1]['notification'] == 'delivered'
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    assert 'main_notices' not in invoke()


def test_claude_a_discarded_result_gives_its_notices_back(tmp_path: Path, native_settings: dict) -> None:
    """Handed over, then never read: held again and carried by the next result, once."""
    agent, session, identity = interrupted_child(tmp_path, native_settings)
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    cancelled = Call()
    with current_call(cancelled):
        assert [notice['id'] for notice in invoke()['main_notices']] == [identity]
    assert record(tmp_path / 'agents', agent)['executions'][-1]['notification'] == 'delivered'
    for discard in cancelled.discards:
        discard()
    assert record(tmp_path / 'agents', agent)['executions'][-1]['notification'] == 'held'
    assert [notice['id'] for notice in invoke()['main_notices']] == [identity]
    assert 'main_notices' not in invoke()


def test_claude_a_discarded_status_gives_the_shown_end_back(tmp_path: Path, native_settings: dict) -> None:
    """A status nobody read showed nothing."""
    agent, session, identity = interrupted_child(tmp_path, native_settings)
    host, invoke, _ = claude_main(tmp_path, native_settings, session)
    cancelled = Call()
    with current_call(cancelled):
        invoke('status', agent=agent)
    for discard in cancelled.discards:
        discard()
    assert [notice['id'] for notice in invoke()['main_notices']] == [identity]


def test_claude_a_live_end_for_an_unbound_session_is_held_not_refused(tmp_path: Path, native_settings: dict) -> None:
    """A child outliving its Main's binding: held for that Session, queued once when it binds."""
    host, _, session = claude_main(tmp_path, native_settings)
    notice = {'parent': None, 'agent': 'a', 'session': 's', 'execution': 'e', 'body': 'b', 'outcome': 'completed',
              'creator': {'host': 'claude-native', 'agent': None, 'session': str(uuid4())}, 'error': None}
    assert host.receive(notice) == 'held'
    assert notice['creator']['session'] not in host.queue
    notice['creator']['session'] = session
    assert host.receive(notice) == 'held'
    assert host.receive(notice) == 'held'
    assert [item['id'] for item in host.queue[session]] == ['e:completed']


def test_claude_a_request_answered_before_the_claim_is_dropped(tmp_path: Path, native_settings: dict) -> None:
    """The notice would ask for a reply already given. Through the bound tool, so no result claims it first."""
    host, _, session = claude_main(tmp_path, native_settings)
    call = host.callers[session]
    agent = call({'action': 'create', 'runtime': 'codex',
                  'instruction': 'request:item/commandExecution/requestApproval'}).document['agent']
    [request] = until(lambda: call({'action': 'requests', 'agent': agent}).document.get('result', {}).get('requests'))
    until(lambda: any(notice['event']['event'] == 'request' for notice in host.queue.get(session, [])))
    assert not call({'action': 'reply', 'agent': agent, 'request': request, 'response': {'decision': 'accept'}}).failed
    assert all(notice['event']['event'] != 'request'
               for notice in host.context({'operation': 'notices', 'session': session})['notices'])
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    stop_host(host)


def test_a_result_sent_to_a_client_already_gone_gives_its_notices_back() -> None:
    """A Main that exited mid-call never read it, so what it carried is not delivered."""
    undone: list[bool] = []

    def responder(message: dict) -> dict:
        """Hand something over, finishing only after the client's input has ended."""
        on_discard(lambda: undone.append(True))
        while not stop_requested():
            time.sleep(0.01)
        return result_response(message['id'], {})

    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'agents', 'arguments': {}}}
    serve_concurrent(io.StringIO(json.dumps(request) + '\n'), io.StringIO(), responder)
    assert undone == [True]


def test_the_mod_acknowledges_a_submission_and_survives_its_failure(tmp_path: Path) -> None:
    """A failed acknowledgement neither requeues nor submits a second prompt."""
    module = tmp_path / 'host_context.mjs'
    module.write_text(Path('src/agent_swarm/claude/host_context.mjs').read_text())
    program = r'''
import assert from 'node:assert/strict';
const {register} = await import(process.argv[1]);
const handlers = new Map();
register((name, matcher, fn) => {handlers.set(fn && matcher.tool ? `${name}:${matcher.tool}` : name, fn ?? matcher); return {catch() {}};});
const operations = [], submitted = [], timers = [];
const pending = [{id: 'e1:completed', event: {alias: 'a', event: 'completed', message: 'done'}}];
const host = {
 session: {id: async () => 'main-session', cwd: async () => '/p'},
 command: {register: async () => {}},
 env: {get: async key => key.endsWith('PYTHON') ? '/venv/python' : '/host/config'},
 process: {run: async (argv, options) => {
   const document = JSON.parse(options.stdin);
   operations.push(document.operation);
   if (document.operation === 'acknowledge') return {exitCode: 1, stdout: '', stderr: 'host gone'};
   return {exitCode: 0, stdout: JSON.stringify({notices: pending.splice(0), position: 0}), stderr: ''};
 }},
 prompt: {submit: async input => { submitted.push(input.text); }},
 clock: {setTimeout: fn => timers.push(fn)},
 ui: {log: () => {}},
};
await handlers.get('session.start')(host, {}, async () => 'started');
await timers.shift()();
await timers.shift()();
assert.equal(submitted.length, 1);
assert.deepEqual(operations, ['notices', 'acknowledge', 'notices']);
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program, module.as_uri()],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


# -- Codex host: a real CodexHost per "process" over the controlled stdio peer ---------------


def codex_child_stopped_with_the_host(tmp_path: Path, host_settings: dict, log: Path) -> tuple[str, str]:
    """A parent creates a long child and its turn ends, which interrupts it."""
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold'))
    agent = running.call('create', runtime='codex', instruction='hold')['agent']
    running.stop()
    # Read at once: run() may not return before this is on disk.
    [execution] = record(tmp_path / 'host', agent)['executions']
    assert (execution['outcome'], execution['notification']) == ('interrupted', 'held')
    assert events(log) == []
    return agent, f"{execution['id']}:interrupted"


def test_codex_a_child_stopped_with_the_host_reaches_the_next_resume_once(
        tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """One host event on the resume, in deliveries too; a further resume sends nothing."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    agent, identity = codex_child_stopped_with_the_host(tmp_path, host_settings, log)

    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    [event] = until(lambda: events(log))
    assert (event['alias'], event['event']) == (agent, 'interrupted')
    assert until(lambda: running.call('status', agent=agent)['result']['last_result']['notification'] == 'delivered')
    first = running.stop()
    assert [delivery['id'] for delivery in first['deliveries']] == [identity]

    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    time.sleep(0.2)
    second = running.stop()
    assert second['deliveries'] == [] and len(events(log)) == 1


def test_codex_a_flush_that_cannot_write_leaves_it_held(
        tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unwritten: held for the next resume. Written and unacknowledged: unconfirmed, not repeated."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    agent, _ = codex_child_stopped_with_the_host(tmp_path, host_settings, log)
    original = CodexAppServer.send_host_event
    written = False

    async def refused(self: CodexAppServer, thread_id: str, event: dict) -> None:
        """Fail as this stage of the case does."""
        error = CodexAdapterError('RUNTIME_CONNECTION_FAILED', 'closed', terminal_confirmed=False)
        error.request_written = written
        raise error

    monkeypatch.setattr(CodexAppServer, 'send_host_event', refused)
    state = lambda: record(tmp_path / 'host', agent)['executions'][-1]['notification']
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    time.sleep(0.2)
    running.stop()
    assert state() == 'held'

    written = True
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    assert until(lambda: state() == 'unconfirmed')
    running.stop()

    monkeypatch.setattr(CodexAppServer, 'send_host_event', original)
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    time.sleep(0.2)
    assert running.stop()['deliveries'] == []
    assert events(log) == []


def test_codex_a_turn_that_closes_mid_flush_finishes_it_first(
        tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The connection stays open for a send already under way, so its result is recorded."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    agent, _ = codex_child_stopped_with_the_host(tmp_path, host_settings, log)
    original = CodexAppServer.send_host_event
    entered = threading.Event()

    async def slow(self: CodexAppServer, thread_id: str, event: dict) -> dict:
        """Be under way while the turn closes."""
        entered.set()
        await asyncio.sleep(0.3)
        return await original(self, thread_id, event)

    monkeypatch.setattr(CodexAppServer, 'send_host_event', slow)
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    assert entered.wait(10)
    running.stop()
    assert record(tmp_path / 'host', agent)['executions'][-1]['notification'] == 'delivered'
    assert len(events(log)) == 1


def test_codex_a_failed_live_send_is_held_and_status_settles_it(
        tmp_path: Path, host_settings: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live end that could not be written is readable, and reading it ends the notice."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    original = CodexAppServer.send_host_event

    async def refused(self: CodexAppServer, thread_id: str, event: dict) -> None:
        """Fail before anything is written."""
        raise CodexAdapterError('RUNTIME_CONNECTION_FAILED', 'closed', terminal_confirmed=False)

    monkeypatch.setattr(CodexAppServer, 'send_host_event', refused)
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold'))
    agent = running.call('create', runtime='codex', instruction='hello')['agent']
    until(lambda: record(tmp_path / 'host', agent)['executions'][-1].get('notification') == 'held')
    shown = running.call('status', agent=agent)['result']['last_result']
    assert (shown['notification'], shown['last_message']) == ('held', 'hello')
    assert record(tmp_path / 'host', agent)['executions'][-1]['notification'] == 'delivered'
    running.stop()

    monkeypatch.setattr(CodexAppServer, 'send_host_event', original)
    running = Running(CodexHost(host_settings, tmp_path / 'host', 'hold', resume=True))
    time.sleep(0.2)
    assert running.stop()['deliveries'] == [] and events(log) == []


def test_codex_a_turn_that_has_ended_holds_a_live_end(tmp_path: Path, host_settings: dict) -> None:
    """Between a parent's turn and its exit the receiver refuses nothing it could lose."""
    host = CodexHost(host_settings, tmp_path / 'host', 'hold')
    notice = {'parent': None, 'agent': 'a', 'session': 's', 'execution': 'e', 'body': 'b', 'outcome': 'completed'}
    assert host._receive_child(notice) == 'held'
    host.native_session, host.loop, host.outcome = 'parent', asyncio.new_event_loop(), {'outcome': 'completed'}
    try:
        assert host._receive_child(notice) == 'held'
    finally:
        host.loop.close()
    assert host._receive_child({**notice, 'parent': 'agent-a'}) is False
