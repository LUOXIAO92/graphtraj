"""User-owned Runtime connections; credentials remain in their native Runtime."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

from graphtraj import file_lock
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError


NAME = re.compile(r"^[A-Za-z0-9_-]+$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
EFFORTS = {
    'codex': {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'},
    'pi': {'off', 'minimal', 'low', 'medium', 'high', 'xhigh'},
    'dsh': {'off', 'low', 'high', 'max'},
}


def connections_file() -> Path:
    """Return the user-level catalog, independent of the current project."""
    return Path.home() / '.graphtraj' / 'connections.yml'


def _text(path: Path) -> str:
    """Read a regular catalog or represent an absent catalog without creating it."""
    if path.is_symlink():
        raise ValueError('Connections must be a regular file.')
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def validate_catalog(document: object) -> dict:
    """Validate only supported nonsecret fields, without echoing invalid values."""
    if not isinstance(document, dict) or set(document) != {'version', 'runtimes'}:
        raise ValueError('Connections require version and runtimes.')
    if type(document['version']) is not int or document['version'] != 1:
        raise ValueError('Unsupported connections version.')

    def entries(value: object) -> dict:
        """Require named mappings with unambiguous reference components."""
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not NAME.fullmatch(key)
            or not isinstance(item, dict) for key, item in value.items()
        ):
            raise ValueError('Connection entries require names and mappings.')
        return value

    def fields(value: dict, allowed: set[str], required: set[str]) -> None:
        """Reject arbitrary credential containers and unknown parameters."""
        if set(value) - allowed or required - set(value):
            raise ValueError('Unsupported or missing connection fields.')

    for runtime in entries(document['runtimes']).values():
        fields(runtime, {'runtime', 'home', 'providers'}, {'runtime', 'providers'})
        kind = runtime['runtime']
        if not isinstance(kind, str) or kind not in EFFORTS:
            raise ValueError('Choose codex, pi or dsh.')
        if 'home' in runtime and (
            not isinstance(runtime['home'], str) or not Path(runtime['home']).is_absolute()
            or '\x00' in runtime['home']
        ):
            raise ValueError('Runtime home must be an absolute directory path.')
        for provider_id, provider in entries(runtime['providers']).items():
            fields(provider, {'base_url', 'api_key_env', 'api', 'models'}, {'models'})
            endpoint = provider.get('base_url')
            if endpoint is not None:
                if not isinstance(endpoint, str):
                    raise ValueError('Base URL must be HTTP(S) without credentials.')
                parsed = urlsplit(endpoint)
                if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                        or parsed.username or parsed.password or parsed.query or parsed.fragment):
                    raise ValueError('Base URL must be HTTP(S) without credentials, query or fragment.')
                # Remote custom routes must explicitly name their own key. Local
                # servers can be unauthenticated; neither route inherits OAuth.
                if 'api_key_env' not in provider and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
                    raise ValueError('A remote custom provider requires api_key_env.')
            if kind == 'dsh' and not endpoint and provider_id != 'deepseek-official':
                raise ValueError('DSH custom providers require a Messages Base URL.')
            env = provider.get('api_key_env')
            if env is not None and (not isinstance(env, str) or not ENV_NAME.fullmatch(env)):
                raise ValueError('api_key_env must be an environment variable name.')
            if kind == 'codex' and env and not endpoint and provider_id != 'openai':
                raise ValueError('A Codex native provider key override requires its explicit Base URL.')
            api = provider.get('api')
            if api is not None and (not isinstance(api, str) or kind != 'pi' or api not in {
                'openai-completions', 'openai-responses', 'anthropic-messages',
            }):
                raise ValueError('Unsupported provider API for this Runtime.')
            if kind == 'pi' and endpoint and api is None:
                raise ValueError('A custom Pi provider requires api.')
            for model in entries(provider['models']).values():
                fields(model, {'id', 'alias', 'source', 'supported_efforts'}, {'id', 'source'})
                for key in ('id', 'alias'):
                    if key in model and (not isinstance(model[key], str) or not model[key].strip()
                                         or any(ord(c) < 32 for c in model[key])):
                        raise ValueError('Model id and alias must be nonempty text.')
                if not isinstance(model['source'], str) or model['source'] not in {'manual', 'native'}:
                    raise ValueError('Model source must be manual or native.')
                efforts = model.get('supported_efforts')
                if efforts is not None and (not isinstance(efforts, list) or any(
                    not isinstance(item, str) or item not in EFFORTS[kind] for item in efforts
                ) or len(set(efforts)) != len(efforts)):
                    raise ValueError('Unsupported model reasoning efforts.')
    return copy.deepcopy(document)


def read_catalog() -> tuple[dict, str]:
    """Read safe settings and the exact byte revision used for conflict checks."""
    from graphtraj.configuration.project_roles import _UniqueKeyLoader

    text = _text(connections_file())
    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader) if text else {'version': 1, 'runtimes': {}}
        return validate_catalog(document), hashlib.sha256(text.encode('utf-8')).hexdigest()
    except yaml.YAMLError:
        raise ValueError('Connections are not valid YAML.') from None


def resolve_connection(reference: str, effort: str | None) -> dict:
    """Resolve an exact Runtime/provider/model reference into existing role fields."""
    document, revision = read_catalog()
    try:
        runtime_id, provider_id, model_id = reference.split('/')
        runtime = document['runtimes'][runtime_id]
        provider = runtime['providers'][provider_id]
        model = provider['models'][model_id]
    except (ValueError, KeyError):
        raise ValueError('Unknown Runtime/provider/model connection reference.') from None
    supported = model.get('supported_efforts')
    if effort is not None and (effort not in EFFORTS[runtime['runtime']]
                              or supported is not None and effort not in supported):
        raise ValueError('The selected reasoning effort is not supported by this model.')
    homes = {'codex': ('CODEX_HOME', '.codex'), 'pi': ('PI_CODING_AGENT_DIR', '.pi/agent'),
             'dsh': ('DSH_HOME', '.dsh')}
    variable, default = homes[runtime['runtime']]
    home = runtime.get('home') or os.environ.get(variable) or str(Path.home() / default)
    return {
        'runtime': runtime['runtime'],
        'model': f"{provider_id}/{model['id']}" if runtime['runtime'] == 'pi' else model['id'],
        'runtime_home': str(Path(home).resolve()), 'runtime_provider': provider_id,
        'base_url': provider.get('base_url'), 'api_key_env': provider.get('api_key_env'),
        'provider_api': provider.get('api'), 'connection_revision': revision,
        'model_source': model['source'],
    }


def manage_connections(arguments: dict, *, cwd: Path) -> dict:
    """Read, preview, discover or atomically save a natively reviewed catalog.

    Save requires the byte revision returned by read. Review runs before the
    replacement lock; the reviewed bytes are compared again under that lock.
    Existing Sessions keep the resolved configuration captured at dispatch.
    """
    from graphtraj.execution.role_organization import _approve
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory

    action = arguments.get('action', 'read')
    before, revision = read_catalog()
    path = connections_file()
    view = {'scope': 'user', 'path': str(path), 'revision': revision, 'catalog': before,
            'account_access': 'unknown',
            'capabilities': {'read': True, 'preview': True, 'save': True,
                             'model_discovery': {'codex': 'native', 'pi': 'native', 'dsh': 'native-host'},
                             'custom_api': {'codex': ['responses'],
                                            'pi': ['openai-completions', 'openai-responses', 'anthropic-messages'],
                                            'dsh': ['anthropic-messages']}}}
    if action == 'read':
        return view
    if action == 'discover':
        from graphtraj.runtimes.model_discovery import discover_models

        runtime = before['runtimes'].get(arguments.get('runtime'))
        if runtime is None:
            raise ValueError('Choose a configured Runtime entry.')
        return {**view, 'discovery': {
            'runtime_entry': arguments['runtime'], **discover_models(runtime),
        }}
    after = validate_catalog(arguments.get('catalog'))
    if action == 'preview':
        return {**view, 'catalog': after, 'applied': False}
    if action != 'save':
        raise ValueError('Choose read, preview, save or discover.')
    root = discover_project_root(cwd)
    if caller_alias(discover_runner_directory(root)) is not None:
        raise RunnerError('authority-denied', 'Only the owning host may save user connections.')
    if arguments.get('expected_revision') != revision:
        raise RunnerError('configuration-conflict', 'Connections changed; reload before saving.')
    if before == after:
        return {**view, 'applied': False}
    _approve({'scope': 'user', 'path': str(path), 'before': before, 'after': after}, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    lock.touch(exist_ok=True)
    with file_lock.replacement_lock(lock):
        if read_catalog()[1] != revision:
            raise RunnerError('configuration-conflict', 'Connections changed during review; nothing was written.')
        write_yaml_durably(path, after)
    saved, revision = read_catalog()
    return {**view, 'catalog': saved, 'revision': revision, 'applied': True}
