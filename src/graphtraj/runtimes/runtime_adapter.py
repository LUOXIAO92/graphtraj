"""Shared Runtime Context, invocation and native execution result contracts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Mapping, Protocol, TypedDict

if TYPE_CHECKING:
    from graphtraj.configuration.role_definitions import ResolvedChildRole


SessionStarted = Callable[[str, int], None]


class RuntimeExecutionResult(TypedDict):
    """One terminal native result; failures use RuntimeAdapterError."""

    outcome: Literal["completed", "interrupted"]
    session_id: str
    execution_id: str
    last_agent_message: str | None


class RuntimeAdapterError(Exception):
    """A Runtime Adapter failed with a stable Runner-facing error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        terminal_confirmed: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.terminal_confirmed = terminal_confirmed


class RuntimeTurn(Protocol):
    """One Adapter-owned Runtime invocation."""

    def run(self) -> Dict[str, Any]:
        """Run the invocation until its Runtime reaches a terminal state."""

    def terminate(self) -> bool:
        """Request termination and confirm that it stopped a live Runtime."""

    def terminate_until_terminal(self) -> None:
        """Keep ownership until the Runtime process group is terminal."""


class RuntimeContext(Protocol):
    """One immutable Adapter-owned launch, evidence, and recovery Context."""

    @property
    def runtime(self) -> str:
        """Return the selected Runtime's stable name."""

    def launch_document(self) -> Dict[str, Any]:
        """Return a fresh durable document for launch and resume."""

    def evidence_document(self) -> Dict[str, Any]:
        """Return a fresh document of the effective Context facts."""

    def session_document(self) -> Dict[str, Any]:
        """Return fresh Adapter-owned configuration for native Session operations."""

    def runtime_environment(self) -> Mapping[str, str]:
        """Return non-persistent environment overrides for the Runtime connection."""


class RuntimeContextPreflight(Protocol):
    """A side-effect-free preparation awaiting Ticket Worktree facts."""

    def finalize(self) -> RuntimeContext:
        """Resolve Worktree-local facts and freeze the effective Context."""


RuntimeAdapter = Callable[
    [Mapping[str, Any], str, Path, SessionStarted], RuntimeTurn
]
ResumeRuntimeAdapter = Callable[
    [Mapping[str, Any], str, str, Path, SessionStarted], RuntimeTurn
]


class RuntimePreparationAdapter(Protocol):
    """Prepare the existing Context contract for a selected Runtime."""

    def preflight_runtime_context(
        self,
        *,
        runtime_store: Path,
        git_common_directory: Path,
        role: ResolvedChildRole,
        worktree: Path,
        evidence: Path,
        requested_skills: tuple[str, ...],
        report_files: tuple[Path, ...] = (),
    ) -> RuntimeContextPreflight:
        """Validate Runtime inputs before a Session allocation is published."""


def select_runtime_adapter(runtime: str) -> RuntimePreparationAdapter:
    """Select an implemented Adapter from the resolved role's Runtime setting."""
    if runtime == "codex":
        from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter

        return CodexRuntimeAdapter()
    raise RuntimeAdapterError(
        "RUNTIME_UNSUPPORTED",
        "The selected Agent Runtime is not supported by this Runner.",
    )
