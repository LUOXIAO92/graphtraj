"""Execution definitions preserve CLI inputs and the existing authority boundary."""

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import tools
from graphtraj.interfaces.cli import agent_runner
from test_direct_control_authority import _record_direct_session
from test_codex_app_server import peer


@pytest.mark.parametrize('command, operation, arguments', [
    (['status', 'one', 'two', '--operation-total', '--baseline', 'base', '--candidate', 'head'],
     'alias_status', {'aliases': ['one', 'two'], 'operation_total': True,
                      'baseline': 'base', 'candidate': 'head'}),
    (['status'], 'alias_status', {'operation_total': False, 'baseline': None, 'candidate': None}),
    (['requests', 'child', '--execution-id', 'turn'],
     'pending_requests', {'alias': 'child', 'execution_id': 'turn'}),
    (['reply', 'child', '--request-file', 'request.yml', '--response', '{"approved":false}'],
     'reply_to_request', {'alias': 'child', 'request': {'request_id': 'native'},
                          'response': {'approved': False}}),
    (['send', 'child', '--instruction', 'Go', '--caused-by-event-id', 'one',
      '--caused-by-event-id', 'two', '--reports-only'],
     'send_instruction', {'alias': 'child', 'instruction': 'Go',
                           'caused_by_event_ids': ['one', 'two'], 'reports_only': True}),
    (['interrupt', 'child'], 'interrupt', {'alias': 'child'}),
    (['replace', 'child', '--actor', 'user', '--caused-by-event-id', 'cause'],
     'replace', {'alias': 'child', 'actor': 'user', 'caused_by_event_ids': ['cause']}),
    (['continue', '--ticket-id', '205', '--caused-by-event-id', 'cause', '--budget-only'],
     'continue', {'ticket_id': '205', 'caused_by_event_ids': ['cause'], 'budget_only': True}),
    (['cleanup', '--ticket-id', '205'], 'cleanup', {'ticket_id': '205'}),
    (['submit-result', '--commit', 'head', '--result-ref', 'a', '--result-ref', 'b',
      '--evidence-ref', 'report', '--completion', 'Done', '--unresolved', 'Remaining'],
     'submit_result', {'commit': 'head', 'result_refs': ['a', 'b'], 'evidence_refs': ['report'],
                       'completion': 'Done', 'unresolved': ['Remaining']}),
    (['decide-result', '--submission-id', 'submitted', '--commit', 'head', '--decision', 'rejected',
      '--reason', 'Reason', '--evidence-ref', 'report'],
     'decide_result', {'submission_id': 'submitted', 'commit': 'head', 'decision': 'rejected',
                       'reason': 'Reason', 'evidence_refs': ['report']}),
    (['main', '--instruction-file', 'instruction.txt', '--resume', 'main_record'],
     'main', {'instruction': 'Exact instruction\n', 'resume': 'main_record'}),
])
def test_cli_passes_execution_arguments_to_registered_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    operation: str,
    arguments: dict[str, Any],
) -> None:
    """File decoding, repeated flags and optional values reach the shared handler."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, '_budget_notices', nullcontext)
    (tmp_path / 'request.yml').write_text('request_id: native\n')
    (tmp_path / 'instruction.txt').write_text('Exact instruction\n')
    received = []

    def handler(values: Mapping[str, Any], *, cwd: Path, **context: Any) -> tools.ToolResult:
        """Capture transport conversion without invoking control or cleanup."""
        received.append((dict(values), cwd))
        assert set(values) <= tools.TOOLS[operation].input_schema['properties'].keys()
        assert set(tools.TOOLS[operation].input_schema.get('required', [])) <= values.keys()
        if operation == 'main':
            assert callable(context['execute'])
        return tools.ToolResult({'received': dict(values)})

    monkeypatch.setitem(tools.TOOLS, operation, replace(tools.TOOLS[operation], handler=handler))
    result = CliRunner().invoke(agent_runner.main, command)
    assert result.exit_code == 0, result.output
    assert received == [(arguments, tmp_path)]
    assert yaml.safe_load(result.stdout) == {'received': arguments}


@pytest.mark.parametrize('operation, command, document', [
    ('cleanup', ['cleanup', '--ticket-id', '205'], {'error': {'message': 'refused'}}),
    ('alias_status', ['status', 'missing'], {'aliases': [{'alias': 'missing', 'error': {'message': 'missing'}}]}),
    ('alias_status', ['status'], {'agents': [{'alias': 'missing', 'error': {'message': 'missing'}}]}),
])
def test_cli_keeps_operation_failure_document_and_exit(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    command: list[str],
    document: dict[str, Any],
) -> None:
    """A shared failure remains a failed CLI command with its domain document."""
    monkeypatch.setattr(agent_runner, '_budget_notices', nullcontext)
    monkeypatch.setitem(tools.TOOLS, operation, replace(
        tools.TOOLS[operation], handler=lambda *a, **k: tools.ToolResult(document, failed=True),
    ))
    result = CliRunner().invoke(agent_runner.main, command)
    assert result.exit_code == 1
    assert yaml.safe_load(result.stdout) == document
    assert ('refused' if operation == 'cleanup' else 'missing') in result.stderr


@pytest.mark.parametrize('caller, actor', [('parent@s1', 'main'), ('outsider@s1', 'main'), ('outsider@s1', 'user')])
def test_registered_replacement_preserves_real_parent_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caller: str, actor: str,
) -> None:
    """Caller labels cannot bypass the real ownership or native approval check."""
    from graphtraj.teams import team_replacement

    runner = tmp_path / 'runner'
    for alias, parent in [('parent@s1', None), ('child@s1', 'parent@s1'), ('outsider@s1', None)]:
        _record_direct_session(runner, alias, 'engineer', parent)
    monkeypatch.setattr(team_replacement, 'discover_project',
                        lambda *a, **k: SimpleNamespace(runner_directory=runner))
    executed = []

    def stopped(alias: str, label: str, causes: tuple[str, ...], cwd: Path) -> dict:
        """Record entry past real authorization without launching a replacement."""
        executed.append((alias, label, causes, cwd))
        return {'replacement_alias': 'successor'}

    monkeypatch.setattr(team_replacement, '_replace_stopped_session', stopped)
    monkeypatch.delenv('CODEX_ESCALATE_SOCKET', raising=False)
    with runtime_caller(runner, caller):
        result = tools.TOOLS['replace'].handler(
            {'alias': 'child@s1', 'actor': actor, 'caused_by_event_ids': ['cause']}, cwd=tmp_path,
        )
    if caller == 'parent@s1':
        assert result.document == {'replacement_alias': 'successor'}
        assert executed == [('child@s1', actor, ('cause',), tmp_path)]
    else:
        assert result.document['replacement_status'] == 'requires-native-approval'
        assert result.document['native_execution']['arguments']['sandbox_permissions'] == 'require_escalated'
        assert not executed


def test_main_requires_host_transport_and_cli_runs_existing_native_peer(
    tmp_path: Path, peer: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery supplies no approval channel; the CLI retains the real native path."""
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.runtimes.codex import main_session

    with pytest.raises(RunnerError) as error:
        tools.TOOLS['main'].handler({'instruction': 'Run'}, cwd=tmp_path)
    assert error.value.code == 'unsupported-operation'
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_runner, '_budget_notices', nullcontext)
    monkeypatch.setattr(main_session, 'runtime_executable', lambda runtime: peer)
    monkeypatch.setenv('PEER_NATIVE_ROLLOUT', str(tmp_path / 'native'))
    instruction = tmp_path / 'instruction.txt'
    instruction.write_text('first')
    command = ['main', '--instruction-file', str(instruction)]
    first = CliRunner().invoke(agent_runner.main, command)
    assert first.exit_code == 0, first.output
    created = yaml.safe_load(first.stdout)
    instruction.write_text('second')
    second = CliRunner().invoke(agent_runner.main, [*command, '--resume', created['record']])
    assert second.exit_code == 0, second.output
    resumed = yaml.safe_load(second.stdout)
    assert resumed['session'] == created['session']
    assert resumed['last_agent_message'] == 'second'
