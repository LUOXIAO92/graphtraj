"""CLI and MCP share list inputs and show Unicode text directly."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.interfaces import mcp, tools
from graphtraj.interfaces.cli.agent_runner import main
from graphtraj.interfaces.tools import ToolResult

EVENTS = ['事件-a', 'b\\u4e2d"c']


@pytest.fixture
def received(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict]:
    """Record the shared core input and answer with a Chinese document."""
    calls: list[dict] = []

    def handler(arguments: dict, **context: object) -> ToolResult:
        calls.append(arguments)
        return ToolResult({'task_id': arguments['task_id'], 'title': '统一输出',
                           'caused_by_event_ids': arguments['caused_by_event_ids']})

    monkeypatch.setitem(tools.TOOLS, 'continue', replace(tools.TOOLS['continue'], handler=handler))
    monkeypatch.delenv('GRAPHTRAJ_CLI_CONNECTION', raising=False)
    monkeypatch.chdir(tmp_path)
    return calls


def test_cli_and_mcp_pass_the_same_list_and_show_unicode(received: list[dict]) -> None:
    """A JSON array reaches the core like MCP's array; output keeps exact values."""
    result = CliRunner().invoke(main, ['continue', '--task-id', '343',
                                       '--caused-by-event-ids', json.dumps(EVENTS, ensure_ascii=False)])
    assert result.exit_code == 0, result.output
    # Non-ASCII text is direct; only the user's literal backslash-u text remains.
    assert '统一输出' in result.output and '\\u7edf' not in result.output.lower()
    assert yaml.safe_load(result.output)['caused_by_event_ids'] == EVENTS
    response = mcp._tool_call_response(1, {'name': 'tasks', 'arguments': {
        'action': 'execute', 'feature': 'continue',
        'arguments': {'task_id': '343', 'caused_by_event_ids': EVENTS}}})
    text = response['result']['content'][0]['text']
    assert '统一输出' in text and '\\u7edf' not in text.lower()
    assert yaml.safe_load(text)['caused_by_event_ids'] == EVENTS
    assert [call['caused_by_event_ids'] for call in received] == [EVENTS, EVENTS]


@pytest.mark.parametrize('value, message', [
    ('[a', 'invalid JSON'), ('"a"', 'JSON array of strings'), ('[1]', 'JSON array of strings'),
])
def test_cli_rejects_a_malformed_event_list(received: list[dict], value: str, message: str) -> None:
    """Invalid JSON and non-string items fail before the core runs."""
    result = CliRunner().invoke(main, ['continue', '--task-id', '343', '--caused-by-event-ids', value])
    assert result.exit_code == 2 and message in result.output
    assert received == []


def test_help_shows_only_the_list_form() -> None:
    """Help documents the JSON array; the repeated singular flag stays hidden."""
    for command in ('continue', 'recover', 'replace'):
        output = CliRunner().invoke(main, [command, '--help']).output
        assert '--caused-by-event-ids JSON' in output
        assert '--caused-by-event-id ' not in output and '--caused-by-event-id:' not in output
