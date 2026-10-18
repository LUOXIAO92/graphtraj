"""Start Main through the existing native Adapter with private Runner callbacks."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
from contextlib import ExitStack
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from graphtraj import file_lock
from graphtraj.runtimes.codex.jsonl_archive import CodexJsonlArchive
from graphtraj.interfaces.agents import configured_archive
from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.runtimes.codex.codex_adapter import (
    CODEX_PERMISSION_REQUEST_FEATURES,
)
from graphtraj.runtimes.codex.access import private_filesystem
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.workspace.runner_project import discover_runner_directory, runtime_executable


@dataclass(frozen=True)
class _MainContext:
    """Project access without selecting Main's model, provider or approval policy."""

    parameters: dict
    runtime: str = 'codex'

    def session_document(self) -> dict:
        """Return native parameters without sharing mutable configuration."""
        return {'runtime': self.runtime, 'adapter_request': copy.deepcopy(self.parameters)}

    def runtime_environment(self) -> dict:
        """Keep the account and connection environment selected by the user."""
        return {}


async def run_main(
    root: Path,
    instruction: str,
    resume: str | None,
    native_request: Callable[[CodexServerRequest], Awaitable[dict]],
) -> dict:
    """Run one Main turn; native user requests keep their original response format.

    A formal Agent cannot become Main in its own Harness. New Main records use
    separate Main storage; resuming one keeps its native identity and
    originally registered tools. No Team or child-role preset is created.
    """
    configuration = load_project_configuration(root)
    runner = discover_runner_directory(root)
    if caller_alias(runner) is not None:
        raise RunnerError('authority-denied', 'A managed Agent cannot start Main in its Harness.')
    if not instruction.strip():
        raise RunnerError('invalid-input', 'Main requires an instruction.')
    if resume is not None and re.fullmatch(r'main_[0-9a-f]{32}', resume) is None:
        raise RunnerError('invalid-input', 'Resume requires a Main record returned by this entry.')
    # Formal status enumeration expects an alias mapping for every sessions/
    # entry. Main owns a native Session, but is not a formal Agent alias.
    record = runner / 'main-sessions' / (resume or ('main_' + uuid.uuid4().hex))
    if resume is None:
        record.mkdir(parents=True, exist_ok=False)
    # Same-Session continuation cannot create a second active Main driver.
    with (record / 'launch.yml').open('a+b') as ownership, ExitStack() as connections:
        try:
            file_lock.flock(ownership, file_lock.LOCK_EX | file_lock.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError('turn-running', 'This Main Session is already executing.') from error
        native_session: str | None = None
        operations: list[dict] = []

        command = (str(runtime_executable('codex')), 'app-server', '--listen', 'stdio://')
        async with CodexAppServer(cwd=root, command=command, on_request=native_request,
                                  request_handler_timeout=None, experimental_api=True) as adapter:
            from agent_swarm import Caller
            from graphtraj.execution.runner_connection import worker_connection
            from graphtraj.execution.runner_status import runtime_caller
            from graphtraj.interfaces.agents import agents_callback
            from graphtraj.interfaces.gateway import handle_request
            from graphtraj.runtimes.codex.managed_session import authorize_mcp_caller

            loop = asyncio.get_running_loop()

            def operate(document: dict) -> dict:
                """Bind only this native Main's authenticated stdio MCP requests."""
                if set(document) != {'cwd', 'request', 'native'} or document['cwd'] != str(root):
                    raise RunnerError('authority-denied', 'The request is outside this Main host.')
                identity, features = asyncio.run_coroutine_threadsafe(authorize_mcp_caller(
                    adapter, native_session, None, root, root, document['native'],
                ), loop).result(timeout=30)
                request = document['request']
                with runtime_caller(runner, identity):
                    if (identity is None and request.get('action') == 'execute'
                            and request.get('feature') == 'agents'):
                        result = agents_callback(root, Caller('runtime-mcp', None,
                                                 session=native_session, runtime='codex'))(request['arguments'])
                    else:
                        result = handle_request(request, cwd=root, allowed_features=features)
                operations.append({'feature': request.get('feature'), 'success': not result.failed})
                return {'document': result.document, 'failed': result.failed}

            address = connections.enter_context(worker_connection(
                record, operate, authenticate=adapter.authenticate_caller,
            ))
            effective = await adapter.read_configuration(root)
            permissions = copy.deepcopy(effective.get('permissions') or {})
            profile = 'graphtraj_main_' + uuid.uuid4().hex
            filesystem = private_filesystem(root / '.codex')
            filesystem[address] = 'write'
            filesystem[':workspace_roots'] = {'.': 'read'}
            filesystem[str(configuration.docs)] = 'write'
            filesystem[str(root / 'CONTEXT.md')] = 'write'
            filesystem[str(root / '.agents')] = 'write'
            filesystem[str(root / '.graphtraj/scratch')] = 'write'
            filesystem[str(configuration.integration_worktree)] = 'write'
            permissions[profile] = {
                'extends': effective.get('default_permissions') or ':workspace',
                'filesystem': filesystem,
            }
            context = _MainContext({
                'cwd': str(root),
                'permissions': profile,
                'config': {
                    'permissions': permissions, 'default_permissions': profile,
                    'features': dict(CODEX_PERMISSION_REQUEST_FEATURES),
                    'mcp_servers': {'graphtraj': {
                        'command': sys.executable, 'args': ['-m', 'graphtraj.interfaces.mcp'],
                        'cwd': str(root), 'env': {'GRAPHTRAJ_CLI_CONNECTION': address,
                                                'GRAPHTRAJ_NATIVE_RUNTIME': 'codex'},
                    }},
                    'shell_environment_policy': {'set': {'GRAPHTRAJ_CLI_CONNECTION': address,
                                                        'GRAPHTRAJ_NATIVE_RUNTIME': 'codex'}},
                },
            })
            if resume is None:
                session = await adapter.create_session(context)
                (record / 'session.yml').write_text(json.dumps({'session': session.thread_id}) + '\n')
            else:
                original = json.loads((record / 'session.yml').read_text())['session']
                session = await adapter.resume_session(context, original)
            native_session = session.thread_id
            adapter.retain_native_trace(session, record / 'events.jsonl', archive=CodexJsonlArchive(
                configured_archive(root), 'main', session.thread_id, session.rollout_path,
                new_session=resume is None,
            ))
            execution = await adapter.start_execution(session, instruction)
            result = await adapter.wait(execution)
            (record / 'execution.yml').write_text(json.dumps(result) + '\n')
            return {'record': record.name, 'session': session.thread_id,
                    'native_operations': operations, **result}
