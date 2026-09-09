"""The allowlisted Codex Runtime adapter used by Agent Runner."""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .runtime_adapter import (
    RuntimeAdapterError,
    RuntimeContext,
    RuntimeContextPreflight,
    SessionStarted,
)
from .runner_transport import runtime_turn_outcome
from .role_definitions import ResolvedChildRole
from .git_repository import GitRepositoryError, SourceRepository
from .skill_check import (
    declared_skill_name,
    harness_skill_root,
    source_history_skill_paths,
)


ADAPTER_ROLE_KEYS = frozenset(
    {
        "model_reasoning_effort",
        "default_permissions",
        "hooks",
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
    hooks: Mapping[str, Any]
    agents: Mapping[str, Any]
    native_settings: Mapping[str, Any]

    def _launch_request(
        self,
        *,
        executable: Path,
        worktree: Path,
        evidence: Path,
        git_common_directory: Path,
        runtime_store: Path,
        effective_skills: Tuple[_EffectiveSkill, ...],
        report_files: Tuple[Path, ...],
        model: str,
        child_batch_write_paths: Tuple[Path, ...] = (),
    ) -> Dict[str, Any]:
        """Render the private request consumed by this Adapter's worker."""

        arguments = [
            str(executable),
            "exec",
            "-C",
            str(worktree),
            "--add-dir",
            str(evidence),
            "--add-dir",
            str(git_common_directory),
            "--model",
            model,
            "--dangerously-bypass-hook-trust",
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
        if self.name == "team-leader":
            # Runner retains and registers a child Batch before returning to the
            # Leader. The Guard still rejects direct writes to these paths.
            for path in child_batch_write_paths:
                native_settings["permissions"][self.default_permissions]["filesystem"][str(path)] = "write"
        if self.name == "merge-resolver":
            native_settings["permissions"][self.default_permissions]["filesystem"][str(evidence)] = "read"
        native_report_paths = _canonical_report_write_paths(
            evidence, report_files
        )
        for path in native_report_paths:
            native_settings["permissions"][self.default_permissions]["filesystem"][
                str(path)
            ] = "write"
        hook_report_paths = _report_write_paths(
            worktree, evidence, report_files
        )
        overrides = (
            *native_settings.items(),
            ("default_permissions", self.default_permissions),
            ("model_reasoning_effort", self.reasoning_effort),
            ("developer_instructions", developer_instructions),
            (
                "hooks",
                _root_owned_hooks(
                    self.hooks, runtime_store, self.name, effective_skills,
                    hook_report_paths,
                ),
            ),
            ("agents", self.agents),
            (
                "projects",
                {str(worktree): {"trust_level": "untrusted"}},
            ),
            (
                "skills",
                {"config": [skill.config_entry() for skill in effective_skills]},
            ),
        )
        for key, value in overrides:
            arguments.extend(("-c", "{0}={1}".format(key, _toml_value(value))))
        arguments.extend(("--json", "-"))
        return {"arguments": arguments, "worktree_path": str(worktree)}


@dataclass(frozen=True)
class _CodexRuntimePreflight:
    _runtime_store: Path
    _executable: Path
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

    def finalize(self) -> RuntimeContext:
        """Resolve Ticket Worktree facts shared by supported role boundaries."""

        effective_skills = self._harness_skills + _resolve_repository_skills(
            self._worktree, self._requested_skills
        )
        request = self._role._launch_request(
            executable=self._executable,
            worktree=self._worktree,
            evidence=self._evidence,
            git_common_directory=self._git_common_directory,
            runtime_store=self._runtime_store,
            effective_skills=effective_skills,
            report_files=self._report_files,
            model=self._model,
            child_batch_write_paths=self._child_batch_write_paths,
        )
        return _CodexRuntimeContext(
            _role=self._role.name,
            _model=self._model,
            _reasoning_effort=self._role.reasoning_effort,
            _arguments=tuple(request["arguments"]),
            _worktree=self._worktree,
            _effective_skills=effective_skills,
            _base_url=self._base_url,
            _api_key_env=self._api_key_env,
            _environment=self._environment,
        )


@dataclass(frozen=True)
class _CodexRuntimeContext:
    _role: str
    _model: str
    _reasoning_effort: str
    _arguments: Tuple[str, ...]
    _worktree: Path
    _effective_skills: Tuple[_EffectiveSkill, ...]
    _base_url: str | None
    _api_key_env: str | None
    _environment: Mapping[str, str]
    runtime: str = "codex"

    def launch_document(self) -> Dict[str, Any]:
        """Return the durable Adapter input for launch and resume."""

        return {
            "runtime": self.runtime,
            "adapter_request": {
                "arguments": list(self._arguments),
                "worktree_path": str(self._worktree),
            },
            "connection": {
                key: value
                for key, value in (
                    ("base_url", self._base_url),
                    ("api_key_env", self._api_key_env),
                )
                if value is not None
            },
        }

    def evidence_document(self) -> Dict[str, Any]:
        """Return the effective Context facts for mechanical evidence."""

        return {
            "runtime": self.runtime,
            "effective_role": self._role,
            "model": self._model,
            "model_reasoning_effort": self._reasoning_effort,
            "effective_skills": [
                skill.evidence_entry() for skill in self._effective_skills
            ],
        }

    def runtime_environment(self) -> Mapping[str, str]:
        """Return the ephemeral connection settings for the Runtime process."""
        return dict(self._environment)


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
        runtime_store=runtime_store,
        executable=executable,
        git_common_directory=git_common_directory,
        worktree=worktree,
        evidence=evidence,
        effective_skills=harness_skills + repository_skills,
        report_files=report_files,
        model=settings.model,
        child_batch_write_paths=child_batch_write_paths,
    )
    return _CodexRuntimePreflight(
        _runtime_store=runtime_store,
        _executable=executable,
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
        stderr_file = self._session_directory / "stderr.log"
        session: Optional[str] = None
        try:
            with stderr_file.open("w", encoding="utf-8") as runtime_stderr:
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

                with events_file.open("a", encoding="utf-8") as events:
                    for line in self._process.stdout:
                        events.write(line)
                        events.flush()
                        os.fsync(events.fileno())
                        if session is None:
                            session = _session_from_event(line)
                            if session is not None:
                                if (
                                    self._expected_session is not None
                                    and session != self._expected_session
                                ):
                                    raise CodexAdapterError(
                                        "RUNTIME_SESSION_NOT_RESUMABLE",
                                        "Codex did not resume the mapped Runtime session.",
                                    )
                                self._session_started(
                                    session, self._process.pid
                                )

                return_code = self._process.wait()
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
    """Attest one durable Codex session identity from Adapter-owned events."""

    events_file = session_directory / "events.jsonl"
    identity: Optional[str] = None
    try:
        if events_file.is_symlink() or not events_file.is_file():
            raise OSError("Codex events are not a regular file")
        with events_file.open("r", encoding="utf-8") as events:
            for line in events:
                session = _session_from_event(line)
                if session is None:
                    continue
                if identity is None:
                    identity = session
                elif session != identity:
                    raise ValueError("Codex events contain multiple sessions")
    except (OSError, UnicodeError, ValueError) as error:
        raise CodexAdapterError(
            "RUNTIME_SESSION_NOT_RESUMABLE",
            "The mapped Codex Runtime session cannot be attested.",
        ) from error
    if identity is None:
        raise CodexAdapterError(
            "RUNTIME_SESSION_NOT_RESUMABLE",
            "The mapped Codex Runtime session cannot be attested.",
        )
    return identity


def _validate_launch_request(
    request: Mapping[str, Any],
) -> Tuple[List[str], Path]:
    if not isinstance(request, dict) or set(request) != {
        "arguments",
        "worktree_path",
    }:
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
    """Refuse Codex releases without the invocation-local hard controls."""
    try:
        result = subprocess.run(
            [str(executable), "exec", "--help"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED", "Cannot verify Codex permission controls.",
        ) from error
    required = ("--sandbox", "--dangerously-bypass-hook-trust")
    if result.returncode or any(flag not in result.stdout for flag in required):
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "Codex must support filesystem sandboxing and invocation-local Hooks.",
        )


def _reject_legacy_user_sandbox_config() -> None:
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
    """Translate a resolved child role using its fixed native permissions and Hooks."""

    document = _packaged_role(role.name)
    _validate_role_schema(document)

    return _CodexRole(
        name=role.name,
        reasoning_effort=document["model_reasoning_effort"],
        developer_instructions=role.instructions,
        required_skills=role.required_skills,
        default_permissions=document["default_permissions"],
        hooks=document["hooks"],
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
    if not isinstance(document["hooks"], dict):
        raise _invalid_role_value("hooks")


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


def _verify_packaged_guard(runtime_store: Path) -> None:
    resource = resources.files("graphtraj.resources").joinpath(
        "codex", "hooks", "worktree_guard.py"
    )
    guard = runtime_store / "hooks" / "worktree_guard.py"
    try:
        if guard.is_symlink() or not guard.is_file():
            raise OSError("guard is not a regular file")
        installed = resource.read_bytes()
        project = guard.read_bytes()
    except OSError as error:
        raise CodexAdapterError(
            "ROLE_GUARD_MISMATCH",
            "The Harness Worktree Guard does not match the installed resource.",
        ) from error
    if project != installed:
        raise CodexAdapterError(
            "ROLE_GUARD_MISMATCH",
            "The Harness Worktree Guard does not match the installed resource.",
        )


def _resolve_harness_skills(
    runtime_store: Path,
    required_skills: Tuple[str, ...],
    repository_skill_source: Path,
) -> Tuple[_EffectiveSkill, ...]:
    """Locate the external Skills required by the resolved GraphTraj role."""

    if not required_skills:
        return ()
    runtime_skills = _discover_skill_files(
        harness_skill_root(runtime_store),
        source_history_paths=_runtime_source_history_paths(
            runtime_store,
            repository_skill_source,
        ),
    )
    user_skills = _discover_skill_files(Path.home() / ".agents" / "skills")
    effective: List[_EffectiveSkill] = []
    for name in required_skills:
        matches = runtime_skills.get(name, ())
        source = "harness"
        if not matches:
            matches = user_skills.get(name, ())
            source = "runtime-user"
        if len(matches) != 1:
            raise CodexAdapterError(
                "HARNESS_SKILL_NOT_FOUND",
                "The required Harness Skill {0} is not uniquely available.".format(
                    name
                ),
            )
        effective.append(
            _EffectiveSkill(
                name=name,
                path=matches[0],
                enabled=True,
                source=source,
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


def _report_write_paths(
    worktree: Path,
    evidence: Path,
    report_files: Tuple[Path, ...],
) -> Tuple[Path, ...]:
    """Return both supported spellings of each exact ticket report target."""
    canonical_paths = _canonical_report_write_paths(evidence, report_files)
    return tuple(
        path
        for report, canonical in zip(report_files, canonical_paths)
        for path in (worktree / report, canonical)
    )


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
) -> Dict[str, Any]:
    """Refresh only exact report permissions in one durable resume request."""
    arguments, request_worktree = _validate_launch_request(request)
    if request_worktree != worktree:
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request targets another Worktree.",
        )
    refreshed = list(arguments)
    if not report_files:
        return {"arguments": refreshed, "worktree_path": str(request_worktree)}

    native_report_paths = _canonical_report_write_paths(
        evidence, report_files
    )
    hook_report_paths = _report_write_paths(worktree, evidence, report_files)
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
    for path, access in tuple(filesystem.items()):
        if access == "write" and _is_prior_report_path(
            path, evidence, report_files
        ):
            del filesystem[path]
    for path in native_report_paths:
        filesystem[str(path)] = "write"
    refreshed[permissions_index + 1] = "permissions={0}".format(
        _toml_value(permissions)
    )

    hooks_index, hooks = _resume_request_setting(refreshed, "hooks")
    if not isinstance(hooks, dict):
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request has invalid report Hooks.",
        )
    hooks = copy.deepcopy(hooks)
    try:
        for event in ("PreToolUse", "SubagentStart"):
            entries = hooks[event]
            if not isinstance(entries, list):
                raise ValueError("Hook entries must be a list")
            for entry in entries:
                commands = entry["hooks"]
                if not isinstance(commands, list):
                    raise ValueError("Nested Hook entries must be a list")
                for hook in commands:
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        raise ValueError("Hook must be a command")
                    hook["command"] = _refresh_guard_write_paths(
                        hook["command"], hook_report_paths
                    )
    except (KeyError, TypeError, ValueError) as error:
        raise CodexAdapterError(
            "RUNTIME_REQUEST_INVALID",
            "The durable Codex launch request has invalid report Hooks.",
        ) from error
    refreshed[hooks_index + 1] = "hooks={0}".format(_toml_value(hooks))
    return {"arguments": refreshed, "worktree_path": str(request_worktree)}


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


def _refresh_guard_write_paths(
    command: Any, report_paths: Tuple[Path, ...]
) -> str:
    if not isinstance(command, str):
        raise ValueError("Hook command must be text")
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        raise ValueError("Hook command cannot be parsed") from error
    if not any(Path(token).name == "worktree_guard.py" for token in tokens):
        raise ValueError("Hook command is not the Worktree Guard")
    refreshed: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index] == "--write-path":
            if index + 1 == len(tokens):
                raise ValueError("Hook write path is missing")
            index += 2
            continue
        if tokens[index].startswith("--write-path="):
            raise ValueError("Hook write path is unsupported")
        refreshed.append(tokens[index])
        index += 1
    for path in report_paths:
        refreshed.extend(("--write-path", str(path)))
    return shlex.join(refreshed)


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


def _root_owned_hooks(
    packaged_hooks: Mapping[str, Any],
    runtime_store: Path,
    role: str,
    effective_skills: Tuple[_EffectiveSkill, ...],
    write_paths: Tuple[Path, ...],
) -> Mapping[str, Any]:
    """Translate canonical Hooks to the root-owned Worktree Guard."""
    _verify_packaged_guard(runtime_store)
    hooks = copy.deepcopy(dict(packaged_hooks))
    command = "{0} {1}".format(
        shlex.quote(sys.executable),
        shlex.quote(str(runtime_store / "hooks" / "worktree_guard.py")),
    )
    if role == "team-leader":
        command += " --team-leader"
    for path in write_paths:
        command += " --write-path " + shlex.quote(str(path))
    for skill in effective_skills:
        if skill.enabled:
            for path in sorted(skill.path.parent.rglob("*")):
                if (
                    path.is_file() and not path.is_symlink()
                    and path.resolve().is_relative_to(skill.path.parent)
                ):
                    command += " --read-skill " + shlex.quote(str(path))
    try:
        for event in ("PreToolUse", "SubagentStart"):
            entries = hooks[event]
            if not isinstance(entries, list):
                raise ValueError("Hook entries must be a list")
            for entry in entries:
                commands = entry["hooks"]
                if not isinstance(commands, list):
                    raise ValueError("Nested Hook entries must be a list")
                for hook in commands:
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        raise ValueError("Hook must be a command")
                    hook["command"] = command
    except (KeyError, TypeError, ValueError) as error:
        raise CodexAdapterError(
            "ROLE_HOOK_MISMATCH",
            "The configured Codex role does not contain the packaged Worktree Guard hooks.",
        ) from error
    return hooks


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
