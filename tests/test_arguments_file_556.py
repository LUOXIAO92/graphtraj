"""MCP arguments files and all-at-once input errors (556), through the real MCP stream."""

import io
import json
from dataclasses import replace
from pathlib import Path

import click
import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import local_tool, mcp, tools
from graphtraj.interfaces.cli.projection import invoke_tool


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configured project used as the MCP server's working directory."""
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    (root / '.graphtraj/config.yml').write_text(default_configuration_content(root, root))
    monkeypatch.chdir(root)
    return root


def call(name: str, arguments: dict) -> dict:
    """Send one tools/call through the MCP stream; return its result."""
    output = io.StringIO()
    mcp.serve(io.StringIO(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': name, 'arguments': arguments},
    }) + '\n'), output)
    return json.loads(output.getvalue())['result']


def write(path: Path, document: object) -> str:
    """Write one JSON arguments file and return its name."""
    path.write_text(json.dumps(document), encoding='utf-8')
    return path.name


def paths(result: dict) -> list[str]:
    """The field paths of one invalid-input result."""
    error = result['structuredContent']['error']
    assert error['code'] == 'invalid-input'
    assert error['message'] == '; '.join(f"{item['path']}: {item['reason']}" for item in error['errors'])
    return [item['path'] for item in error['errors']]


def test_schema_and_feature_errors_return_together_then_fixed_file_succeeds(project: Path) -> None:
    """One call lists every problem; fixing only the file makes the next call succeed."""
    name = write(project / 'event.json', {
        'event': {'event': 'not plain!', 'caused_by_event_ids': 'x', 'evidence_refs': ['', '']},
        'extra': 1,
    })
    failed = call('tasks', {'action': 'execute', 'feature': 'worldline_append', 'arguments_file': name})
    assert failed['isError'] is True
    assert paths(failed) == ['arguments.extra', 'arguments.event.event',
                             'arguments.event.caused_by_event_ids', 'arguments.event.evidence_refs']

    write(project / 'event.json', {'event': {'event': 'fixture-fact', 'caused_by_event_ids': [],
                                             'evidence_refs': []}})
    done = call('tasks', {'action': 'execute', 'feature': 'worldline_append', 'arguments_file': name})
    assert done['isError'] is False, done
    assert done['structuredContent']['event'] == 'fixture-fact'


def test_recovery_and_revision_feature_checks_are_all_reported(project: Path) -> None:
    """approved_recovery and task_revise report all their own problems with schema ones."""
    recovery = call('tasks', {'action': 'execute', 'feature': 'approved_recovery', 'arguments': {
        'alias': 'member', 'reason': ' ', 'caused_by_event_ids': ['a', 'a'], 'additional_minutes': -1,
        'unknown': True,
    }})
    assert paths(recovery) == [
        'arguments.unknown', 'arguments.reason', 'arguments.instruction', 'arguments.allowed_scope',
        'arguments.forbidden_scope', 'arguments.caused_by_event_ids', 'arguments.additional_minutes',
    ]

    revision = call('tasks', {'action': 'execute', 'feature': 'task_revise', 'arguments': {
        'product_preserving': True, 'caused_by_event_ids': ['a', 'a'], 'evidence_refs': [], 'tasks': [],
    }})
    assert {'arguments.caused_by_event_ids', 'arguments.evidence_refs'} <= set(paths(revision))


