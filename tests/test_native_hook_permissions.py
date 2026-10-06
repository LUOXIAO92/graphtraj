"""Opt-in native hook observations; never use the user's native home.

The execution probe additionally requires explicit approval of trusting the
inert fixture hook, expressed with GRAPHTRAJ_NATIVE_HOOK_TRUST_ONCE=1.
No account material, current-host configuration or trust bypass is used.
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


# Capture only this explicit opt-in before the autouse Runner environment cleanup.
# Never retain or render the surrounding environment in assertion diagnostics.
_TRUST_APPROVED = os.environ.get('GRAPHTRAJ_NATIVE_HOOK_TRUST_ONCE') == '1'


pytestmark = pytest.mark.skipif(
    os.environ.get('GRAPHTRAJ_NATIVE_HOOK_PROBE') != '1',
    reason='Explicit opt-in required for the real native hook permission probe',
)


def require_fixture_trust() -> None:
    """Refuse before native setup unless this invocation explicitly opted in."""
    if not _TRUST_APPROVED:
        pytest.fail(
            'Explicit user approval to trust this exact inert fixture hook is required; '
            'no native setup, turn or trust write was performed.',
            pytrace=False,
        )


@dataclass
class HookContext:
    """Carry fixture parameters to the production Runtime Adapter."""

    parameters: dict
    runtime: str = 'codex'

    def session_document(self) -> dict:
        """Return native thread parameters, with no model turn or identity claim."""
        return {'runtime': self.runtime, 'adapter_request': self.parameters}

    def runtime_environment(self) -> dict:
        """Use the connection's disposable native home."""
        return {}


