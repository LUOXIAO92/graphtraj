"""Explicit Harness-owned connection to an existing loopback Codex service."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def validate_connection(value: Any) -> dict | None:
    """Validate one opt-in service without accepting remote or arbitrary endpoints."""
    if value is None:
        return None
    if (not isinstance(value, dict)
            or set(value) != {'url', 'codex_home', 'token_file', 'worktrees'}
            or value['url'] != 'ws://127.0.0.1:45345/rpc'
            or not isinstance(value['worktrees'], list) or not value['worktrees']):
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Invalid codex.local_websocket configuration.')
    paths = [value['codex_home'], value['token_file'], *value['worktrees']]
    if any(not isinstance(p, str) or not Path(p).is_absolute()
           or '..' in Path(p).parts or any(c in p for c in '*?[\x00') for p in paths):
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'local_websocket requires exact absolute paths.')
    return copy.deepcopy(value)


def configured_connection(cwd: Path, home: str) -> dict | None:
    """Read the owning Harness configuration, never connection fields from events."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.workspace.runner_project import discover_project_root

    try:
        root = discover_project_root(cwd)
    except RunnerError as error:
        if error.code == 'PROJECT_NOT_FOUND':
            return None
        raise
    value = validate_connection((load_project_configuration(root).codex or {}).get('local_websocket'))
    if value is None or str(cwd.absolute()) not in value['worktrees']:
        return None
    if home != value['codex_home']:
        raise RuntimeAdapterError('authority-denied', 'Configured WebSocket belongs to another Codex home.')
    return value


def project_access(request: dict, value: Any) -> None:
    """Project and revoke only the explicit host and token-file grants on resume.

    Native domain policy is host-wide: this does not provide port isolation.
    The prior values are retained so withdrawal restores rather than broadens them.
    """
    value = validate_connection(value)
    config = request['session_parameters']['config']
    profile = config['permissions'][config['default_permissions']]
    previous = request.pop('local_websocket_projection', None)
    if previous:
        network = profile['network']
        domains = network['domains']
        for mapping, key, saved in (
            (domains, '127.0.0.1', previous['domain']),
            (profile['filesystem'], previous['token_file'], previous['file']),
        ):
            if saved is None:
                mapping.pop(key, None)
            else:
                mapping[key] = saved
        if not domains and not previous['had_domains']:
            network.pop('domains')
        for key, saved in previous['network'].items():
            if saved is None:
                network.pop(key, None)
            else:
                network[key] = saved
        if not network and not previous['had_network']:
            profile.pop('network')
        features = dict(config.get('features', {}))
        if previous['proxy'] is None:
            features.pop('network_proxy', None)
        else:
            features['network_proxy'] = previous['proxy']
        config['features'] = features
    if value and request['worktree_path'] in value['worktrees']:
        if (config.get('features', {}).get('network_proxy') is not True
                or profile.get('network', {}).get('enabled') is not True):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID',
                                      'local_websocket requires an already enabled native network proxy.')
        had_network = 'network' in profile
        network = profile['network']
        if network.get('enabled') is False:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'local_websocket conflicts with disabled network.')
        had_domains = 'domains' in network
        domains = network.setdefault('domains', {})
        token = value['token_file']
        # Explicit denials are not converted to grants by this resource projection.
        if domains.get('127.0.0.1') == 'deny' or profile['filesystem'].get(token) == 'deny':
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'local_websocket conflicts with an explicit deny.')
        request['local_websocket_projection'] = {
            'domain': domains.get('127.0.0.1'), 'file': profile['filesystem'].get(token),
            'token_file': token, 'had_domains': had_domains, 'had_network': had_network,
            'network': {key: network.get(key) for key in (
                'enabled', 'allow_local_binding', 'dangerously_allow_all_unix_sockets',
                'dangerously_allow_non_loopback_proxy')},
            'proxy': config.get('features', {}).get('network_proxy'),
        }
        domains['127.0.0.1'] = 'allow'
        profile['filesystem'][token] = 'read'
        network.setdefault('enabled', True)
        network.update(allow_local_binding=False, dangerously_allow_all_unix_sockets=False,
                       dangerously_allow_non_loopback_proxy=False)
        config['features'] = {**config.get('features', {}), 'network_proxy': True}
    if value or previous:
        from graphtraj.runtimes.codex.codex_adapter import _toml_value
        arguments = request['arguments']
        for key in ('permissions', 'features'):
            for index in range(len(arguments) - 2, -1, -1):
                if arguments[index] == '-c' and arguments[index + 1].startswith(key + '='):
                    del arguments[index:index + 2]
            arguments[2:2] = ['-c', key + '=' + _toml_value(config[key])]
