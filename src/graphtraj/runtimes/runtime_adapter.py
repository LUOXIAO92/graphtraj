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


def review_role_request(
    harness_root: Path,
    role_reference: str,
    context: Mapping[str, Any],
) -> dict:
    """Return the review decision one mapped role's own Runtime gives a request.

    The caller supplies only Runtime-agnostic facts: who asked, which seat the
    request names and what the request is. Each Runtime decides how its roles
    review, so an implementation resolves the role's own provider route, a
    hosted default, or its own user channel without the caller knowing which.
    A Runtime without a review path raises :class:`RuntimeAdapterError`.
    """
    from graphtraj.configuration.project_roles import load_project_roles

    settings = load_project_roles(harness_root).preset(role_reference)
    if settings.runtime == "codex":
        from graphtraj.runtimes.codex.approval import review_role_request as review

        return review(settings, harness_root / ".codex", context)
    raise RuntimeAdapterError(
        "ROLE_NOT_SUPPORTED",
        "The caller's role runs on a Runtime that reviews no request.",
    )


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