def test_inline_arguments_replace_file_fields(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inline arguments override the file's top-level fields before validation."""
    seen = []
    monkeypatch.setitem(tools.TOOLS, 'task_graph', replace(
        tools.TOOLS['task_graph'],
        input_schema={'type': 'object', 'properties': {'a': {'type': 'string'}, 'b': {'type': 'string'}}},
        handler=lambda arguments, *, cwd=None: seen.append(dict(arguments)) or tools.ToolResult({'ok': True}),
    ))
    name = write(project / 'args.json', {'a': 'file', 'b': 'file'})
    result = call('tasks', {'action': 'execute', 'feature': 'task_graph', 'arguments_file': name,
                            'arguments': {'b': 'inline'}})
    assert result['isError'] is False
    assert seen == [{'a': 'file', 'b': 'inline'}]


def test_file_refusals_name_the_path_only(project: Path, tmp_path: Path) -> None:
    """Outside the workspace, private state and escaping links are refused without content."""
    outside = tmp_path / 'outside.json'
    outside.write_text('{"secret": "outside-content"}', encoding='utf-8')
    (project / 'escape.json').symlink_to(outside)
    (project / 'private.json').symlink_to(project / '.graphtraj/config.yml')

    for named, reason in ((str(outside), 'outside the directory'),
                          ('escape.json', 'outside the directory'),
                          ('.graphtraj/config.yml', 'GraphTraj private state'),
                          ('private.json', 'GraphTraj private state'),
                          ('missing.json', 'does not exist')):
        for name in ('tasks', 'agents'):
            refused = call(name, {'action': 'execute', 'feature': 'task_graph' if name == 'tasks' else 'status',
                                  'arguments_file': named})
            assert refused['isError'] is True
            errors = refused['structuredContent']['error']['errors']
            assert len(errors) == 1 and errors[0]['path'] == 'request.arguments_file'
            assert reason in errors[0]['reason']
            assert 'outside-content' not in json.dumps(refused)


def test_agents_file_arguments_report_every_schema_error(project: Path) -> None:
    """The agents entry reads the same file and returns graftling's full error list."""
    name = write(project / 'wait.json', {'seconds': 'soon', 'bogus': 1})
    result = call('agents', {'action': 'execute', 'feature': 'wait', 'arguments_file': name})
    assert result['isError'] is True
    found = {item['path'] for item in result['structuredContent']['error']['errors']}
    assert {'arguments.seconds', 'arguments.bogus'} <= found


def test_authorization_runs_only_on_valid_input_and_is_unchanged(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid input never reaches the handler; valid input still meets its authorization refusal."""
    reached = []

    def denied(arguments: dict, *, cwd: Path | None = None) -> tools.ToolResult:
        """Stand for the handler's own authority check."""
        reached.append(arguments)
        raise RunnerError('authority-denied', 'not the direct parent')

    monkeypatch.setitem(tools.TOOLS, 'approved_recovery', replace(tools.TOOLS['approved_recovery'], handler=denied))
    invalid = call('tasks', {'action': 'execute', 'feature': 'approved_recovery', 'arguments': {'alias': 'x'}})
    assert 'arguments.reason' in paths(invalid)
    assert reached == []

    valid = {'alias': 'x', 'reason': 'r', 'instruction': 'i', 'allowed_scope': 'a', 'forbidden_scope': 'f',
             'caused_by_event_ids': ['e']}
    refused = call('tasks', {'action': 'execute', 'feature': 'approved_recovery', 'arguments': valid})
    assert refused['isError'] is True
    assert refused['content'][0]['text'] == 'not the direct parent'
    assert len(reached) == 1


def test_json_bridge_and_cli_share_the_validation(project: Path) -> None:
    """The JSON CLI bridge reads files the same way; Click commands list every problem."""
    name = write(project / 'event.json', {'event': {'event': 'not plain!', 'caused_by_event_ids': 'x',
                                                    'evidence_refs': []}})
    answer = local_tool.answer({'action': 'execute', 'feature': 'worldline_append', 'arguments_file': name},
                               cwd=project)
    assert answer['failed'] is True
    assert [item['path'] for item in answer['result']['error']['errors']] == [
        'arguments.event.event', 'arguments.event.caused_by_event_ids']
    refused = local_tool.answer({'action': 'execute', 'feature': 'task_graph',
                                 'arguments_file': '.graphtraj/config.yml'}, cwd=project)
    assert 'GraphTraj private state' in refused['result']['error']['message']

    with pytest.raises(click.ClickException) as raised:
        invoke_tool('worldline_append', {'event': {'event': 'not plain!', 'caused_by_event_ids': 'x',
                                                   'evidence_refs': []}}, cwd=project)
    assert not isinstance(raised.value, click.UsageError)
    assert 'arguments.event.event' in raised.value.message
    assert 'arguments.event.caused_by_event_ids' in raised.value.message


def test_describe_documents_arguments_file(project: Path) -> None:
    """describe explains arguments_file for every executable feature."""
    described = call('tasks', {'action': 'describe', 'feature': 'task_revise'})['structuredContent']
    assert 'arguments_file' in described['arguments_file']
    assert '.graphtraj' in described['arguments_file']
