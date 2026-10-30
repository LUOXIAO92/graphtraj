"""The independent Claude Code host runs children on other Runtimes (381).

A Codex child runs the real CodexDriver against the controlled stdio peer;
Claude children run the controlled Claude CLI. Model discovery is faked. No
network, no real model.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable
from uuid import uuid4

import pytest

import agent_swarm
import agent_swarm.control
from agent_swarm.claude.host import IndependentCalls
from test_claude_runtime import claude_environment  # noqa: F401
from test_codex_independent_control import native_settings  # noqa: F401


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake native discovery: Codex offers gpt-5.5 with three efforts."""
    def discover(connection):
        return {'runtime': connection['runtime'], 'status': 'available', 'message': 'fake catalog',
                'models': [{'id': 'gpt-5.5', 'alias': 'GPT-5.5', 'provider': 'openai',
                            'supported_efforts': ['low', 'medium', 'high']}]}

    monkeypatch.setattr(agent_swarm.control, '_discover_models', discover)


def main_call(host: IndependentCalls, cwd: Path):
    """Bind one verified Main Session; ``shown`` collects notices attached to its results."""
    session = str(uuid4())
    call = host.make_call(session, cwd)
    shown: list[dict] = []

    def invoke(feature: str, **arguments) -> dict:
        result = call('agents', {'action': 'execute', 'feature': feature, 'arguments': arguments})
        assert not result.failed, result.document
        shown.extend(result.document.get('main_notices', []))
        return result.document

    return invoke, call, session, shown


def answered(invoke: Callable, agent: str, shown: list[dict]) -> dict:
    """Wait for an end and return it with the body the Main got, which it must get exactly once.

    The wait shows it, unless an earlier result already carried it as a notice: a
    quick child can end before its own create, send or resume returns.
    """
    last    = invoke('wait', agent=agent, timeout_seconds=10)['result']['last_result']
    carried = [notice['event']['message'] for notice in shown
               if (notice['event']['execution'], notice['event']['event']) == (last['id'], last['outcome'])]
    bodies  = carried + ([last['last_message']] if last['last_message'] is not None else [])
    assert len(bodies) == 1, (last, carried)
    return {**last, 'last_message': bodies[0]}


def claimed(host: IndependentCalls, session: str, until: int, shown: list[dict],
            timeout: float = 20) -> list[dict]:
    """Collect this Main's notices from results and the mod's claim until ``until`` arrived."""
    deadline = time.monotonic() + timeout
    while len(shown) < until and time.monotonic() < deadline:
        shown += host.context({'operation': 'notices', 'session': session})['notices']
        time.sleep(0.05)
    return shown


