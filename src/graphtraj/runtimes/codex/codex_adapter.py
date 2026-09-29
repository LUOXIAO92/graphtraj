"""The allowlisted Codex Runtime adapter used by Agent Runner."""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import signal
import subprocess
import time
import tomllib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from graphtraj.runtimes.runtime_adapter import (
    RuntimeAdapterError,
    RuntimeContext,
    RuntimeContextPreflight,
    SessionStarted,
)
from graphtraj.execution.runner_transport import record_runtime_identity, runtime_turn_outcome
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.codex.approval import approval_route
from graphtraj.configuration.project_configuration import configuration_exists, load_project_configuration
from graphtraj.configuration.role_definitions import ResolvedChildRole


ADAPTER_ROLE_KEYS = frozenset(
    {
        "model_reasoning_effort",
        "default_permissions",
    }
)
REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

# The generic Codex Runtime projection shared by every Harness-owned role.
# Per-role selections (worktree access, instructions, reasoning effort and
# connection) are applied on top of a copy of this projection.
_CODEX_ROLE_PROJECTION: Mapping[str, Any] = {
    "model_reasoning_effort": "high",
    "default_permissions": "project-documents-read-only",
    "permissions": {
        "project-documents-read-only": {
            "extends": ":workspace",
            "filesystem": {
                ":workspace_roots": {
                    ".": "write",
                    ".agents": "read",
                    "AGENTS.md": "read",
                    "CONTEXT.md": "read",
                    "docs": "read",
                }
            },
        }
    },
}


# The Runtime callback reuses these public handlers and argument schemas.
# Ticket state mutation and arbitrary file operations are not Runtime tools.
NATIVE_RUNNER_TOOLS = {
    'graphtraj_status': 'alias_status',
    'graphtraj_swarm': 'swarm',
    'graphtraj_send': 'send_instruction',
    'graphtraj_interrupt': 'interrupt',
    'graphtraj_requests': 'pending_requests',
    'graphtraj_reply': 'reply_to_request',
    'graphtraj_reports': 'session_reports',
    'graphtraj_submit_report': 'submit_report',
    'graphtraj_submit_result': 'submit_result',
    'graphtraj_decide_result': 'decide_result',
    'graphtraj_ticket_graph': 'ticket_graph',
}


def native_runner_tools() -> list[dict[str, Any]]:
    """Describe existing Runner operations for the native callback transport."""
    from graphtraj.interfaces.tools import TOOLS

    return [
        {'type': 'function', 'name': name, 'description': TOOLS[key].description,
         'inputSchema': TOOLS[key].input_schema}
        for name, key in NATIVE_RUNNER_TOOLS.items()
    ]


class CodexAdapterError(RuntimeAdapterError):
    """A selected Codex role cannot be launched safely."""


@dataclass(frozen=True)
class _CodexRole:
    """Validated effective settings for one Harness-owned custom Agent."""

    name: str
    reasoning_effort: str
    developer_instructions: str
    default_permissions: str
    agents: Mapping[str, Any]
    native_settings: Mapping[str, Any]
    approval: Mapping[str, str] | None = None

    def _launch_request(
        self,
        *,
        executable: Path,
        runtime_store: Path,
        worktree: Path,
        evidence: Path,
        git_common_directory: Path,
        native_skills: Mapping[str, Any] | None,
        report_files: Tuple[Path, ...],
        model: str,
    ) -> Dict[str, Any]:
        """Render the private request consumed by this Adapter's worker."""

        arguments = [
            str(executable),
            "exec",
            "-C",
            str(worktree),
            "--model",
            model,
        ]
        developer_instructions = self.developer_instructions
        native_settings = copy.deepcopy(dict(self.native_settings))
        filesystem = native_settings["permissions"][self.default_permissions][
            "filesystem"
        ]
        from graphtraj.runtimes.codex.access import private_filesystem

        # Control now runs on the private native callback, not through files
        # writable by an Agent or by a helper inheriting its tool permissions.
        filesystem.update(private_filesystem(runtime_store))
        if filesystem.get(":workspace_roots", {}).get(".") == "write":
            filesystem[str(git_common_directory)] = "write"
            filesystem[str(git_common_directory / 'config')] = "read"
            filesystem[str(git_common_directory / 'hooks')] = "read"
        native_report_paths = _canonical_report_write_paths(
            evidence, report_files
        )
        for path in native_report_paths:
            filesystem[str(path)] = "read"
        if native_skills is not None:
            native_settings["skills"] = dict(native_skills)
            for entry in native_skills.get("config", []):
                if isinstance(entry, dict) and entry.get("enabled", True):
                    path = entry.get("path")
                    if isinstance(path, str):
                        resource = Path(path)
                        directory = (
                            resource.parent if resource.name == "SKILL.md" else resource
                        )
                        filesystem.setdefault(str(directory), "read")
        approvals_reviewer = (
            "user" if self.approval is not None
            else _harness_approvals_reviewer(runtime_store)
        )
        overrides = (
            *native_settings.items(),
            ("default_permissions", self.default_permissions),
            ("model_reasoning_effort", self.reasoning_effort),
            *(
                (("approvals_reviewer", approvals_reviewer),)
                if approvals_reviewer is not None
                else ()
            ),
            ("developer_instructions", developer_instructions),
            ("agents", self.agents),
        )
        for key, value in overrides:
            arguments.extend(("-c", "{0}={1}".format(key, _toml_value(value))))
        arguments.extend(("--json", "-"))
        return {
            **({"approval": dict(self.approval)} if self.approval is not None else {}),
            "arguments": arguments,
            "worktree_path": str(worktree),
            "session_parameters": {
                "cwd": str(worktree),
                "model": model,
                "dynamicTools": native_runner_tools(),
                "developerInstructions": developer_instructions,
                "config": {
                    key: value for key, value in overrides
                    if key != "developer_instructions"
                },
            },
        }


