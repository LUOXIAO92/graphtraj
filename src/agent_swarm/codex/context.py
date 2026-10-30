"""Captured Codex native settings; no role or project discovery."""
from __future__ import annotations
import copy
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple
from agent_swarm.runtime import RuntimeAdapterError, RuntimeContext

BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
class CodexAdapterError(RuntimeAdapterError):
    """A selected Codex role cannot be launched safely."""


@dataclass(frozen=True)
class CodexRuntimeContext:
    """Immutable native configuration, safe to retain and restore in a Worker."""

    launch: str
    evidence: str
    environment: Mapping[str, str]
    runtime: str = "codex"

    def launch_document(self) -> Dict[str, Any]:
        """Return the durable Adapter input for launch and resume."""
        return json.loads(self.launch)

    def evidence_document(self) -> Dict[str, Any]:
        """Return the effective Context facts for mechanical evidence."""
        return json.loads(self.evidence)

    def session_document(self) -> Dict[str, Any]:
        """Return the resolved role and access as native thread parameters."""
        return {
            "runtime": self.runtime,
            "adapter_request": self.launch_document()["adapter_request"]["session_parameters"],
        }

    def runtime_environment(self) -> Mapping[str, str]:
        """Return ephemeral connection settings for the Runtime process."""
        return dict(self.environment)


def restore_codex_context(
    request: Mapping[str, Any], evidence: Mapping[str, Any],
) -> RuntimeContext:
    """Restore a Worker's resolved Context without consulting current role defaults."""
    arguments, worktree = validate_codex_launch_request(request)
    params = request.get("session_parameters")
    if params is None:
        # Historical exec launches retain the actual settings in CLI overrides.
        # Reconstruct only those captured values, never current role defaults.
        try:
            config = {}
            for index, argument in enumerate(arguments[:-1]):
                if argument == "-c":
                    config.update(tomllib.loads(arguments[index + 1]))
            model = arguments[arguments.index("--model") + 1]
            params = {
                "cwd": str(worktree), "model": model,
                "developerInstructions": config.pop("developer_instructions"),
                "config": config,
            }
        except (ValueError, IndexError, KeyError, tomllib.TOMLDecodeError) as error:
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID", "The retained Codex CLI Context is invalid.",
            ) from error
        request = {**request, "session_parameters": params}
    if (
        not isinstance(params, dict)
        or params.get("cwd") != request["worktree_path"]
        or not isinstance(params.get("config"), dict)
        or not isinstance(params.get("model"), str)
        or not isinstance(params.get("developerInstructions"), str)
    ):
        raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The native Session Context is invalid.")
    return CodexRuntimeContext(
        json.dumps({"runtime": "codex", "adapter_request": request}),
        json.dumps(evidence), {},
    )


def validate_codex_launch_request(
    request: Mapping[str, Any],
) -> Tuple[List[str], Path]:
    if (
        not isinstance(request, dict)
        or not {"arguments", "worktree_path"}.issubset(request)
        or not set(request).issubset({"arguments", "worktree_path", "session_parameters", "approval", "local_websocket_projection"})
    ):
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request is invalid.",
        )
    arguments = request["arguments"]
    worktree_value = request["worktree_path"]
    if (
        not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(argument, str) for argument in arguments)
        or not isinstance(worktree_value, str)
    ):
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request is invalid.",
        )
    worktree = Path(worktree_value)
    if not worktree.is_absolute() or not worktree.is_dir():
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request is invalid.",
        )
    return arguments, worktree


def reject_legacy_sandbox_config(codex_home: Path | None = None) -> None:
    """Reject legacy sandbox settings in the selected service's configuration."""
    if codex_home is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    config = codex_home / "config.toml"
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return

    profile = document.get("profile")
    profiles = document.get("profiles")
    selected_profile = (
        profiles.get(profile)
        if isinstance(profile, str) and isinstance(profiles, dict)
        else None
    )
    if "sandbox_mode" in document or (
        isinstance(selected_profile, dict) and "sandbox_mode" in selected_profile
    ):
        raise CodexAdapterError(
            "LEGACY_SANDBOX_CONFIG_CONFLICT",
            "The loaded Codex user configuration contains sandbox_mode, "
            "which disables the selected permission profile.",
        )


