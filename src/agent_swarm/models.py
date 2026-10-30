"""Candidate models of one Runtime connection, from configuration or its native client.

Discovery reads metadata only: it never starts a model turn, never passes
project resources to the native client and never claims that the account may
call a listed model. Credentials never appear in a result; a failed native
query reports only ``status: unknown`` with a fixed instruction.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Mapping


RUNTIMES = ('claude', 'codex', 'pi', 'dsh')

# The provider a configured model belongs to when neither the entry nor the
# connection names one; Pi and DSH catalogs always name their own provider.
DEFAULT_PROVIDERS = {'claude': 'anthropic', 'codex': 'openai'}

AVAILABLE  = 'Native catalog metadata does not establish account calling permission.'
CONFIGURED = 'Configured models; the Runtime was not queried and account calling permission is not established.'
UNKNOWN    = 'Native metadata query failed. Check installation/login in the original Runtime client and refresh.'

TIMEOUT = 30


def discover_models(connection: Mapping[str, Any]) -> dict:
    """Return the candidate models of one ``config.yml`` Runtime connection.

    Parameters
    ----------
    connection : Mapping
        ``runtime`` (``claude``, ``codex``, ``pi`` or ``dsh``) and optional
        ``home`` (the native home directory), ``provider`` and ``models``.
        ``base_url`` and ``api_key_env`` route a DSH query as they route a DSH
        child; the other Runtimes list models without them. A ``models`` list (strings or mappings with ``id`` and optional
        ``alias``, ``provider`` and ``supported_efforts``) is the candidate
        list itself, and the Runtime is not queried. A ``provider`` filters
        the Pi and DSH catalogs, which span providers; Claude and Codex list
        the models of their own configured provider, unfiltered.

    Returns
    -------
    dict
        ``{"runtime", "status", "models", "message"}``. ``status`` is
        ``available`` or ``unknown``; each model is ``{"id", "alias",
        "provider", "supported_efforts"}`` where ``supported_efforts`` is a
        list or ``None`` when the Runtime does not enumerate efforts. A DSH
        result also carries ``provider_status`` (provider id to ``available``
        or ``unknown``).

    Raises
    ------
    ValueError
        The connection names no supported Runtime or its ``models`` list is
        malformed; these are configuration errors, not discovery failures.

    Examples
    --------
    >>> discover_models({'runtime': 'codex', 'models': ['gpt-5']})['models']
    [{'id': 'gpt-5', 'alias': 'gpt-5', 'provider': 'openai', 'supported_efforts': None}]
    """
    runtime = connection.get('runtime')
    if runtime not in RUNTIMES:
        raise ValueError('Choose claude, codex, pi or dsh.')

    if connection.get('models') is not None:
        return {'runtime': runtime, 'status': 'available',
                'models': _configured(connection), 'message': CONFIGURED}

    query = {'claude': _claude, 'codex': _codex, 'pi': _pi_catalog, 'dsh': _dsh}[runtime]
    try:
        # No project resources, extensions or task prompt enter a discovery query.
        with tempfile.TemporaryDirectory(prefix='agents-models-') as directory:
            found = query(connection, Path(directory))
    except Exception:
        # Native diagnostics may contain endpoint credentials; disclose none.
        return {'runtime': runtime, 'status': 'unknown', 'models': [], 'message': UNKNOWN}

    # A successful query keeps the metadata message even when DSH marks every
    # provider unknown; the status carries that outcome.
    return {'runtime': runtime, 'status': 'available', **found, 'message': AVAILABLE}


def _configured(connection: Mapping[str, Any]) -> list[dict]:
    """Normalize a configured candidate list without consulting the Runtime."""
    default = connection.get('provider') or DEFAULT_PROVIDERS.get(connection['runtime'])
    models  = connection['models']
    if not isinstance(models, list):
        raise ValueError('Configured models must be a list.')

    candidates = []
    for entry in models:
        item = {'id': entry} if isinstance(entry, str) else entry
        if (not isinstance(item, Mapping) or not isinstance(item.get('id'), str) or not item['id']
                or set(item) - {'id', 'alias', 'provider', 'supported_efforts'}):
            raise ValueError('A configured model needs an id and only alias, provider or supported_efforts.')
        efforts = item.get('supported_efforts')
        candidates.append({
            'id': item['id'], 'alias': item.get('alias') or item['id'],
            'provider': item.get('provider') or default,
            'supported_efforts': list(efforts) if efforts is not None else None,
        })
    return candidates


def _environment(connection: Mapping[str, Any], variable: str) -> dict[str, str]:
    """Inherit the caller's environment, pointing the native client at the connection's home."""
    environment = dict(os.environ)
    if connection.get('home'):
        environment[variable] = str(connection['home'])
    return environment


def _executable(name: str) -> str:
    """Resolve an installed Runtime client on PATH, or fail without naming anything else."""
    found = shutil.which(name)
    if found is None and name == 'claude':
        # Claude Code's documented native installation path.
        native = Path.home() / '.local/bin/claude'
        found  = str(native) if native.is_file() and os.access(native, os.X_OK) else None
    if found is None:
        raise ValueError('The Runtime client is not installed.')
    return found


def _filter(connection: Mapping[str, Any], models: list[dict]) -> list[dict]:
    """Keep the connection's provider from a catalog that spans providers."""
    provider = connection.get('provider')
    return [model for model in models if provider is None or model['provider'] == provider]


