"""Bounded, metadata-only native queries with a nonsecret output projection."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile


def discover_models(runtime: dict, cwd: Path) -> dict:
    """Query native catalogs without creating a turn or testing account access.

    Native diagnostics may contain endpoint credentials, so failures disclose
    only capability and a stable instruction to check the original client.
    DSH's supported adapter has no boot-free model-list operation.
    """
    result = {'runtime': runtime['runtime'], 'source': 'native', 'account_access': 'unknown',
              'models': [], 'supported_efforts': 'unknown', 'catalog_scope': 'runtime'}
    if runtime['runtime'] == 'dsh':
        return {**result, 'status': 'unsupported', 'capability': 'model-list',
                'message': 'DSH has no supported standalone metadata query; configure models manually.'}
    try:
        # No project resources, extensions or task prompt enter a discovery query.
        with tempfile.TemporaryDirectory(prefix='graphtraj-models-') as directory:
            if runtime['runtime'] == 'codex':
                models = asyncio.run(_codex(runtime, Path(directory)))
            else:
                models = _pi(runtime, Path(directory))
        return {**result, 'status': 'available', 'models': models,
                'message': 'Native catalog metadata does not establish account calling permission.'}
    except Exception:
        return {**result, 'status': 'unknown',
                'message': 'Native metadata query failed. Check installation/login in the original Runtime client and refresh.'}


async def _codex(runtime: dict, cwd: Path) -> list[dict]:
    """Read native configuration and every model/list page from the selected Home."""
    from graphtraj.runtimes.codex.app_server import CodexAppServer
    from graphtraj.workspace.runner_project import runtime_executable

    environment = {'CODEX_HOME': runtime['home']} if runtime.get('home') else {}
    async with CodexAppServer(
        cwd=cwd, command=(str(runtime_executable('codex')), 'app-server', '--listen', 'stdio://'),
        environment=environment,
    ) as server:
        config = await server.read_configuration(cwd)
        provider = config.get('model_provider') or 'openai'
        models = await server.list_models()
    return [{
        'id': item['model'], 'alias': item.get('displayName') or item['model'],
        'provider': provider, 'source': 'native',
        'supported_efforts': [effort['reasoningEffort'] for effort in item.get('supportedReasoningEfforts', [])],
    } for item in models]


def _pi(runtime: dict, cwd: Path) -> list[dict]:
    """Use Pi's public RPC catalog query; no prompt or authentication file read."""
    from graphtraj.workspace.runner_project import runtime_executable

    environment = dict(os.environ)
    if runtime.get('home'):
        environment['PI_CODING_AGENT_DIR'] = runtime['home']
    completed = subprocess.run(
        [str(runtime_executable('pi')), '--mode', 'rpc', '--no-session', '--no-extensions',
         '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files'],
        input=json.dumps({'id': 'models', 'type': 'get_available_models'}) + '\n',
        cwd=cwd, env=environment, capture_output=True, text=True, timeout=30, check=True,
    )
    for line in completed.stdout.splitlines():
        reply = json.loads(line)
        if reply.get('id') == 'models' and reply.get('success'):
            return [{
                'id': model['id'], 'alias': model.get('name') or model['id'],
                'provider': model['provider'], 'source': 'native',
                # A reasoning boolean is not a supported effort enumeration.
                'supported_efforts': None,
            } for model in reply['data']['models']]
    raise ValueError('Pi did not return model metadata.')
