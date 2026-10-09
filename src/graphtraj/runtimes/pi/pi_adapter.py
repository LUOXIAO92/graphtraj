"""Resolve Pi child roles and retain native launch and permission settings."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping

import yaml

from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, SessionStarted, finalize_usage


def unsupported(*args: object, **kwargs: object) -> Any:
    """Reject host-only operations; Pi is a child Runtime in this Adapter."""
    raise RuntimeAdapterError('RUNTIME_UNSUPPORTED', 'Pi interactive Main/finalize hosting is not supported.')


@dataclass(frozen=True)
class PiContext:
    """Immutable, credential-free launch snapshot for a Pi child."""

    document: str
    runtime: str = 'pi'

    def finalize(self) -> PiContext:
        """Return the prepared context without changing user configuration."""
        return self

    def launch_document(self) -> dict:
        """Return retained arguments, resource references and native permissions."""
        request = json.loads(self.document)
        return {'runtime': 'pi', 'adapter_request': request,
                'connection': {'api_key_env': request.get('api_key_env')}}

    def evidence_document(self) -> dict:
        """Expose model and resource selection without credential values."""
        request = json.loads(self.document)
        return {'runtime': 'pi', 'model': request['model'], 'provider': request['provider'],
                'version': request['version'], 'resources': request['resources'],
                'worktree_access': request['worktree_access']}

    def session_document(self) -> dict:
        """Return the same captured request for native Session operations."""
        return self.launch_document()

    def runtime_environment(self) -> Mapping[str, str]:
        """Resolve only the selected credential name, keeping its value transient."""
        name = json.loads(self.document).get('api_key_env')
        return {name: os.environ[name]} if name and name in os.environ else {}


class PiRuntimeAdapter:
    """Prepare and control Pi children; leave all task authority with Runner."""

    finalize_usage = staticmethod(finalize_usage)

    finalize_event = staticmethod(unsupported)
    check_main_finalize = staticmethod(unsupported)
    finalize_response = staticmethod(unsupported)
    send_host_event = staticmethod(unsupported)
    parent_host_status = staticmethod(unsupported)

    def current_host_connection(self) -> dict | None:
        """Read the association scoped by Pi's actual Session extension callback."""
        from graphtraj.runtimes.pi.session_entry import current_connection

        return current_connection()

    def verify_finalize_main(self, connection: dict) -> str:
        """Exclude supported plugin children using Pi's native Session facts."""
        from graphtraj.runtimes.pi.session_entry import verify_main

        return verify_main(connection)

    def finalize_hook(self, path: Path, binding: dict) -> dict:
        """Return the native extension path without installing or enabling it."""
        return {'extension': str(Path(__file__).with_name('extension.mjs'))}

    def native_replacement_approval(self) -> None:
        """Pi has no built-in execution approval mechanism."""
        return None

    def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
        """Use an explicitly bound reviewer; never synthesize additional spending."""
        from graphtraj.runtimes.runtime_adapter import current_recovery_reviewer

        reviewer = current_recovery_reviewer()
        if reviewer is None:
            raise RuntimeAdapterError('native-approval-unavailable', 'Pi has no recovery approval channel.')
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
    ) -> PiContext:
        """Validate installed native dependencies before allocating a Session."""
        from graphtraj.workspace.runner_project import runtime_executable
        from graphtraj.configuration.project_configuration import configuration_exists, load_project_configuration

        settings = role.settings
        config = dict(settings.pi or {})
        allowed = {'sandbox_python', 'sandbox_path', 'agent_dir', 'read_paths'}
        if set(config) - allowed or requested_skills or settings.codex or settings.base_url:
            raise RuntimeAdapterError('ROLE_CONFIG_UNSUPPORTED',
                                      'Use Pi native provider configuration and pi resource/sandbox settings.')
        provider, separator, model = settings.model.partition('/')
        if not separator or not provider or not model:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Pi model must be provider/model-id.')
        reasoning = settings.reasoning_effort
        if reasoning is not None and reasoning not in {'off', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Pi does not support this thinking level.')
        executable = runtime_executable('pi')
        python = config.get('sandbox_python', sys.executable)
        sandbox_path = config.get('sandbox_path', os.environ.get('PATH', ''))
        if not isinstance(python, str) or not isinstance(sandbox_path, str):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'Pi sandbox_python and sandbox_path must be strings.')
        if 'sandbox_path' in config:
            sandbox_path += os.pathsep + os.environ.get('PATH', '')
        resources = config.get('read_paths', [])
        if not isinstance(resources, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in resources):
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'pi.read_paths must contain absolute resource paths.')
        env = {**os.environ, 'PATH': sandbox_path}
        if shutil.which('srt', path=sandbox_path) is None:
            raise RuntimeAdapterError('RUNTIME_EXECUTABLE_INVALID', 'Pi requires srt on pi.sandbox_path; no fallback.')
        try:
            subprocess.run([python, '-c', 'from agent_sandbox import wrap_command, is_sandbox_available, resolve_profile'],
                           env=env, capture_output=True, check=True, timeout=10)
            version = subprocess.run([str(executable), '--version'], capture_output=True,
                                     text=True, check=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeAdapterError('RUNTIME_EXECUTABLE_INVALID',
                                      'Pi and agent-sandbox must be installed in the selected environment.') from error
        agent_path = config.get('agent_dir', os.environ.get('PI_CODING_AGENT_DIR', str(Path.home() / '.pi/agent')))
        if not isinstance(agent_path, str) or not agent_path:
            raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'pi.agent_dir must name a native resource directory.')
        agent_dir = Path(agent_path).resolve()
        project = load_project_configuration(harness_root) if configuration_exists(harness_root) else None
        state = project.state if project else harness_root / '.graphtraj/state'
        protected = (state, harness_root / '.graphtraj/runner', harness_root / '.graphtraj/cli',
                     harness_root / '.codex', Path.home() / '.codex', agent_dir / 'sessions')
        for resource in resources:
            path = Path(resource).resolve()
            if any(path.is_relative_to(p.resolve()) or p.resolve().is_relative_to(path) for p in protected):
                raise RuntimeAdapterError('RUNTIME_ACCESS_DENIED', 'A Pi resource grant would expose private control/history.')
        if state.resolve().is_relative_to(worktree.resolve()):
            raise RuntimeAdapterError('RUNTIME_ACCESS_DENIED', 'Pi needs a Worktree outside private state.')
        request = {
            'worktree_path': str(worktree), 'harness_root': str(harness_root),
            'git_common_directory': str(git_common_directory), 'evidence': str(evidence),
            'executable': str(executable), 'sandbox_python': python, 'sandbox_path': sandbox_path,
            'provider': provider, 'model': model, 'reasoning_effort': reasoning,
            'api_key_env': settings.api_key_env, 'version': version,
            'instructions': role.instructions, 'agent_dir': str(agent_dir),
            'resources': resources, 'worktree_access': settings.worktree_access,
            'reports': report_paths(report_files, evidence),
            'state_directory': str(state),
            'docs_directory': str(project.docs if project else harness_root / 'docs'),
        }
        return PiContext(json.dumps(request))

    def recovery_environment(self, connection: Mapping[str, Any]) -> Mapping[str, str]:
        """Resolve retained credential references without storing their values."""
        if set(connection) - {'api_key_env'}:
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'Invalid retained Pi connection.')
        name = connection.get('api_key_env')
        if name is not None and (not isinstance(name, str) or not name.isidentifier()):
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'Invalid Pi credential variable name.')
        return {name: os.environ[name]} if name and name in os.environ else {}

    def read_session_identity(self, session_directory: Path) -> str:
        """Read the actual Pi identity recorded before its first task prompt."""
        try:
            document = yaml.safe_load((session_directory / 'session.yml').read_text())
            session = document['session']
            if not isinstance(session, str) or not session:
                raise ValueError('missing identity')
            return session
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Pi native identity is unavailable.') from error

    def recover_report_files(self, request: Mapping[str, Any], evidence: Path) -> tuple[str, ...]:
        """Recover only the original exact report assignments."""
        try:
            return tuple(str(Path('.state') / Path(p).relative_to(evidence)) for p in request['reports'])
        except (KeyError, ValueError, TypeError) as error:
            raise RuntimeAdapterError('session-not-resumable', 'Pi report assignments are invalid.') from error

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
        """Refresh assigned report reads and tighten recovery without changing resources."""
        refreshed = copy.deepcopy(dict(request))
        if refreshed.get('worktree_path') != str(worktree):
            raise RuntimeAdapterError('session-not-resumable', 'Pi Worktree changed during recovery.')
        refreshed['reports'] = report_paths(report_files, evidence)
        if reports_only:
            refreshed['worktree_access'] = 'read'
        return refreshed

    def operation_total(self, trace_file: Path, session: str) -> int:
        """Count actual Pi tool calls in the retained native Session history."""
        try:
            text = trace_file.read_text()
            records = text.splitlines() if text.endswith('\n') else text.splitlines()[:-1]
            return len({part['id'] for line in records for part in
                        json.loads(line).get('message', {}).get('content', [])
                        if isinstance(part, dict) and part.get('type') == 'toolCall'})
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeAdapterError('OPERATION_TOTAL_UNREADABLE', 'Cannot read Pi native Trace.') from error

    def current_execution_diagnostic(
        self,
        session_directory: Path,
        trace_file: Path,
        stderr_offset: int,
        trace_offset: int,
    ) -> str:
        """Read only the current execution's native stderr diagnostics."""
        try:
            with (session_directory / 'stderr.log').open('rb') as stream:
                stream.seek(stderr_offset)
                return stream.read().decode('utf-8', errors='replace')
        except OSError:
            return ''

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
    ):
        """Construct one unstarted owner of a persistent Pi RPC execution."""
        from graphtraj.runtimes.pi.managed_session import PiManagedExecution

        return PiManagedExecution(request, prompt, session_directory, session_started,
                                  session_created, trace_file, expected_session)


def report_paths(paths: tuple[Path, ...], evidence: Path) -> list[str]:
    """Resolve Runner's Worktree-relative assignments to their retained evidence."""
    result = []
    for path in paths:
        if path.is_absolute() or path.parts[:1] != ('.state',) or '..' in path.parts:
            raise RuntimeAdapterError('REPORT_FILE_INVALID', 'Pi report paths must be assigned .state paths.')
        result.append(str(evidence.joinpath(*path.parts[1:]).resolve()))
    return result