@dataclass(frozen=True)
class _CodexRuntimePreflight:
    _executable: Path
    _runtime_store: Path
    _git_common_directory: Path
    _role: _CodexRole
    _model: str
    _base_url: str | None
    _api_key_env: str | None
    _environment: Mapping[str, str]
    _worktree: Path
    _evidence: Path
    _native_skills: Mapping[str, Any] | None
    _report_files: Tuple[Path, ...]

    def finalize(self) -> RuntimeContext:
        """Resolve Ticket Worktree facts shared by supported role boundaries."""

        request = self._role._launch_request(
            executable=self._executable,
            runtime_store=self._runtime_store,
            worktree=self._worktree,
            evidence=self._evidence,
            git_common_directory=self._git_common_directory,
            native_skills=self._native_skills,
            report_files=self._report_files,
            model=self._model,
        )
        return _CodexRuntimeContext(
            _launch=json.dumps({
                "runtime": "codex",
                "adapter_request": request,
                "connection": {
                    key: value for key, value in (
                        ("base_url", self._base_url), ("api_key_env", self._api_key_env),
                    ) if value is not None
                },
            }),
            _evidence=json.dumps({
                "runtime": "codex", "effective_role": self._role.name,
                "model": self._model,
                "model_reasoning_effort": self._role.reasoning_effort,
                "native_skills": self._native_skills,
            }),
            _environment=self._environment,
        )


@dataclass(frozen=True)
class _CodexRuntimeContext:
    """Immutable native configuration, safe to retain and restore in a Worker."""

    _launch: str
    _evidence: str
    _environment: Mapping[str, str]
    runtime: str = "codex"

    def launch_document(self) -> Dict[str, Any]:
        """Return the durable Adapter input for launch and resume."""
        return json.loads(self._launch)

    def evidence_document(self) -> Dict[str, Any]:
        """Return the effective Context facts for mechanical evidence."""
        return json.loads(self._evidence)

    def session_document(self) -> Dict[str, Any]:
        """Return the resolved role and access as native thread parameters."""
        return {
            "runtime": self.runtime,
            "adapter_request": self.launch_document()["adapter_request"]["session_parameters"],
        }

    def runtime_environment(self) -> Mapping[str, str]:
        """Return ephemeral connection settings for the Runtime process."""
        return dict(self._environment)


def restore_codex_context(
    request: Mapping[str, Any], evidence: Mapping[str, Any],
) -> RuntimeContext:
    """Restore a Worker's resolved Context without consulting current role defaults."""
    _validate_launch_request(request)
    params = request.get("session_parameters")
    if (
        not isinstance(params, dict)
        or params.get("cwd") != request["worktree_path"]
        or not isinstance(params.get("config"), dict)
        or not isinstance(params.get("model"), str)
        or not isinstance(params.get("developerInstructions"), str)
    ):
        raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The native Session Context is invalid.")
    return _CodexRuntimeContext(
        json.dumps({"runtime": "codex", "adapter_request": request}),
        json.dumps(evidence), {},
    )