def prepare_hook_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Write an inert hook that stops its triggering turn before generation.

    Native 0.160.0 runs SessionStart on the first turn, not thread creation.
    The hook stops that turn before generation. Native startup can still
    prewarm the official transport with generate=false; errors are retained
    separately from hook events. No credentials or provider are substituted.
    """
    native_home = tmp_path / 'native-home'
    native_home.mkdir()
    root = tmp_path / 'project'
    root.mkdir()
    private = root / '.graphtraj'
    private.mkdir()
    sentinel = private / 'sentinel'
    sentinel.write_text('disposable-canary', encoding='utf-8')
    code = (
        'import json,sys; from pathlib import Path\n'
        'event=json.load(sys.stdin)\n'
        'try:\n'
        ' Path(sys.argv[1]).read_bytes(); result="read"\n'
        'except PermissionError:\n'
        ' result="denied"\n'
        '(Path(event["cwd"])/"hook.json").write_text(json.dumps('
        '{"result":result,"event":event.get("hook_event_name")}))\n'
        'print(json.dumps({"continue":False,"stopReason":"canary complete"}))\n'
    )
    command = shlex.join([sys.executable, '-c', code, str(sentinel)])
    (native_home / 'hooks.json').write_text(json.dumps({'hooks': {
        'SessionStart': [{'matcher': 'startup', 'hooks': [{
            'type': 'command', 'command': command,
            'statusMessage': 'GraphTraj isolated file permission probe',
        }]}],
    }}))
    (native_home / 'config.toml').write_text(
        '[features]\nhooks = true\n'
    )
    return native_home, root, sentinel


async def loaded_hook(adapter: object, root: Path) -> dict:
    """Inspect the public native registry before attempting a lifecycle trigger."""
    result = await adapter._call('hooks/list', {'cwds': [str(root)]})
    print('hooks/list ' + json.dumps(result), flush=True)
    entries = result.get('data', [])
    assert len(entries) == 1 and not entries[0]['errors'], result
    hooks = entries[0]['hooks']
    assert len(hooks) == 1, 'The disposable user hooks.json was not loaded exactly once'
    hook = hooks[0]
    assert hook['eventName'] == 'sessionStart' and hook['enabled'], hook
    assert hook['handlerType'] == 'command' and not hook['isManaged'], hook
    return hook


async def observe_fixture(tmp_path: Path, *, execute: bool) -> None:
    """Observe registry/trust, then optionally actual hook events on two threads."""
    if execute:
        require_fixture_trust()

    from graphtraj.runtimes.codex.app_server import CodexAppServer, CodexServerRequest

    executable = shutil.which('codex')
    assert sys.platform == 'darwin' and executable, 'Requires native macOS Codex'
    native_home, root, sentinel = prepare_hook_fixture(tmp_path)

    async def refuse_approval(request: CodexServerRequest) -> dict:
        """Fail on additional native review; never invent a decision."""
        raise RuntimeError(f'Unexpected native review required: {request.method}')

    adapter = CodexAppServer(
        cwd=root, command=(executable, 'app-server', '--listen', 'stdio://'),
        environment={'CODEX_HOME': str(native_home)}, on_request=refuse_approval,
        experimental_api=True, request_timeout=10,
    )
    try:
        async with adapter:
            config = await adapter.read_configuration(root)
            assert config['features']['hooks'] is True
            account = await adapter._call('account/read', {'refreshToken': False})
            print(json.dumps({'authenticated': account.get('account') is not None,
                              'requiresOpenaiAuth': account.get('requiresOpenaiAuth')}), flush=True)
            hook = await loaded_hook(adapter, root)
            assert hook['trustStatus'] == 'untrusted', hook
            if not execute:
                return
            # The operator must explicitly approve this fixture-only native trust write.
            # This is not a model-supplied approval or current-host configuration.
            await adapter._call('config/batchWrite', {
                'edits': [{'keyPath': 'hooks.state', 'value': {
                    hook['key']: {'trusted_hash': hook['currentHash']},
                }, 'mergeStrategy': 'upsert'}],
                'filePath': str(native_home / 'config.toml'), 'reloadUserConfig': True,
            })
            trusted = await loaded_hook(adapter, root)
            assert trusted['trustStatus'] == 'trusted', trusted
            assert trusted['currentHash'] == hook['currentHash'], trusted
            for name, access, expected in (
                ('owner', 'read', 'read'), ('other', 'none', 'denied'),
            ):
                cwd = root / name
                cwd.mkdir()
                context = HookContext({
                    'cwd': str(cwd), 'approvalPolicy': 'on-request', 'permissions': name,
                    'config': {'permissions': {name: {
                        'extends': ':workspace', 'filesystem': {
                            str(root): 'write', str(sentinel.parent): 'none',
                            str(sentinel): access,
                        },
                    }}},
                })
                session = await adapter.create_session(context)
                execution = await adapter.start_execution(session, 'Run the inert startup canary.')
                events = []
                try:
                    async with asyncio.timeout(10):
                        while True:
                            event = await adapter.next_notification()
                            params = event.get('params', {})
                            if params.get('threadId') != session.thread_id:
                                continue
                            method = event.get('method')
                            if method in ('hook/started', 'hook/completed', 'turn/completed', 'error'):
                                events.append(event)
                                print(json.dumps(event), flush=True)
                            if method == 'turn/completed':
                                break
                except TimeoutError:
                    await adapter.interrupt(execution)
                    pytest.fail(f'Native lifecycle did not finish: {events}; stderr={adapter.stderr_tail}')
                completed = [e['params']['run'] for e in events if e['method'] == 'hook/completed']
                assert any(e['eventName'] == 'sessionStart' and e['status'] == 'stopped'
                           for e in completed), events
                output = cwd / 'hook.json'
                assert output.is_file(), f'Native hook completed without canary output: {events}'
                result = json.loads(output.read_text())
                print(json.dumps({'profile': name, **result}), flush=True)
                assert result == {'result': expected, 'event': 'SessionStart'}, result
    finally:
        if adapter.stderr_tail:
            print(adapter.stderr_tail, file=sys.stderr)


def test_native_hook_configuration_is_visible_before_start(tmp_path: Path) -> None:
    """Read actual loading/enabled/untrusted metadata without turns or trust writes."""
    asyncio.run(observe_fixture(tmp_path, execute=False))


def test_fixture_trust_opt_in_survives_runner_cleanup() -> None:
    """Exercise authorization propagation without launching any native process."""
    require_fixture_trust()


def test_native_session_hooks_keep_per_thread_file_permissions(tmp_path: Path) -> None:
    """Run trusted inert hooks; missing setup/events must not count as read denial."""
    asyncio.run(observe_fixture(tmp_path, execute=True))