def test_claude_host_runs_a_codex_child_like_a_claude_child(
        tmp_path: Path, native_settings: dict, catalog: None) -> None:
    """Create with model and effort, send, status hierarchy, interrupt, resume, request, retire."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'codex': native_settings})
    invoke, _, session, shown = main_call(host, tmp_path)
    try:
        created = invoke('create', runtime='codex', instruction='configuration',
                         model='gpt-5.5', reasoning_effort='high')
        agent = created['agent']
        assert (created['result']['runtime'], created['result']['model'],
                created['result']['reasoning_effort']) == ('codex', 'gpt-5.5', 'high')
        assert created['result']['creator'] == {'host': 'claude-native', 'agent': None, 'session': session}
        # The Codex child actually ran the chosen model and effort.
        observed = json.loads(answered(invoke, agent, shown)['last_message'])
        assert observed['model'] == 'gpt-5.5'
        assert observed['config']['model_reasoning_effort'] == 'high'
        [node] = invoke('status')['result']['agents']
        assert (node['agent'], node['runtime'], node['parent'], node['state']) == (agent, 'codex', None, 'standby')

        invoke('resume', agent=agent, message='hold')
        invoke('send', agent=agent, message='second answer')
        assert answered(invoke, agent, shown)['last_message'] == 'second answer'
        invoke('resume', agent=agent, message='hold')
        invoke('interrupt', agent=agent)
        assert answered(invoke, agent, shown)['outcome'] == 'interrupted'

        # Every end so far reached the Main once, by a wait or a result, never both (367 result 2).
        earlier = len(shown)
        # A native request reaches the Main once as a notice; the Main answers with reply.
        invoke('resume', agent=agent, message='request:item/commandExecution/requestApproval')
        assert invoke('wait', agent=agent, timeout_seconds=10)['result']['pending_requests'] == 1
        [notice] = claimed(host, session, earlier + 1, shown)[earlier:]
        assert (notice['event']['alias'], notice['event']['event']) == (agent, 'request')
        assert 'item/commandExecution/requestApproval' in notice['event']['message']
        assert notice['id'].startswith(notice['event']['execution'] + ':request:')
        [request] = invoke('requests', agent=agent)['result']['requests']
        invoke('reply', agent=agent, request=request, response={'decision': 'accept'})
        assert answered(invoke, agent, shown)['last_message'] == 'request accepted'
        assert host.context({'operation': 'notices', 'session': session})['notices'] == []
        assert len([item for item in shown if item['event']['event'] == 'request']) == 1

        invoke('retire', agent=agent)
        assert invoke('status')['result']['agents'] == []
    finally:
        for owned in host.control.interrupt_owned():
            deadline = time.monotonic() + 10
            while host.control.owns_running(owned) and time.monotonic() < deadline:
                time.sleep(0.05)


def test_a_codex_childs_end_reaches_the_claude_main_once(tmp_path: Path, native_settings: dict) -> None:
    """Without a wait the mod claims the Codex child's answer once; another Session never sees it."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'codex': native_settings})
    invoke, call, session, shown = main_call(host, tmp_path)
    agent = invoke('create', runtime='codex', instruction='codex says hi')['agent']
    notices = claimed(host, session, 1, shown)
    assert [(n['event']['alias'], n['event']['event'], n['event']['message']) for n in notices] == [
        (agent, 'completed', 'codex says hi')]
    assert host.context({'operation': 'notices', 'session': session})['notices'] == []
    assert host.context({'operation': 'notices', 'session': str(uuid4())})['notices'] == []
    assert 'main_notices' not in call('agents', {'action': 'discover'}).document


@pytest.mark.parametrize('arguments, code', [
    ({'runtime': 'pi'}, 'unsupported-runtime'),
    ({'runtime': 'codex', 'model': 'not-a-model'}, 'invalid-model'),
    ({'runtime': 'codex', 'model': 'gpt-5.5', 'reasoning_effort': 'max'}, 'invalid-reasoning-effort'),
    ({'runtime': 'codex', 'reasoning_effort': 'max'}, 'invalid-reasoning-effort'),
    ({'runtime': 'codex', 'preset': 'missing'}, 'invalid-preset'),
    ({'runtime': 'codex', 'configuration': 'x'}, 'invalid-config'),
])
def test_invalid_choices_for_a_codex_child_are_refused(
        tmp_path: Path, native_settings: dict, catalog: None, arguments: dict, code: str) -> None:
    """Each refusal keeps its code and prepares no Agent."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'codex': native_settings})
    _, call, _, _ = main_call(host, tmp_path)
    result = call('agents', {'action': 'execute', 'feature': 'create',
                             'arguments': {'instruction': 'work', **arguments}})
    assert result.failed and result.document['error']['code'] == code, result.document
    assert not (tmp_path / 'agents' / 'control' / 'agents').exists() or not any(
        (tmp_path / 'agents' / 'control' / 'agents').iterdir())


def test_without_a_runtimes_entry_codex_is_unsupported(tmp_path: Path) -> None:
    """A Runtime with no entry has no driver in this host."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {})
    _, call, _, _ = main_call(host, tmp_path)
    result = call('agents', {'action': 'execute', 'feature': 'create',
                             'arguments': {'runtime': 'codex', 'instruction': 'work'}})
    assert result.document['error']['code'] == 'unsupported-runtime'


@pytest.mark.parametrize('runtimes, code, text', [
    ({'pi': {}}, 'unsupported-runtime', "does not support Runtime 'pi' yet"),
    ({'claude': {}}, 'invalid-config', 'runtimes.claude'),
    ({'codex': {}}, 'invalid-config', ''),
    ({'codex': 'settings.json'}, 'invalid-config', 'driver settings object'),
    ([], 'invalid-config', 'driver settings object'),
])
def test_runtimes_entries_are_checked_when_the_host_is_built(
        tmp_path: Path, runtimes: object, code: str, text: str) -> None:
    """An unsupported or malformed entry refuses the host instead of a later create."""
    with pytest.raises(agent_swarm.AgentsError) as refused:
        IndependentCalls(tmp_path / 'agents', tmp_path, {}, runtimes)
    assert refused.value.code == code and text in str(refused.value)