class CodexRuntimeAdapter:
    """Prepare Codex Context and interpret native statistics and current diagnostics."""

    def current_execution_diagnostic(
        self,
        session_directory: Path,
        trace_file: Path,
        stderr_offset: int,
        trace_offset: int,
    ) -> str:
        """Collect Runtime output recorded since this execution started.

        The Runtime writes its own records into the Runtime-owned Session file,
        which reaches the Harness only through the retained Trace entry, so that
        entry supplies the Runtime's error records for the current execution.
        """

        diagnostics = [_diagnostic_since(session_directory / "stderr.log", stderr_offset)]
        try:
            diagnostics.append(
                (session_directory / "worker-stderr.log").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError):
            pass
        try:
            with trace_file.open("rb") as events:
                events.seek(trace_offset)
                diagnostics.extend(_runtime_event_errors(events.read()))
        except OSError:
            pass
        return "\n".join(diagnostic for diagnostic in diagnostics if diagnostic)

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
    ) -> RuntimeContextPreflight:
        """Resolve Codex and delegate its existing preflight validation."""
        from graphtraj.workspace.runner_project import runtime_executable
        from graphtraj.runtimes.codex.codex_project import CodexProjectFiles

        return preflight_runtime_context(
            runtime_store=CodexProjectFiles.runtime_store(harness_root),
            executable=runtime_executable(role.settings.runtime),
            git_common_directory=git_common_directory,
            role=role,
            worktree=worktree,
            evidence=evidence,
            requested_skills=requested_skills,
            report_files=report_files,
        )

    def operation_total(self, trace_file: Path, session: str) -> int:
        """Count one native Codex tool request for each call ID in one Session.

        The linked native record is read exactly as the Runtime wrote it: only
        Codex's own ``response_item`` tool requests are counted, repeated
        records dedupe to one operation per ``(session, call ID)``, and a
        trailing record that is still being written is ignored.
        """
        try:
            text = trace_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise RuntimeAdapterError(
                "OPERATION_TOTAL_UNREADABLE",
                "The Session's native records could not be read.",
            ) from error
        # The Runtime appends to the linked native file, so a running Session
        # can end with a record that is not written completely yet.
        records = text.splitlines() if text.endswith("\n") else text.splitlines()[:-1]
        calls = set()
        try:
            for record in records:
                item = json.loads(record)
                if item.get("type") != "response_item":
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                item_type = payload.get("type")
                if item_type in {"function_call", "custom_tool_call"}:
                    request_id = payload.get("call_id")
                elif item_type in {"local_shell_call", "tool_search_call"}:
                    request_id = payload.get("call_id") or payload.get("id")
                elif item_type in {"web_search_call", "image_generation_call"}:
                    request_id = payload.get("id")
                else:
                    continue
                if isinstance(request_id, str) and request_id:
                    calls.add((session, request_id))
        except (TypeError, json.JSONDecodeError) as error:
            raise RuntimeAdapterError(
                "OPERATION_TOTAL_UNREADABLE",
                "The Session's native records could not be read.",
            ) from error
        return len(calls)


def preflight_runtime_context(
    *,
    runtime_store: Path,
    executable: Path,
    git_common_directory: Path,
    role: ResolvedChildRole,
    worktree: Path,
    evidence: Path,
    requested_skills: Tuple[str, ...],
    report_files: Tuple[Path, ...] = (),
) -> RuntimeContextPreflight:
    """Prepare one Codex role without crossing role-specific boundaries."""

    _reject_legacy_user_sandbox_config()
    _require_codex_permissions(executable)
    resolved_role = _resolve_codex_role(role, runtime_store.parent)
    settings = role.settings
    if requested_skills:
        raise CodexAdapterError(
            "SKILL_SELECTION_UNSUPPORTED",
            "Skill names are no longer selected by GraphTraj; use Runtime native "
            "selection or explicit external resource references.",
        )
    native_skills = _harness_native_skills(runtime_store)
    resolved_role._launch_request(
        executable=executable,
        runtime_store=runtime_store,
        git_common_directory=git_common_directory,
        worktree=worktree,
        evidence=evidence,
        native_skills=native_skills,
        report_files=report_files,
        model=settings.model,
    )
    return _CodexRuntimePreflight(
        _executable=executable,
        _runtime_store=runtime_store,
        _git_common_directory=git_common_directory,
        _role=resolved_role,
        _model=settings.model,
        _base_url=settings.base_url,
        _api_key_env=settings.api_key_env,
        _environment=_connection_environment(settings.base_url, settings.api_key_env),
        _worktree=worktree,
        _evidence=evidence,
        _native_skills=native_skills,
        _report_files=report_files,
    )


