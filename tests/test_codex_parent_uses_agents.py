"""The Codex note's example gets the parent to agents, and a run that bypasses it shows (432).

A controlled peer stands in for Codex, so this covers only what can be determined:
the note's literal calls work and the output tells the cases apart. Which tool a real
model chooses can only be observed in a real run (392's partial rerun of step 63).
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

from agent_swarm.codex.host import CodexHost
from test_codex_host_cross_runtime import Running, events, until
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture

INSTALL = Path(__file__).resolve().parents[1] / 'src/agent_swarm/install'
NOTE = (INSTALL / 'codex.md').read_text()
USER_TEXT = 'Retain native settings.'
ANSWER = 'The child answered: Ready.'


def section(text: str, heading: str) -> str:
    """The body of one ``##`` section of an install note."""
    return text.split(f'## {heading}\n', 1)[1].split('\n## ', 1)[0]


def note_instruction() -> str:
    """The instruction the note's run block passes, parsed as the shell parses it."""
    block = re.search(r'```sh\n(.*?)```', section(NOTE, 'Run it'), re.S).group(1)
    return shlex.split(block.replace('\\\n', ' '))[-1]


def literal_calls(instruction: str) -> list[dict]:
    """The numbered JSON calls an instruction spells out."""
    return [json.loads(call) for call in re.findall(r'^\d+\. (\{.*\})$', instruction, re.M)]


def note_settings(tmp_path: Path, native_settings: dict) -> dict:
    """The note's own minimal settings with its placeholders filled, on the controlled peer."""
    work = tmp_path / 'work'
    work.mkdir()
    block = re.search(r'```json\n(.*?)```', section(NOTE, 'Minimal configuration'), re.S).group(1)
    settings = json.loads(block.replace('/absolute/work', str(work)))
    settings['adapter_request']['arguments'] = native_settings['adapter_request']['arguments']
    return settings


