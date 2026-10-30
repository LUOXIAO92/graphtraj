"""A Pi child that is itself a parent gets its children's ends and requests (410).

The real PiDriver and PiExecution run against the controlled Pi peer
(pi_rpc_fixture.py), whose input log shows each user message when Pi takes it.
A ``wait-take`` turn takes steered input at once; any other ``wait`` turn only
at its end, so a stop before that drops it. No network, no real Pi, no real model.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys

import pytest

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.codex.host import CodexHost
from agent_swarm.dsh import host as dsh_host
from agent_swarm.pi import execution, host as pi_host
from agent_swarm.pi.driver import PiDriver
from test_codex_host_cross_runtime import Running, until
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture
from test_hosts_pi_children import ENTRY, ClaudeMain, CodexMain, codex_settings, install_node, project  # noqa: F401
from test_pi_generic_execution import generic
from test_pi_runtime import pi_environment  # noqa: F401 - pytest fixture

PERMISSION = 'Permission request pi/confirm waits for your reply. Read it with requests and answer once with reply.'


class Tree:
    """A root caller, its Pi child acting as parent, and that child's own tool."""

    def __init__(self, tmp_path: Path, environment: dict, monkeypatch: pytest.MonkeyPatch,
                 instruction: str = 'wait-take') -> None:
        """Start the host control and the child."""
        self.tmp_path = tmp_path
        self.request = generic(tmp_path, environment)
        self.log = tmp_path / 'pi-input.jsonl'
        monkeypatch.setenv('PI_FIXTURE_INPUT_LOG', str(self.log))
        monkeypatch.setenv('PI_FIXTURE_HELD_SECONDS', '60')
        self.host()
        created = self.call({'action': 'create', 'runtime': 'pi', 'instruction': instruction}).document
        self.parent, self.session = created['agent'], created['session']
        self.tool = bind(self.control, Caller('pi', self.parent, self.session, 'pi'))

    def host(self) -> None:
        """One host process's control over the same data root."""
        self.control = AgentControl(self.tmp_path / 'data', {'pi': PiDriver(self.request)},
                                    request_notices=True, hold_notices=True)
        self.call = bind(self.control, Caller('standalone-host', None))
        if hasattr(self, 'parent'):
            self.tool = bind(self.control, Caller('pi', self.parent, self.session, 'pi'))

    def child(self, instruction: str) -> str:
        """Create one grandchild through the child's own identity."""
        created = self.tool({'action': 'create', 'runtime': 'pi', 'instruction': instruction})
        assert not created.failed, created.document
        return created.document['agent']

    def record(self, agent: str) -> dict:
        """Read one Agent's durable record."""
        return json.loads((self.tmp_path / 'data' / 'control' / 'agents' / f'{agent}.json').read_text())

    def executions(self) -> list[dict]:
        """Return the parent's executions, oldest first."""
        return self.record(self.parent)['executions']

    def end_state(self, agent: str) -> str | None:
        """The delivery state of the Agent's last end."""
        return self.record(agent)['executions'][-1].get('notification')

    def request_states(self, agent: str) -> list[str]:
        """The delivery states of the requests of the Agent's last execution."""
        return list(self.record(agent)['executions'][-1].get('request_notices', {}).values())

    def ended(self, agent: str) -> dict:
        """Wait until the Agent has no running execution; return its last."""
        until(lambda: self.record(agent)['executions'][-1]['state'] == 'ended')
        return self.record(agent)['executions'][-1]

    def send(self, agent: str, message: str) -> None:
        """Send as the root, once the Agent has accepted its first prompt."""
        until(lambda: not self.call({'action': 'send', 'agent': agent, 'message': message}).failed)

    def resume(self, instruction: str = 'wait-take') -> None:
        """Resume the standby parent; its held notices are flushed before this returns."""
        result = self.call({'action': 'resume', 'agent': self.parent, 'message': instruction})
        assert not result.failed, result.document

    def stop_parent(self) -> dict:
        """Interrupt the parent and wait for its standby."""
        assert not self.call({'action': 'interrupt', 'agent': self.parent}).failed
        return self.ended(self.parent)

    def finish_parent(self) -> dict:
        """End the parent's held turn normally and wait for its standby."""
        self.send(self.parent, 'finish')
        return self.ended(self.parent)

    def notices(self) -> list[str]:
        """Every notice the fake Pi took as input, in order."""
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [text for text in map(json.loads, lines) if text.startswith('[agents · ')]

    def took(self, *expected: str) -> None:
        """Wait until the fake Pi has taken these notices; it logs just after its acknowledgement."""
        until(lambda: self.notices() == list(expected))

    def notice(self, agent: str, body: str) -> str:
        """The text one notice has as the parent's input."""
        return f'[agents · {agent} → {self.parent}]\n{body}'

    def close(self) -> None:
        """Stop what this host still runs."""
        for owned in self.control.interrupt_owned():
            until(lambda: not self.control.owns_running(owned))