class CodexTurn:
    """Adapter-owned lifecycle for one Codex process group."""

    def __init__(
        self,
        request: Mapping[str, Any],
        prompt: str,
        session_directory: Path,
        session_started: SessionStarted,
        expected_session: Optional[str] = None,
    ) -> None:
        self._request = request
        self._prompt = prompt
        self._session_directory = session_directory
        self._session_started = session_started
        self._expected_session = expected_session
        self._process: Optional[subprocess.Popen] = None

    def run(self) -> Dict[str, Any]:
        """Own the process and translate its private JSONL protocol."""

        arguments, worktree = _validate_launch_request(self._request)
        _reject_legacy_user_sandbox_config()
        if self._expected_session is not None:
            arguments = _resume_arguments(arguments, self._expected_session)
        events_file = self._session_directory / "events.jsonl"
        record_runtime_identity(events_file, "codex")
        stderr_file = self._session_directory / "stderr.log"
        session: Optional[str] = None
        rollout: Optional[Path] = None
        position = 0
        if self._expected_session is not None:
            rollout, position = _native_session_state(
                self._session_directory, self._expected_session
            )
            if rollout is None:
                rollout = _find_native_session(self._expected_session)
                if rollout is not None:
                    position = rollout.stat().st_size
        try:
            with stderr_file.open("a", encoding="utf-8") as runtime_stderr:
                self._process = subprocess.Popen(
                    arguments,
                    cwd=worktree,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=runtime_stderr,
                    text=True,
                    start_new_session=True,
                )
                if self._process.stdin is None or self._process.stdout is None:
                    raise OSError("Codex pipes were not established")
                self._process.stdin.write(self._prompt)
                self._process.stdin.close()

                output: queue.Queue[Optional[str]] = queue.Queue()

                def read_output() -> None:
                    assert self._process is not None
                    assert self._process.stdout is not None
                    for line in self._process.stdout:
                        output.put(line)
                    output.put(None)

                reader = threading.Thread(target=read_output, daemon=True)
                reader.start()
                finished = False
                while not finished:
                    try:
                        line = output.get(timeout=0.02)
                    except queue.Empty:
                        line = ""
                    if line is None:
                        finished = True
                    elif line:
                        reported_session = _session_from_event(line)
                        if session is None and reported_session is not None:
                            session = reported_session
                            if (
                                self._expected_session is not None
                                and session != self._expected_session
                            ):
                                raise CodexAdapterError(
                                    "RUNTIME_SESSION_NOT_RESUMABLE",
                                    "Codex did not resume the mapped Runtime session.",
                                )
                            if rollout is None:
                                rollout, position = _native_session_state(
                                    self._session_directory, session
                                )
                            _append_transport_event(events_file, line)
                            self._session_started(session, self._process.pid)
                        else:
                            _append_transport_event(events_file, line)
                    if session is not None:
                        if rollout is None:
                            rollout = _find_native_session(session)
                        if rollout is not None:
                            position = _append_native_records(
                                rollout, position, events_file,
                                self._session_directory,
                            )
                reader.join()

                return_code = self._process.wait()
                if session is not None:
                    if rollout is None:
                        rollout = _find_native_session(session)
                    if rollout is not None:
                        _append_native_records(
                            rollout, position, events_file,
                            self._session_directory,
                        )
        except CodexAdapterError as error:
            terminal = _stop_process(self._process)
            if terminal or not error.terminal_confirmed:
                raise
            raise CodexAdapterError(
                error.code,
                error.message,
                terminal_confirmed=False,
            ) from error
        except (OSError, BrokenPipeError) as error:
            terminal = _stop_process(self._process)
            raise CodexAdapterError(
                "RUNTIME_START_FAILED",
                "The Codex Runtime could not be started.",
                terminal_confirmed=terminal,
            ) from error
        except BaseException:
            _stop_process(self._process)
            raise

        if session is None:
            raise CodexAdapterError(
                "RUNTIME_SESSION_MISSING",
                "Codex exited before reporting a Runtime session.",
            )
        return runtime_turn_outcome(return_code)

    def terminate(self) -> bool:
        """Signal only this Codex process group and confirm its exit."""

        if self._process is None or self._process.poll() is not None:
            return False
        return _stop_process(self._process)

    def terminate_until_terminal(self) -> None:
        """Retain ownership until this Codex process group has stopped."""

        while not _stop_process(self._process):
            time.sleep(0.01)


class _NativePositionStorageError(OSError):
    """A raw append succeeded but its durable native position did not."""

    def __init__(self, position: int) -> None:
        super().__init__("The native Codex Session position could not be retained.")
        self.position = position