def run_host(tmp_path: Path, settings: dict, instruction: str, *extra: str) -> tuple:
    """Run the packaged host once; return the process, its stderr lines and its --output."""
    (tmp_path / 'settings.json').write_text(json.dumps(settings))
    output = tmp_path / 'output.json'
    output.unlink(missing_ok=True)
    process = subprocess.run([
        sys.executable, '-m', 'agent_swarm.codex.host', '--settings', str(tmp_path / 'settings.json'),
        '--directory', str(tmp_path / 'data'), '--output', str(output), *extra, instruction,
    ], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    lines = [json.loads(line) for line in process.stderr.splitlines() if line.startswith('{')]
    return process, lines, json.loads(output.read_text()) if output.exists() else None


def client_messages(path: Path, method: str) -> list[dict]:
    """The params of every ``method`` the controlled Codex services received, in order."""
    messages = [json.loads(line) for line in path.read_text().splitlines()]
    return [message['params'] for message in messages if message.get('method') == method]


def test_the_note_example_names_agents_and_its_calls_create_and_wait(
    tmp_path: Path, native_settings: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The note's settings, an empty config.yml and its literal calls give operations the child."""
    instruction = note_instruction()
    assert 'only the MCP tool agents' in instruction and 'not spawn_agent' in instruction
    calls = literal_calls(instruction)
    assert [call['feature'] for call in calls] == ['create', 'wait']
    assert 'model' not in calls[0]['arguments']

    log = tmp_path / 'protocol.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(log))
    monkeypatch.setenv('PEER_MCP_CALLS', json.dumps(calls))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/config.yml').write_text('')
    # The peer makes these calls in place of the model.
    process, lines, output = run_host(tmp_path, note_settings(tmp_path, native_settings), 'mcp-in-turn')
    assert process.returncode == 0, process.stdout + process.stderr
    create, wait = output['operations']
    assert (create['action'], create['failed'], wait['action'], wait['failed']) == ('create', False, 'wait', False)
    assert wait['result']['agent'] == create['result']['agent']
    assert wait['result']['result']['last_result']['outcome'] == 'completed'
    assert lines[-1] == {'run_summary': {'agents_calls': 2, 'native_subagents': 0}}
    # The note's empty developerInstructions: the passage alone, with nothing before it.
    assert client_messages(log, 'thread/start')[0]['developerInstructions'].startswith('The MCP tool `agents`')


def test_only_the_parent_gets_the_guidance_after_the_users_text_on_start_and_resume(
    tmp_path: Path, native_settings: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """thread/start and thread/resume carry it, a Codex child does not, and nothing disables native subagents."""
    log = tmp_path / 'protocol.jsonl'
    received = tmp_path / 'host-events.jsonl'
    monkeypatch.setenv('PEER_PROTOCOL_LOG', str(log))
    monkeypatch.setenv('PEER_HOST_EVENTS', str(received))
    running = Running(CodexHost(native_settings, tmp_path / 'host', 'hold'))
    try:
        child = running.call('create', runtime='codex', instruction='configuration')['agent']
        done = running.call('wait', agent=child, timeout_seconds=10)
        # The running host pushes the child's reply to its parent once (431), so wait
        # shows that body hidden; the reply is what the parent's Session received.
        try:
            [reply] = until(lambda: [event for event in events(received) if event.get('alias') == child])
        except (AssertionError, ValueError):
            raise AssertionError(json.dumps({'wait': done, 'parent_received': events(received)}, indent=1))
        observed = json.loads(reply['message'])
    finally:
        running.stop()
    assert observed['developerInstructions'] == USER_TEXT

    Running(CodexHost(native_settings, tmp_path / 'host', 'hold', resume=True)).stop()
    start = client_messages(log, 'thread/start')[0]
    [resume] = client_messages(log, 'thread/resume')
    [server] = start['config']['mcp_servers']
    for params in (start, resume):
        text = params['developerInstructions']
        assert text.startswith(USER_TEXT + '\n\nThe MCP tool `agents`')
        assert f'`mcp__{server}__agents`' in text and '`spawn_agent`' in text
        assert not {'multi_agent', 'collab', 'collaboration'} & set(params['config'].get('features', {}))


@pytest.mark.parametrize('prompt', ['native-subagent', 'native-subagent-late'])
def test_a_native_subagent_shows_without_changing_stdout_or_the_exit_status(
    tmp_path: Path, native_settings: dict, prompt: str,
) -> None:
    """Started and completed count once, the prompt stays out, and parent_session stays first."""
    process, lines, output = run_host(tmp_path, native_settings, prompt)
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stdout == 'The child answered.\n'
    assert 'parent_session' in lines[0]
    session = lines[0]['parent_session']
    [entry] = output['native_subagents']
    assert entry == {'id': 'native-spawn', 'sender_thread': session, 'receiver_threads': ['native-child'],
                     'status': 'completed', 'model': 'native-model'}
    [line] = [line['native_subagent'] for line in lines if 'native_subagent' in line]
    assert line['id'] == 'native-spawn' and "Codex's own subagent, not an agents child" in line['note']
    assert 'the native prompt body' not in process.stderr + json.dumps(output)
    assert output['operations'] == []
    summary = lines[-1]['run_summary']
    assert (summary['agents_calls'], summary['native_subagents']) == (0, 1)
    assert 'made no agents call' in summary['note']


def test_a_run_with_no_notification_and_no_agents_call_still_says_so(
    tmp_path: Path, native_settings: dict,
) -> None:
    """The walk's exact case: operations empty, a claim on stdout, exit 0, and only this line to tell."""
    process, lines, output = run_host(tmp_path, native_settings, ANSWER)
    assert process.returncode == 0, process.stdout + process.stderr
    assert process.stdout == ANSWER + '\n'
    assert output['operations'] == [] and output['native_subagents'] == []
    assert list(lines[0]) == ['parent_session', 'service_pid', 'source']
    summary = lines[-1]['run_summary']
    assert (summary['agents_calls'], summary['native_subagents']) == (0, 0)
    assert 'not created through agents' in summary['note']


def test_a_run_with_an_agents_call_has_no_note(
    tmp_path: Path, native_settings: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agents calls are counted from what the host served, not from a notification."""
    monkeypatch.setenv('PEER_MCP_CALLS', json.dumps([{'action': 'execute', 'feature': 'status', 'arguments': {}}]))
    process, lines, output = run_host(tmp_path, native_settings, 'mcp-in-turn')
    assert process.returncode == 0, process.stdout + process.stderr
    assert [call['action'] for call in output['operations']] == ['status']
    assert lines[-1] == {'run_summary': {'agents_calls': 1, 'native_subagents': 0}}


def test_a_refused_start_has_no_summary(tmp_path: Path, native_settings: dict) -> None:
    """No Session ran, so there is nothing to summarize; the error document stays the whole report."""
    assert run_host(tmp_path, native_settings, 'first')[0].returncode == 0
    process, lines, _ = run_host(tmp_path, native_settings, 'second')
    assert process.returncode == 1
    assert json.loads(process.stdout)['error']['code'] == 'session-exists'
    assert lines == []


@pytest.mark.parametrize(('note', 'native'), [
    ('claude-code', "not Claude Code's own subagents"),
    ('dsh', "not DSH's own subagents"),
    ('pi', None),  # Pi has no native subagents to exclude.
])
def test_every_other_install_note_child_example_names_the_tool(note: str, native: str | None) -> None:
    """The same wording risk as Codex's; these hosts' observables are already agents-only."""
    example = re.search(r'^- Ask .*?(?=^- |^$)', section((INSTALL / f'{note}.md').read_text(), 'See that it worked'),
                        re.M | re.S).group(0)
    words = ' '.join(example.split())
    assert 'use the `agents` tool' in words and 'child that answers one word' in words
    assert native is None or native in words
