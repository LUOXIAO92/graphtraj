"""The ``tasks`` entry a subagents-created, Task-free child Agent reaches.

A child created through ``subagents`` has no Task, Team or Runner alias. It still
uses GraphTraj's general methods through the same product entry as a Task
member: progressive ``tasks`` discover/describe, which returns the installed
manual's ``manual_ref``. Nothing is copied and no second source exists.

Deliberate limit (551): only the general method features are exposed. They
are describe-only; no execution feature (``submit_result``, ``decide_result``,
``swarm``, ``task_graph`` ...) is offered, so such a request answers
``Unknown feature`` through the gateway's existing ``allowed_features`` gate.
``task_graph`` stays out because some of its revision branches only refuse a
caller that is Main-or-member by checking ``caller_alias is not None``; a
Task-free caller there is not provably refused. Every call still runs with the
child's own Agent ID bound as the native caller: never ``None`` (Main) and
never its parent's alias.
"""
from __future__ import annotations

from pathlib import Path

from graftling import AgentsResult

from graphtraj.interfaces.tools import METHOD_FEATURE_NAMES

# What a Task-free child may discover and describe.
TASK_FREE_FEATURES = frozenset(METHOD_FEATURE_NAMES)

TASKS_DESCRIPTION = 'Discover, describe, or execute Task features.'

# The names of the tools task_free_tools declares beside subagents.
TASK_FREE_TOOL_NAMES = ('tasks',)


def manuals_directory() -> Path:
    """Return the installed directory holding the delivered method manuals."""
    from graphtraj.interfaces.gateway import delivered_manuals_root

    return delivered_manuals_root() / 'manuals'


def serve_task_free(root: Path, agent: str, request: object) -> AgentsResult:
    """Answer one ``tasks`` request from Task-free child ``agent`` of project ``root``."""
    from graphtraj.configuration.project_configuration import runner_directory
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import ALIAS, runtime_caller
    from graphtraj.interfaces.gateway import handle_request

    if not isinstance(agent, str) or not agent or ALIAS.fullmatch(agent):
        # A Runner alias is a Task member's identity, never a Task-free child's.
        return AgentsResult({'error': {'code': 'authority-denied',
                                       'message': 'A Task-free child needs its own Agent identity.'}}, failed=True)
    if not isinstance(request, dict):
        return AgentsResult({'error': 'Expected an object request.'}, failed=True)
    if request.get('feature') == 'subagents':
        return AgentsResult({'error': {'code': 'invalid-input',
                                       'message': 'Use the subagents entry for Agent controls.'}}, failed=True)
    try:
        with runtime_caller(runner_directory(Path(root)), agent):
            result = handle_request(request, cwd=Path(root), allowed_features=TASK_FREE_FEATURES)
    except RunnerError as error:
        return AgentsResult({'error': {'code': error.code, 'message': error.message}}, failed=True)
    return AgentsResult(result.document, failed=result.failed)


def task_free_tools(root: Path, agent: str) -> list[tuple[dict, object]]:
    """Return the ``tasks`` tool for graftling's ``extra_tools`` hook, bound to ``agent``."""
    from graphtraj.interfaces.gateway import INPUT_SCHEMA

    descriptor = {'name': 'tasks', 'description': TASKS_DESCRIPTION, 'inputSchema': INPUT_SCHEMA}
    return [(descriptor, lambda arguments: serve_task_free(root, agent, arguments))]