class CodexNativeTrace:
    """Read one Runtime-owned native Session record through its retained Trace.

    The Trace entry is a symbolic link to the native rollout file that the
    Runtime owns, so a reader sees the native records themselves, including
    records appended while the Session runs, and no copy is retained.
    GraphTraj never writes through this link.
    """

    def __init__(
        self,
        trace_file: Path,
        session: str,
        rollout_path: Path | None,
        codex_home: Path,
    ) -> None:
        """Record the Trace entry and the native Session it must read."""

        self._trace_file = trace_file
        self._session = session
        self._codex_home = codex_home
        self._rollout = rollout_path

    def collect(self) -> None:
        """Link the Trace entry to the native Session file once it exists."""

        if self._rollout is None or not self._rollout.is_file():
            discovered = _find_native_session(self._session, self._codex_home)
            if discovered is None:
                return
            self._rollout = discovered
        if _linked_to(self._trace_file, self._rollout):
            return
        if _retains_records(self._trace_file):
            return
        _link_native_trace(self._trace_file, self._rollout)


def _linked_to(trace_file: Path, rollout: Path) -> bool:
    """Return whether this Trace entry already reads that native file."""

    try:
        if not trace_file.is_symlink():
            return False
        return Path(os.path.realpath(trace_file)) == Path(os.path.realpath(rollout))
    except OSError:
        return False


def _retains_records(trace_file: Path) -> bool:
    """Return whether this Trace entry already holds an earlier record set."""

    try:
        return not trace_file.is_symlink() and trace_file.stat().st_size > 0
    except OSError:
        return False


def _link_native_trace(trace_file: Path, rollout: Path) -> None:
    """Point one Trace entry at its Runtime-owned native Session file.

    The link replaces any placeholder atomically so a reader never observes a
    missing Trace entry.
    """

    trace_file.parent.mkdir(parents=True, exist_ok=True)
    pending = trace_file.with_name("." + trace_file.name + ".link")
    pending.unlink(missing_ok=True)
    pending.symlink_to(rollout)
    os.replace(pending, trace_file)


def create_codex_turn(
    request: Mapping[str, Any],
    prompt: str,
    session_directory: Path,
    session_started: SessionStarted,
) -> CodexTurn:
    """Create an invocation without exposing Codex mechanics to the worker."""

    return CodexTurn(request, prompt, session_directory, session_started)


def create_codex_resume_turn(
    request: Mapping[str, Any],
    prompt: str,
    session: str,
    session_directory: Path,
    session_started: SessionStarted,
) -> CodexTurn:
    """Resume exactly one mapped Codex session in a fresh invocation."""

    return CodexTurn(
        request,
        prompt,
        session_directory,
        session_started,
        expected_session=session,
    )


def read_codex_session_identity(session_directory: Path) -> str:
    """Read the identity retained from the app-server Session handle."""
    source = session_directory / "session.yml"
    try:
        if source.is_symlink() or not source.is_file():
            raise ValueError("Session metadata is not a regular file")
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not _nonempty_string(document.get("session")):
            raise ValueError("Session metadata has no native identity")
        return document["session"]
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        raise CodexAdapterError(
            "RUNTIME_SESSION_NOT_RESUMABLE",
            "The mapped native Codex Session cannot be attested.",
        ) from error


def read_codex_last_agent_message(events_file: Path) -> Optional[str]:
    """Read the final Codex answer from native or retained historical records."""

    result: Optional[str] = None
    for line in events_file.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    result = text
        elif event.get("type") == "event_msg":
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("type") == "task_complete":
                text = payload.get("last_agent_message")
                if isinstance(text, str):
                    result = text
    return result


def _append_transport_event(events_file: Path, line: str) -> None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict) or event.get("type") not in {
        "thread.started", "error", "turn.failed",
    }:
        return
    with events_file.open("a", encoding="utf-8") as events:
        events.write(line if line.endswith("\n") else line + "\n")
        events.flush()
        os.fsync(events.fileno())


