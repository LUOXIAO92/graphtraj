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


# Oldest native DSH whose service protocol the driver uses.
MINIMUM_VERSION = '0.2.0-rc.2'


def version_order(version: str) -> tuple:
    """Return a semver sort key: release numbers, then prerelease identifiers.

    A release sorts after its prereleases; numeric identifiers compare as
    numbers and before alphanumeric ones (so alpha < beta < rc).
    """
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', version)
    if match is None:
        raise ValueError(f'Not a semantic version: {version!r}.')
    release = tuple(int(part) for part in match.groups()[:3])
    if match[4] is None:
        return release, (1,)
    return release, (0, *((0, int(part), '') if part.isdigit() else (1, 0, part) for part in match[4].split('.')))


def resumes_by_address(package: str | None) -> bool:
    """Whether the installed DSH resumes a stored Session by addressing it.

    DSH after 0.2.0-rc.2 mints a new Session from ``session/create`` once the
    named one has a turn (dsh-api-session-controller lib/index.js:345-365) and
    resumes a stored Session on any Session-addressed call (:160-213). An
    unreadable version keeps the 0.2.0-rc.2 ``session/create`` path.
    """
    try:
        version = json.loads(Path(package).read_text(encoding='utf-8'))['version']
        return version_order(version) > version_order(MINIMUM_VERSION)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def dsh_version_refusal(package: str | Path) -> str | None:
    """Return why the DSH with this ``package.json`` cannot run, or ``None`` when it can.

    Older than ``MINIMUM_VERSION`` in semver order, or a version that cannot be
    read, is refused; no newer DSH is refused for its version.

    Examples
    --------
    >>> dsh_version_refusal('/no/such/package.json')
    'DSH 0.2.0-rc.2 or later is required (installed unknown).'
    """
    installed = 'unknown'
    try:
        installed = json.loads(Path(package).read_text(encoding='utf-8'))['version']
        if version_order(installed) >= version_order(MINIMUM_VERSION):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return f'DSH {MINIMUM_VERSION} or later is required (installed {installed}).'


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
    refusal = dsh_version_refusal(package)
    if refusal is not None:
        raise DshError('RUNTIME_UNSUPPORTED', refusal)
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
