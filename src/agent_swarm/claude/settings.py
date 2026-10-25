"""Validate explicit native Claude settings without project or role discovery."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from agent_swarm import AgentsError
from .support import credential_environment


def current_cli(executable: str | None = None) -> tuple[str, str]:
    """Return the resolved Claude Code executable and its checked version.

    Without an explicit ``executable``, ``claude`` on PATH or the native
    install link is used. That link names a versioned binary which a Claude
    Code update replaces, so a resume resolves it again.
    """
    executable = executable or shutil.which('claude')
    if executable is None:
        native = Path.home() / '.local/bin/claude'
        executable = str(native) if native.is_file() else None
    if not executable:
        raise AgentsError('RUNTIME_EXECUTABLE_INVALID', 'Claude Code executable is unavailable.')
    try:
        version = subprocess.run([executable, '--version'], capture_output=True, text=True,
                                 check=True, timeout=10).stdout.strip()
        match = re.match(r'(\d+)\.(\d+)\.(\d+) \(Claude Code\)', version)
        if match is None or tuple(map(int, match.groups())) < (2, 1, 299):
            raise ValueError('version')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise AgentsError('RUNTIME_EXECUTABLE_INVALID', 'Claude Code 2.1.299 or later is required.') from error
    return str(Path(executable).resolve()), version


def prepare(configuration: Mapping[str, Any], cwd: Path) -> dict:
    """Freeze native settings and credential references for the original Session."""
    config = dict(configuration)
    allowed = {'executable', 'model', 'reasoning_effort', 'runtime_home', 'base_url',
               'api_key_env', 'instructions', 'worktree_access', 'read_paths', 'permission_mode'}
    if set(config) - allowed:
        raise AgentsError('invalid-config', 'Unknown Claude settings: ' + ', '.join(sorted(set(config) - allowed)))
    executable, version = current_cli(config.get('executable'))
    mode = config.get('permission_mode', 'auto')
    effort = config.get('reasoning_effort')
    access = config.get('worktree_access', 'write')
    model = config.get('model', 'claude-opus-5-5')
    if (mode not in {'default', 'auto'} or access not in {'read', 'write'}
            or effort not in (None, 'low', 'medium', 'high', 'xhigh', 'max')
            or not isinstance(model, str) or not model):
        raise AgentsError('invalid-config', 'Invalid Claude model, effort, access or permission mode.')
    home = Path(config.get('runtime_home') or os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).resolve()
    resources = config.get('read_paths', [])
    if (not isinstance(resources, list)
            or any(not isinstance(p, str) or not Path(p).is_absolute() for p in resources)):
        raise AgentsError('invalid-config', 'Claude read_paths must list absolute resource paths.')
    resources = [str(Path(p).resolve()) for p in resources]
    if any(Path(p).is_relative_to(home) or home.is_relative_to(p) for p in resources):
        raise AgentsError('RUNTIME_ACCESS_DENIED', 'A Claude resource grant would expose the native home.')
    endpoint = config.get('base_url')
    if endpoint:
        from urllib.parse import urlsplit

        url = urlsplit(endpoint)
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username
                or url.password or url.query or url.fragment):
            raise AgentsError('invalid-config', 'Claude Base URL must be credential-free HTTP(S).')
    credential_environment(config.get('api_key_env'))
    return {
        'runtime': 'claude', 'executable': executable, 'version': version,
        'worktree_path': str(cwd.resolve()), 'runtime_home': str(home),
        'explicit_runtime_home': bool(config.get('runtime_home') or os.environ.get('CLAUDE_CONFIG_DIR')),
        'model': model, 'reasoning_effort': effort, 'base_url': endpoint,
        'api_key_env': config.get('api_key_env'), 'instructions': config.get('instructions', ''),
        'worktree_access': access, 'resources': resources,
        'permission_mode': mode, 'permission_mode_source': 'role' if 'permission_mode' in config else 'default',
    }
