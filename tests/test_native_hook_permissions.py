"""Opt-in observation of actual native hook access, without model turns.

Run with GRAPHTRAJ_NATIVE_HOOK_PROBE=1. The disposable native home contains
only a canary hook; no user configuration, account or hook trust is changed.
This is a prerequisite experiment, not an adoption or credential implementation.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

@dataclass
class HookContext:
    """Carry the isolated fixture's native parameters without changing a host."""

    parameters: dict
    runtime: str = 'codex'

    def session_document(self) -> dict:
        """Return the same native request shape consumed by the production Adapter."""
        return {'runtime': self.runtime, 'adapter_request': self.parameters}

    def runtime_environment(self) -> dict:
        """Use the connection's already selected disposable native home."""
        return {}


@pytest.mark.skipif(
    os.environ.get('GRAPHTRAJ_NATIVE_HOOK_PROBE') != '1',
    reason='Explicit opt-in required for the real native hook permission probe',
)
def test_native_session_hooks_keep_per_thread_file_permissions(tmp_path: Path) -> None:
    """Two threads on one actual server must not share a protected read grant.

    SessionStart avoids a model call. A missing hook or refused startup is a
    failure of the experiment, never a successful access denial. Stop hooks,
    fork inheritance and actual additional-permission approval remain separate.
    """
    from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest

    executable = shutil.which('codex')
    assert sys.platform == 'darwin' and executable, 'Requires native macOS Codex'
    native_home = tmp_path / 'native-home'
    native_home.mkdir()
    root = tmp_path / 'project'
    root.mkdir()
    private = root / '.graphtraj'
    private.mkdir()
    sentinel = private / 'sentinel'
    sentinel.write_text('disposable-canary', encoding='utf-8')

    async def refuse_approval(request: CodexServerRequest) -> dict:
        """Never manufacture a native approval for a setup or hook request."""
        raise RuntimeError(f'Native review required: {request.method}')

    async def observe() -> None:
        """Use one native server for both profiles and collect only canary results."""
        adapter = CodexAppServer(
            cwd=root, command=(executable, 'app-server', '--listen', 'stdio://'),
            environment={'CODEX_HOME': str(native_home)},
            on_request=refuse_approval, experimental_api=True, request_timeout=10,
        )
        try:
            async with adapter:
                for name, access, expected in (
                    ('owner', 'read', 'read'), ('other', 'none', 'denied'),
                ):
                    output = root / f'{name}.json'
                    code = (
                        'import json,sys; from pathlib import Path\n'
                        'event=json.load(sys.stdin)\n'
                        'try:\n'
                        ' Path(sys.argv[1]).read_bytes(); result="read"\n'
                        'except PermissionError:\n'
                        ' result="denied"\n'
                        'Path(sys.argv[2]).write_text(json.dumps('
                        '{"result":result,"event":event.get("hook_event_name")}))\n'
                    )
                    command = shlex.join([sys.executable, '-c', code,
                                          str(sentinel), str(output)])
                    context = HookContext({
                        'cwd': str(root), 'approvalPolicy': 'on-request',
                        'permissions': name,
                        'config': {
                            'permissions': {name: {
                                'extends': ':workspace',
                                'filesystem': {
                                    str(root): 'write', str(private): 'none',
                                    str(sentinel): access,
                                },
                            }},
                            'hooks': {'SessionStart': [{'hooks': [{
                                'type': 'command', 'command': command,
                            }]}]},
                        },
                    })
                    await adapter.create_session(context)
                    async with asyncio.timeout(5):
                        while not output.exists():
                            await asyncio.sleep(0.05)
                    result = json.loads(output.read_text())
                    print(json.dumps({'profile': name, **result}), flush=True)
                    assert result == {'result': expected, 'event': 'SessionStart'}
        finally:
            if adapter.stderr_tail:
                print(adapter.stderr_tail, file=sys.stderr)

    asyncio.run(observe())
