"""Existing native execution values shared by Runtime owners and consumers.

Task preparation, role selection and host routing belong to consumers.
"""

from __future__ import annotations

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
        """Retain the native error and whether execution termination is confirmed."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.terminal_confirmed = terminal_confirmed


class RuntimeTurn(Protocol):
    """One managed invocation, including native control and public identity."""

    def run(self) -> Dict[str, Any]:
        """Run the invocation until its Runtime reaches a terminal state."""

    @property
    def execution_id(self) -> str | None:
        """Return the opaque execution ID, available before session_started."""

    def operate(self, request: dict) -> dict:
        """Control the exact Session/execution named by a Worker request."""

    def terminate(self) -> bool:
        """Retain a stop request; return whether native interruption was scheduled.

        This is not terminal confirmation. run() retains ownership until the
        Runtime stops, including a stop requested before Session creation.
        """


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


def credential_environment(name: str | None) -> dict[str, str]:
    """Require a named execution credential without retaining or exposing its value."""
    import os
    import re

    if name is None:
        return {}
    if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise RuntimeAdapterError('ROLE_CONFIG_INVALID', 'api_key_env must name an environment variable.')
    value = os.environ.get(name)
    if not value:
        raise RuntimeAdapterError('RUNTIME_CREDENTIAL_MISSING', 'The configured api_key_env is missing or empty.')
    return {name: value}