@pytest.fixture
def tree(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch):
    """A running Pi parent that takes steered input at once."""
    made = Tree(tmp_path, pi_environment, monkeypatch)
    yield made
    made.close()


@pytest.fixture
def holding(tmp_path: Path, pi_environment: dict, monkeypatch: pytest.MonkeyPatch):
    """A running Pi parent that leaves steered input queued until its turn ends."""
    made = Tree(tmp_path, pi_environment, monkeypatch, 'wait-hold')
    yield made
    made.close()


def test_a_running_pi_parent_takes_its_childs_end_into_the_turn_once(tree: Tree) -> None:
    """Steered with the Claude and Codex framing; the turn goes on and answers with it."""
    grandchild = tree.child('wait-child')
    tree.send(grandchild, 'finish')
    expected = tree.notice(grandchild, 'wait-child|finish')
    tree.took(expected)
    until(lambda: tree.end_state(grandchild) == 'delivered')
    assert tree.executions()[-1]['state'] == 'running'
    assert tree.finish_parent()['last_message'] == f'wait-take|{expected}|finish'
    assert tree.notices() == [expected] and len(tree.executions()) == 1


def test_a_running_pi_parent_is_told_of_each_request_once_and_answers_them(tree: Tree) -> None:
    """Two requests are two notices; the parent reads and replies through its own tool."""
    grandchild = tree.child('dialogs')
    first = tree.notice(grandchild, PERMISSION)
    tree.took(first)
    until(lambda: tree.request_states(grandchild) == ['delivered'])

    def answer() -> None:
        """Answer the one request now pending."""
        [request] = tree.tool({'action': 'requests', 'agent': grandchild}).document['result']['requests']
        replied = tree.tool({'action': 'reply', 'agent': grandchild, 'request': request,
                             'response': {'confirmed': True}})
        assert not replied.failed, replied.document

    answer()
    tree.took(first, first)
    until(lambda: tree.request_states(grandchild) == ['delivered', 'delivered'])
    answer()
    tree.ended(grandchild)
    tree.took(first, first, tree.notice(grandchild, 'dialogs'))
    until(lambda: tree.end_state(grandchild) == 'delivered')


def test_a_standby_pi_parent_is_continued_with_its_childs_end(tree: Tree) -> None:
    """Same native Session; the notice is the prompt; once, with no further turn."""
    grandchild = tree.child('wait-child')
    tree.finish_parent()
    tree.send(grandchild, 'finish')
    until(lambda: len(tree.executions()) == 2 and tree.executions()[1]['state'] == 'ended')
    first, second = tree.executions()
    expected = tree.notice(grandchild, 'wait-child|finish')
    assert second['session'] == first['session'] and second['operation'] == 'receive'
    assert second['last_message'].endswith(expected)
    until(lambda: tree.end_state(grandchild) == 'delivered')
    tree.took(expected)
    assert len(tree.executions()) == 2


def test_a_standby_pi_parent_is_not_started_for_a_request_or_an_end_without_a_body(tree: Tree) -> None:
    """Both held, with no turn; the next resume takes each once, in that turn."""
    tree.finish_parent()
    requesting = tree.child('dialog')
    failing = tree.child('provider-error')
    until(lambda: tree.request_states(requesting) == ['held'])
    failed = tree.ended(failing)
    assert (failed['outcome'], failed['last_message']) == ('failed', None)
    until(lambda: tree.end_state(failing) == 'held')
    assert len(tree.executions()) == 1 and tree.notices() == []

    tree.resume()
    until(lambda: len(tree.notices()) == 2)
    assert sorted(tree.notices()) == sorted([tree.notice(requesting, PERMISSION),
                                             tree.notice(failing, 'fixture provider rejected request')])
    assert tree.request_states(requesting) == ['delivered'] and tree.end_state(failing) == 'delivered'
    assert len(tree.executions()) == 2 and tree.executions()[1]['state'] == 'running'