def test_fallback_report_is_unchanged_beside_a_codex_driver(
        tmp_path: Path, claude_environment: None, native_settings: dict) -> None:
    """A Claude child's model fallback names requested, observed model and reason in a two-driver host."""
    host = IndependentCalls(tmp_path / 'agents', tmp_path, {}, {'codex': native_settings})
    invoke, _, _, _ = main_call(host, tmp_path)
    agent = invoke('create', runtime='claude', instruction='fallback')['agent']
    last = invoke('wait', agent=agent, timeout_seconds=20)['result']['last_result']
    assert last['outcome'] == 'failed' and last['error']['code'] == 'RUNTIME_REQUEST_FAILED'
    message = last['error']['message']
    assert message.startswith('Claude changed the configured model: requested model ')
    assert 'observed model claude-opus-4-8' in message
    assert "Runtime reason: model_refusal_fallback: Opus 5.5's safeguards flagged this session." in message


def write_host(project: Path, runtimes: object = None, config_yml: str | None = None) -> Path:
    """Write a claude-host.json whose verified native parent is this test's launcher."""
    root = project / '.agents-control'
    root.mkdir(parents=True)
    document = {'root': str(root), 'cwd': str(project), 'claude': sys.executable,
                'channel_file': str(root / 'live' / 'channel.json'), 'settings': {}}
    if runtimes is not None:
        document['runtimes'] = runtimes
    if config_yml is not None:
        (root / 'config.yml').write_text(config_yml)
    (root / 'claude-host.json').write_text(json.dumps(document))
    return root


@pytest.mark.parametrize('runtimes, config_yml, code, text', [
    ({'pi': {}}, None, 'unsupported-runtime', "does not support Runtime 'pi' yet"),
    (None, 'connections:\n  work-codex:\n    runtime: codex\n', 'unsupported-runtime',
     "Connection 'work-codex' uses Runtime 'codex'"),
    (None, 'connections:\n  work-claude:\n    runtime: claude\n    api_key_env: AGENTS_381_UNSET_KEY\n',
     'runtime-unavailable', ''),
])
def test_host_start_refusals_keep_their_code(
        tmp_path: Path, runtimes: object, config_yml: str | None, code: str, text: str) -> None:
    """runtimes and require_connections refuse through the readable refusal path."""
    project = tmp_path / 'project'
    root = write_host(project, runtimes, config_yml)
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': 'agents', 'arguments': {'action': 'discover'}}}]
    launcher = ('import subprocess, sys\n'
                'done = subprocess.run([sys.executable, "-m", "agent_swarm.claude.host", "serve", "--config",'
                ' sys.argv[1]], input=sys.stdin.read(), capture_output=True, text=True, timeout=30)\n'
                'sys.stdout.write(done.stdout); sys.stderr.write(done.stderr)\n')
    source = str(Path(agent_swarm.__file__).parents[1])
    environment = {key: value for key, value in os.environ.items() if key != 'AGENTS_381_UNSET_KEY'}
    # No real claude on PATH: the check reports it not installed without touching this machine's login.
    environment.update(PATH=str(Path(sys.executable).parent), HOME=str(tmp_path / 'home'))
    finished = subprocess.run(
        [sys.executable, '-c', launcher, str(root / 'claude-host.json')], cwd=project,
        input=''.join(json.dumps(message) + '\n' for message in messages), capture_output=True, text=True,
        timeout=60, env={**environment, 'PYTHONPATH': source + os.pathsep + os.environ.get('PYTHONPATH', '')})
    replies = [json.loads(line) for line in finished.stdout.splitlines()]
    error = replies[1]['result']['structuredContent']['error']
    assert error['code'] == code and text in error['message'], error
    assert error['message'] in (root / 'host.log').read_text()
    assert not (root / 'control').exists() and not (root / 'live').exists()

