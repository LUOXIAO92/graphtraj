"""Claude Main and member calls with an ``arguments_file`` (575), through the Claude MCP stream.

The mod prepares the native association with Claude Code's exact tool input,
which names the file; the file is read only for the call that then runs.
"""
from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
from uuid import uuid4

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces.agents import GraphTrajAgents
from graphtraj.runtimes.claude import mcp as claude_mcp
from graphtraj.runtimes.claude.host import NativeCalls, main_calls

DEFINITION = {
    'schema_version': 2, 'task_id': '901', 'parent_id': None, 'disposition': 'active',
    'replaced_by': [], 'retirement_reason': None, 'task_name': 'probe-575', 'source': 'test 575',
    'title': 'Probe 575', 'body': 'Registered from an arguments file.', 'dependencies': [],
}


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configured project served by one native Claude host started in it."""
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    monkeypatch.chdir(root)
    return root


def native_host(root: Path) -> NativeCalls:
    """The host's own association and Main backend, as ``host.main`` builds them."""
    return NativeCalls(main_calls(root, GraphTrajAgents(root, root), None), root)


def prepare(host: NativeCalls, root: Path, tool: str, request: dict, session: str) -> None:
    """Prepare one call as the mod does: with Claude Code's exact tool input."""
    host.context({'operation': 'prepare', 'tool': tool, 'session': session, 'cwd': str(root),
                  'agent': None, 'request': request})


def call(root: Path, tool: str, request: dict, native_call=None) -> dict:
    """Send one tools/call through the Claude MCP entry; return its structured result."""
    output = StringIO()
    claude_mcp.serve(StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                          'params': {'name': tool, 'arguments': request}}) + '\n'),
                     output, root, native_call=native_call)
    return json.loads(output.getvalue())['result']['structuredContent']


def write(path: Path, document: object) -> str:
    """Write one JSON arguments file and return its name."""
    path.write_text(json.dumps(document), encoding='utf-8')
    return path.name


def test_native_main_writes_and_reads_tasks_with_arguments_files(project: Path) -> None:
    """The exact prepared input runs once; the file's contents are what the operation applies."""
    host, session = native_host(project), str(uuid4())
    register = {'action': 'execute', 'feature': 'task_register',
                'arguments_file': write(project / 'register.json', DEFINITION)}
    prepare(host, project, 'tasks', register, session)
    written = call(project, 'tasks', register, host.call)
    assert 'error' not in written, written
    assert (project / '.graphtraj/state/tasks/901-probe-575/task.yml').is_file()

    graph = {'action': 'execute', 'feature': 'task_graph',
             'arguments_file': write(project / 'graph.json', {'view': 'full'}), 'arguments': {'view': 'current'}}
    prepare(host, project, 'tasks', graph, session)
    read = call(project, 'tasks', graph, host.call)
    assert 'error' not in read, read
    assert '901' in json.dumps(read)
    # The association was consumed by the call that ran.
    assert call(project, 'tasks', graph, host.call)['error']['code'] == 'authority-denied'


def test_native_main_agents_call_reads_its_arguments_file(project: Path) -> None:
    """The agents entry of the same Main matches the raw input and reads the file afterwards."""
    host, session = native_host(project), str(uuid4())
    status = {'action': 'execute', 'feature': 'status', 'arguments_file': write(project / 'status.json', {})}
    prepare(host, project, 'subagents', status, session)
    answer = call(project, 'subagents', status, host.call)
    assert 'error' not in answer, answer

    wait = {'action': 'execute', 'feature': 'wait',
            'arguments_file': write(project / 'wait.json', {'seconds': 'soon', 'bogus': 1})}
    prepare(host, project, 'subagents', wait, session)
    refused = call(project, 'subagents', wait, host.call)['error']
    assert refused['code'] == 'invalid-input'
    assert {'arguments.seconds', 'arguments.bogus'} <= {item['path'] for item in refused['errors']}


def test_unprepared_or_foreign_arguments_file_calls_stay_refused(project: Path) -> None:
    """Only the exact input this Session prepared runs; the expanded request or another Session's does not."""
    host, session, other = native_host(project), str(uuid4()), str(uuid4())
    name = write(project / 'register.json', DEFINITION)
    register = {'action': 'execute', 'feature': 'task_register', 'arguments_file': name}

    assert call(project, 'tasks', register, host.call)['error']['code'] == 'authority-denied'
    # A preparation of the request as it reads after expansion is a different call.
    prepare(host, project, 'tasks', {'action': 'execute', 'feature': 'task_register', 'arguments': DEFINITION},
            session)
    assert call(project, 'tasks', register, host.call)['error']['code'] == 'authority-denied'
    # Another Session cannot prepare while this one has a pending call.
    with pytest.raises(Exception, match='already pending'):
        prepare(host, project, 'tasks', register, other)
    # A call whose native call ended before it was served is refused, also for the other entry.
    host.context({'operation': 'end'})
    prepare(host, project, 'subagents', register, other)
    assert call(project, 'tasks', register, host.call)['error']['code'] == 'authority-denied'
    host.context({'operation': 'end'})
    assert call(project, 'tasks', register, host.call)['error']['code'] == 'authority-denied'
    assert not (project / '.graphtraj/state/tasks/901-probe-575').exists()


@pytest.mark.parametrize(('named', 'reason'), [('missing.json', 'does not exist'),
                                               ('.graphtraj/config.yml', 'GraphTraj private state')])
def test_prepared_call_with_a_bad_file_is_invalid_input(project: Path, named: str, reason: str) -> None:
    """The file rules are unchanged on the native path: one request.arguments_file problem."""
    host = native_host(project)
    for tool, feature in (('tasks', 'task_graph'), ('subagents', 'status')):
        request = {'action': 'execute', 'feature': feature, 'arguments_file': named}
        prepare(host, project, tool, request, str(uuid4()))
        error = call(project, tool, request, host.call)['error']
        assert error['code'] == 'invalid-input'
        assert [item['path'] for item in error['errors']] == ['request.arguments_file']
        assert reason in error['errors'][0]['reason']


def test_member_path_reads_arguments_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a native host the entry reads the file before its existing channel."""
    graph = {'action': 'execute', 'feature': 'task_graph', 'arguments_file': write(project / 'graph.json',
                                                                                   {'view': 'current'})}
    assert 'error' not in call(project, 'tasks', graph), graph

    forwarded = []
    monkeypatch.setattr(claude_mcp, 'agents_dispatch',
                        lambda request, cwd: forwarded.append(dict(request)) or claude_mcp.AgentsResult({}))
    status = {'action': 'execute', 'feature': 'status', 'arguments_file': write(project / 'status.json', {})}
    assert 'error' not in call(project, 'subagents', status)
    assert forwarded and 'arguments_file' not in json.dumps(forwarded)
