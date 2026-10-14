"""Prepare Claude Code's structured CLI without changing user configuration."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

import yaml

from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import (
    RuntimeAdapterError, SessionStarted, credential_environment,
    current_recovery_reviewer, finalize_usage,
)


MINIMUM_VERSION = (2, 1, 299)
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')


def executable() -> str:
    """Find the official CLI on PATH or its documented native installation path."""
    found = shutil.which('claude')
    native = Path.home() / '.local/bin/claude'
    if found is None and native.is_file() and os.access(native, os.X_OK):
        found = str(native)
    if found is None:
        raise RuntimeAdapterError('RUNTIME_EXECUTABLE_INVALID', 'Claude Code executable is unavailable.')
    return str(Path(found).resolve())


def unsupported(*args: object, **kwargs: object) -> Any:
    """Fail closed for interactive Main hosting, outside this child Adapter."""
    raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'Claude Code interactive Main hosting is unavailable.')


def _validated_resources(value: object, root: Path, state: Path, home: Path) -> list[str]:
    """Validate explicit read grants against the same private paths on launch and resume."""
    if (not isinstance(value, list)
            or any(not isinstance(path, str) or not Path(path).is_absolute() for path in value)):
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'claude.read_paths must list absolute resource paths.')
    protected = (state, root / '.graphtraj/runner', root / '.graphtraj/cli',
                 root / '.codex', Path.home() / '.codex', home)
    for resource in value:
        path = Path(resource).resolve()
        if any(path.is_relative_to(item.resolve()) or item.resolve().is_relative_to(path) for item in protected):
            raise RuntimeAdapterError('RUNTIME_ACCESS_DENIED', 'A Claude resource grant would expose private control/history.')
    return list(value)


@dataclass(frozen=True)
class ClaudeContext:
    """Immutable native launch and configuration provenance, without credentials."""

    document: str
    runtime: str = 'claude'

    def finalize(self) -> ClaudeContext:
        """Return the prepared native settings."""
        return self

    def launch_document(self) -> dict:
        """Return a detached launch snapshot and transient credential reference."""
        request = json.loads(self.document)
        return {'runtime': self.runtime, 'adapter_request': request,
                'connection': {'api_key_env': request['api_key_env']}}

    def session_document(self) -> dict:
        """Use the captured settings for same-Session operations."""
        return self.launch_document()

    def evidence_document(self) -> dict:
        """Keep requested settings distinct from native observations in session.yml."""
        request = json.loads(self.document)
        return {key: request[key] for key in (
            'runtime', 'executable', 'version', 'model', 'reasoning_effort',
            'runtime_home', 'connection', 'connection_revision', 'model_source',
            'worktree_access', 'settings_sources', 'provider', 'base_url', 'base_url_source', 'credential_source',
            'permission_mode', 'permission_mode_source',
        )}

    def runtime_environment(self) -> Mapping[str, str]:
        """Resolve credentials only into transient process environment."""
        return credential_environment(json.loads(self.document)['api_key_env'])


class ClaudeRuntimeAdapter:
    """Bind Claude child Sessions to the common Runner lifecycle and controls."""

    finalize_usage = staticmethod(finalize_usage)
    verify_finalize_main = staticmethod(unsupported)
    finalize_hook = staticmethod(unsupported)
    finalize_event = staticmethod(unsupported)
    check_main_finalize = staticmethod(unsupported)
    finalize_response = staticmethod(unsupported)
    send_host_event = staticmethod(unsupported)
    parent_host_status = staticmethod(unsupported)

    def current_host_connection(self) -> None:
        """No interactive Main host is captured by this child-only Adapter."""
        return None

    def native_replacement_approval(self) -> Any:
        """Claude has approvals; an unavailable host never means no mechanism."""
        raise RuntimeAdapterError('native-approval-unavailable', 'Claude native replacement approval is unavailable.')

    def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
        """Use the owning host's reviewer, or refuse recovery."""
        reviewer = current_recovery_reviewer()
        if reviewer is None:
            raise RuntimeAdapterError('native-approval-unavailable', 'Claude native recovery approval is unavailable.')
        return reviewer(proposal)

    def preflight_runtime_context(
        self,
        *,
        harness_root: Path,
        git_common_directory: Path,
        role: ResolvedChildRole,
        worktree: Path,
        evidence: Path,
        requested_skills: tuple[str, ...],
        report_files: tuple[Path, ...] = (),
    ) -> ClaudeContext:
        """Validate the installed protocol and exact model before Session allocation."""
        from graphtraj.configuration.project_configuration import configuration_exists, load_project_configuration

        settings = role.settings
        if requested_skills or settings.codex or settings.pi or settings.allow_runtime_swarm:
            raise RuntimeAdapterError('ROLE_CONFIG_UNSUPPORTED', 'Claude uses native resources and no native helpers.')
        if settings.reasoning_effort not in (None, *EFFORTS):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Unsupported Claude effort.')
        if settings.model != 'claude-opus-5-5' and not settings.connection:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Use exact claude-opus-5-5 or an explicit model connection.')
        # Only an explicit connection endpoint may replace the official service.
        base_url = settings.base_url
        base_url_source = 'configuration' if base_url else 'native'
        if base_url:
            from urllib.parse import urlsplit

            url = urlsplit(base_url)
            if (url.scheme not in {'http', 'https'} or not url.hostname or url.username
                    or url.password or url.query or url.fragment):
                raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Claude Base URL must be credential-free HTTP(S).')
        config = dict(settings.claude or {})
        resources = config.get('read_paths', [])
        if (set(config) - {'read_paths', 'permission_mode'} or not isinstance(resources, list)
                or any(not isinstance(path, str) or not Path(path).is_absolute() for path in resources)):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'claude.read_paths must list absolute resource paths.')
        if 'permission_mode' in config and config['permission_mode'] not in ('default', 'auto'):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'claude.permission_mode must be default or auto.')
        credential_environment(settings.api_key_env)
        binary = executable()
        try:
            version = subprocess.run([binary, '--version'], capture_output=True, text=True,
                                     check=True, timeout=10).stdout.strip()
            match = re.match(r'(\d+)\.(\d+)\.(\d+) \(Claude Code\)', version)
            if match is None or tuple(map(int, match.groups())) < MINIMUM_VERSION:
                raise ValueError('version')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise RuntimeAdapterError('RUNTIME_EXECUTABLE_INVALID', 'Claude Code 2.1.299 or later is required.') from error
        reports = []
        for path in report_files:
            if path.is_absolute() or path.parts[:1] != ('.state',) or '..' in path.parts:
                raise RuntimeAdapterError('REPORT_FILE_INVALID', 'Reports must use assigned .state paths.')
            reports.append(str(path))
        project = load_project_configuration(harness_root) if configuration_exists(harness_root) else None
        state = project.state if project else harness_root / '.graphtraj/state'
        if state.resolve().is_relative_to(worktree.resolve()):
            raise RuntimeAdapterError('RUNTIME_ACCESS_DENIED', 'Claude needs a Worktree outside private state.')
        resources = _validated_resources(
            resources, harness_root, state,
            Path(settings.runtime_home or os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))),
        )
        return ClaudeContext(json.dumps({
            'runtime': 'claude', 'executable': binary, 'version': version,
            'harness_root': str(harness_root), 'worktree_path': str(worktree),
            'git_common_directory': str(git_common_directory), 'state_directory': str(state),
            'docs_directory': str(project.docs if project else harness_root / 'docs'),
            'runtime_home': settings.runtime_home or os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude')),
            'explicit_runtime_home': bool(settings.runtime_home or os.environ.get('CLAUDE_CONFIG_DIR')),
            'model': settings.model, 'reasoning_effort': settings.reasoning_effort,
            'connection': settings.connection, 'connection_revision': settings.connection_revision,
            'model_source': settings.model_source, 'base_url': base_url,
            'base_url_source': base_url_source,
            'provider': settings.runtime_provider or 'native',
            'credential_source': 'api_key_env' if settings.api_key_env else 'native',
            'api_key_env': settings.api_key_env, 'instructions': role.instructions,
            'worktree_access': settings.worktree_access, 'reports': reports, 'resources': resources,
            'settings_sources': 'managed settings and explicit Runner settings; restricted mode',
            'permission_mode': config.get('permission_mode'),
            'permission_mode_source': ('role' if 'permission_mode' in config else
                                       'native restricted selection; user/project/local settings excluded'),
        }))

    def recovery_environment(self, connection: Mapping[str, Any]) -> Mapping[str, str]:
        """Restore only the captured credential reference, never a fresh catalog."""
        if set(connection) - {'api_key_env'}:
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'Invalid retained Claude connection.')
        return credential_environment(connection.get('api_key_env'))

    def read_session_identity(self, session_directory: Path) -> str:
        """Read the identity attested by the native startup hook."""
        try:
            value = yaml.safe_load((session_directory / 'session.yml').read_text())['session']
            if not isinstance(value, str) or not value:
                raise ValueError('identity')
            return value
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude native identity is unavailable.') from error

    def recover_report_files(self, request: Mapping[str, Any], evidence: Path) -> tuple[str, ...]:
        """Keep original assignments; reports are written through the hosted tool."""
        return tuple(request['reports'])

    def refresh_report_paths(
        self,
        request: Mapping[str, Any],
        *,
        worktree: Path,
        evidence: Path,
        report_files: tuple[Path, ...],
        role: str,
        reports_only: bool = False,
        session_directory: Path | None = None,
    ) -> dict:
        """Refresh reports and explicit resource grants for the original configured role.

        Model, connection and other captured permissions remain unchanged. An
        inline or removed role has no current configured grants to import.
        """
        refreshed = copy.deepcopy(dict(request))
        if refreshed.get('worktree_path') != str(worktree):
            raise RuntimeAdapterError('session-not-resumable', 'Claude Worktree changed during recovery.')
        if session_directory is not None:
            from graphtraj.configuration.project_roles import load_project_roles, ProjectRolesError

            try:
                mapping = yaml.safe_load((session_directory / 'mapping.yml').read_text())
                reference = mapping.get('role_reference')
                presets = load_project_roles(Path(request['harness_root'])).presets
                preset = presets.get(reference)
                config = preset.claude if preset is not None else None
                if config is not None and 'read_paths' in config:
                    # Connection presets have no resolved runtime here. The
                    # original captured connection fixes it without reloading
                    # a mutable catalog during Session recovery.
                    same_connection = (preset.connection is not None
                                       and preset.connection == request.get('connection'))
                    if not (same_connection or preset.connection is None and preset.runtime == 'claude'):
                        raise ValueError('Original role no longer configures Claude resources')
                    refreshed['resources'] = _validated_resources(
                        config['read_paths'], Path(request['harness_root']),
                        Path(request['state_directory']), Path(request['runtime_home']),
                    )
            except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError, ProjectRolesError) as error:
                raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Cannot refresh original role resource grants: ' + str(error)) from error
        refreshed['reports'] = [str(path) for path in report_files]
        if reports_only:
            refreshed['worktree_access'] = 'read'
        return refreshed

    def operation_total(self, trace_file: Path, session: str) -> int:
        """Count native tool-use identifiers once, retaining resumed Trace history."""
        try:
            return len({part['id'] for line in trace_file.read_text().splitlines()
                        for record in [json.loads(line)] if record.get('session_id') == session
                        for part in record.get('message', {}).get('content', [])
                        if isinstance(part, dict) and part.get('type') == 'tool_use'})
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeAdapterError('OPERATION_TOTAL_UNREADABLE', 'Cannot read Claude native Trace.') from error

    def confirm_termination(
        self, directory: Path, mapping: Mapping[str, Any], request: Mapping[str, Any],
    ) -> dict:
        """Use retained settlement or current owned-group observations.

        Missing historical EOF/idle observations do not prevent proving that
        the original process group has now stopped. Identity mismatches remain
        errors; current observations never overwrite the original outcome.
        """
        if not isinstance(mapping.get('execution_id'), str) or not mapping['execution_id']:
            raise RuntimeAdapterError('termination-unconfirmed', 'The original Claude execution identity is missing.',
                                      terminal_confirmed=False)
        identity = {key: mapping[key] for key in ('session', 'execution_id', 'runtime_pid', 'worker_pid')}
        path = directory / f"claude-termination-{mapping['execution_id']}.yml"
        facts = ('process_group_closed', 'stdout_eof', 'stderr_eof', 'pipes_closed', 'native_idle')
        try:
            if path.parent != directory or path.is_symlink():
                raise ValueError('Invalid evidence path')
            evidence = yaml.safe_load(path.read_text()) if path.exists() else None
            if evidence is None and not path.exists():
                return self._confirm_current_group(directory, mapping, request)
            if not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in identity.items()):
                raise ValueError('Termination evidence does not match the original execution')
        except (OSError, ValueError, yaml.YAMLError) as error:
            raise RuntimeAdapterError(
                'termination-unconfirmed',
                'Original Claude termination evidence is unavailable or mismatched; required: '
                + ', '.join((*facts, 'runtime_exit_code')) + '.', terminal_confirmed=False,
            ) from error
        missing = [key for key in facts if evidence.get(key) is not True]
        if type(evidence.get('runtime_exit_code')) is not int:
            missing.append('runtime_exit_code')
        if missing:
            return self._confirm_current_group(directory, mapping, request)
        return evidence

    def _confirm_current_group(
        self, directory: Path, mapping: Mapping[str, Any], request: Mapping[str, Any],
    ) -> dict:
        """Confirm present stopping under the Runner's ownership/startup guard."""
        from graphtraj.execution.runner_process import settle_runtime_group
        from graphtraj.execution.runner_heartbeat import read_heartbeat

        try:
            if (self.read_session_identity(directory) != mapping['session']
                    or request.get('runtime') != 'claude'
                    or request.get('worktree_path') != mapping['worktree_path']):
                raise ValueError('Retained Claude launch identity differs')
            heartbeat = read_heartbeat(directory)
            owned_at = (heartbeat['updated_at'] if heartbeat is not None
                        and all(heartbeat.get(key) == mapping[key]
                                for key in ('execution_id', 'worker_pid')) else None)
            return settle_runtime_group(
                mapping['runtime_pid'], Path(request['executable']), mapping['session'], owned_at,
            )
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            raise RuntimeAdapterError('termination-unconfirmed',
                                      'Current Claude stopping is unconfirmed: ' + str(error),
                                      terminal_confirmed=False) from error

    def current_execution_diagnostic(
        self,
        session_directory: Path,
        trace_file: Path,
        stderr_offset: int,
        trace_offset: int,
    ) -> str:
        """Read current stderr and native result errors, excluding assistant prose."""
        from graphtraj.runtimes.activity import redact

        parts = []
        for path, offset in ((session_directory / 'stderr.log', stderr_offset), (trace_file, trace_offset)):
            try:
                with path.open('rb') as stream:
                    stream.seek(offset)
                    text = stream.read().decode('utf-8', errors='replace')
                if path == trace_file:
                    for line in text.splitlines():
                        record = json.loads(line)
                        if record.get('type') == 'result' and record.get('is_error'):
                            parts.append(str(record.get('errors') or record.get('result') or record.get('subtype')))
                else:
                    parts.append(text)
            except (OSError, ValueError):
                continue
        return redact('\n'.join(parts))

    def managed_execution(
        self,
        request: dict,
        prompt: str,
        session_directory: Path,
        session_started: SessionStarted,
        context_evidence: dict,
        *,
        trace_file: Path,
        expected_session: str | None = None,
        session_created: SessionStarted,
    ) -> Any:
        """Construct an unstarted native CLI owner."""
        from graphtraj.runtimes.claude.execution import ClaudeExecution

        return ClaudeExecution(request, prompt, session_directory, session_started,
                               session_created, trace_file, expected_session)
