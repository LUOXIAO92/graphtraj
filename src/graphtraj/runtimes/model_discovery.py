"""Bounded, metadata-only native queries with a nonsecret output projection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile


def discover_models(runtime: dict) -> dict:
    """Query native catalogs through agents without a turn or an account check.

    ``runtime`` is one entry of the user connections catalog; only its
    ``runtime`` and ``home`` select the native catalog, as before. The agents
    result is projected onto GraphTraj's existing document: models and the
    whole catalog are marked ``native`` and account access stays unknown.
    """
    from agent_swarm import discover_models as agents_discover_models

    # The catalog's provider/model entries are GraphTraj's manual records and
    # must not replace the native query, so no ``models`` key is passed.
    connection = {'runtime': runtime['runtime']}
    if runtime.get('home'):
        connection['home'] = runtime['home']
    found = agents_discover_models(connection)

    document = {'runtime': found['runtime'], 'source': 'native', 'account_access': 'unknown',
                'models': [{**model, 'source': 'native'} for model in found['models']],
                'supported_efforts': 'unknown', 'catalog_scope': 'runtime',
                'status': found['status']}
    if 'provider_status' in found:
        document['provider_status'] = found['provider_status']
    return {**document, 'message': found['message']}


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