def _run_async(work: Callable[[], Any]) -> Any:
    """Run a coroutine factory to completion, also when the caller already runs a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(work())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(work())).result()


def _codex(connection: Mapping[str, Any], cwd: Path) -> dict:
    """Read the effective provider and every ``model/list`` page from the selected home."""
    from agent_swarm.codex.app_server import CodexAppServer

    environment = {'CODEX_HOME': str(connection['home'])} if connection.get('home') else {}
    command     = (_executable('codex'), 'app-server', '--listen', 'stdio://')

    async def query() -> tuple[dict, list[dict]]:
        """Open one stdio service, read configuration and the catalog, then close it."""
        async with CodexAppServer(cwd=cwd, command=command, environment=environment,
                                  request_timeout=TIMEOUT) as server:
            return await server.read_configuration(cwd), await server.list_models()

    configuration, models = _run_async(query)
    provider = configuration.get('model_provider') or 'openai'
    return {'models': [{
        'id': item['model'], 'alias': item.get('displayName') or item['model'],
        'provider': provider,
        'supported_efforts': [effort['reasoningEffort']
                              for effort in item.get('supportedReasoningEfforts', [])],
    } for item in models]}


def _pi_models(connection: Mapping[str, Any], cwd: Path) -> list[dict]:
    """Return Pi's native ``get_available_models`` records of the connection's home.

    The home is the connection's, else ``PI_CODING_AGENT_DIR``, else Pi's own
    default. No key is passed: Pi lists the models its own login and environment
    authenticate, so discovery never handles a credential value.
    """
    chosen = connection.get('home') or os.environ.get('PI_CODING_AGENT_DIR')
    home   = Path(chosen).expanduser() if chosen else Path.home() / '.pi/agent'
    return _pi_available_models(_executable('pi'), home, cwd)


def write_key_reference(agent: Path, provider: str, api_key_env: str) -> None:
    """Write Pi's private ``auth.json`` in ``agent``, naming the key's variable.

    Pi resolves ``$NAME`` from its environment when it needs the key and prefers
    stored auth to the keys of its model files, so the value is never on a
    command line or in a file. Exclusive creation refuses a remaining entry,
    so a link is never written through.
    """
    descriptor = os.open(agent / 'auth.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({provider: {'type': 'api_key', 'key': '$' + api_key_env}}, stream)


def _private_catalog(home: Path, agent: Path) -> None:
    """Give ``agent`` what Pi's catalog reads from ``home``, besides the native login.

    ``models.json`` may hold a key, so it stays a link. Pi rewrites
    ``models-store.json`` in place when it refreshes, so a copy keeps ``home``
    unwritten. ``settings.json`` feeds no catalog, and its packages would be
    installed afresh into this empty directory.
    """
    if (home / 'models.json').exists():
        (agent / 'models.json').symlink_to((home / 'models.json').resolve())
    if (home / 'models-store.json').exists():
        shutil.copy(home / 'models-store.json', agent)


def _pi_available_models(executable: str, home: Path, cwd: Path, *selection: str,
                         provider: str | None = None, api_key_env: str | None = None) -> list[dict]:
    """Return Pi's available-model records of ``home``, read from a private agent directory in ``cwd``.

    Pi creates its stores in the directory it runs on and installs that
    directory's configured packages outside any sandbox, so it never runs on
    ``home``. ``api_key_env`` becomes the private ``auth.json``; without one a
    link gives Pi the native login, which it locks beside the link and reads
    through, writing only when a login changes.
    """
    agent = cwd / 'agent'
    agent.mkdir()
    if api_key_env:
        write_key_reference(agent, provider, api_key_env)
    elif (home / 'auth.json').exists():
        (agent / 'auth.json').symlink_to((home / 'auth.json').resolve())
    _private_catalog(home, agent)
    completed = subprocess.run(
        [executable, '--mode', 'rpc', '--no-session', '--no-extensions', '--no-skills',
         '--no-prompt-templates', '--no-themes', '--no-context-files', *selection],
        input=json.dumps({'id': 'models', 'type': 'get_available_models'}) + '\n',
        cwd=cwd, env=_environment({'home': agent}, 'PI_CODING_AGENT_DIR'),
        capture_output=True, text=True, timeout=TIMEOUT, check=True,
    )
    for line in completed.stdout.splitlines():
        reply = json.loads(line)
        if reply.get('id') == 'models' and reply.get('success'):
            return reply['data']['models']
    raise ValueError('Pi did not return model metadata.')


def pi_destination(executable: str, home: str, provider: str, model: str, api_key_env: str | None = None) -> str:
    """Return the hostname Pi sends ``provider``/``model`` requests to.

    Reads Pi's own ``get_available_models`` record for the selected model from
    ``home``, through a private agent directory. With ``api_key_env`` that
    directory's ``auth.json`` names the variable, as a launch does, so a model
    that only that key authenticates is listed; without one the native login
    decides. Extension-only or unavailable models, and destinations that are
    not plain http(s) hosts, are refused rather than launched under another
    provider's network grants.
    """
    from urllib.parse import urlsplit
    from agent_swarm.runtime import RuntimeAdapterError, credential_environment

    try:
        if api_key_env:
            credential_environment(api_key_env)
        with tempfile.TemporaryDirectory(prefix='agents-pi-destination-') as directory:
            models = _pi_available_models(executable, Path(home), Path(directory),
                                          '--provider', provider, '--model', model,
                                          provider=provider, api_key_env=api_key_env)
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


def _pi_catalog(connection: Mapping[str, Any], cwd: Path) -> dict:
    """Project Pi's catalog; a reasoning boolean is not an effort enumeration."""
    return {'models': _filter(connection, [{
        'id': model['id'], 'alias': model.get('name') or model['id'],
        'provider': model['provider'], 'supported_efforts': None,
    } for model in _pi_models(connection, cwd)])}


