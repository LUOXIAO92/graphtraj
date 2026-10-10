"""Shared Runtime Context, invocation and native execution result contracts."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Mapping, Protocol, Sequence, TypedDict

if TYPE_CHECKING:
    from graphtraj.configuration.role_definitions import ResolvedChildRole


SessionStarted = Callable[[str, int], None]
NativeReplacement = Callable[[Sequence[str]], dict]
_recovery_reviewer: ContextVar[Callable[[dict], dict] | None] = ContextVar('recovery_reviewer', default=None)
_process_owner: ContextVar[Callable[[int, dict | None], None] | None] = ContextVar('process_owner', default=None)


@dataclass(frozen=True)
class CheckUsage:
    """Observed whole-check increments; None means unavailable, never zero.

    Output includes reasoning where the Runtime counts it as output. Model
    requests require independent native evidence, not a tool or user-turn count.
    """

    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    tool_calls: int | None = None
    model_requests: int | None = None

    def document(self) -> dict:
        """Return normalized facts with the whole-check cached/input ratio."""
        ratio = None
        if self.input_tokens and self.cached_input_tokens is not None:
            ratio = self.cached_input_tokens / self.input_tokens
        return {**asdict(self), 'cache_hit_ratio': ratio}

    def summary(self) -> str:
        """Render one compact English usage line without native protocol keys.

        Counters use thousands separators and stay explicitly unknown when
        unavailable. Cached input carries its hit rate, while reasoning is shown
        as the part of output rather than a parallel total.
        """
        def count(value: int | None) -> str:
            """Keep unavailable counters distinct from measured zero."""
            return f'{value:,}' if value is not None else 'unknown'

        ratio = self.document()['cache_hit_ratio']
        if self.cached_input_tokens is None:
            cached = 'Cached unknown'
        elif ratio is None:
            cached = f'Cached {count(self.cached_input_tokens)} (unknown)'
        else:
            cached = f'Cached {count(self.cached_input_tokens)} ({ratio:.1%})'
        return ' · '.join((
            f'Input {count(self.input_tokens)}',
            cached,
            f'Output {count(self.output_tokens)} (Reasoning {count(self.reasoning_tokens)})',
            f'Tools {count(self.tool_calls)}',
        ))


def finalize_usage(native: dict | None = None) -> CheckUsage:
    """Consume only Adapter-normalized usage; absent support needs no host."""
    usage = native.get('usage') if native else None
    return usage if isinstance(usage, CheckUsage) else CheckUsage()


@contextmanager
def runtime_process_owner(record: Callable[[int, dict | None], None]):
    """Bind the trusted Worker's pre-Session process creation callback."""
    token = _process_owner.set(record)
    try:
        yield
    finally:
        _process_owner.reset(token)


def record_runtime_process(pid: int, outcome: dict | None = None) -> None:
    """Publish owned process creation or termination without establishing a Session."""
    record = _process_owner.get()
    if record is not None:
        record(pid, outcome)


@contextmanager
def recovery_review(reviewer: Callable[[dict], dict] | None):
    """Bind the trusted host's selected reviewer, never a model request field."""
    token = _recovery_reviewer.set(reviewer)
    try:
        yield
    finally:
        _recovery_reviewer.reset(token)


def current_recovery_reviewer() -> Callable[[dict], dict] | None:
    """Return the reviewer bound by this call's owning host."""
    return _recovery_reviewer.get()


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

    def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
        """Return the selected reviewer's decision for this exact recovery.

        No mutation or executable proposal is returned. Missing capability,
        refusal and errors must never permit an unreviewed repair.
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

    def current_host_connection(self) -> dict | None:
        """Capture this Runtime's owning host, or None when no host is available."""

    def verify_finalize_main(self, connection: dict) -> str:
        """Verify the captured Main host and return its native Session identity."""

    def finalize_hook(self, path: Path, binding: dict) -> dict:
        """Return host-specific adoption material for an already captured binding."""

    def finalize_event(self, binding: dict, event: dict) -> dict | None:
        """Normalize an actual owning-host end event, ignoring unrelated events."""

    def check_main_finalize(
        self,
        binding: dict,
        context: dict,
        prompt: str,
        created: Callable[[str], None],
    ) -> dict | None:
        """Fork native context and bind the child before appending its check task."""

    def finalize_response(self, result: dict | None, continued: bool) -> dict:
        """Translate a check or bounded failure into the native host's end response."""

    def finalize_usage(self, native: dict | None = None) -> CheckUsage:
        """Return normalized current-check facts, including unsupported fields."""

    def send_host_event(self, connection: Mapping[str, Any], event: dict[str, str]) -> dict:
        """Forward an event to the captured owning host, without creating a Session."""

    def parent_host_status(self, connection: Mapping[str, Any], timeout_seconds: float) -> dict:
        """Observe a captured host, optionally waiting within a bounded interval."""

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
    from graphtraj.runtimes.replacement import caller_runtime
    from graphtraj.runtimes.codex.host_events import request_connection

    connection = request_connection()
    if connection is not None:
        return connection

    runtime = caller_runtime()
    if runtime is None:
        import os

        if any(os.environ.get(name) for name in (
            'CODEX_THREAD_ID', 'GRAPHTRAJ_NATIVE_RUNTIME', 'DSH_SESSION_ID',
        )):
            raise RuntimeAdapterError(
                'authority-unavailable',
                'A native Session locator is present but its calling Runtime cannot be verified.',
            )
        return None
    try:
        adapter = select_runtime_adapter(runtime)
    except RuntimeAdapterError as error:
        if error.code == "RUNTIME_UNSUPPORTED":
            return None
        raise
    return adapter.current_host_connection()


def select_runtime_adapter(runtime: str) -> RuntimeAdapter:
    """Select an implemented Adapter from the resolved role's Runtime setting."""
    if runtime == "dsh":
        from graphtraj.runtimes.dsh.adapter import DshRuntimeAdapter

        return DshRuntimeAdapter()
    if runtime == "codex":
        from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter

        return CodexRuntimeAdapter()
    if runtime == "pi":
        from graphtraj.runtimes.pi.pi_adapter import PiRuntimeAdapter

        return PiRuntimeAdapter()
    raise RuntimeAdapterError(
        "RUNTIME_UNSUPPORTED",
        "The selected Agent Runtime is not supported by this Runner.",
    )


def native_replacement_approval(runtime: str | None) -> NativeReplacement | None:
    """Resolve approval capability without treating unsupported Runtimes as absent.

    Every implemented Runtime reports its native capability through its Adapter.
    """
    if runtime is None:
        raise RuntimeAdapterError("RUNTIME_UNSUPPORTED", "The calling Runtime is unknown.")
    return select_runtime_adapter(runtime).native_replacement_approval()


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