def _native_session_state(
    session_directory: Path, session: str
) -> Tuple[Optional[Path], int]:
    state = session_directory / "native-session.yml"
    try:
        retained = yaml.safe_load(state.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, 0
    path = retained.get("path") if isinstance(retained, dict) else None
    position = retained.get("position") if isinstance(retained, dict) else None
    if (
        not isinstance(path, str)
        or not Path(path).name.endswith(session + ".jsonl")
        or not isinstance(position, int)
        or isinstance(position, bool)
        or position < 0
    ):
        raise OSError("retained native Codex Session state is invalid")
    return Path(path), position


def _find_native_session(
    session: str,
    codex_home: Path | None = None,
) -> Optional[Path]:
    if codex_home is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sessions = codex_home / "sessions"
    try:
        return next(sessions.rglob("*{0}.jsonl".format(session)), None)
    except OSError:
        return None


def _append_native_records(
    rollout: Path,
    position: int,
    events_file: Path,
    session_directory: Path,
) -> int:
    try:
        with rollout.open("rb") as native:
            native.seek(position)
            available = native.read()
    except OSError:
        return position
    complete = available.rfind(b"\n") + 1
    if complete == 0:
        return position
    records = available[:complete]
    with events_file.open("ab") as events:
        events.write(records)
        events.flush()
        os.fsync(events.fileno())
    position += complete
    try:
        write_yaml_durably(
            session_directory / "native-session.yml",
            {"path": str(rollout), "position": position},
        )
    except OSError as error:
        raise _NativePositionStorageError(position) from error
    return position


def _validate_launch_request(
    request: Mapping[str, Any],
) -> Tuple[List[str], Path]:
    if (
        not isinstance(request, dict)
        or not {"arguments", "worktree_path"}.issubset(request)
        or not set(request).issubset({"arguments", "worktree_path", "session_parameters", "approval"})
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


def _require_codex_permissions(executable: Path) -> None:
    """Refuse Codex releases without filesystem sandboxing."""
    try:
        result = subprocess.run(
            [str(executable), "exec", "--help"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED", "Cannot verify Codex permission controls.",
        ) from error
    required = ("--sandbox",)
    if result.returncode or any(flag not in result.stdout for flag in required):
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "Codex must support filesystem sandboxing.",
        )


def _reject_legacy_user_sandbox_config(codex_home: Path | None = None) -> None:
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


def _harness_approvals_reviewer(runtime_store: Path) -> Any | None:
    """Return the approvals reviewer the Harness Runtime Store selects.

    One Session runs with its Ticket Worktree as the native project root, so
    the Runtime Store configuration sits outside the native lookup. Only this
    selected value is forwarded; a missing, unreadable or unparsable file adds
    no override and keeps the native default.
    """
    config = runtime_store / "config.toml"
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    return document.get("approvals_reviewer")


def _resume_arguments(launch_arguments: List[str], session: str) -> List[str]:
    if (
        len(launch_arguments) < 4
        or launch_arguments[1] != "exec"
        or launch_arguments[-2:] != ["--json", "-"]
        or not session
    ):
        raise CodexAdapterError(
            "RUNTIME_SESSION_NOT_RESUMABLE",
            "The mapped Codex Runtime session cannot be resumed.",
        )
    return [*launch_arguments[:-1], "resume", session, "-"]


def _session_from_event(line: str) -> Optional[str]:
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, dict) or event.get("type") != "thread.started":
        return None
    session = event.get("thread_id")
    return session if isinstance(session, str) and session else None


def _stop_process(process: Optional[subprocess.Popen]) -> bool:
    if process is None:
        return True
    process_group = process.pid
    process.poll()
    if not _process_group_is_alive(process_group):
        return process.poll() is not None
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return not _process_group_is_alive(process_group)
    except OSError:
        return False
    if _await_process_group_exit(process, process_group, timeout=5):
        return True
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        process.poll()
        return not _process_group_is_alive(process_group)
    except OSError:
        return False
    return _await_process_group_exit(process, process_group, timeout=5)


def _await_process_group_exit(
    process: subprocess.Popen, process_group: int, timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_is_alive(process_group):
            return process.poll() is not None
        time.sleep(0.01)
    process.poll()
    return (
        process.poll() is not None
        and not _process_group_is_alive(process_group)
    )


def _process_group_is_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _resolve_codex_role(role: ResolvedChildRole, harness_root: Path) -> _CodexRole:
    """Translate a resolved child role using its fixed native permissions."""

    document = copy.deepcopy(dict(_CODEX_ROLE_PROJECTION))
    _validate_role_schema(document)
    document["permissions"][document["default_permissions"]]["filesystem"][
        ":workspace_roots"
    ]["."] = role.settings.worktree_access
    if role.settings.base_url is not None:
        document["model_provider"] = "graphtraj-role"
        document["model_providers"] = {"graphtraj-role": {
            "name": "GraphTraj role",
            "base_url": role.settings.base_url,
            "env_key": role.settings.api_key_env or "OPENAI_API_KEY",
            "wire_api": "responses",
        }}
    reasoning_effort = (
        document["model_reasoning_effort"]
        if role.settings.reasoning_effort is None
        else role.settings.reasoning_effort
    )
    if (
        not isinstance(reasoning_effort, str)
        or reasoning_effort not in REASONING_EFFORTS
    ):
        raise _invalid_role_value("reasoning_effort")

    defaults = (
        load_project_configuration(harness_root).codex
        if configuration_exists(harness_root) else None
    )
    return _CodexRole(
        name=role.name,
        approval=approval_route(
            role.settings.codex,
            custom=role.settings.base_url is not None,
            defaults=defaults,
        ),
        reasoning_effort=reasoning_effort,
        developer_instructions=role.instructions,
        default_permissions=document["default_permissions"],
        agents={"enabled": role.allow_runtime_swarm},
        native_settings={
            key: value
            for key, value in document.items()
            if key not in ADAPTER_ROLE_KEYS
        },
    )


def _validate_role_schema(document: Mapping[str, Any]) -> None:
    keys = frozenset(document)
    if not ADAPTER_ROLE_KEYS.issubset(keys):
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "The configured Codex role uses an unsupported top-level schema.",
        )
    if document["model_reasoning_effort"] not in REASONING_EFFORTS:
        raise _invalid_role_value("model_reasoning_effort")
    if not _nonempty_string(document["default_permissions"]):
        raise _invalid_role_value("default_permissions")
def _invalid_role_value(field: str) -> CodexAdapterError:
    return CodexAdapterError(
        "ROLE_CONFIG_INVALID",
        "The configured Codex role has an invalid {0} value.".format(field),
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _connection_environment(
    base_url: str | None,
    api_key_env: str | None,
) -> Mapping[str, str]:
    """Translate optional role connection choices without persisting a key."""
    environment: dict[str, str] = {}
    if base_url is not None:
        environment["OPENAI_BASE_URL"] = base_url
    if api_key_env is not None:
        api_key = os.environ.get(api_key_env)
        if api_key:
            environment["OPENAI_API_KEY"] = api_key
    return environment


def codex_connection_environment(
    base_url: str | None,
    api_key_env: str | None,
) -> Mapping[str, str]:
    """Return transient Codex connection overrides for a resumed Session."""
    return _connection_environment(base_url, api_key_env)


def _harness_native_skills(runtime_store: Path) -> Mapping[str, Any] | None:
    """Forward explicit native resources outside the Ticket's config lookup.

    Relative resource paths are anchored at the Harness config directory.
    Discovery and selection remain native; no Skill contents or professional
    names are inspected.
    """
    config = runtime_store / "config.toml"
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CodexAdapterError(
            "RUNTIME_CONFIG_INVALID", f"Cannot read native configuration {config}: {error}",
        ) from error
    skills = document.get("skills")
    if skills is None:
        return None
    if not isinstance(skills, dict) or not isinstance(skills.get("config", []), list):
        raise CodexAdapterError(
            "RUNTIME_CONFIG_INVALID", f"Invalid native skills configuration in {config}.",
        )
    for entry in skills.get("config", []):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            path = Path(entry["path"]).expanduser()
            entry["path"] = str(
                (path if path.is_absolute() else runtime_store / path).resolve()
            )
    return skills


def _canonical_report_write_paths(
    evidence: Path,
    report_files: Tuple[Path, ...],
) -> Tuple[Path, ...]:
    """Return the native canonical target for each exact ticket report."""
    paths: list[Path] = []
    for report in report_files:
        if (
            report.is_absolute()
            or len(report.parts) < 2
            or report.parts[0] != ".state"
            or ".." in report.parts
        ):
            raise CodexAdapterError(
                "ROLE_CONFIG_INVALID", "A report path must be inside .state."
            )
        paths.append(evidence.joinpath(*report.parts[1:]))
    return tuple(paths)


def refresh_codex_report_paths(
    request: Mapping[str, Any],
    *,
    worktree: Path,
    evidence: Path,
    report_files: Tuple[Path, ...],
    role: str,
    reports_only: bool = False,
    session_directory: Path | None = None,
) -> Dict[str, Any]:
    """Refresh only exact report and direct-control permissions in one resume."""

    arguments, request_worktree = _validate_launch_request(request)
    if request_worktree != worktree:
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request targets another Worktree.",
        )
    refreshed = list(arguments)
    for index in range(len(refreshed) - 2, -1, -1):
        if (
            refreshed[index] == "-c"
            and refreshed[index + 1].startswith("hooks=")
        ):
            del refreshed[index:index + 2]
    refreshed = [
        argument
        for argument in refreshed
        if argument != "--dangerously-bypass-hook-trust"
    ]
    native_report_paths = _canonical_report_write_paths(
        evidence, report_files
    )
    _, default_permissions = _resume_request_setting(
        refreshed, "default_permissions"
    )
    permissions_index, permissions = _resume_request_setting(
        refreshed, "permissions"
    )
    if not isinstance(default_permissions, str) or not isinstance(permissions, dict):
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request has invalid report permissions.",
        )
    permissions = copy.deepcopy(permissions)
    profile = permissions.get(default_permissions)
    if not isinstance(profile, dict) or not isinstance(
        profile.get("filesystem"), dict
    ):
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request has invalid report permissions.",
        )
    filesystem = profile["filesystem"]
    workspace_roots = filesystem.get(":workspace_roots")
    if reports_only:
        if not isinstance(workspace_roots, dict) or "." not in workspace_roots:
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The durable Codex launch request has invalid Worktree permissions.",
            )
        workspace_roots["."] = "read"
    for path, access in tuple(filesystem.items()):
        if access in ("read", "write") and _is_prior_report_path(
            path, evidence, report_files
        ):
            del filesystem[path]
    native_tools = {
        tool.get('name') for tool in request.get('session_parameters', {}).get('dynamicTools', [])
        if isinstance(tool, dict)
    }
    for path in native_report_paths:
        filesystem[str(path)] = "read" if 'graphtraj_submit_report' in native_tools else "write"
    if (
        session_directory is not None
        and 'graphtraj_swarm' not in native_tools
    ):
        # Continuing one direct child writes its Session directory, which
        # exists only after this Session started. Every other Session path is
        # already granted by the durable launch request.
        for path in _direct_child_session_directories(session_directory):
            filesystem[str(path)] = "write"
    refreshed[permissions_index + 1] = "permissions={0}".format(
        _toml_value(permissions)
    )

    result = {**copy.deepcopy(request), "arguments": refreshed}
    params = result.get("session_parameters")
    if params is not None:
        params["config"]["permissions"] = permissions
    return result