def test_a_childs_end_while_the_pi_parent_stops_is_held_and_delivered_once_on_resume(
        tmp_path: Path, tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent stopping, then interrupted: not continued; resume delivers it; a further resume nothing."""
    gate = tmp_path / 'abort-gate'
    monkeypatch.setenv('PI_FIXTURE_ABORT_GATE', str(gate))
    tree.close()  # the fixture's parent knows no gate; this one must
    tree.host()
    tree.resume()
    grandchild = tree.child('wait-child')
    try:
        assert not tree.call({'action': 'interrupt', 'agent': tree.parent}).failed
        tree.send(grandchild, 'finish')
        tree.ended(grandchild)
        until(lambda: tree.end_state(grandchild) == 'held')
        assert tree.executions()[-1]['state'] == 'running'
    finally:
        gate.touch()
    assert tree.ended(tree.parent)['outcome'] == 'interrupted'
    assert tree.end_state(grandchild) == 'held' and tree.notices() == []
    before = len(tree.executions())

    tree.resume()
    expected = tree.notice(grandchild, 'wait-child|finish')
    tree.took(expected)
    assert tree.end_state(grandchild) == 'delivered'
    assert len(tree.executions()) == before + 1
    tree.finish_parent()
    tree.resume()
    tree.finish_parent()
    assert tree.notices() == [expected]


def test_a_held_notice_reaches_the_turn_that_resumed_a_parent_whose_prompt_is_still_being_accepted(
        tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flushed while Pi has not acknowledged the first prompt: it waits for it, then takes that same turn."""
    tree.finish_parent()
    grandchild = tree.child('dialog')
    until(lambda: tree.request_states(grandchild) == ['held'])

    monkeypatch.setenv('PI_FIXTURE_PROMPT_SECONDS', '1')
    tree.resume()
    # Before resume returned: the turn it started has the notice, still running.
    assert tree.request_states(grandchild) == ['delivered']
    tree.took(tree.notice(grandchild, PERMISSION))
    assert tree.executions()[-1]['state'] == 'running'


@pytest.mark.parametrize('kind', ['end', 'request'])
def test_a_notice_queued_and_dropped_by_a_stop_is_held_again_and_delivered_once(holding: Tree, kind: str) -> None:
    """Acknowledged is not taken: clear_queue drops it, so the record returns to held for resume."""
    tree = holding
    if kind == 'end':
        grandchild = tree.child('wait-child')
        tree.send(grandchild, 'finish')
        expected = tree.notice(grandchild, 'wait-child|finish')
        state = lambda: tree.end_state(grandchild)  # noqa: E731
    else:
        grandchild = tree.child('dialog')
        expected = tree.notice(grandchild, PERMISSION)
        state = lambda: (tree.request_states(grandchild) or [None])[0]  # noqa: E731
    until(lambda: state() == 'delivered')
    assert tree.notices() == []

    assert tree.stop_parent()['outcome'] == 'interrupted'
    assert state() == 'held' and tree.notices() == []

    tree.resume()
    tree.took(expected)
    assert state() == 'delivered'
    tree.finish_parent()
    tree.resume()
    tree.finish_parent()
    assert tree.notices() == [expected] and state() == 'delivered'


def test_a_notice_the_turn_took_stays_delivered_after_a_stop(tree: Tree) -> None:
    """Taken and then interrupted: in the Session already, so resume repeats nothing."""
    grandchild = tree.child('wait-child')
    tree.send(grandchild, 'finish')
    expected = tree.notice(grandchild, 'wait-child|finish')
    tree.took(expected)
    until(lambda: tree.end_state(grandchild) == 'delivered')

    assert tree.stop_parent()['outcome'] == 'interrupted'
    assert tree.end_state(grandchild) == 'delivered'
    tree.resume()
    tree.finish_parent()
    assert tree.notices() == [expected] and tree.end_state(grandchild) == 'delivered'


def test_a_refused_notice_stays_held_and_arrives_when_the_turn_ends(
        tmp_path: Path, tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pi refused it, so nothing was written: not unconfirmed, and the parent's end continues it once."""
    refuse = tmp_path / 'refuse'
    refuse.touch()
    monkeypatch.setenv('PI_FIXTURE_REFUSE_NOTICES', str(refuse))
    tree.close()  # the fixture's parent knows no refusal; this one must
    tree.host()
    tree.resume()
    grandchild = tree.child('wait-child')
    tree.send(grandchild, 'finish')
    tree.ended(grandchild)
    until(lambda: tree.end_state(grandchild) == 'held')
    assert tree.notices() == []

    refuse.unlink()
    before = len(tree.executions())
    tree.send(tree.parent, 'finish')
    expected = tree.notice(grandchild, 'wait-child|finish')
    tree.took(expected)
    until(lambda: tree.end_state(grandchild) == 'delivered')
    assert tree.executions()[before]['operation'] == 'receive'


def test_a_continued_turn_whose_prompt_pi_refused_holds_its_notice_again(
        tmp_path: Path, tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """The notice was this turn's prompt and never ran: held, and the next child's end brings it, once."""
    refuse = tmp_path / 'refuse'
    refuse.touch()
    monkeypatch.setenv('PI_FIXTURE_REFUSE_NOTICES', str(refuse))
    grandchild, other = tree.child('wait-child'), tree.child('wait-other')
    tree.finish_parent()
    tree.send(grandchild, 'finish')
    until(lambda: len(tree.executions()) == 2 and tree.executions()[1]['state'] == 'ended')
    assert tree.executions()[1]['outcome'] == 'failed'
    until(lambda: tree.end_state(grandchild) == 'held')

    # The failed turn never accepted a prompt: its receiver must not wait for one.
    refuse.unlink()
    tree.send(other, 'finish')
    until(lambda: len(tree.notices()) == 2)
    assert sorted(tree.notices()) == sorted([tree.notice(grandchild, 'wait-child|finish'),
                                             tree.notice(other, 'wait-other|finish')])
    until(lambda: tree.end_state(grandchild) == 'delivered' and tree.end_state(other) == 'delivered')


def test_a_notice_a_completed_turn_rewrote_is_not_delivered_again(
        tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """An input handler hides the notice from the check; an empty queue at the end still means Pi had it."""
    monkeypatch.setenv('PI_FIXTURE_REWRITE_NOTICES', '1')
    tree.close()  # the fixture's parent rewrites nothing; this one must
    tree.host()
    tree.resume()
    before = len(tree.executions())
    grandchild = tree.child('wait-child')
    tree.send(grandchild, 'finish')
    until(lambda: tree.end_state(grandchild) == 'delivered')
    assert tree.finish_parent()['outcome'] == 'completed'
    assert tree.end_state(grandchild) == 'delivered' and len(tree.executions()) == before


def test_a_lost_acknowledgement_is_unconfirmed_and_never_repeats(
        tmp_path: Path, tree: Tree, monkeypatch: pytest.MonkeyPatch) -> None:
    """Written with no answer may have been taken: unconfirmed, not held again by a stop, not resent."""
    lose = tmp_path / 'lose'
    lose.touch()
    monkeypatch.setenv('PI_FIXTURE_LOSE_NOTICE_ACKS', str(lose))
    tree.close()  # the fixture's parent knows no lost acknowledgement; this one must
    tree.host()
    tree.resume('wait-hold')
    grandchild = tree.child('wait-child')
    with monkeypatch.context() as short:
        short.setattr(execution, 'RPC_SECONDS', 1)
        tree.send(grandchild, 'finish')
        tree.ended(grandchild)
        until(lambda: tree.end_state(grandchild) == 'unconfirmed')
    assert tree.stop_parent()['outcome'] == 'interrupted'
    assert tree.end_state(grandchild) == 'unconfirmed'
    lose.unlink()
    tree.resume()
    tree.finish_parent()
    assert tree.notices() == [] and tree.end_state(grandchild) == 'unconfirmed'


def test_a_new_host_delivers_what_the_stopped_host_held_once(tree: Tree) -> None:
    """Parent and child stop with the host; a new control on the root delivers on resume, once."""
    grandchild = tree.child('wait-child')
    tree.close()
    assert tree.end_state(grandchild) == 'held'
    tree.host()
    tree.resume()
    tree.took(tree.notice(grandchild, 'wait-child'))
    assert tree.end_state(grandchild) == 'delivered'
    tree.close()
    tree.host()
    tree.resume()
    tree.finish_parent()
    assert len(tree.notices()) == 1


def test_a_notice_queued_when_the_host_stopped_is_delivered_by_the_next_host_once(holding: Tree) -> None:
    """Delivered on an acknowledgement, then the host's stop dropped it: the next host has it."""
    tree = holding
    grandchild = tree.child('wait-child')
    tree.send(grandchild, 'finish')
    until(lambda: tree.end_state(grandchild) == 'delivered')
    tree.close()
    assert tree.end_state(grandchild) == 'held' and tree.notices() == []
    tree.host()
    tree.resume()
    tree.took(tree.notice(grandchild, 'wait-child|finish'))
    assert tree.end_state(grandchild) == 'delivered'


@pytest.mark.parametrize('event', [{'parent': 'someone-else', 'session': 'native'},
                                   {'parent': None, 'session': None}])
def test_the_receiver_takes_only_this_parents_notices_with_a_session(tree: Tree, event: dict) -> None:
    """Addressed elsewhere, or from a child with no Session: nothing reaches Pi and no turn starts."""
    grandchild = tree.child('wait-child')
    receiver = tree.control._receivers[tree.parent][1]
    parent = tree.parent if event['parent'] is None else event['parent']
    assert receiver({'agent': grandchild, 'execution': 'e', 'body': 'not for you', 'outcome': 'completed',
                     **event, 'parent': parent}) is False
    tree.finish_parent()
    assert tree.notices() == [] and len(tree.executions()) == 1


def install_claude(bin_directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the controlled Claude CLI beside the fake Pi."""
    binary = bin_directory / 'claude'
    binary.write_text(f'#!{sys.executable}\n' + Path(__file__).with_name('claude_cli_fixture.py').read_text())
    binary.chmod(0o755)
    monkeypatch.setenv('CLAUDE_FIXTURE_HOME', str(bin_directory.parent))


@pytest.mark.parametrize('runtime', ['codex', 'claude'])
def test_a_pi_parent_gets_the_end_of_a_child_on_another_runtime(
        tmp_path: Path, project: Path, monkeypatch: pytest.MonkeyPatch, runtime: str) -> None:  # noqa: F811
    """A Codex and a Claude grandchild under a Pi child of a real Codex host."""
    install_claude(tmp_path / 'bin', monkeypatch)
    monkeypatch.setenv('PI_FIXTURE_INPUT_LOG', str(tmp_path / 'input.jsonl'))
    monkeypatch.setenv('PI_FIXTURE_HELD_SECONDS', '60')
    monkeypatch.setenv('PEER_HOST_EVENTS', str(tmp_path / 'events.jsonl'))
    settings = codex_settings(project, dict(ENTRY))
    settings['runtimes']['claude'] = {}
    running = Running(CodexHost(settings, tmp_path / 'data', 'hold'))
    try:
        created = running.call('create', runtime='pi', instruction='wait-take')
        tool = bind(running.host.control, Caller('pi', created['agent'], created['session'], 'pi'))
        made = tool({'action': 'create', 'runtime': runtime, 'instruction': 'hello'})
        assert not made.failed, made.document
        expected = f"[agents · {made.document['agent']} → {created['agent']}]\nhello"
        log = tmp_path / 'input.jsonl'
        until(lambda: expected in map(json.loads, log.read_text().splitlines()))
        record = tmp_path / 'data' / 'control' / 'agents' / f"{made.document['agent']}.json"
        until(lambda: json.loads(record.read_text())['executions'][-1].get('notification') == 'delivered')
        assert [json.loads(line) for line in log.read_text().splitlines()].count(expected) == 1
    finally:
        running.stop()


class PiMain:
    """The real Pi host seen from its Main Session, with a real Pi child driver."""

    def __init__(self, project: Path, root: Path, entry: dict, log: Path) -> None:  # noqa: F811
        """Start the host through its own ``start`` on the given data root."""
        self.root = root
        patch = pytest.MonkeyPatch()
        self.patch = patch
        patch.setenv('AGENT_SWARM_PI_ENTRY', str(project.parent / 'bin' / 'pi'))
        patch.setenv('AGENT_SWARM_PI_PROVIDER', entry['provider'])
        patch.setenv('AGENT_SWARM_PI_MODEL', entry['model'])
        patch.setattr(pi_host, 'verify_native_parent', lambda *_: None)
        patch.setattr(pi_host, 'current_connection', lambda: {
            'runtime': 'pi', 'session': 'main', 'session_file': str(project.parent / 's.jsonl')})
        patch.setattr(pi_host, 'runtime_drivers', lambda cwd, request, settings: {'pi': PiDriver(dict(request))})
        patch.chdir(project)
        config = project.parent / 'host.json'
        config.write_text(json.dumps({'root': str(root)}))
        header = {'type': 'session', 'version': 3, 'id': 'main', 'cwd': str(project)}
        with patch.context() as started:
            started.setattr(sys, 'stdin', io.StringIO(json.dumps({'header': header, 'entries': []}) + '\n'))
            started.setattr(sys, 'stdout', io.StringIO())
            _, self.notices, self.operate, self.inner, self.control, _ = pi_host.start(config)
        self.notices.timeout = 0.05

    def call(self, feature: str, **arguments: object) -> dict:
        """Call one feature and require success."""
        result = self.operate({'action': feature, **arguments})
        assert not result.failed, result.document
        return result.document

    def close(self) -> None:
        """Stop what this host still runs."""
        self.notices.close()
        for owned in self.control.interrupt_owned():
            until(lambda: not self.control.owns_running(owned))
        self.patch.undo()


class DshMain(PiMain):
    """The real DSH host seen from its Main Session, with a real Pi child driver."""

    def __init__(self, project: Path, root: Path, entry: dict, log: Path) -> None:  # noqa: F811
        """Start the host through its own ``start`` on the given data root."""
        self.patch = patch = pytest.MonkeyPatch()
        request = pi_host.pi_request(entry, project, {**os.environ, 'AGENT_SWARM_PI_ENTRY': str(
            project.parent / 'bin' / 'pi')})
        patch.setattr(dsh_host, 'verify_native_parent', lambda *_: None)
        patch.setattr(dsh_host, 'runtime_drivers', lambda *_: {'pi': PiDriver(request)})
        patch.chdir(project)
        config = project.parent / 'host.json'
        config.write_text(json.dumps({'root': str(root)}))
        header = {'version': 4, 'id': 'main', 'cwd': str(project), 'isSeeded': False}
        with patch.context() as started:
            started.setattr(sys, 'stdout', io.StringIO())
            _, _, self.notices, self.operate, self.inner, self.control, _ = dsh_host.start(config, {'header': header})
        self.notices.timeout = 0.05


@pytest.fixture(params=[ClaudeMain, CodexMain, PiMain, DshMain], ids=['claude', 'codex', 'pi', 'dsh'])
def host_main(request: pytest.FixtureRequest, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    """Each host a Pi child can run under, from its real constructor or ``start``."""
    log = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_HOST_EVENTS', str(log))
    monkeypatch.setenv('PI_FIXTURE_INPUT_LOG', str(tmp_path / 'input.jsonl'))
    monkeypatch.setenv('PI_FIXTURE_HELD_SECONDS', '60')
    made = request.param(project, tmp_path / 'data', dict(ENTRY), log)
    yield made
    made.close()


def test_each_host_holds_a_standby_pi_parents_notice_for_its_next_run(host_main, tmp_path: Path) -> None:
    """This depends on the host's own hold_notices: without it nothing holds or flushes."""
    created = host_main.call('create', runtime='pi', instruction='answer')
    child, session = created['agent'], created['session']
    records = tmp_path / 'data' / 'control' / 'agents'

    def executions(agent: str) -> list[dict]:
        """Read one Agent's executions from its durable record."""
        return json.loads((records / f'{agent}.json').read_text())['executions']

    until(lambda: executions(child)[-1]['state'] == 'ended')
    control = (host_main.host.control if isinstance(host_main, ClaudeMain)
               else host_main.running.host.control if isinstance(host_main, CodexMain) else host_main.control)
    made = bind(control, Caller('pi', child, session, 'pi'))({'action': 'create', 'runtime': 'pi', 'instruction': 'dialog'})
    assert not made.failed, made.document
    grandchild = made.document['agent']
    until(lambda: list(executions(grandchild)[-1].get('request_notices', {}).values()) == ['held'])
    assert len(executions(child)) == 1

    host_main.call('resume', agent=child, message='wait-take')
    log = tmp_path / 'input.jsonl'
    expected = f'[agents · {grandchild} → {child}]\n{PERMISSION}'
    until(lambda: expected in map(json.loads, log.read_text().splitlines()))
    until(lambda: list(executions(grandchild)[-1]['request_notices'].values()) == ['delivered'])
