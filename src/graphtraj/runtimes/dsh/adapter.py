"""Translate roles and retained native Sessions to DeepSeek Harness."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
from urllib.parse import urlsplit

from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, finalize_usage, credential_environment


class DshContext:
    """A credential-free launch configuration; secrets remain environment references."""

    runtime = 'dsh'

    def __init__(self, request: dict, evidence: dict | None = None) -> None:
        """Freeze role inputs so preparation and recovery cannot mutate old launches."""
        self.request = copy.deepcopy(request)
        self.evidence = copy.deepcopy(evidence or {})

    def finalize(self) -> DshContext:
        """Return the validated Context; no native service is started at preparation."""
        return self

    def launch_document(self) -> dict:
        """Return only nonsecret native settings and credential variable names."""
        return {'runtime': self.runtime, 'adapter_request': copy.deepcopy(self.request), 'connection': {}}

    def evidence_document(self) -> dict:
        """Disclose effective settings and the accepted native read limitation."""
        return {**copy.deepcopy(self.evidence), 'runtime': self.runtime,
                'model': self.request['model'], 'native_read_isolation': False,
                'sandbox': self.request['sandbox'], 'service_scope': 'agent',
                **({'connection': self.request['connection'],
                    'connection_revision': self.request['connection_revision'],
                    'runtime_home': self.request['runtime_home']} if self.request.get('connection') else {})}

    def session_document(self) -> dict:
        """Return a detached copy of native launch inputs."""
        return {'runtime': self.runtime, 'adapter_request': copy.deepcopy(self.request)}

    def runtime_environment(self) -> Mapping[str, str]:
        """Credentials stay in the inherited host environment, never launch records."""
        return {}


class DshRuntimeAdapter:
    """DSH child-Agent adapter; Main-specific host features are explicitly unavailable."""

    finalize_usage = staticmethod(finalize_usage)

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
    ) -> DshContext:
        """Validate the official provider, native binary and role before allocation."""
        if requested_skills or role.settings.codex or role.allow_runtime_swarm:
            raise RuntimeAdapterError('ROLE_CONFIG_UNSUPPORTED',
                                      'DSH uses native resource discovery; Codex settings/helpers are unsupported.')
        credential_environment(role.settings.api_key_env)
        if not role.settings.connection and role.settings.model not in {'deepseek-flash', 'deepseek-official/deepseek-flash'}:
            raise RuntimeAdapterError('ROLE_CONFIG_UNSUPPORTED', 'DSH requires deepseek-official/deepseek-flash.')
        effort = role.settings.reasoning_effort
        if effort not in {None, 'off', 'low', 'high', 'max'}:
            raise RuntimeAdapterError('ROLE_CONFIG_UNSUPPORTED', 'Unsupported DSH reasoning effort.')
        executable = shutil.which('dsh')
        tool = shutil.which('graphtraj-tool')
        if not executable or not tool:
            raise RuntimeAdapterError('RUNTIME_UNAVAILABLE', 'Install DSH and GraphTraj public CLI first.')
        package = Path(executable).resolve().parent.parent / 'package.json'
        try:
            if json.loads(package.read_text())['version'] != '0.2.0-rc.2':
                raise ValueError('version')
        except (OSError, ValueError, KeyError) as error:
            raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH 0.2.0-rc.2 is required.') from error
        base_url = role.settings.base_url or 'https://api.deepseek.com/anthropic'
        parsed = urlsplit(base_url)
        schemes = {'http', 'https'} if role.settings.connection else {'https'}
        if (parsed.scheme not in schemes or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'DSH requires a credential-free Messages root (HTTPS for legacy inline roles).')
        legacy_official = (
            not role.settings.connection and parsed.scheme == 'https'
            and parsed.netloc.lower() in {'api.deepseek.com', 'api.deepseek.com:443'}
        )
        unauthenticated = bool(
            role.settings.base_url and not role.settings.api_key_env and not legacy_official
        )
        reports = []
        for path in report_files:
            if path.is_absolute() or '..' in path.parts or path.parts[:1] != ('.state',):
                raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Reports must be assigned inside .state.')
            reports.append(str(path))
        return DshContext({
            'executable': executable, 'package': str(package), 'tool': tool,
            'worktree_path': str(worktree), 'harness_root': str(harness_root),
            'model': (role.settings.model if role.settings.connection else
                      role.settings.model.removeprefix('deepseek-official/')),
            'provider': 'deepseek-official',
            'runtime_home': role.settings.runtime_home,
            'connection': role.settings.connection,
            'connection_revision': role.settings.connection_revision,
            'model_source': role.settings.model_source,
            'reasoning_effort': effort,
            'base_url': role.settings.base_url if role.settings.connection else base_url,
            'api_key_env': role.settings.api_key_env or (
                'GRAPHTRAJ_CONNECTION_KEY' if unauthenticated else
                None if role.settings.connection else 'DEEPSEEK_API_KEY'
            ),
            'unauthenticated': unauthenticated,
            'instructions': role.instructions, 'reports': reports,
            'sandbox': 'read-only' if role.settings.worktree_access == 'read' else 'workspace-write',
        }, {'effective_role': role.name})

    def managed_execution(
        self,
        request: dict,
        prompt: str,
        session_directory: Path,
        session_started: Any,
        context_evidence: dict,
        *,
        trace_file: Path,
        expected_session: str | None = None,
        session_created: Any,
    ) -> Any:
        """Construct the owner; binding callbacks run before any model input."""
        from graphtraj.runtimes.dsh.execution import DshExecution

        return DshExecution(request, prompt, session_directory, session_started,
                            session_created, trace_file, expected_session)

    def read_session_identity(self, session_directory: Path) -> str:
        """Recover only the native identity recorded by this owner."""
        import yaml

        document = yaml.safe_load((session_directory / 'session.yml').read_text())
        return document['session']

    def recovery_environment(self, connection: Mapping[str, Any]) -> Mapping[str, str]:
        """Recovery uses fresh inherited credentials, not captured values."""
        if connection:
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'Unexpected DSH connection settings.')
        return {}

    def recover_report_files(self, request: Mapping[str, Any], evidence: Path) -> tuple[str, ...]:
        """Recover the original public report assignments without filesystem grants."""
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
        """Refresh public report assignments while preserving native Session permissions."""
        if str(worktree) != request['worktree_path']:
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'DSH recovery cannot change workspace.')
        if reports_only and request['sandbox'] != 'read-only':
            raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH cannot tighten an existing Session to reports-only.')
        return {**copy.deepcopy(dict(request)), 'reports': [str(path) for path in report_files]}

    def operation_total(self, trace_file: Path, session: str) -> int:
        """Count distinct native tool-call records in the retained raw Session log."""
        return sum(1 for line in trace_file.read_text().splitlines()
                   if json.loads(line).get('type') == 'tool/call')

    def current_execution_diagnostic(
        self,
        session_directory: Path,
        trace_file: Path,
        stderr_offset: int,
        trace_offset: int,
    ) -> str:
        """Read only sanitized owner diagnostics from the current execution."""
        path = session_directory / 'stderr.log'
        if not path.exists():
            return ''
        with path.open('rb') as stream:
            stream.seek(stderr_offset)
            return stream.read().decode('utf-8', errors='replace')

    def current_host_connection(self) -> dict | None:
        """Capture the association supplied by the native execution's shell registry."""
        from graphtraj.runtimes.dsh.session_entry import current_connection

        return current_connection()

    def native_replacement_approval(self) -> Any:
        """Fail rather than treat an unimplemented native approval route as absent."""
        raise RuntimeAdapterError('native-approval-unavailable', 'DSH replacement approval is unavailable.')

    def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
        """Parent-owned recovery remains on the parent's existing approval route."""
        raise RuntimeAdapterError('native-approval-unavailable', 'DSH host recovery approval is unavailable.')

    def verify_finalize_main(self, connection: dict) -> str:
        """Verify DSH's actual agent/created Session header."""
        from graphtraj.runtimes.dsh.session_entry import verify_main

        return verify_main(connection)

    def finalize_hook(self, path: Path, binding: dict) -> dict:
        """Return the native plugin path without enabling it."""
        return {'plugin': str(Path(__file__).with_name('tool.mjs'))}

    def finalize_event(self, binding: dict, event: dict) -> None:
        """Reject rather than reinterpret DSH events as Main lifecycle events."""
        raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH completion uses its native plugin lifecycle.')

    def check_main_finalize(self, binding: dict, context: dict, prompt: str, created: Any) -> None:
        """DSH does not launch Main finalization checkers."""
        raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH completion uses its native plugin lifecycle.')

    def finalize_response(self, result: dict | None, continued: bool) -> dict:
        """DSH has no Main finalization response protocol."""
        raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH completion uses its native plugin lifecycle.')

    def send_host_event(self, connection: Mapping[str, Any], event: dict) -> dict:
        """Managed DSH children receive events through their existing Worker."""
        raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH external host event delivery is unavailable.')

    def parent_host_status(self, connection: Mapping[str, Any], timeout_seconds: float) -> dict:
        """There is no separately adopted DSH Main host to query."""
        raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'DSH external host status is unavailable.')
