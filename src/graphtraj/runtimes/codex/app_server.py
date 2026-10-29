"""GraphTraj budget notice policy and its independent Codex control imports."""
from __future__ import annotations
import json
import math
import os
import select
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from graphtraj.execution.execution_budget import _duration
from agent_swarm.codex.context import CodexAdapterError
from agent_swarm.codex.app_server import (
    CodexAppServer as NativeCodexAppServer, CodexSession, CodexExecution, CodexServerRequest, CodexRPCError,
)

# The completion checker's fork-only profile: Main's own with Codex managed network enabled.
CHECKER_PERMISSION_PROFILE = 'graphtraj_checker'

_DEFAULT_STOP_INSTRUCTION = (
    "The task has stopped because of its execution budget. "
    "Use retained results and unfinished work to explain its current "
    "status and next steps. Resuming still requires existing authorization."
)


def _configured_stop_instruction() -> str | None:
    """Return the stop text configured for the project around this process.

    The value is ``None`` when no readable configuration sets the setting, so a
    caller outside a project keeps the generic guidance. A missing or invalid
    configuration never turns a stop delivery into a failure.
    """
    from graphtraj.configuration.project_configuration import (
        ProjectConfigurationError,
        load_project_configuration,
    )

    try:
        current = Path.cwd().resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        try:
            return load_project_configuration(candidate).stop_instruction
        except (ProjectConfigurationError, OSError):
            continue
    return None