def _dsh(connection: Mapping[str, Any], cwd: Path) -> dict:
    """Read the host-generation catalog of an owned ``dsh web``; never create a Session.

    As for a child, the endpoint and key are the connection's: the parent's
    endpoint variables are removed, and what the connection declares reaches DSH
    through a patch in ``cwd``, so the connection's home gains nothing.
    """
    from agent_swarm.dsh.service import DshService
    from agent_swarm.dsh.settings import AMBIENT_ENDPOINTS

    environment = _environment(connection, 'DSH_HOME')
    for ambient in AMBIENT_ENDPOINTS:
        environment.pop(ambient, None)
    route = {name: connection[field] for name, field in (('baseURL', 'base_url'), ('apiKeyEnv', 'api_key_env'))
             if connection.get(field)}
    options = {}
    if route:
        options['profile_patch'] = cwd / 'discovery.patch.yml'
        options['profile_patch'].write_text(json.dumps([{'id': 'llm-deepseek', 'config': route}]), encoding='utf-8')
    service = DshService(_executable('dsh'), cwd, environment, **options)
    try:
        service.start()
        catalog = service.rpc('session/modelCatalog')
    finally:
        service.close()

    models = _filter(connection, [{
        'id': model['id'], 'alias': model.get('name') or model['id'], 'provider': group['id'],
        'supported_efforts': ([effort['id'] for effort in model['reasoning']['efforts']]
                              if model.get('reasoning') is not None else None),
    } for group in catalog['groups'] for model in group['models']])
    providers = {group['id']: 'available' for group in catalog['groups']}
    providers.update({failure['id']: 'unknown' for failure in catalog.get('failures', [])})

    # Every provider failing leaves the catalog unknown rather than empty.
    return {'models': models, 'provider_status': providers,
            'status': 'available' if models or not catalog.get('failures') else 'unknown'}


def _claude(connection: Mapping[str, Any], cwd: Path) -> dict:
    """Read the official ``initialize`` model catalog without sending user input."""
    command = [_executable('claude'), '--print', '--verbose', '--input-format', 'stream-json',
               '--output-format', 'stream-json', '--restricted', '--tools', '',
               '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}']
    query   = {'type': 'control_request', 'request_id': 'catalog',
               'request': {'subtype': 'initialize'}}

    response = subprocess.run(
        command, input=json.dumps(query) + '\n', text=True, capture_output=True,
        timeout=TIMEOUT, env=_environment(connection, 'CLAUDE_CONFIG_DIR'), cwd=cwd, check=True,
    )
    for line in response.stdout.splitlines():
        event = json.loads(line)
        reply = event.get('response', {})
        if event.get('type') == 'control_response' and reply.get('request_id') == 'catalog':
            if reply.get('subtype') != 'success':
                raise ValueError('Claude initialization failed.')
            return {'models': [{
                'id': item['value'], 'alias': item.get('displayName', item['value']),
                'provider': 'anthropic', 'supported_efforts': item.get('supportedEffortLevels'),
            } for item in reply['response']['models']]}
    raise ValueError('Claude did not expose a model catalog.')