def _direct_child_session_directories(
    session_directory: Path,
) -> Tuple[Path, ...]:
    """Return the registered direct child Session directories of one parent."""
    directories: list[Path] = []
    for mapping_file in sorted(session_directory.parent.glob("*/mapping.yml")):
        try:
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if (
            isinstance(mapping, dict)
            and mapping.get("parent") == session_directory.name
        ):
            directories.append(mapping_file.parent)
    return tuple(directories)


def _resume_request_setting(
    arguments: List[str], name: str
) -> Tuple[int, Any]:
    matches: list[Tuple[int, Any]] = []
    for index, argument in enumerate(arguments[:-1]):
        if argument != "-c" or not arguments[index + 1].startswith(name + "="):
            continue
        try:
            setting = tomllib.loads(arguments[index + 1])
        except tomllib.TOMLDecodeError as error:
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The durable Codex launch request has an invalid {0} setting.".format(
                    name
                ),
            ) from error
        if set(setting) != {name}:
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The durable Codex launch request has an invalid {0} setting.".format(
                    name
                ),
            )
        matches.append((index, setting[name]))
    if len(matches) != 1:
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request has an invalid {0} setting.".format(
                name
            ),
        )
    return matches[0]


def _is_prior_report_path(
    path: Any,
    evidence: Path,
    report_files: Tuple[Path, ...],
) -> bool:
    if not isinstance(path, str):
        return False
    try:
        candidate = Path(path).resolve(strict=False).relative_to(
            evidence.resolve(strict=False)
        ).parts
    except (OSError, ValueError):
        return False
    for report in report_files:
        expected = report.parts[1:]
        if candidate == expected:
            return True
        if (
            len(expected) >= 5
            and expected[-3] == "rounds"
            and candidate[:-2] == expected[:-2]
            and candidate[-1:] == expected[-1:]
        ):
            return True
    return False


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


