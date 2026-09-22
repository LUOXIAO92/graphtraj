"""Shared Runtime Context, invocation and native execution result contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping, Protocol, TypedDict


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


def native_command_approval(command: str, cwd: str) -> bool:
    """Return whether the caller's own native Runtime approved this command.

    The Runtime details stay in the Adapter: this entry only asks whether the
    decision already recorded for the command line this process is running,
    in the working directory it is running in, is an approval. It reads what
    already happened; it produces no request and stores nothing.
    """

    from graphtraj.runtimes.codex.native_approval import codex_native_command_approval

    return codex_native_command_approval(command, cwd)
