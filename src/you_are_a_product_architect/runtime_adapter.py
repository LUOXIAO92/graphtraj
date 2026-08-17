"""Runtime-neutral contracts for one background Engineer turn."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Protocol


SessionStarted = Callable[[str, int], None]


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


class EngineerRuntimeContext(Protocol):
    """One immutable Adapter-owned launch, evidence, and recovery Context."""

    @property
    def runtime(self) -> str:
        """Return the selected Runtime's stable name."""

    def launch_document(self) -> Dict[str, Any]:
        """Return a fresh durable document for launch and resume."""

    def evidence_document(self) -> Dict[str, Any]:
        """Return a fresh document of the effective Context facts."""


class EngineerRuntimeContextPreflight(Protocol):
    """A side-effect-free preparation awaiting Ticket Worktree facts."""

    def finalize(self) -> EngineerRuntimeContext:
        """Resolve Worktree-local facts and freeze the effective Context."""


RuntimeAdapter = Callable[
    [Mapping[str, Any], str, Path, SessionStarted], RuntimeTurn
]
ResumeRuntimeAdapter = Callable[
    [Mapping[str, Any], str, str, Path, SessionStarted], RuntimeTurn
]
