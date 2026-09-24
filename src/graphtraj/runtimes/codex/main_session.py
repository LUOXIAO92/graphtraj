"""Start Main through the existing native Adapter with private Runner callbacks."""

from __future__ import annotations

import asyncio
import copy
import fcntl
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.interfaces.mcp import NATIVE_RUNNER_TOOLS, native_runner_tools
from graphtraj.runtimes.codex.access import private_filesystem
from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest
from graphtraj.runtimes.codex.managed_session import run_native_operation
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
    with (record / 'launch.yml').open('a+b') as ownership:
        try:
            fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError('turn-running', 'This Main Session is already executing.') from error
        native_session: str | None = None
        operations: list[dict] = []

        async def handle(request: CodexServerRequest) -> dict:
            """Use native issuer identity for Runner calls, forwarding other requests."""
            if request.method == 'item/tool/call' and request.params.get('tool') in NATIVE_RUNNER_TOOLS:
                result = await run_native_operation(adapter, native_session, None, root, request)
                # Summarize actual callback results without exporting private
                # helper IDs, conversations or report contents to a caller.
                summary = {'tool': request.params['tool'], 'success': result['success'],
                           'from_main': request.params.get('threadId') == native_session}
                if request.params['tool'] == 'graphtraj_status':
                    document = json.loads(result['contentItems'][0]['text'])
                    summary['aliases'] = [
                        {'alias': item.get('alias'), 'has_session': 'session' in item,
                         'has_execution_id': 'execution_id' in item}
                        for item in document.get('aliases', [])
                    ]
                operations.append(summary)
                return result
            return await native_request(request)

        command = (str(runtime_executable('codex')), 'app-server', '--listen', 'stdio://')
        async with CodexAppServer(cwd=root, command=command, on_request=handle,
                                  request_handler_timeout=None, experimental_api=True) as adapter:
            effective = await adapter.read_configuration(root)
            permissions = copy.deepcopy(effective.get('permissions') or {})
            profile = 'graphtraj_main_' + uuid.uuid4().hex
            filesystem = private_filesystem(root / '.codex')
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
                'cwd': str(root), 'dynamicTools': native_runner_tools(),
                'permissions': profile,
                'config': {'permissions': permissions, 'default_permissions': profile},
            })
            if resume is None:
                session = await adapter.create_session(context)
                (record / 'session.yml').write_text(json.dumps({'session': session.thread_id}) + '\n')
            else:
                original = json.loads((record / 'session.yml').read_text())['session']
                session = await adapter.resume_session(context, original)
            native_session = session.thread_id
            adapter.retain_native_trace(session, record / 'events.jsonl')
            execution = await adapter.start_execution(session, instruction)
            result = await adapter.wait(execution)
            (record / 'execution.yml').write_text(json.dumps(result) + '\n')
            return {'record': record.name, 'session': session.thread_id,
                    'native_operations': operations, **result}