def _instant(value: Any) -> bool:
    """Accept only an event instant that names its own explicit UTC offset."""
    if not isinstance(value, str) or not value:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _elapsed_minutes(value: Any) -> bool:
    """Accept only a finite nonnegative elapsed duration in minutes."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


class CodexMainRecovery:
    """Return one enforced stop through the Runner call Main is awaiting.

    The binding owns the neutral caller-notice channel of one Runner
    operation. A sampled stochastic stop that arrives on that channel is
    retained as a delivery - stop identity, the stop's own absolute instant,
    the elapsed work duration and status guidance - so
    the document this call returns carries it to the active Main. Ordinary
    estimate and allowance notices stay inert. Nothing is queued into Main's
    native input, and no second Main or Driver is created.
    """

    def __init__(self, stop_instruction: str | None = None) -> None:
        """Bind one caller channel without requiring an installed Skill.

        ``stop_instruction`` is the configured text carried by a delivered stop:
        ``None`` selects the generic guidance, while an empty string delivers
        only the stop facts.
        """
        self._read_fd: int | None = None
        self._notice_fd: int | None = None
        self._reader: threading.Thread | None = None
        self._closing = threading.Event()
        self._idle_pass = threading.Event()
        self._lock = threading.Lock()
        self._pending = b""
        self._stops: set[str] = set()
        self._deliveries: list[dict[str, Any]] = []
        self._error: CodexAdapterError | None = None
        self._stop_instruction = stop_instruction
        self._opened = False
        self._closed = False

    @classmethod
    def from_environment(cls) -> "CodexMainRecovery | None":
        """Return the caller binding when this process owns a Codex Main."""
        if not os.environ.get("CODEX_THREAD_ID") or os.environ.get("GRAPHTRAJ_ROLE"):
            return None
        return cls(_configured_stop_instruction())

    @classmethod
    def from_request(
        cls, metadata: object
    ) -> "CodexMainRecovery | None":
        """Return the caller binding for one request's own Codex metadata.

        The caller sends the identity of the Codex thread that made the request,
        so a host-serving process selects the right Main without guessing from
        its own environment. A request without that metadata keeps the generic
        behaviour of no notice channel instead of failing its operation.
        """
        thread_id = (
            metadata.get("threadId") if isinstance(metadata, Mapping) else None
        )
        if not isinstance(thread_id, str) or not thread_id:
            return None
        return cls(_configured_stop_instruction())

    def __enter__(self) -> "CodexMainRecovery":
        """Start the narrow notice reader before the wrapped Runner operation."""
        with self._lock:
            if self._opened or self._closed:
                raise CodexAdapterError(
                    "RUNTIME_LIFECYCLE_INVALID",
                    "The Codex Main recovery binding cannot be opened twice.",
                )
            self._read_fd, self._notice_fd = os.pipe()
            self._opened = True
            self._reader = threading.Thread(
                target=self._read_notices,
                name="graphtraj-codex-main-recovery",
            )
            self._reader.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop reading notices and preserve any wrapped-operation exception chain."""
        self.close()

    @property
    def notice_fd(self) -> int:
        """Return the existing neutral caller-notice channel while it is open."""
        with self._lock:
            if self._notice_fd is None:
                raise CodexAdapterError(
                    "RUNTIME_LIFECYCLE_INVALID",
                    "Open the Codex Main recovery binding before selecting its notice channel.",
                )
            return self._notice_fd

    def close(self) -> None:
        """Release the caller channel and surface any retained reader failure."""
        with self._lock:
            first_close = not self._closed
            self._closing.set()
            if self._notice_fd is not None:
                os.close(self._notice_fd)
                self._notice_fd = None
            reader = self._reader
        if first_close and reader is not None and reader is not threading.current_thread():
            reader.join()
        with self._lock:
            self._closed = True
            error = self._error
        if error is not None:
            raise error

    def take_stop_deliveries(self) -> tuple[dict[str, Any], ...]:
        """Return the stops this call now delivers, each stamped once at the return.

        The delivery instant is the actual moment this document returns to
        Main, so a stop withheld until a long operation finished keeps showing
        its own trigger instant instead of appearing to have just happened.
        """
        # Let the reader retain input already waiting in the caller channel, so
        # a stop written by this operation is not left behind by the return.
        self._idle_pass.clear()
        self._idle_pass.wait(0.5)
        with self._lock:
            deliveries, self._deliveries = self._deliveries, []
        if not deliveries:
            return ()
        delivered_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return tuple(
            {**delivery, "delivered_at": delivered_at} for delivery in deliveries
        )

    def attach_stop_deliveries(
        self, document: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return one Runner document carrying the stops this call delivered.

        Ordinary results keep their existing shape: the field appears only when
        this call actually returns a stop to the Main that made it.
        """
        deliveries = self.take_stop_deliveries()
        if not deliveries:
            return dict(document)
        return {**document, "stop_deliveries": list(deliveries)}

    def _deliver_notice(self, line: bytes) -> None:
        """Retain one stochastic stop while keeping ordinary caller notices inert."""
        try:
            notice = json.loads(line)
            if not isinstance(notice, dict):
                raise ValueError("Budget notice is not an object")
            stop = self._stop_key(notice)
            if stop is None:
                return
            with self._lock:
                if stop in self._stops:
                    return
                task_id, task_name, limit = json.loads(stop)
                delivery = self._stop_delivery(
                    task_id,
                    task_name,
                    limit,
                    notice["occurred_at"],
                    notice["actual"]["elapsed_minutes"],
                )
                self._stops.add(stop)
                self._deliveries.append(delivery)
        except CodexAdapterError as error:
            self._record_error(error)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self._record_error(CodexAdapterError(
                "RUNTIME_REQUEST_INVALID",
                "The Codex Main budget notice is invalid: {0}".format(error),
            ))

    def _stop_delivery(
        self,
        task_id: str,
        task_name: str,
        limit: float,
        triggered_at: str,
        elapsed_minutes: float,
    ) -> dict[str, Any]:
        """Describe one enforced stop for the Runner call that returns it."""
        elapsed = _duration(elapsed_minutes)
        stop_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "graphtraj:budget-stop:{0}:{1}:{2}".format(task_id, task_name, limit),
        ))
        delivery = {
            "stop_id": stop_id,
            "stop": "stochastic_stop:{0}".format(limit),
            "task": {"task_id": task_id, "task_name": task_name},
            "triggered_at": triggered_at,
            "elapsed": elapsed,
        }
        instruction = (
            _DEFAULT_STOP_INSTRUCTION
            if self._stop_instruction is None
            else self._stop_instruction
        )
        if instruction:
            delivery["instruction"] = instruction
        return delivery

    def _record_error(self, error: CodexAdapterError) -> None:
        """Keep the first concrete delivery failure for every close caller."""
        with self._lock:
            if self._error is None:
                self._error = error

    def _read_notices(self) -> None:
        """Read JSONL until this caller closes the channel."""
        pending = self._pending
        try:
            while self._read_fd is not None:
                ready, _, _ = select.select([self._read_fd], [], [], 0.05)
                if not ready:
                    if self._closing.is_set():
                        return
                    self._idle_pass.set()
                    continue
                chunk = os.read(self._read_fd, 8192)
                if not chunk:
                    return
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    self._deliver_notice(line)
        except (OSError, ValueError) as error:
            self._record_error(
                CodexAdapterError(
                    "RUNTIME_CONNECTION_FAILED",
                    "The Codex Main notice channel failed: {0}".format(error),
                    terminal_confirmed=False,
                )
            )
        finally:
            with self._lock:
                self._pending = pending

    @staticmethod
    def _stop_key(notice: Mapping[str, Any]) -> str | None:
        """Return a stable stop identity without adding Codex fields to budget state."""
        if not isinstance(notice, Mapping) or notice.get("type") != "execution-budget-exceeded":
            return None
        threshold = notice.get("threshold")
        if not isinstance(threshold, Mapping) or not isinstance(threshold.get("kind"), str):
            raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The budget notice threshold is invalid.")
        if threshold["kind"] != "stochastic_stop":
            return None
        task = notice.get("task")
        limit = threshold.get("limit")
        actual = notice.get("actual")
        if (
            not isinstance(task, Mapping)
            or not isinstance(task.get("task_id"), str)
            or not task["task_id"]
            or not isinstance(task.get("task_name"), str)
            or not task["task_name"]
            or isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(limit)
            or not _instant(notice.get("occurred_at"))
            or not isinstance(actual, Mapping)
            or not _elapsed_minutes(actual.get("elapsed_minutes"))
        ):
            raise CodexAdapterError("RUNTIME_REQUEST_INVALID", "The stochastic-stop notice is invalid.")
        return json.dumps(
            (task["task_id"], task["task_name"], limit),
            allow_nan=False,
            separators=(",", ":"),
        )


class CodexAppServer(NativeCodexAppServer):
    """Supply GraphTraj's existing optional archive to the shared native owner."""

    async def retain_ordered_history(self, session: CodexSession, archive: object, agent: str) -> None:
        """Construct the existing collector without making native control import it."""
        from agent_swarm.sessions.codex_history import CodexHistoryArchive
        from graphtraj.interfaces.agents import graphtraj_fields

        await super().retain_ordered_history(
            session, lambda: CodexHistoryArchive(
                archive, session.inherited_history, self._call,
                extra_fields=graphtraj_fields(str(archive.root), agent)),
        )

    async def refresh_mcp(self, thread_id: str, server: str, *, observe_only: bool = False) -> dict[str, Any]:
        """Request native MCP refresh and observe one loaded thread without resuming it.

        A reload acknowledgement means queued refresh, not adopted code. Return
        the actual discovery stamp for the operator's comparison; never start a
        turn, change configuration, or accept a native approval on their behalf.
        """
        thread = await self.read_thread(thread_id)
        if thread.get('status', {}).get('type') not in {'active', 'idle'}:
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'The selected Main is not loaded.')
        from .session_entry import session_source

        if session_source(thread) != 'main':
            raise CodexAdapterError('RUNTIME_REQUEST_INVALID', 'The selected Session is not a native Main.')
        if not observe_only:
            await self._call('config/mcpServer/reload', None)
        inventory = await self._call('mcpServerStatus/list', {
            'threadId': thread_id, 'serverName': server, 'detail': 'toolsAndAuthOnly',
        })
        discovery = await self._call('mcpServer/tool/call', {
            'threadId': thread_id, 'server': server, 'tool': 'tasks',
            'arguments': {'action': 'discover'}, '_meta': {'threadId': thread_id},
        })
        document = discovery.get('structuredContent')
        report = {'main_session': thread_id, 'cwd': thread.get('cwd'),
                  'activity': thread['status']['type'], 'reload_requested': not observe_only,
                  'servers': [{key: item[key] for key in ('name', 'runtimeStatus', 'authStatus', 'toolsError')
                               if key in item} | {'tools': sorted(item.get('tools', {}))}
                              for item in inventory.get('data', []) if item.get('name') == server]}
        if discovery.get('isError') or not isinstance(document, dict) or not isinstance(document.get('service'), dict):
            # Keep what the host did return: its error, the fields present and
            # the bounded tool text, so the missing stamp has a diagnosable cause.
            return {**report, 'service': None, 'adoption_certified': False, 'discovery': {
                        'isError': discovery.get('isError'),
                        'structured_fields': sorted(document) if isinstance(document, dict) else None,
                        'content': [str(item.get('text', item))[:2000] if isinstance(item, dict) else str(item)[:2000]
                                    for item in (discovery.get('content') or [])[:4]]},
                    'note': 'MCP discovery returned no serving-source evidence; reload may still be queued. '
                            'No adoption is certified.'}
        return {**report, 'service': document['service'],
                'note': 'Compare actual source stamps. Reload ACK alone is not refresh completion or cutover.'}
