"""The review plugin on Claude: PreToolUse, fail closed and parent fallback (386).

The controlled official-CLI peer (claude_cli_fixture.py) stands in for Claude
Code; it proves this host's side of the protocol, not what the real CLI does
with a hook answer. scripts/real-host/386-review.sh shows that. Most tests
replace only the reviewer's answer; the configured reviewer is a real process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

import agent_swarm
from agent_swarm import AgentControl, Caller
from agent_swarm.approval import REVIEW_METHOD, approves, check_reply, review_failed
from agent_swarm.claude.driver import ClaudeDriver
from agent_swarm.claude.execution import AGENTS_TOOL, REVIEW_HOOK_MIN_SECONDS, ClaudeExecution
from agent_swarm import review as review_core

# A reviewer process: it refuses Write and allows everything else, the connectivity check included.
REVIEWER_SCRIPT = """
import json, sys
tool = json.load(sys.stdin)['request']['tool']
print(json.dumps({'decision': 'deny', 'reason': 'Process refuses Write.'} if tool == 'Write'
                 else {'decision': 'allow', 'reason': 'Process allows this.'}))
"""
DENIED = {'decision': 'deny', 'reason': 'Not part of the task.'}
ALLOWED = {'decision': 'allow', 'reason': 'Inside the workspace.'}
WRITE = {'tool': 'Write', 'input': {'file_path': 'a.txt', 'content': 'x'}}
OTHER = {'tool': 'Write', 'input': {'file_path': 'b.txt', 'content': 'x'}}


class Harness:
    """One parent over one Claude child, recording notices and reviewer calls."""

    def __init__(self, root: Path, *, timeout: int | None = None, reviewed: bool = True) -> None:
        self.root = root
        self.notices: list[dict] = []
        if reviewed:
            (root / 'home').mkdir()
            (root / 'home/.claude.json').write_text('{}')
            (root / 'reviewer.py').write_text(REVIEWER_SCRIPT)
            (root / 'agents').mkdir()
            limit = f'\n    timeout_seconds: {timeout}' if timeout is not None else ''
            (root / 'agents/config.yml').write_text(
                f'reviewers:\n  checker:\n    command: [{sys.executable}, {root}/reviewer.py]{limit}\n'
                f'connections:\n  reviewed:\n    runtime: claude\n    home: {root}/home\n    review: checker\n')
        self.control = AgentControl(root / 'agents', {'claude': ClaudeDriver(root, {
            'model': 'claude-opus-5-5', 'permission_mode': 'default'})},
            event_receiver=self.notices.append, request_notices=True)
        self.call = agent_swarm.bind(self.control, Caller('review-test', 'actual-parent', 'parent-session', 'claude'))

    def invoke(self, action: str, **arguments: object) -> dict:
        """Fail at the public result rather than reading driver internals."""
        result = self.call({'action': action, **arguments})
        assert not result.failed, result.document
        return result.document

    def start(self, **script: object) -> str:
        """Create a child that runs one scripted tool sequence."""
        return self.invoke('create', runtime='claude', instruction='review-script ' + json.dumps(script))['agent']

    def wait(self, agent: str) -> dict:
        """Wait for standby or a pending request."""
        return self.invoke('wait', agent=agent, timeout_seconds=20)['result']

    def pending(self, agent: str) -> list[dict]:
        """Return the requests the parent can read."""
        return self.invoke('requests', agent=agent)['result']['requests']

    def log(self) -> list[dict]:
        """Return what the peer received, in order."""
        path = self.root / 'native-review.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def answers(self, tool_use_id: str) -> list[dict]:
        """Return the hook answers one tool call got."""
        return [item['answer'] for item in self.log() if item.get('hook') == tool_use_id]

    def ran(self) -> list[str]:
        """Return the tool calls the peer ran."""
        return [item['ran'] for item in self.log() if 'ran' in item]

    def decisions(self) -> list[dict]:
        """Return the child's retained review records."""
        path = next((self.root / 'agents').rglob('review.jsonl'))
        return [json.loads(line) for line in path.read_text().splitlines()]

    def request_notices(self) -> list[dict]:
        """Return the parent's request notices."""
        return [notice for notice in self.notices if notice['outcome'] == 'request']

    def standby(self, agent: str) -> dict:
        """Wait for standby even while a retained request ends each ``wait``."""
        eventually(lambda: self.invoke('status', agent=agent)['result']['state'] == 'standby')
        return self.invoke('status', agent=agent)['result']

    def close(self) -> None:
        """Stop what a test leaves running."""
        for owned in self.control.interrupt_owned():
            self.standby(owned)


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the controlled peer where a Claude driver finds it."""
    binary = tmp_path / 'bin/claude'
    binary.parent.mkdir()
    binary.write_text(f'#!{sys.executable}\n' + Path(__file__).with_name('claude_cli_fixture.py').read_text())
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('CLAUDE_FIXTURE_HOME', str(tmp_path))
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1] / 'src'))


@pytest.fixture
def harness(tmp_path: Path, native: None):
    """Run one reviewed child under one parent."""
    created = Harness(tmp_path)
    yield created
    created.close()


@pytest.fixture
def reviewer(monkeypatch: pytest.MonkeyPatch):
    """Answer each review from a list, recording the calls asked about."""
    answers: list = []
    calls: list[dict] = []

    def review_call(connection: dict, request: dict) -> dict:
        calls.append(dict(request))
        answer = answers.pop(0) if answers else ALLOWED
        if isinstance(answer, Exception):
            raise answer
        return answer() if callable(answer) else answer

    monkeypatch.setattr(review_core, 'review_call', review_call)
    return answers, calls


def eventually(condition) -> None:
    """Wait for something a background thread does."""
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def refused(answer: dict) -> bool:
    """Whether a hook answer is Claude's own PreToolUse refusal."""
    output = answer.get('hookSpecificOutput', {})
    return (output.get('hookEventName') == 'PreToolUse' and output.get('permissionDecision') == 'deny'
            and 'direct parent' in output['permissionDecisionReason']
            and 'do not retry' in output['permissionDecisionReason'])


