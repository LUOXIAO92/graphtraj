"""The allowlisted Codex Runtime adapter used by Agent Runner."""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import signal
import subprocess
import time
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

from .runtime_adapter import (
    EngineerRuntimeContextPreflight,
    RuntimeAdapterError,
    RuntimeContext,
    RuntimeContextPreflight,
    SessionStarted,
)
from .runner_transport import runtime_turn_outcome
from .runner_models import LOGICAL_ROLES, managed_runtime_policy_matches
from .git_repository import GitRepositoryError, SourceRepository
from .skill_check import (
    declared_skill_name,
    harness_skill_root,
    source_history_skill_paths,
)


ADAPTER_ROLE_KEYS = frozenset(
    {
        "name",
        "description",
        "model",
        "model_reasoning_effort",
        "developer_instructions",
        "default_permissions",
        "hooks",
        "agents",
    }
)
REQUIRED_ROLE_KEYS = ADAPTER_ROLE_KEYS - {"description"}
SUPPORTED_AGENT_KEYS = frozenset(
    {
        "enabled",
        "max_concurrent_threads_per_session",
        "default_subagent_model",
        "default_subagent_reasoning_effort",
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
    model: str
    reasoning_effort: str
    developer_instructions: str
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
        report_file: Path | None,
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
            self.model,
            "--dangerously-bypass-hook-trust",
        ]
        developer_instructions = self.developer_instructions
        for skill in effective_skills:
            if (
                skill.enabled
                and skill.source in ("harness", "runtime-user")
                and skill.name in ENGINEER_REQUIRED_SKILLS
            ):
                developer_instructions = developer_instructions.replace(
                    "${0}".format(skill.name),
                    "[${0}]({1})".format(skill.name, skill.path),
                )
        native_settings = copy.deepcopy(dict(self.native_settings))
        if report_file is not None:
            native_settings["permissions"][self.default_permissions]["filesystem"][
                str(evidence / "reviews" / report_file.name)
            ] = "write"
        overrides = (
            *native_settings.items(),
            ("default_permissions", self.default_permissions),
            ("model_reasoning_effort", self.reasoning_effort),
            ("developer_instructions", developer_instructions),
            ("hooks", _root_owned_hooks(self.hooks, runtime_store)),
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
    _worktree: Path
    _evidence: Path
    _harness_skills: Tuple[_EffectiveSkill, ...]
    _requested_skills: Tuple[str, ...]
    _report_file: Path | None

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
            report_file=self._report_file,
        )
        return _CodexRuntimeContext(
            _role=self._role.name,
            _model=self._role.model,
            _reasoning_effort=self._role.reasoning_effort,
            _arguments=tuple(request["arguments"]),
            _worktree=self._worktree,
            _effective_skills=effective_skills,
        )


@dataclass(frozen=True)
class _CodexRuntimeContext:
    _role: str
    _model: str
    _reasoning_effort: str
    _arguments: Tuple[str, ...]
    _worktree: Path
    _effective_skills: Tuple[_EffectiveSkill, ...]
    runtime: str = "codex"

    def launch_document(self) -> Dict[str, Any]:
        """Return the durable Adapter input for launch and resume."""

        return {
            "runtime": self.runtime,
            "adapter_request": {
                "arguments": list(self._arguments),
                "worktree_path": str(self._worktree),
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


def preflight_engineer_runtime_context(
    *,
    runtime_store: Path,
    executable: Path,
    git_common_directory: Path,
    role: str,
    worktree: Path,
    evidence: Path,
    repository_skill_source: Path,
    requested_skills: Tuple[str, ...],
) -> EngineerRuntimeContextPreflight:
    """Validate every Engineer Context fact available before provisioning."""

    if role not in ENGINEER_ROLES:
        raise CodexAdapterError(
            "ROLE_NOT_SUPPORTED",
            "The configured Codex role is not supported by this Runner.",
        )
    return cast(
        EngineerRuntimeContextPreflight,
        preflight_runtime_context(
            runtime_store=runtime_store,
            executable=executable,
            git_common_directory=git_common_directory,
            role=role,
            worktree=worktree,
            evidence=evidence,
            repository_skill_source=repository_skill_source,
            requested_skills=requested_skills,
            report_file=None,
        ),
    )


def preflight_runtime_context(
    *,
    runtime_store: Path,
    executable: Path,
    git_common_directory: Path,
    role: str,
    worktree: Path,
    evidence: Path,
    repository_skill_source: Path,
    requested_skills: Tuple[str, ...],
    report_file: Path | None = None,
) -> RuntimeContextPreflight:
    """Prepare one Codex role without crossing role-specific boundaries."""

    _reject_legacy_user_sandbox_config()
    resolved_role = _resolve_codex_role(runtime_store, role)
    if role in ENGINEER_ROLES:
        harness_skills = _resolve_engineer_harness_skills(
            runtime_store,
            role,
            repository_skill_source,
        )
    elif role in REVIEWER_ROLES:
        harness_skills = ()
    else:
        raise CodexAdapterError(
            "ROLE_NOT_SUPPORTED",
            "The configured Codex role is not supported by this Runner.",
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
        report_file=report_file,
    )
    return _CodexRuntimePreflight(
        _runtime_store=runtime_store,
        _executable=executable,
        _git_common_directory=git_common_directory,
        _role=resolved_role,
        _worktree=worktree,
        _evidence=evidence,
        _harness_skills=harness_skills,
        _requested_skills=requested_skills,
        _report_file=report_file,
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


def _resolve_codex_role(runtime_store: Path, binding: str) -> _CodexRole:
    """Resolve and vet one canonical role from the Harness Runtime Store."""

    agent_directory = runtime_store / "agents"
    if not agent_directory.is_dir() or agent_directory.is_symlink():
        raise CodexAdapterError(
            "ROLE_NOT_FOUND",
            "The configured Codex role was not found in Harness Agent files.",
        )

    matching: List[Tuple[Path, Dict[str, Any]]] = []
    canonical_document: Optional[Dict[str, Any]] = None
    for path in sorted(agent_directory.glob("*.toml")):
        if path.is_symlink() or not path.is_file():
            raise CodexAdapterError(
                "ROLE_CONFIG_INVALID",
                "Harness Codex Agent files must be regular files.",
            )
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise CodexAdapterError(
                "ROLE_CONFIG_INVALID",
                "A Harness Codex Agent file is not valid readable TOML.",
            ) from error
        if path.name == "{0}.toml".format(binding):
            canonical_document = document
        if document.get("name") == binding:
            matching.append((path, document))

    if not matching:
        if canonical_document is not None:
            _validate_role_schema(canonical_document)
            raise CodexAdapterError(
                "ROLE_CONFIG_MISMATCH",
                "The configured Codex role contains managed policy drift.",
            )
        raise CodexAdapterError(
            "ROLE_NOT_FOUND",
            "The configured Codex role was not found in Harness Agent files.",
        )
    if len(matching) != 1:
        raise CodexAdapterError(
            "ROLE_DUPLICATE",
            "The configured Codex role resolves to more than one Harness Agent file.",
        )

    _, document = matching[0]
    _validate_role_schema(document)
    expected = _packaged_role(binding, runtime_store)
    if document["hooks"] != expected.get("hooks"):
        raise CodexAdapterError(
            "ROLE_HOOK_MISMATCH",
            "The configured Codex role does not contain the packaged Worktree Guard hooks.",
        )
    if not managed_runtime_policy_matches(document, expected):
        raise CodexAdapterError(
            "ROLE_CONFIG_MISMATCH",
            "The configured Codex role contains managed policy drift.",
        )
    _verify_packaged_guard(runtime_store)

    return _CodexRole(
        name=binding,
        model=document["model"],
        reasoning_effort=document["model_reasoning_effort"],
        developer_instructions=document["developer_instructions"],
        default_permissions=document["default_permissions"],
        hooks=document["hooks"],
        agents=document["agents"],
        native_settings={
            key: value
            for key, value in document.items()
            if key not in ADAPTER_ROLE_KEYS
        },
    )


def _validate_role_schema(document: Mapping[str, Any]) -> None:
    keys = frozenset(document)
    if not REQUIRED_ROLE_KEYS.issubset(keys):
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "The configured Codex role uses an unsupported top-level schema.",
        )
    if not isinstance(document["name"], str):
        raise _invalid_role_value("name")
    if "description" in document and not isinstance(document["description"], str):
        raise _invalid_role_value("description")
    if not _nonempty_string(document["model"]):
        raise _invalid_role_value("model")
    if document["model_reasoning_effort"] not in REASONING_EFFORTS:
        raise _invalid_role_value("model_reasoning_effort")
    if not _nonempty_string(document["developer_instructions"]):
        raise _invalid_role_value("developer_instructions")
    if not _nonempty_string(document["default_permissions"]):
        raise _invalid_role_value("default_permissions")
    if not isinstance(document["hooks"], dict):
        raise _invalid_role_value("hooks")

    agents = document["agents"]
    if not isinstance(agents, dict) or frozenset(agents) != SUPPORTED_AGENT_KEYS:
        raise CodexAdapterError(
            "ROLE_CONFIG_UNSUPPORTED",
            "The configured Codex role uses an unsupported agents schema.",
        )
    if not isinstance(agents["enabled"], bool):
        raise _invalid_role_value("agents.enabled")
    maximum = agents["max_concurrent_threads_per_session"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise _invalid_role_value("agents.max_concurrent_threads_per_session")
    if not _nonempty_string(agents["default_subagent_model"]):
        raise _invalid_role_value("agents.default_subagent_model")
    if agents["default_subagent_reasoning_effort"] not in REASONING_EFFORTS:
        raise _invalid_role_value("agents.default_subagent_reasoning_effort")


def _invalid_role_value(field: str) -> CodexAdapterError:
    return CodexAdapterError(
        "ROLE_CONFIG_INVALID",
        "The configured Codex role has an invalid {0} value.".format(field),
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _packaged_role(binding: str, runtime_store: Path) -> Dict[str, Any]:
    if binding not in SUPPORTED_ROLES:
        raise CodexAdapterError(
            "ROLE_NOT_SUPPORTED",
            "The configured Codex role is not supported by this Runner.",
        )
    try:
        from .codex_project import CodexProjectFiles

        content = CodexProjectFiles.load().runtime_resources(runtime_store)[
            "agents/{0}.toml".format(binding)
        ]
        return tomllib.loads(content.decode())
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CodexAdapterError(
            "PACKAGED_ROLE_INVALID",
            "The installed Codex role resource is invalid.",
        ) from error


def _verify_packaged_guard(runtime_store: Path) -> None:
    resource = resources.files("you_are_a_product_architect.resources").joinpath(
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


ENGINEER_ROLES = frozenset(
    role for role in LOGICAL_ROLES if role.startswith("engineer-")
)
REVIEWER_ROLES = frozenset(LOGICAL_ROLES) - ENGINEER_ROLES
SUPPORTED_ROLES = ENGINEER_ROLES | REVIEWER_ROLES
ENGINEER_REQUIRED_SKILLS = ("implement", "ponytail", "tdd")


def _resolve_engineer_harness_skills(
    runtime_store: Path,
    role: str,
    repository_skill_source: Path,
) -> Tuple[_EffectiveSkill, ...]:
    """Resolve the Engineer role's required external Harness Skills."""

    if role not in ENGINEER_ROLES:
        raise CodexAdapterError(
            "ROLE_NOT_SUPPORTED",
            "The configured Codex role is not supported by this Runner.",
        )
    runtime_skills = _discover_skill_files(
        harness_skill_root(runtime_store),
        source_history_paths=_runtime_source_history_paths(
            runtime_store,
            repository_skill_source,
        ),
    )
    user_skills = _discover_skill_files(Path.home() / ".agents" / "skills")
    effective: List[_EffectiveSkill] = []
    for name in ENGINEER_REQUIRED_SKILLS:
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
) -> Mapping[str, Any]:
    """Translate canonical Hooks to the root-owned Worktree Guard."""
    _verify_packaged_guard(runtime_store)
    hooks = copy.deepcopy(dict(packaged_hooks))
    command = "python3 {0}".format(
        shlex.quote(str(runtime_store / "hooks" / "worktree_guard.py"))
    )
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
