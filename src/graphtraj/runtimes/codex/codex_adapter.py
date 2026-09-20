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
from importlib import resources
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
from graphtraj.configuration.project_roles import ROLE_REFERENCES
from graphtraj.configuration.role_definitions import ResolvedChildRole
from graphtraj.workspace.git_repository import GitRepositoryError, SourceRepository
from graphtraj.configuration.skill_check import (
    declared_skill_name,
    required_skill_paths,
    source_history_skill_paths,
)


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


class CodexAdapterError(RuntimeAdapterError):
    """A selected Codex role cannot be launched safely."""


@dataclass(frozen=True)
class _EffectiveSkill:
    """One explicit Codex Skill selection persisted with a launch request."""

    name: str
    path: Path
    enabled: bool
    source: str

    def config_entry(self) -> Dict[str, Any]:
        return {"path": str(self.path), "enabled": self.enabled}

    def evidence_entry(self) -> Dict[str, str | bool]:
        return {
            "name": self.name,
            "path": str(self.path),
            "enabled": self.enabled,
            "source": self.source,
        }


@dataclass(frozen=True)
class _CodexRole:
    """Validated effective settings for one Harness-owned custom Agent."""

    name: str
    reasoning_effort: str
    developer_instructions: str
    required_skills: Tuple[str, ...]
    default_permissions: str
    agents: Mapping[str, Any]
    native_settings: Mapping[str, Any]

    def _launch_request(
        self,
        *,
        executable: Path,
        runtime_store: Path,
        worktree: Path,
        evidence: Path,
        git_common_directory: Path,
        effective_skills: Tuple[_EffectiveSkill, ...],
        report_files: Tuple[Path, ...],
        model: str,
        child_batch_write_paths: Tuple[Path, ...] = (),
        leader_control_write_paths: Tuple[Path, ...] = (),
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
        for skill in effective_skills:
            if (
                skill.enabled
                and skill.source in ("harness", "runtime-user")
                and skill.name in self.required_skills
            ):
                developer_instructions = developer_instructions.replace(
                    "${0}".format(skill.name),
                    "[${0}]({1})".format(skill.name, skill.path),
                )
        native_settings = copy.deepcopy(dict(self.native_settings))
        filesystem = native_settings["permissions"][self.default_permissions][
            "filesystem"
        ]
        if self.name == "team-leader":
            # Runner retains and registers a child Batch before returning to the
            # Leader. The native profile permits only these exact paths.
            for path in child_batch_write_paths:
                filesystem[str(path)] = "write"
            # Direct control also reads causal Worldline events and takes one
            # Runner capacity position. Later resumes inherit these exact
            # paths from this durable request instead of re-granting them.
            for path in leader_control_write_paths:
                filesystem[str(path)] = "write"
        if self.name == "merge-resolver":
            filesystem[str(evidence)] = "read"
        if self.name in {"engineer", "merge-resolver"}:
            filesystem[str(git_common_directory)] = "write"
        native_report_paths = _canonical_report_write_paths(
            evidence, report_files
        )
        for path in native_report_paths:
            filesystem[str(path)] = "write"
        for skill in effective_skills:
            if skill.enabled:
                filesystem[str(skill.path.parent)] = "read"
        approvals_reviewer = _harness_approvals_reviewer(runtime_store)
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
            (
                "skills",
                {"config": [skill.config_entry() for skill in effective_skills]},
            ),
        )
        for key, value in overrides:
            arguments.extend(("-c", "{0}={1}".format(key, _toml_value(value))))
        arguments.extend(("--json", "-"))
        return {
            "arguments": arguments,
            "worktree_path": str(worktree),
            "session_parameters": {
                "cwd": str(worktree),
                "model": model,
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
    _harness_skills: Tuple[_EffectiveSkill, ...]
    _requested_skills: Tuple[str, ...]
    _report_files: Tuple[Path, ...]
    _child_batch_write_paths: Tuple[Path, ...]
    _leader_control_write_paths: Tuple[Path, ...]

    def finalize(self) -> RuntimeContext:
        """Resolve Ticket Worktree facts shared by supported role boundaries."""

        effective_skills = self._harness_skills + _resolve_repository_skills(
            self._worktree, self._requested_skills
        )
        request = self._role._launch_request(
            executable=self._executable,
            runtime_store=self._runtime_store,
            worktree=self._worktree,
            evidence=self._evidence,
            git_common_directory=self._git_common_directory,
            effective_skills=effective_skills,
            report_files=self._report_files,
            model=self._model,
            child_batch_write_paths=self._child_batch_write_paths,
            leader_control_write_paths=self._leader_control_write_paths,
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
                "effective_skills": [skill.evidence_entry() for skill in effective_skills],
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


def preflight_runtime_context(
    *,
    runtime_store: Path,
    executable: Path,
    git_common_directory: Path,
    role: ResolvedChildRole,
    worktree: Path,
    evidence: Path,
    repository_skill_source: Path,
    requested_skills: Tuple[str, ...],
    report_files: Tuple[Path, ...] = (),
    child_batch_write_paths: Tuple[Path, ...] = (),
    leader_control_write_paths: Tuple[Path, ...] = (),
) -> RuntimeContextPreflight:
    """Prepare one Codex role without crossing role-specific boundaries."""

    _reject_legacy_user_sandbox_config()
    _require_codex_permissions(executable)
    resolved_role = _resolve_codex_role(role)
    settings = role.settings
    harness_skills = _resolve_harness_skills(
        runtime_store, role.required_skills, repository_skill_source,
    )
    repository_skills = _resolve_repository_skills(
        repository_skill_source, requested_skills
    )
    resolved_role._launch_request(
        executable=executable,
        runtime_store=runtime_store,
        git_common_directory=git_common_directory,
        worktree=worktree,
        evidence=evidence,
        effective_skills=harness_skills + repository_skills,
        report_files=report_files,
        model=settings.model,
        child_batch_write_paths=child_batch_write_paths,
        leader_control_write_paths=leader_control_write_paths,
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
        _harness_skills=harness_skills,
        _requested_skills=requested_skills,
        _report_files=report_files,
        _child_batch_write_paths=child_batch_write_paths,
        _leader_control_write_paths=leader_control_write_paths,
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
        or not set(request).issubset({"arguments", "worktree_path", "session_parameters"})
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


def _resolve_codex_role(role: ResolvedChildRole) -> _CodexRole:
    """Translate a resolved child role using its fixed native permissions."""

    document = _packaged_role(role.name)
    _validate_role_schema(document)
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

    return _CodexRole(
        name=role.name,
        reasoning_effort=reasoning_effort,
        developer_instructions=role.instructions,
        required_skills=role.required_skills,
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


def _packaged_role(binding: str) -> Dict[str, Any]:
    try:
        content = resources.files("graphtraj.resources").joinpath(
            "codex", "agents", "{0}.toml".format(binding)
        ).read_bytes()
        return tomllib.loads(content.decode())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CodexAdapterError(
            "PACKAGED_ROLE_INVALID",
            "The installed Codex role resource is invalid.",
        ) from error


def _resolve_harness_skills(
    runtime_store: Path,
    required_skills: Tuple[str, ...],
    repository_skill_source: Path,
) -> Tuple[_EffectiveSkill, ...]:
    """Locate the external Skills required by the resolved GraphTraj role."""

    if not required_skills:
        return ()
    source_history_paths = _runtime_source_history_paths(
        runtime_store,
        repository_skill_source,
    )
    skills = required_skill_paths(
        runtime_store,
        Path.home() / ".agents" / "skills",
        required_skills,
        source_history_paths=source_history_paths,
    )
    harness_skills = required_skill_paths(
        runtime_store,
        Path.home() / ".agents" / "skills",
        required_skills,
        source_history_paths=source_history_paths,
        include_user_skills=False,
    )
    effective: List[_EffectiveSkill] = []
    for name in required_skills:
        path = skills.get(name)
        if path is None:
            raise CodexAdapterError(
                "HARNESS_SKILL_NOT_FOUND",
                "The required Harness Skill {0} is not uniquely available.".format(
                    name
                ),
            )
        effective.append(
            _EffectiveSkill(
                name=name,
                path=path,
                enabled=True,
                source="harness" if name in harness_skills else "runtime-user",
            )
        )
    return tuple(effective)


def _runtime_source_history_paths(
    runtime_store: Path,
    repository_skill_source: Path,
) -> frozenset[str]:
    """Return tracked Skill paths when the runtime root shares this Source."""

    try:
        harness_repository = SourceRepository.from_root(runtime_store.parent)
        source_repository = SourceRepository.from_root(repository_skill_source)
        if harness_repository.common_directory != source_repository.common_directory:
            return frozenset()
        return source_history_skill_paths(harness_repository, harness_repository.head)
    except (GitRepositoryError, OSError):
        return frozenset()


def _resolve_repository_skills(
    worktree: Path,
    requested_names: Tuple[str, ...],
) -> Tuple[_EffectiveSkill, ...]:
    """Resolve the explicit Skill configuration beneath one Worktree."""

    repository_skills = _discover_skill_files(
        worktree / ".agents" / "skills"
    )
    selected_paths = set()
    for name in requested_names:
        matches = repository_skills.get(name, ())
        if not matches:
            raise CodexAdapterError(
                "REPOSITORY_SKILL_NOT_FOUND",
                "The requested Repository Skill {0} was not found in the Ticket Worktree.".format(
                    name
                ),
            )
        if len(matches) != 1:
            raise CodexAdapterError(
                "REPOSITORY_SKILL_AMBIGUOUS",
                "The requested Repository Skill {0} is ambiguous: {1}.".format(
                    name,
                    ", ".join(str(path) for path in matches),
                ),
            )
        selected_paths.add(matches[0])
    repository_entries = [
        (name, path)
        for name, paths in repository_skills.items()
        for path in paths
    ]
    effective: List[_EffectiveSkill] = []
    for name, path in sorted(repository_entries, key=lambda entry: str(entry[1])):
        effective.append(
            _EffectiveSkill(
                name=name,
                path=path,
                enabled=path in selected_paths,
                source="repository",
            )
        )
    return tuple(effective)


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

    resolved_role = ROLE_REFERENCES.get(role, role)
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
    if (
        resolved_role == "engineer"
        and isinstance(workspace_roots, dict)
        and workspace_roots.get(".") == "write"
        and workspace_roots.get("README.md") == "read"
    ):
        del workspace_roots["README.md"]
    if reports_only:
        if not isinstance(workspace_roots, dict) or "." not in workspace_roots:
            raise CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The durable Codex launch request has invalid Worktree permissions.",
            )
        workspace_roots["."] = "read"
    for path, access in tuple(filesystem.items()):
        if access == "write" and _is_prior_report_path(
            path, evidence, report_files
        ):
            del filesystem[path]
    for path in native_report_paths:
        filesystem[str(path)] = "write"
    if resolved_role == "team-leader" and session_directory is not None:
        # Continuing one direct child writes its Session directory, which
        # exists only after this Session started. Every other Leader path is
        # already granted by the durable launch request.
        for path in _leader_child_session_directories(session_directory):
            filesystem[str(path)] = "write"
    refreshed[permissions_index + 1] = "permissions={0}".format(
        _toml_value(permissions)
    )

    result = {**copy.deepcopy(request), "arguments": refreshed}
    params = result.get("session_parameters")
    if params is not None:
        params["config"]["permissions"] = permissions
    return result


def _leader_child_session_directories(
    session_directory: Path,
) -> Tuple[Path, ...]:
    """Return the registered direct child Session directories of one Leader."""
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


def _discover_skill_files(
    root: Path,
    *,
    source_history_paths: frozenset[str] = frozenset(),
) -> Dict[str, Tuple[Path, ...]]:
    """Return valid declared Skills beneath one explicit Runtime boundary."""
    try:
        if root.is_symlink() or not root.is_dir():
            return {}
        resolved_root = root.resolve(strict=True)
        candidates = tuple(sorted(root.rglob("SKILL.md")))
    except OSError:
        return {}
    discovered: Dict[str, List[Path]] = {}
    for candidate in candidates:
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if (
                candidate.relative_to(root.parents[1]).as_posix()
                in source_history_paths
            ):
                continue
            resolved = candidate.resolve(strict=True)
            if resolved_root not in (resolved, *resolved.parents):
                continue
            name = declared_skill_name(candidate.read_bytes())
        except OSError:
            continue
        if name is not None:
            discovered.setdefault(name, []).append(resolved)
    return {name: tuple(paths) for name, paths in discovered.items()}


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