def apply_unix_socket_access(request: dict, configured: Mapping[str, Any] | None) -> None:
    """Project Main-owned, Worktree-scoped socket grants into native permissions.

    ``codex.unix_sockets`` maps exact absolute Worktrees to socket path lists.
    It does not read Agent-writable native configuration or change filesystem,
    account, approval or external network rules. An explicit empty list revokes
    previously projected socket grants on normal same-Session continuation.
    """
    if configured is None:
        return
    if not isinstance(configured, dict):
        raise _invalid_role_value('codex.unix_sockets')
    for worktree, paths in configured.items():
        if (not isinstance(worktree, str) or not Path(worktree).is_absolute()
                or not isinstance(paths, list)
                or any(not isinstance(path, str) or not Path(path).is_absolute()
                       or any(token in path for token in ('*', '?', '[', '\x00'))
                       or '..' in Path(path).parts for path in paths)):
            raise _invalid_role_value('codex.unix_sockets')
    paths = configured.get(request['worktree_path'])
    if paths is None:
        return
    config = request['session_parameters']['config']
    profile = config['permissions'][config['default_permissions']]
    network = profile.setdefault('network', {})
    # Keep narrower existing external-network policy. No wildcard socket grant
    # or permission to listen on arbitrary local addresses is introduced.
    network.setdefault('enabled', True)
    network.update(allow_local_binding=False, dangerously_allow_all_unix_sockets=False,
                   dangerously_allow_non_loopback_proxy=False)
    previous = network.get('unix_sockets', {})
    network['unix_sockets'] = {**{path: 'deny' for path in previous},
                               **{path: 'allow' for path in paths}}
    config['features'] = {**config.get('features', {}), 'network_proxy': True}
    arguments = request['arguments']
    for key in ('permissions', 'features'):
        for index in range(len(arguments) - 2, -1, -1):
            if arguments[index] == '-c' and arguments[index + 1].startswith(key + '='):
                del arguments[index:index + 2]
        arguments[2:2] = ['-c', key + '=' + _toml_value(config[key])]


def codex_api_key_env(base_url: str | None, name: str | None) -> str | None:
    """Retain the legacy default key only for its official HTTPS API origin."""
    from urllib.parse import urlsplit

    if name is None and base_url is not None:
        parsed = urlsplit(base_url)
        if parsed.scheme == 'https' and parsed.netloc.lower() in {'api.openai.com', 'api.openai.com:443'}:
            return 'OPENAI_API_KEY'
    return name


def _connection_environment(
    base_url: str | None,
    api_key_env: str | None,
    runtime_home: str | None = None,
) -> Mapping[str, str]:
    """Resolve explicit credentials transiently; never fall back to official auth."""

    if runtime_home is None:
        api_key_env = codex_api_key_env(base_url, api_key_env)
    environment = dict(credential_environment(api_key_env))
    if runtime_home is not None:
        environment["CODEX_HOME"] = runtime_home
        # Home-bound references carry routing in native per-Session provider
        # settings. Do not create process-wide overrides inherited by children.
        return environment
    api_key = environment.get(api_key_env) if api_key_env is not None else None
    if base_url is not None:
        environment["OPENAI_BASE_URL"] = base_url
        environment["OPENAI_API_KEY"] = ""
    if api_key is not None:
        environment["OPENAI_API_KEY"] = api_key
    return environment


def codex_connection_environment(
    base_url: str | None,
    api_key_env: str | None,
    runtime_home: str | None = None,
) -> Mapping[str, str]:
    """Return transient overrides for the captured connection on resume."""
    return _connection_environment(base_url, api_key_env, runtime_home)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[{0}]".format(", ".join(_toml_value(item) for item in value))
    if isinstance(value, dict):
        pairs = (
            "{0} = {1}".format(_toml_key(key), _toml_value(item))
            for key, item in value.items()
        )
        return "{{ {0} }}".format(", ".join(pairs))
    raise CodexAdapterError(
        "ROLE_CONFIG_UNSUPPORTED",
        "The configured Codex role contains a value that cannot be translated.",
    )


def _toml_key(value: Any) -> str:
    if not isinstance(value, str):
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "The configured Codex role contains a non-string key.",
        )
    return value if BARE_TOML_KEY.fullmatch(value) else json.dumps(value)


def credential_environment(name: str | None) -> dict[str, str]:
    """Require a named execution credential without retaining or exposing its value."""
    import os
    import re

    if name is None:
        return {}
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'api_key_env must name an environment variable.')
    value = os.environ.get(name)
    if not value:
        raise RuntimeAdapterError('RUNTIME_CREDENTIAL_MISSING', 'The configured api_key_env is missing or empty.')
    return {name: value}


def recovery_environment(connection: Mapping[str, str]) -> Mapping[str, str]:
    """Resolve captured connection values without retaining credential contents."""
    if any(key not in {'base_url', 'api_key_env', 'runtime_home'}
           or not isinstance(value, str) or not value for key, value in connection.items()):
        raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'The retained Codex connection is invalid.')
    return codex_connection_environment(connection.get('base_url'), connection.get('api_key_env'),
                                       connection.get('runtime_home'))


def _invalid_role_value(field: str) -> CodexAdapterError:
    return CodexAdapterError(
        "ROLE_CONFIG_INVALID",
        "The configured Codex role has an invalid {0} value.".format(field),
    )