def _diagnostic_since(path: Path, offset: int) -> str:
    """Read only bytes appended during the current execution."""
    try:
        with path.open("rb") as diagnostic:
            diagnostic.seek(offset)
            return diagnostic.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _runtime_event_errors(events: bytes) -> list[str]:
    """Extract errors from Codex native events, excluding successful output."""
    errors = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in {"error", "turn.failed"}:
            error = _runtime_error_text(event)
        else:
            item = event.get("item")
            if event_type == "event_msg" and isinstance(event.get("payload"), dict):
                item = event["payload"].get("item")
            error = (
                _runtime_error_text(item)
                if isinstance(item, dict)
                and (
                    item.get("type") in {"error", "tool_error", "Error", "ToolError"}
                    or (
                        item.get("type") in {"command_execution", "CommandExecution", "FileChange"}
                        and (
                            item.get("status") in {"failed", "error"}
                            or isinstance(item.get("error"), (dict, str))
                            or (
                                isinstance(item.get("exit_code"), int)
                                and item["exit_code"] != 0
                            )
                        )
                    )
                )
                else ""
            )
        if error:
            errors.append(error)
    return errors


def _runtime_error_text(event: dict[str, Any]) -> str:
    """Collect the diagnostic fields of one known Codex error record."""
    values = []
    for key in ("aggregated_output", "stderr", "stdout", "message", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    error = event.get("error")
    if isinstance(error, str) and error:
        values.append(error)
    elif isinstance(error, dict):
        values.extend(
            value
            for key in ("message", "detail")
            if isinstance(value := error.get(key), str) and value
        )
    return "\n".join(values)