@pytest.mark.parametrize('limit, timeout', [(None, REVIEW_HOOK_MIN_SECONDS), (60, REVIEW_HOOK_MIN_SECONDS), (900, 960)])
def test_hook_covers_every_tool_and_outlasts_the_reviewer(
    tmp_path: Path, native: None, limit: int | None, timeout: int,
) -> None:
    """Review on: PreToolUse has no matcher and a timeout the host always beats."""
    harness = Harness(tmp_path, timeout=limit)
    harness.wait(harness.start(steps=[]))
    hooks = json.loads((tmp_path / 'native-initialize.json').read_text())
    assert hooks['PreToolUse'] == [{'matcher': None, 'hookCallbackIds': ['agents_review'], 'timeout': timeout}]


def test_configured_reviewer_process_decides(harness: Harness) -> None:
    """The whole path with a real reviewer process and no replaced part."""
    agent = harness.start(steps=[{'tool': 'Read', 'input': {'file_path': 'a.txt'}}, WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    eventually(lambda: harness.answers('use-2'))
    assert harness.answers('use-1') == [{}] and harness.ran() == ['use-1']
    assert 'Process refuses Write.' in harness.answers('use-2')[0]['hookSpecificOutput']['permissionDecisionReason']
    assert harness.invoke('status', agent=agent)['result']['review'] == 'checker'
    assert [(item['decision'], item['tool']) for item in harness.decisions()] == [('allow', 'Read'), ('deny', 'Write')]


def test_no_review_keeps_initialize_hooks_and_settings_unchanged(native: None, tmp_path: Path) -> None:
    """Without a reviewer nothing changes, and a prompt still goes to the parent."""
    plain = Harness(tmp_path, reviewed=False)
    agent = plain.start(steps=[{**WRITE, 'ask': True}])
    assert plain.wait(agent)['pending_requests'] == 1
    assert json.loads((tmp_path / 'native-initialize.json').read_text()) == {
        'UserPromptSubmit': [{'matcher': None, 'hookCallbackIds': ['graphtraj_start']}],
        'SubagentStop': [{'matcher': None, 'hookCallbackIds': ['graphtraj_collect_child']}],
        'PostToolUse': [{'matcher': 'mcp__agents__agents', 'hookCallbackIds': ['graphtraj_agents_display']}],
    }
    [request] = plain.pending(agent)
    assert request['method'] == 'claude/can_use_tool'
    plain.invoke('reply', agent=agent, request=request, response={'behavior': 'deny'})
    assert plain.wait(agent)['state'] == 'standby'
    prepared = ClaudeDriver(tmp_path, {'model': 'claude-opus-5-5'}).prepare('claude', Caller('h', None))
    assert 'review' not in prepared


def test_allow_runs_with_no_decision_and_answers_the_later_prompt(harness: Harness, reviewer) -> None:
    """``{}`` keeps native rules; the prompt that follows needs no parent."""
    answers, calls = reviewer
    agent = harness.start(steps=[{**WRITE, 'prompt': True}])
    assert harness.wait(agent)['state'] == 'standby'
    assert harness.answers('use-1') == [{}]
    assert [item['answer'] for item in harness.log() if 'prompt' in item] == [
        {'behavior': 'allow', 'updatedInput': WRITE['input']}]
    assert harness.ran() == ['use-1'] and not harness.request_notices()
    assert [(call['tool']) for call in calls] == ['Write']
    [record] = harness.decisions()
    assert record['decision'] == 'allow' and 'content' not in json.dumps(record)


def test_allowed_call_without_tool_use_id_matches_exact_input(harness: Harness, reviewer) -> None:
    """The fallback is exact: the same input is answered, another goes to the parent."""
    agent = harness.start(steps=[{**WRITE, 'prompt': True, 'no_id': True},
                                 {**OTHER, 'prompt': True, 'no_id': True,
                                  'prompt_input': {'file_path': 'c.txt', 'content': 'x'}}])
    assert harness.wait(agent)['pending_requests'] == 1
    assert harness.ran() == ['use-1']
    [request] = harness.pending(agent)
    assert request['method'] == 'claude/can_use_tool'
    assert request['params']['input']['file_path'] == 'c.txt'


@pytest.mark.parametrize('prompt', [
    {'prompt_fields': {'blocked_path': '/outside/a.txt'}},
    {'prompt_input': {**WRITE['input'], 'dangerouslyDisableSandbox': True}},
    {'prompt_input': {'file_path': 'a.txt', 'content': 'changed'}},
])
def test_prompt_widening_or_changing_an_allowed_call_goes_to_the_parent(
    harness: Harness, reviewer, prompt: dict,
) -> None:
    """A reviewer's allow never answers a native limit, nor another input."""
    agent = harness.start(steps=[{**WRITE, 'prompt': True, **prompt}])
    assert harness.wait(agent)['pending_requests'] == 1
    [request] = harness.pending(agent)
    assert request['method'] == 'claude/can_use_tool' and harness.answers('use-1') == [{}]
    assert harness.ran() == []
    harness.invoke('reply', agent=agent, request=request, response={'behavior': 'deny'})
    assert harness.wait(agent)['state'] == 'standby'
    assert harness.ran() == []


def test_prompt_for_a_call_never_reviewed_goes_to_the_parent(harness: Harness, reviewer) -> None:
    """Native prompts stay as they are when the reviewer never saw the call."""
    agent = harness.start(steps=[{**WRITE, 'ask': True}])
    assert harness.wait(agent)['pending_requests'] == 1
    assert harness.pending(agent)[0]['method'] == 'claude/can_use_tool'


@pytest.mark.parametrize('decision', [
    DENIED, {'decision': 'escalate', 'reason': 'Needs the parent.'}, review_failed('connection refused'),
])
def test_refused_review_denies_and_asks_the_parent_once(harness: Harness, reviewer, decision: dict) -> None:
    """Deny, escalate and failed: one refusal, one request, one notice."""
    reviewer[0].append(decision)
    agent = harness.start(steps=[WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    [answer] = harness.answers('use-1')
    assert refused(answer) and decision['reason'] in answer['hookSpecificOutput']['permissionDecisionReason']
    [request] = harness.pending(agent)
    assert request['method'] == REVIEW_METHOD and request['request_id'].startswith('agents-review:')
    assert request['params'] == {**WRITE, 'decision': decision['decision'], 'reason': decision['reason']}
    eventually(harness.request_notices)
    assert len(harness.request_notices()) == 1 and harness.ran() == []
    assert 'content' not in harness.request_notices()[0]['body']
    assert harness.decisions()[0]['decision'] == decision['decision']


@pytest.mark.parametrize('broken', ['review_call', 'build_request', 'record_decision', 'malformed'])
def test_any_failure_in_the_review_path_denies(
    harness: Harness, reviewer, monkeypatch: pytest.MonkeyPatch, broken: str,
) -> None:
    """A review path that fails anywhere is a refusal for the parent, not a free pass."""
    original = getattr(review_core, broken, None)

    def fail(*arguments: object, **options: object) -> dict:
        if arguments[0] == 'agents':  # The connectivity check at create still works.
            return original(*arguments, **options)
        raise RuntimeError('secret detail')

    if broken == 'malformed':
        reviewer[0].append({'decision': 'allow'})
    else:
        monkeypatch.setattr(review_core, broken, fail)
    agent = harness.start(steps=[WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    [answer] = harness.answers('use-1')
    assert refused(answer) and 'secret detail' not in json.dumps(answer)
    [request] = harness.pending(agent)
    assert request['method'] == REVIEW_METHOD and request['params']['decision'] == 'escalate'
    assert harness.ran() == []


def test_protocol_loop_answers_an_interrupt_while_a_review_runs(harness: Harness, reviewer) -> None:
    """A slow reviewer is off the pipe reader; the interrupted call asks nobody."""
    release = threading.Event()
    started = threading.Event()

    def slow() -> dict:
        started.set()
        release.wait(30)
        return DENIED

    reviewer[0].append(slow)
    agent = harness.start(steps=[WRITE])
    assert started.wait(10)
    try:
        began = time.monotonic()
        harness.invoke('interrupt', agent=agent)
        finished = harness.invoke('wait', agent=agent, timeout_seconds=20)['result']
        assert finished['state'] == 'standby' and finished['last_result']['outcome'] == 'interrupted'
        assert time.monotonic() - began < 15
    finally:
        release.set()
    time.sleep(0.2)
    assert not harness.request_notices() and harness.ran() == []


def test_cancelled_hook_holds_nothing(harness: Harness, reviewer) -> None:
    """A callback Claude withdrew has nobody to answer and asks no parent."""
    gate = threading.Event()

    def held() -> dict:
        gate.wait(10)
        return DENIED

    reviewer[0].append(held)
    agent = harness.start(steps=[{**WRITE, 'cancel': True}])
    eventually(lambda: {'cancelled': 'use-1'} in harness.log())
    gate.set()
    assert harness.wait(agent)['state'] == 'standby'
    time.sleep(0.2)
    assert harness.answers('use-1') == [] and not harness.request_notices()


def test_identical_early_retry_does_not_ask_again(harness: Harness, reviewer) -> None:
    """While one refusal waits, the same call is refused without a second question."""
    answers, calls = reviewer
    answers.append(DENIED)
    agent = harness.start(steps=[WRITE, WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    eventually(lambda: harness.answers('use-2'))
    assert refused(harness.answers('use-2')[0])
    assert len(calls) == 1 and len(harness.pending(agent)) == 1 and harness.ran() == []


def test_accept_releases_one_exact_retry_only(harness: Harness, reviewer) -> None:
    """The retry skips the reviewer once; a repeat and a changed input are reviewed."""
    answers, calls = reviewer
    answers.extend([DENIED, ALLOWED, ALLOWED])
    agent = harness.start(steps=[WRITE], on_accept=[{**WRITE, 'prompt': True}, WRITE, OTHER])
    assert harness.wait(agent)['pending_requests'] == 1
    [request] = harness.pending(agent)
    receipt = harness.invoke('reply', agent=agent, request=request, response={'decision': 'accept'})['result']
    assert receipt['reply_status'] == 'submitted' and receipt['request_id'] == request['request_id']
    assert harness.invoke('reply', agent=agent, request=request, response={'decision': 'decline'})['result']['duplicate']
    finished = harness.wait(agent)
    assert finished['state'] == 'standby', finished
    assert any('you may retry exactly that call once' in item.get('answer', '') for item in harness.log()
               if isinstance(item.get('answer'), str))
    # The retry got {} and its native prompt was answered, without the reviewer.
    assert harness.ran() == ['use-2', 'use-3', 'use-4']
    assert [call['input'] for call in calls] == [WRITE['input'], WRITE['input'], OTHER['input']]
    assert [item['answer'] for item in harness.log() if 'prompt' in item] == [
        {'behavior': 'allow', 'updatedInput': WRITE['input']}]
    assert [record['decision'] for record in harness.decisions()] == ['deny', 'released', 'allow', 'allow']


def test_changed_input_after_accept_is_reviewed_and_the_release_stays_unused(harness: Harness, reviewer) -> None:
    """A release is for the exact call; another input goes to the reviewer and parent."""
    answers, calls = reviewer
    answers.extend([DENIED, DENIED])
    agent = harness.start(steps=[WRITE], on_accept=[OTHER])
    assert harness.wait(agent)['pending_requests'] == 1
    harness.invoke('reply', agent=agent, request=harness.pending(agent)[0], response={'decision': 'accept'})
    eventually(lambda: len(calls) == 2)
    assert harness.wait(agent)['pending_requests'] >= 1
    eventually(lambda: harness.answers('use-2'))
    assert refused(harness.answers('use-2')[0]) and harness.ran() == []
    assert [item['params']['input'] for item in harness.pending(agent)] == [OTHER['input']]


def test_decline_after_the_turn_ended_starts_nothing(harness: Harness, reviewer) -> None:
    """The refusal stands and the execution closes with no further prompt."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    [request] = harness.pending(agent)
    eventually(lambda: harness.answers('use-1'))
    time.sleep(0.3)  # The turn's result and idle arrive after the refusal.
    assert harness.invoke('status', agent=agent)['result']['state'] == 'active'
    harness.invoke('reply', agent=agent, request=request, response={'decision': 'decline'})
    finished = harness.wait(agent)
    assert finished['state'] == 'standby' and finished['last_result']['outcome'] == 'completed'
    assert finished['last_result']['last_message'] == 'review-done'
    assert not [item for item in harness.log() if 'answer' in item and isinstance(item['answer'], str)]
    assert harness.ran() == []


def test_execution_stays_open_and_an_accept_after_the_turn_ended_runs_a_follow_up(
    harness: Harness, reviewer,
) -> None:
    """The finished turn does not close the execution; the follow-up prompt is not lost."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[WRITE], on_accept=[WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    eventually(lambda: harness.answers('use-1'))
    time.sleep(0.5)
    status = harness.invoke('status', agent=agent)['result']
    assert status['state'] == 'active'
    harness.invoke('reply', agent=agent, request=harness.pending(agent)[0], response={'decision': 'accept'})
    finished = harness.wait(agent)
    assert finished['state'] == 'standby' and finished['last_result']['outcome'] == 'completed', finished
    assert harness.ran() == ['use-2'] and harness.answers('use-2') == [{}]


@pytest.mark.parametrize('decision, text', [('accept', 'you may retry'), ('decline', 'do not retry')])
def test_answer_while_the_turn_runs_is_input_to_it(harness: Harness, reviewer, decision: str, text: str) -> None:
    """Either answer reaches a running turn."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[WRITE], running=True)
    assert harness.wait(agent)['pending_requests'] == 1
    eventually(lambda: harness.answers('use-1'))
    time.sleep(0.2)
    assert harness.invoke('status', agent=agent)['result']['state'] == 'active'
    harness.invoke('reply', agent=agent, request=harness.pending(agent)[0], response={'decision': decision})
    finished = harness.wait(agent)
    assert finished['state'] == 'standby' and finished['last_result']['outcome'] == 'completed', finished
    assert text in next(item['answer'] for item in harness.log() if isinstance(item.get('answer'), str))


@pytest.mark.parametrize('response', [
    {'decision': 'acceptForSession'}, {'behavior': 'allow'}, {'decision': 'accept', 'scope': 'session'}, {},
])
def test_invalid_reply_is_refused_and_the_request_stays(harness: Harness, reviewer, response: dict) -> None:
    """Only exactly accept or decline answers a held review."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[WRITE])
    assert harness.wait(agent)['pending_requests'] == 1
    [request] = harness.pending(agent)
    result = harness.call({'action': 'reply', 'agent': agent, 'request': request, 'response': response})
    assert result.failed and result.document['error']['code'] == 'invalid-input'
    assert harness.pending(agent) == [request]


def test_reply_rules_are_consistent() -> None:
    """approves and check_reply read a held review's answer the same way."""
    request = {'method': REVIEW_METHOD}
    assert approves(request, {'decision': 'accept'})
    assert not approves(request, {'decision': 'decline'})
    assert not approves(request, {'decision': 'acceptForSession'})
    check_reply(request, {'decision': 'accept'})
    check_reply(request, {'decision': 'decline'})
    with pytest.raises(agent_swarm.AgentsError):
        check_reply(request, {'behavior': 'allow'})


def test_interrupt_drops_unanswered_requests(harness: Harness, reviewer) -> None:
    """Nothing native is answered for a held review, and the execution ends."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[WRITE], running=True)
    assert harness.wait(agent)['pending_requests'] == 1
    harness.invoke('interrupt', agent=agent)
    finished = harness.standby(agent)
    assert finished['last_result']['outcome'] == 'interrupted' and 'pending_requests' not in finished
    assert harness.ran() == []


def test_release_ends_with_its_execution(harness: Harness, reviewer) -> None:
    """A later execution reviews the call again."""
    answers, calls = reviewer
    answers.extend([DENIED, ALLOWED])
    agent = harness.start(steps=[WRITE], running=True)
    assert harness.wait(agent)['pending_requests'] == 1
    harness.invoke('reply', agent=agent, request=harness.pending(agent)[0], response={'decision': 'accept'})
    harness.wait(agent)
    harness.invoke('send', agent=agent, message='review-script ' + json.dumps({'steps': [WRITE]}))
    assert harness.wait(agent)['state'] == 'standby'
    assert len(calls) == 2 and harness.ran() == ['use-1']


def test_agents_tool_is_not_reviewed(harness: Harness, reviewer) -> None:
    """The child's channel to its parent works with the reviewer down."""
    answers, calls = reviewer
    answers.append(RuntimeError('reviewer down'))
    tool = {'tool': AGENTS_TOOL, 'input': {'action': 'status'}}
    agent = harness.start(steps=[tool])
    assert harness.wait(agent)['state'] == 'standby'
    assert harness.answers('use-1') == [{}] and harness.ran() == ['use-1']
    assert calls == [] and not harness.request_notices()


def test_reviewers_key_is_not_passed_to_the_child(
    tmp_path: Path, native: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's key stays with the host; the child's own key reference stays."""
    monkeypatch.setenv('CHECKER_KEY', 'fake-review-key')
    monkeypatch.setenv('CHILD_KEY', 'fake-child-key')
    driver = ClaudeDriver(tmp_path, {'model': 'claude-opus-5-5', 'api_key_env': 'CHILD_KEY'})

    def environment(key_env: str) -> dict:
        settings = driver.prepare('claude', Caller('h', None), selection={
            'settings': None, 'review': {'name': 'checker', 'base_url': 'https://r/v1', 'model': 'm',
                                         'api_key_env': key_env}})
        turn = ClaudeExecution(settings, 'x', tmp_path, lambda *_: None, lambda *_: None, tmp_path / 't', None)
        return turn._prepare(None)[1]

    assert 'CHECKER_KEY' not in environment('CHECKER_KEY')
    assert environment('CHILD_KEY')['ANTHROPIC_API_KEY'] == 'fake-child-key'


def test_read_only_tools_are_reviewed_too(harness: Harness, reviewer) -> None:
    """There is no tool allowlist beyond the bound control tool."""
    reviewer[0].append(DENIED)
    agent = harness.start(steps=[{'tool': 'Read', 'input': {'file_path': 'a.txt'}}])
    assert harness.wait(agent)['pending_requests'] == 1
    assert refused(harness.answers('use-1')[0])
