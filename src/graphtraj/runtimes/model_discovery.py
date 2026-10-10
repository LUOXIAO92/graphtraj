"""Bounded, metadata-only native queries with a nonsecret output projection."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile


def discover_models(runtime: dict) -> dict:
    """Query native catalogs without creating a turn or testing account access.

    Native diagnostics may contain endpoint credentials, so failures disclose
    only capability and a stable instruction to check the original client.
    DSH uses its host catalog endpoint without creating a Session.
    """
    result = {'runtime': runtime['runtime'], 'source': 'native', 'account_access': 'unknown',
              'models': [], 'supported_efforts': 'unknown', 'catalog_scope': 'runtime'}
    try:
        # No project resources, extensions or task prompt enter a discovery query.
        with tempfile.TemporaryDirectory(prefix='graphtraj-models-') as directory:
            if runtime['runtime'] == 'codex':
                metadata = {'models': asyncio.run(_codex(runtime, Path(directory)))}
            elif runtime['runtime'] == 'pi':
                metadata = {'models': [{
                    'id': model['id'], 'alias': model.get('name') or model['id'],
                    'provider': model['provider'], 'source': 'native',
                    # A reasoning boolean is not an effort enumeration.
                    'supported_efforts': None,
                } for model in _pi(runtime, Path(directory))]}
            else:
                metadata = _dsh(runtime, Path(directory))
        return {**result, 'status': 'available', **metadata,
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
    command = [str(runtime_executable('pi')), '--mode', 'rpc', '--no-session', '--no-extensions',
               '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files']
    if runtime.get('provider') and runtime.get('model'):
        command += ['--provider', runtime['provider'], '--model', runtime['model']]
    if runtime.get('api_key_env'):
        from graphtraj.runtimes.runtime_adapter import credential_environment

        key = credential_environment(runtime['api_key_env'])[runtime['api_key_env']]
        command += ['--api-key', key]
    completed = subprocess.run(
        command,
        input=json.dumps({'id': 'models', 'type': 'get_available_models'}) + '\n',
        cwd=cwd, env=environment, capture_output=True, text=True, timeout=30, check=True,
    )
    for line in completed.stdout.splitlines():
        reply = json.loads(line)
        if reply.get('id') == 'models' and reply.get('success'):
            return reply['data']['models']
    raise ValueError('Pi did not return model metadata.')


def pi_model_domain(home: str, provider: str, model: str, api_key_env: str | None = None) -> str:
    """Resolve a selected native destination without exposing endpoint credentials.

    Extension-only or unavailable models are unsupported by this metadata seam;
    they must not be launched under an unrelated provider's network grants.
    """
    from urllib.parse import urlsplit
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

    try:
        with tempfile.TemporaryDirectory(prefix='graphtraj-pi-destination-') as directory:
            models = _pi({'home': home, 'provider': provider, 'model': model,
                          'api_key_env': api_key_env}, Path(directory))
        selected = next(item for item in models if (item['provider'], item['id']) == (provider, model))
        destination = urlsplit(selected['baseUrl'])
        if (destination.scheme not in {'http', 'https'} or not destination.hostname
                or destination.username or destination.password):
            raise ValueError('Unsupported destination')
        return destination.hostname
    except Exception:
        raise RuntimeAdapterError(
            'ROLE_CONFIG_UNSUPPORTED',
            'Pi did not expose a supported native destination for the selected provider/model.',
        ) from None


def _dsh(runtime: dict, cwd: Path) -> dict:
    """Read the public host-generation catalog; never create or prompt a Session."""
    from graphtraj.runtimes.dsh.service import DshService
    import shutil

    environment = dict(os.environ)
    if runtime.get('home'):
        environment['DSH_HOME'] = runtime['home']
    executable = shutil.which('dsh')
    if executable is None:
        raise ValueError('DSH is unavailable.')
    service = DshService(executable, cwd, environment)
    try:
        service.start()
        catalog = service.rpc('session/modelCatalog')
        models = [{
            'id': model['id'], 'alias': model.get('name') or model['id'],
            'provider': group['id'], 'source': 'native',
            'supported_efforts': ([effort['id'] for effort in model['reasoning']['efforts']]
                                  if model.get('reasoning') is not None else None),
        } for group in catalog['groups'] for model in group['models']]
        providers = {group['id']: 'available' for group in catalog['groups']}
        providers.update({failure['id']: 'unknown' for failure in catalog.get('failures', [])})
        return {'models': models, 'provider_status': providers,
                'status': 'available' if models or not catalog.get('failures') else 'unknown'}
    finally:
        service.close()
