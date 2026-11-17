"""A headless DSH Main's root Agent stops with the DSH Main; its end is queued, then delivered once (486).

The DSH Main's ``agents``/``tasks`` tools are the MCP server ``python -m
graphtraj.interfaces.mcp`` that DSH starts over stdio (``tool.mjs``
``attachMain``). A root Agent created through it runs its execution in that
server process (``worker_pid``), so it cannot outlive it. DSH closes the server
with input EOF, then SIGTERM 2 s later, then SIGKILL 2 s after that (the MCP
SDK's ``StdioClientTransport.close``). Before 486 the server just exited: the
record stayed ``running`` under a dead owner and no end reached the Main's queue
(Task 481 D1/D2/X398). Here the real server entry runs in its own process with
only the Runtime driver faked; nothing else is.
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

from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution.main_continuity import pending_notices
from test_external_session_entry import dsh_session, native, project  # noqa: F401

SOURCE = Path(__file__).resolve().parents[1] / 'src'
SESSION = 'dsh-main-486'
HEADER = {'version': 4, 'id': SESSION, 'isSeeded': False}
# DSH sends SIGTERM this long after closing the server's input.
DSH_WINDOW = 2.0
SERVER = r'''
from graphtraj.runtimes import replacement
import graphtraj.execution.agent_driver as agent_driver
from agents_helpers import ScriptedDriver

replacement.caller_runtime = lambda: 'dsh'   # in a real host DSH's node is this server's parent
driver = ScriptedDriver()                     # one native owner per process, as AdapterDriver's _TURNS
agent_driver.AdapterDriver = lambda root, cwd: driver
from graphtraj.interfaces.mcp import main
main()
'''


def execute(feature: str, **arguments: object) -> dict:
    """Return one public ``agents`` call."""
    return {'action': 'execute', 'feature': feature, 'arguments': arguments}


def start_server(project: Path, call: dict) -> tuple[subprocess.Popen, dict]:
    """Start the DSH Main's MCP server as DSH does, send ``call`` and return its result; the input stays open."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('DSH_', 'GRAFTLING_', 'GRAPHTRAJ_'))}
    environment.update(DSH_SESSION_ID=SESSION, DSH_AGENT_SOURCE='main',
                       PYTHONPATH=os.pathsep.join([str(SOURCE), str(Path(__file__).parent)]))
    server = subprocess.Popen([sys.executable, '-c', SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, cwd=project, env=environment)
    server.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                   'params': {'name': 'agents', 'arguments': call}}) + '\n')
    server.stdin.flush()
    return server, json.loads(server.stdout.readline())['result']


def closed_within(server: subprocess.Popen, close) -> tuple[float, str]:
    """Close the server with ``close``; return the seconds until it exited and its stderr."""
    started = time.monotonic()
    close()
    _, stderr = server.communicate(timeout=30)
    return time.monotonic() - started, stderr


def main_created_root(project: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[subprocess.Popen, str, str]:
    """Start the headless DSH Main (agent/created) and create g398 through its server."""
    dsh_session(monkeypatch, SESSION)
    assert native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': HEADER}) == {'source': 'main'}
    server, created = start_server(project, execute('create', runtime='claude', name='g398', instruction='work'))
    assert not created['isError'], created
    return server, created['structuredContent']['agent'], created['structuredContent']['execution']


def assert_end_queued(project: Path, agent: str, execution: str) -> None:
    """The root Agent's end is recorded as interrupted and queued once, undelivered, for the DSH Main."""
    record = json.loads((project / '.graphtraj/swarm/control/agents' / f'{agent}.json').read_text())
    assert record['parent'] is None and record['creator']['session'] == SESSION
    ended, = record['executions']
    assert (ended['id'], ended['state'], ended['outcome']) == (execution, 'ended', 'interrupted'), ended
    notices, _ = pending_notices(runner_directory(project), 'dsh', SESSION)
    assert [(item['event']['alias'], item['event']['event'], item['event']['execution']) for item in notices] == [
        (agent, 'interrupted', execution)]


def test_input_eof_stops_the_root_agent_in_the_window_and_the_resumed_main_gets_it_once(
    project: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """D1 then D2 of Task 481, with the fix: EOF stops g398 within 2 s; resume delivers its end once."""
    server, agent, execution = main_created_root(project, monkeypatch)
    seconds, stderr = closed_within(server, server.stdin.close)
    assert server.returncode == 0 and seconds < DSH_WINDOW, (seconds, stderr)
    assert_end_queued(project, agent, execution)

    assert native('dsh', {'event': 'agent/created', 'source': 'resume', 'header': HEADER}) == {'source': 'main'}
    pending = native('dsh', {'event': 'notices'})
    assert pending['notices'] == 1 and agent in pending['text'] and 'interrupted' in pending['text'], pending
    assert native('dsh', {'event': 'notices_ack', 'position': pending['position']}) == {'acknowledged': True}
    assert native('dsh', {'event': 'notices'})['notices'] == 0
    # A later server of the resumed Main reads the Agent stopped and queues nothing again.
    server, status = start_server(project, execute('status', agent=agent))
    closed_within(server, server.stdin.close)
    assert status['structuredContent']['result']['state'] == 'standby', status
    assert native('dsh', {'event': 'notices'})['notices'] == 0
    lines = (runner_directory(project) / 'main-sessions/inbox').glob('*.jsonl')
    assert sum(execution in line for path in lines for line in path.read_text().splitlines()) == 1


def test_sigterm_stops_the_root_agent_and_queues_its_end(
    project: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    """SIGTERM while the input is still open (DSH's second step) ends serving and stops g398 the same way."""
    server, agent, execution = main_created_root(project, monkeypatch)
    seconds, stderr = closed_within(server, lambda: server.send_signal(signal.SIGTERM))
    assert server.returncode == 128 + signal.SIGTERM and seconds < DSH_WINDOW, (server.returncode, seconds, stderr)
    assert_end_queued(project, agent, execution)


def test_a_server_that_owns_nothing_writes_nothing(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Closing a server that ran no Agent leaves the project's Agent records and queues as they were."""
    dsh_session(monkeypatch, SESSION)
    native('dsh', {'event': 'agent/created', 'source': 'startup', 'header': HEADER})
    server, status = start_server(project, execute('status'))
    closed_within(server, server.stdin.close)
    assert server.returncode == 0 and not status['isError'], status
    assert not list((project / '.graphtraj/swarm/control/agents').glob('*.json'))
    assert pending_notices(runner_directory(project), 'dsh', SESSION)[0] == []
