"""The allowlisted Codex Runtime adapter used by Agent Runner."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .runtime_adapter import RuntimeAdapterError, SessionStarted


SUPPORTED_ROLE_KEYS = frozenset(
    {
        "name",
        "description",
        "model",
        "model_reasoning_effort",
        "developer_instructions",
        "sandbox_mode",
        "hooks",
        "agents",
    }
)
REQUIRED_ROLE_KEYS = SUPPORTED_ROLE_KEYS - {"description"}
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
SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class CodexAdapterError(RuntimeAdapterError):
    """A selected Codex role cannot be launched safely."""


@dataclass(frozen=True)
class CodexRole:
    """Validated effective settings for one project-local custom Agent."""

    name: str
    model: str
    reasoning_effort: str
    developer_instructions: str
    sandbox_mode: str
    hooks: Mapping[str, Any]
    agents: Mapping[str, Any]

    def launch_request(
        self,
        *,
        executable: Path,
        worktree: Path,
        evidence: Path,
    ) -> Dict[str, Any]:
        """Render the private request consumed by this Adapter's worker."""

        arguments = [
            str(executable),
            "exec",
            "-C",
            str(worktree),
            "--add-dir",
            str(evidence),
            "--model",
            self.model,
            "--sandbox",
            self.sandbox_mode,
            "--dangerously-bypass-hook-trust",
        ]
        overrides = (
            ("model_reasoning_effort", self.reasoning_effort),
            ("developer_instructions", self.developer_instructions),
            ("hooks", self.hooks),
            ("agents", self.agents),
        )
        for key, value in overrides:
            arguments.extend(("-c", "{0}={1}".format(key, _toml_value(value))))
        arguments.extend(("--json", "-"))
        return {"arguments": arguments, "worktree_path": str(worktree)}


class CodexTurn:
    """Adapter-owned lifecycle for one Codex process group."""

    def __init__(
        self,
        request: Mapping[str, Any],
        prompt: str,
        session_directory: Path,
        session_started: SessionStarted,
    ) -> None:
        self._request = request
        self._prompt = prompt
        self._session_directory = session_directory
        self._session_started = session_started
        self._process: Optional[subprocess.Popen] = None

    def run(self) -> Dict[str, Any]:
        """Own the process and translate its private JSONL protocol."""

        arguments, worktree = _validate_launch_request(self._request)
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
        return {
            "outcome": "completed" if return_code == 0 else "runtime-error",
            "runtime_exit_code": return_code,
        }

    def terminate(self) -> bool:
        """Signal only this Codex process group and confirm its exit."""

        return _stop_process(self._process)


def create_codex_turn(
    request: Mapping[str, Any],
    prompt: str,
    session_directory: Path,
    session_started: SessionStarted,
) -> CodexTurn:
    """Create an invocation without exposing Codex mechanics to the worker."""

    return CodexTurn(request, prompt, session_directory, session_started)


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
    if process is None or process.poll() is not None:
        return True
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        return True
    except ProcessLookupError:
        try:
            process.wait(timeout=0.1)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return process.poll() is not None
        return True


def resolve_codex_role(worktree: Path, binding: str) -> CodexRole:
    """Resolve and vet one project custom-Agent name from a Worktree."""

    agent_directory = worktree / ".codex" / "agents"
    if not agent_directory.is_dir() or agent_directory.is_symlink():
        raise CodexAdapterError(
            "ROLE_NOT_FOUND",
            "The configured Codex role was not found in project Agent files.",
        )

    matching: List[Tuple[Path, Dict[str, Any]]] = []
    for path in sorted(agent_directory.glob("*.toml")):
        if path.is_symlink() or not path.is_file():
            raise CodexAdapterError(
                "ROLE_CONFIG_INVALID",
                "Project Codex Agent files must be regular files.",
            )
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise CodexAdapterError(
                "ROLE_CONFIG_INVALID",
                "A project Codex Agent file is not valid readable TOML.",
            ) from error
        if document.get("name") == binding:
            matching.append((path, document))

    if not matching:
        raise CodexAdapterError(
            "ROLE_NOT_FOUND",
            "The configured Codex role was not found in project Agent files.",
        )
    if len(matching) != 1:
        raise CodexAdapterError(
            "ROLE_DUPLICATE",
            "The configured Codex role resolves to more than one project Agent file.",
        )

    _, document = matching[0]
    _validate_role_schema(document)
    expected = _packaged_role(binding)
    if document["hooks"] != expected.get("hooks"):
        raise CodexAdapterError(
            "ROLE_HOOK_MISMATCH",
            "The configured Codex role does not contain the packaged Worktree Guard hooks.",
        )
    _verify_packaged_guard(worktree)

    return CodexRole(
        name=binding,
        model=document["model"],
        reasoning_effort=document["model_reasoning_effort"],
        developer_instructions=document["developer_instructions"],
        sandbox_mode=document["sandbox_mode"],
        hooks=document["hooks"],
        agents=document["agents"],
    )


def _validate_role_schema(document: Mapping[str, Any]) -> None:
    keys = frozenset(document)
    if not REQUIRED_ROLE_KEYS.issubset(keys) or not keys.issubset(
        SUPPORTED_ROLE_KEYS
    ):
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
    if document["sandbox_mode"] not in SANDBOX_MODES:
        raise _invalid_role_value("sandbox_mode")
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


def _packaged_role(binding: str) -> Dict[str, Any]:
    if not re.fullmatch(r"engineer-(?:junior|senior|expert)", binding):
        raise CodexAdapterError(
            "ROLE_NOT_SUPPORTED",
            "The configured Codex role is not supported by this Runner.",
        )
    resource = resources.files("you_are_a_product_architect.resources").joinpath(
        "codex", "agents", "{0}.toml".format(binding)
    )
    try:
        return tomllib.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CodexAdapterError(
            "PACKAGED_ROLE_INVALID",
            "The installed Codex role resource is invalid.",
        ) from error


def _verify_packaged_guard(worktree: Path) -> None:
    resource = resources.files("you_are_a_product_architect.resources").joinpath(
        "codex", "hooks", "worktree_guard.py"
    )
    guard = worktree / ".codex" / "hooks" / "worktree_guard.py"
    try:
        if guard.is_symlink() or not guard.is_file():
            raise OSError("guard is not a regular file")
        installed = resource.read_bytes()
        project = guard.read_bytes()
    except OSError as error:
        raise CodexAdapterError(
            "ROLE_GUARD_MISMATCH",
            "The project Worktree Guard does not match the installed resource.",
        ) from error
    if project != installed:
        raise CodexAdapterError(
            "ROLE_GUARD_MISMATCH",
            "The project Worktree Guard does not match the installed resource.",
        )


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
