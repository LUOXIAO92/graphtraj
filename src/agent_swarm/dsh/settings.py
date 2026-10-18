"""Explicit DSH launch settings; no Task, Git or GraphTraj role discovery."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
from typing import Mapping, Any
from urllib.parse import urlsplit

from .errors import DshError


def credential_environment(name: str | None) -> dict[str, str]:
    """Read only the explicitly named credential, without retaining its value."""
    if name is None:
        return {}
    if not isinstance(name, str) or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) is None:
        raise DshError('ROLE_CONFIG_INVALID', 'api_key_env must name an environment variable.')
    value = os.environ.get(name)
    if not value:
        raise DshError('RUNTIME_CREDENTIAL_MISSING', 'The configured api_key_env is missing or empty.')
    return {name: value}


def prepare(configuration: Mapping[str, Any], cwd: Path) -> dict:
    """Validate caller-owned native settings and freeze a resumable request.

    The host supplies the existing model, effort, permission mode and optional
    native home/provider endpoint. Credentials remain environment references.
    No configuration search, model discovery, inference or global write occurs.
    """
    settings = deepcopy(dict(configuration))
    executable = settings.get('executable') or shutil.which('dsh')
    if not executable:
        raise DshError('RUNTIME_UNAVAILABLE', 'Install the native DSH runtime first.')
    package = Path(executable).resolve().parent.parent / 'package.json'
    try:
        if json.loads(package.read_text(encoding='utf-8'))['version'] != '0.2.0-rc.2':
            raise ValueError('version')
    except (OSError, ValueError, KeyError) as error:
        raise DshError('RUNTIME_UNSUPPORTED', 'DSH 0.2.0-rc.2 is required.') from error
    if not isinstance(settings.get('model'), str) or not settings['model']:
        raise DshError('ROLE_CONFIG_INVALID', 'Supply the actual native DSH model.')
    if settings.get('sandbox') not in {'read-only', 'workspace-write'}:
        raise DshError('ROLE_CONFIG_INVALID', 'Supply the existing native permission mode.')
    if settings.get('reasoning_effort') not in {None, 'off', 'low', 'high', 'max'}:
        raise DshError('ROLE_CONFIG_UNSUPPORTED', 'Unsupported DSH reasoning effort.')
    if settings.get('base_url'):
        parsed = urlsplit(settings['base_url'])
        if (parsed.scheme not in {'https', 'http'} or not parsed.netloc or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise DshError('ROLE_CONFIG_INVALID', 'Supply a credential-free native provider endpoint.')
    credential_environment(settings.get('api_key_env'))
    return {
        **settings, 'executable': str(executable), 'package': str(package),
        'worktree_path': str(Path(cwd).resolve()), 'provider': 'deepseek-official',
        'reasoning_effort': settings.get('reasoning_effort'),
        'instructions': settings.get('instructions', ''), 'connection': True,
    }
