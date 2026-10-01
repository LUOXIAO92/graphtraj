"""Bind a Main completion check to its existing host and native Session."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.graph.ticket_graph import read_graph
from graphtraj.runtimes.runtime_adapter import current_host_connection, select_runtime_adapter
from graphtraj.workspace.runner_project import discover_runner_directory


def bind_main_finalize(summary_issue: str, cwd: Path) -> dict[str, Any]:
    """Capture the actual root caller; return hook material for host adoption.

    No identity, model or connection is accepted from operation arguments.
    This records Session ownership, not a second task-completion state.
    """
    runner = discover_runner_directory(cwd)
    if caller_alias(runner) is not None:
        raise RunnerError('authority-denied', 'Only the owning Main can bind its completion check.')
    if not summary_issue.strip():
        raise ValueError('A summary Issue reference is required.')
    connection = current_host_connection()
    if connection is None:
        raise RunnerError('unsupported-operation', 'The current native Main host is unavailable.')
    adapter = select_runtime_adapter(connection['runtime'])
    session = adapter.verify_finalize_main(connection)
    # Forks need not have a native child marker. Their Runner creation binding
    # still prevents a checker from registering itself as another Main.
    for path in (runner / 'main-sessions').glob('*/checks/*/session.yml'):
        child = yaml.safe_load(path.read_text(encoding='utf-8'))
        if child['runtime'] == connection['runtime'] and child['session'] == session:
            raise RunnerError('authority-denied', 'A bound checker cannot register Main completion.')
    configuration = load_project_configuration(cwd)
    key = hashlib.sha256((connection['runtime'] + ':' + session).encode()).hexdigest()
    directory = runner / 'main-sessions' / ('finalize_' + key)
    binding = {
        'runtime': connection['runtime'], 'session': session,
        'connection': connection, 'summary_issue': summary_issue,
        'cwd': str(configuration.harness_root),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'session.yml'
    if path.exists():
        previous = yaml.safe_load(path.read_text())
        if any(previous.get(key) != binding[key]
               for key in ('runtime', 'session', 'connection', 'cwd')):
            raise RunnerError('authority-denied', 'This Main already has a different Session binding.')
    write_yaml_durably(path, binding)
    return {'binding': str(path), 'session': session,
            'hook': adapter.finalize_hook(path, binding)}


def parse_check_result(text: str) -> dict[str, Any]:
    """Validate the checker result without interpreting or persisting task truth."""
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {'status', 'reason', 'nodes'}:
        raise ValueError('The completion checker must return status, reason and nodes.')
    if result['status'] not in ('completed', 'waiting', 'actionable', 'error'):
        raise ValueError('The completion checker returned an unknown status.')
    if not isinstance(result['reason'], str) or not result['reason'].strip():
        raise ValueError('The completion checker returned no reason.')
    nodes = result['nodes']
    if not isinstance(nodes, list) or any(not isinstance(n, str) or not n.strip() for n in nodes):
        raise ValueError('Completion nodes must be nonempty Ticket identifiers or URLs.')
    if result['status'] == 'actionable' and not nodes:
        raise ValueError('Actionable work must identify concrete unfinished nodes.')
    return result


def check_main_finalize(binding_file: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Handle one trusted host event through its Adapter and existing Task Graph.

    The host, not the model tool gateway, supplies the lifecycle event. The
    Adapter filters other Sessions and interruptions before any checker starts.
    Every actual child Session is retained with its creation-time parent binding.
    """
    binding = yaml.safe_load(binding_file.read_text(encoding='utf-8'))
    adapter = select_runtime_adapter(binding['runtime'])
    context = adapter.finalize_event(binding, event)
    if context is None:
        return adapter.finalize_response(None, False)
    try:
        root = Path(binding['cwd'])
        configuration = load_project_configuration(root)
        graph = read_graph(configuration.state)
        prompt = files('graphtraj').joinpath('prompts/main_finalize_check.md').read_text(encoding='utf-8')
        prompt += '\n\n' + json.dumps({
            'summary_issue': binding['summary_issue'], 'task_graph': graph,
        }, ensure_ascii=False)
        child_binding: tuple[str, Path] | None = None

        def created(child: str) -> None:
            """Bind only a fresh native handle returned to this Main's Adapter."""
            nonlocal child_binding
            if child_binding is not None:
                raise ValueError('One Stop cannot bind multiple completion checkers.')
            if not isinstance(child, str) or not child or child == binding['session']:
                raise ValueError('The checker did not create a distinct native Session.')
            key = hashlib.sha256(child.encode()).hexdigest()
            directory = binding_file.parent / 'checks' / key
            directory.mkdir(parents=True, exist_ok=False)
            write_yaml_durably(directory / 'session.yml', {
                'runtime': binding['runtime'], 'session': child,
                'parent': binding['session'], 'parent_connection': binding['connection'],
                'summary_issue': binding['summary_issue'],
            })
            child_binding = (child, directory)

        native = adapter.check_main_finalize(binding, context, prompt, created)
        if native is None:  # The owning host stopped while the checker ran.
            return adapter.finalize_response(None, False)
        if child_binding is None or native.get('session') != child_binding[0]:
            raise ValueError('The completion result does not belong to the bound child.')
        write_yaml_durably(child_binding[1] / 'execution.yml', native)
        result = parse_check_result(native['output'])
    except Exception as error:
        result = {'status': 'error', 'reason': f'Completion check failed: {error}', 'nodes': []}
    return adapter.finalize_response(result, context['continued'])
