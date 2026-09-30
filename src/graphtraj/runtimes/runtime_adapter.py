"""Shared Runtime Context, invocation and native execution result contracts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Mapping, Protocol, Sequence, TypedDict

if TYPE_CHECKING:
    from graphtraj.configuration.role_definitions import ResolvedChildRole


SessionStarted = Callable[[str, int], None]
NativeReplacement = Callable[[Sequence[str]], dict]


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


class RuntimeContextPreflight(Protocol):
    """A side-effect-free preparation awaiting Ticket Worktree facts."""

    def finalize(self) -> RuntimeContext:
        """Resolve Worktree-local facts and freeze the effective Context."""


class RuntimePreparationAdapter(Protocol):
    """Prepare Context and interpret execution diagnostics for a Runtime."""

    def current_execution_diagnostic(
        self,
        session_directory: Path,
        trace_file: Path,
        stderr_offset: int,
        trace_offset: int,
    ) -> str:
        """Return diagnostic text without assigning task failure categories.

        Offsets are byte positions captured before the current execution.
        Interpret only new native error records and current stderr; preserve
        the stored Trace and ignore successful output and Agent prose.
        """

    def native_replacement_approval(self) -> NativeReplacement | None:
        """Return native execution, or None only for known absence of approvals.

        Unknown capability and unavailable channels must raise, never return None.
        The operation returns its replacement result or native execution request;
        rejection and execution failure must raise without local fallback.
        """

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
        """Validate Runtime inputs before a Session allocation is published."""

    def operation_total(self, trace_file: Path, session: str) -> int:
        """Return the Runtime's own count of native operations for one Session.

        The Adapter interprets its own native records, so a caller observes
        the Runtime's operations without knowing that Runtime's event shapes.
        An unreadable record must fail rather than report no operations.
        """


class RuntimeAdapter(RuntimePreparationAdapter, Protocol):
    """Prepare Context and own managed execution for the selected Runtime."""

    def send_host_event(self, connection: Mapping[str, Any], event: dict[str, str]) -> dict:
        """Forward an event to the captured owning host, without creating a Session."""

    def read_session_identity(self, session_directory: Path) -> str:
        """Attest the native Session identity from its retained Runtime record."""

    def recovery_environment(self, connection: Mapping[str, Any]) -> Mapping[str, str]:
        """Validate retained connection settings and resolve transient overrides."""

    def recover_report_files(
        self, request: Mapping[str, Any], evidence: Path,
    ) -> tuple[str, ...]:
        """Recover old report assignments from exact retained native write grants.

        Return Worktree-relative .state paths; fail if ownership cannot be
        established. Read grants must never become report assignments.
        """

    def refresh_report_paths(
        self,
        request: Mapping[str, Any],
        *,
        worktree: Path,
        evidence: Path,
        report_files: tuple[Path, ...],
        role: str,
        reports_only: bool = False,
        session_directory: Path | None = None,
    ) -> Dict[str, Any]:
        """Validate and copy retained settings for same-Session recovery.

        Preserve native permissions/settings except refreshed report access and
        explicit reports-only tightening. Never mutate the retained launch.
        """

    def managed_execution(
        self,
        request: dict,
        prompt: str,
        session_directory: Path,
        session_started: SessionStarted,
        context_evidence: dict,
        *,
        trace_file: Path,
        expected_session: str | None = None,
        session_created: SessionStarted,
    ) -> RuntimeTurn:
        """Construct an unstarted owner from retained Adapter configuration.

        run() calls session_created with Session ID and service PID before any
        task execution, allowing binding and member registration to finish.
        It then calls session_started with those identities once execution_id
        is available, before acknowledging execution to the caller. A resumed
        owner must retain expected_session. Callbacks may refuse execution.
        """


def current_host_connection() -> dict | None:
    """Capture supported host context at the trusted root launch boundary."""
    from graphtraj.runtimes.codex.host_events import current_connection

    return current_connection()


def select_runtime_adapter(runtime: str) -> RuntimeAdapter:
    """Select an implemented Adapter from the resolved role's Runtime setting."""
    if runtime == "codex":
        from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter

        return CodexRuntimeAdapter()
    raise RuntimeAdapterError(
        "RUNTIME_UNSUPPORTED",
        "The selected Agent Runtime is not supported by this Runner.",
    )


def native_replacement_approval(runtime: str | None) -> NativeReplacement | None:
    """Resolve approval capability without treating unsupported Runtimes as absent.

    pi's previously supported absence is retained here without pretending it has
    a launch Adapter. Every implemented Runtime uses the shared Adapter selector.
    """
    if runtime == "pi":
        return None
    if runtime is None:
        raise RuntimeAdapterError("RUNTIME_UNSUPPORTED", "The calling Runtime is unknown.")
    return select_runtime_adapter(runtime).native_replacement_approval()
