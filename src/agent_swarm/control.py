"""Task-free Agent control: identity records, executions and actions.

:class:`AgentControl` is the ``agents`` :class:`~agent_swarm.Backend`. It owns
one data root chosen by the caller and keeps, per Agent, a JSON record::

    <root>/control/agents/<agent>.json   identity, Session and executions
    <root>/live/agents/<agent>.lock      per-Agent cross-process lock
    <root>/native/<agent>/               files the Runtime driver keeps
    <root>/config.yml                    the tool's own settings (config.py)

A record holds the stable Agent reference, readable name, verified host,
true control parent (from the host's :class:`~agent_swarm.Caller`, never a
model argument), Runtime, native Session references, retained continuation
settings and every execution with its process facts and receipts. It holds
no Task, Team, Round, Worldline, budget, report or Worktree field.

Lifecycle
---------
The visible state is ``active`` while an execution runs and ``standby``
otherwise. A finished or interrupted execution leaves the Agent in standby
with its native Session kept; ``send`` or ``resume`` continues that Session.
``retire`` hides the Agent from hierarchy listings and refuses further work,
keeping the record. Diagnostics and the last result are extra fields, never
further states.

Concurrency
-----------
Every state change happens under the Agent's lock, so repeated ``send``,
``resume`` or ``interrupt`` calls observe the same current execution: a
second start can never begin while one runs. A delivery whose result is
unknown is recorded as such and never resent automatically.

Runtime drivers
---------------
A :class:`RuntimeDriver` performs the native work. ``start`` must return
once native work is under way, reporting facts through the
:class:`ExecutionEvents` of the :class:`Run`. The driver that started an
execution controls it; another process gets ``not-owned`` instead of a
second channel.

Connections, presets and models
-------------------------------
One control may register drivers for several Runtimes. ``create`` resolves
its Runtime, optional ``preset``, ``model`` and ``reasoning_effort`` against
the connections and presets in ``config.yml`` (see :meth:`AgentControl.select`)
and passes the result to the driver as ``prepare(..., selection=...)``. A
create that selects nothing calls ``prepare`` exactly as before, so a Runtime
without a declared connection keeps the host's own settings and native login.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol

from agent_swarm.approval import DECISION_METHOD, check_reply
from agent_swarm.calls import pause
from agent_swarm.config import CONFIG_FILE, read_config, read_connections
from agent_swarm.locks import exclusive
from agent_swarm.notices import needs_parent
from agent_swarm.tool import AgentsError, AgentsResult, Binding, Caller, Outcome, SessionArchive, bind, unavailable


ACTIVE  = "active"
STANDBY = "standby"

# Polling interval of a finite wait; records are replaced atomically.
WAIT_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True)
class Run:
    """One execution as the driver sees it.

    ``session`` is the native Session to continue, or ``None`` for the first
    execution. ``settings`` are the driver's own retained continuation
    settings from :meth:`RuntimeDriver.prepare`. ``archive`` is bound only
    when the tool's ``save_normalized_sessions`` setting is on.
    ``call`` is the owning core's execution-scoped business callback. Drivers
    expose it only after authenticating their actual native child process;
    request JSON cannot choose its caller. It expires with this execution.
    ``extra_fields`` is the Agent's ``create`` header container: drivers pass
    it to the collector, which writes it on a Session's first archived header.
    """

    agent: str
    execution: str
    runtime: str
    settings: Mapping[str, Any]
    message: str
    session: str | None
    directory: Path
    archive: SessionArchive | None
    events: "ExecutionEvents"
    call: Callable[[dict], AgentsResult] | None = None
    extra_fields: Mapping[str, Any] | None = None


class RuntimeDriver(Protocol):
    """Native execution for one or more Runtimes.

    Failures raise :class:`AgentsError` carrying the native code and message.
    """

    def prepare(self, runtime: str, caller: Caller, *, configuration: str | None = None) -> dict:
        """Resolve an optional driver-owned reference into retained JSON settings.

        A driver that runs selected connections, models or efforts also
        accepts ``selection`` (see :meth:`AgentControl.select`); it is passed
        only when ``create`` selected something. A driver may also define
        ``require_available(connection)``, raising ``runtime-unavailable`` when
        the Runtime is not installed or not logged in on this machine.
        """

    def start(self, run: Run) -> None:
        """Begin native work and return without waiting for it to finish."""

    def deliver(self, run: Run, message: str) -> None:
        """Send input into the running execution."""

    def interrupt(self, run: Run) -> bool:
        """Request a native stop; return whether it was scheduled."""

    def requests(self, run: Run) -> list[dict]:
        """Return pending native approval or input requests."""

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Answer one pending native request exactly once."""


def _now() -> float:
    """Return wall-clock seconds; records keep their own event times."""
    return time.time()


def _alive(pid: object) -> bool:
    """Return whether a process with ``pid`` still exists.

    ponytail: PID reuse is not distinguished; the owned_at fact is kept for a
    consumer that needs to compare process start times.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # ponytail: os.kill(pid, 0) would signal on Windows; assume alive.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(pid: int) -> bool:
    """Return whether the process group led by Runtime ``pid`` still has a member.

    The Runtime runs as a process-group leader, so its children may outlive it.
    """
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _discover_models(connection: Mapping[str, Any]) -> dict:
    """Return the connection's native model candidates (``agent_swarm.models``)."""
    from agent_swarm.models import discover_models

    return discover_models(connection)


def require_available(
    connection: Mapping[str, Any],
    *,
    executable: str | None,
    home: Path,
    logins: tuple[str, ...] | None,
) -> None:
    """Raise ``runtime-unavailable`` unless the connection's Runtime can run here.

    ``executable`` is the resolved native command, or ``None`` when it is not
    installed. The Runtime counts as logged in when the connection's
    ``api_key_env`` variable is set, or one of ``logins`` (native login files
    relative to ``home``) exists; ``None`` means the Runtime's login state is
    not inspectable and its own start reports it. Only existence is checked:
    no credential is read, copied or returned.
    """
    runtime, name = connection["runtime"], connection.get("name")
    where = f"Runtime {runtime!r}" + (f" (connection {name!r})" if name else "")
    if executable is None:
        raise AgentsError("runtime-unavailable", f"{where} is not installed on this machine: "
                                                 f"no {runtime} executable was found.")
    variable = connection.get("api_key_env")
    if variable is not None:
        if not os.environ.get(variable):
            raise AgentsError("runtime-unavailable", f"{where} is not logged in: the environment "
                                                     f"variable {variable} is unset or empty.")
        return
    if logins is not None and not any((home / login).is_file() for login in logins):
        raise AgentsError("runtime-unavailable", f"{where} is not logged in: no native login was found "
                                                 f"in {home}. Log in with the {runtime} client first.")


def within_workspace(workspace: str | Path, boundary: str | Path) -> Path:
    """Return ``workspace`` resolved, refusing a directory outside ``boundary``.

    A child's workspace (layer 1) is its working directory and, where the
    Runtime sandboxes by working directory, its sandbox root. It may only
    narrow the parent's: it never adds a writable root, network or approval.
    Links are resolved first, so a link inside ``boundary`` cannot point out.
    """
    path = Path(workspace)
    if not path.is_absolute() or not path.is_dir():
        raise AgentsError("invalid-input", f"request.workspace: {workspace} is not an existing absolute directory")
    resolved, limit = path.resolve(), Path(boundary).resolve()
    if not resolved.is_relative_to(limit):
        raise AgentsError("workspace-denied", f"Workspace {resolved} lies outside the parent's workspace {limit}.")
    return resolved


def _accepts(method: Callable, name: str) -> bool:
    """Whether ``method`` takes keyword ``name``; older drivers do not."""
    import inspect

    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(item.kind is inspect.Parameter.VAR_KEYWORD
                                     for item in parameters.values())


def _scope(caller: Caller) -> dict[str, str | None]:
    """Return the verified identity a root record keeps as its creator."""
    return {"host": caller.host, "agent": caller.agent, "session": caller.session}


class ExecutionEvents:
    """Facts a driver reports for one execution, each applied under the lock.

    A report for an execution that is no longer current is ignored, so a late
    or repeated report never changes another execution.
    """

    def __init__(self, control: "AgentControl", agent: str, execution: str) -> None:
        """Bind the control, Agent and execution the reports belong to."""
        self._control   = control
        self._agent     = agent
        self._execution = execution

    def session(self, session: str) -> None:
        """Record the native Session this execution runs in."""
        def apply(record: dict, current: dict) -> None:
            """Keep every native Session the Agent was bound to, in order."""
            current["session"] = session
            if session not in record["sessions"]:
                record["sessions"].append(session)
            record["session"] = session

        self._apply(apply)

    def process(self, **facts: Any) -> None:
        """Record process facts such as ``runtime_pid`` and ``owned_at``."""
        allowed = {"worker_pid", "runtime_pid", "owned_at", "runtime_exit"}
        if set(facts) - allowed:
            raise ValueError("unknown process fact")
        self._apply(lambda record, current: current["process"].update(facts))

    def request(self, details: Mapping[str, Any]) -> None:
        """Retain that a native request now waits for a reply, and notify the parent once.

        A repeated report of the same request (same token or native ID) is
        ignored. With ``request_notices`` the parent's receiver (a parent
        Agent's native receiver, else the host's ``event_receiver``) gets one
        ``request`` notice; the parent still answers with ``requests`` and
        ``reply``, and polling keeps working.
        """
        key = _reply_key(details)
        with self._control._locked(self._agent) as record:
            current = _running(record)
            if (current is None or current["id"] != self._execution
                    or any(_reply_key(item) == key for item in current["requests"])):
                return
            current["requests"].append(dict(details))
            notice = self._control._request_notice(record, current, details)
        _send_request_notice(notice)

    def receive_children(self, receiver: Callable[[dict], bool]) -> None:
        """Bind a host reply receiver to this actual active parent execution."""
        with self._control._locked(self._agent) as record:
            current = _running(record)
            if current is None or current['id'] != self._execution:
                raise AgentsError('stale-execution', 'The reply receiver belongs to an ended execution.')
            self._control._receivers[self._agent] = (self._execution, receiver)

    def continue_from_child(self, notice: dict, archive: SessionArchive | None) -> bool:
        """Resume the retained parent with one trusted native child reply.

        The owning Runtime receiver calls this after its native service has
        closed. Identity comes from the child's persisted completion, never
        from a model argument. Launch happens outside both Agent locks.
        """
        control = self._control
        with control._locked(notice['agent']) as child:
            ended = next((item for item in child['executions']
                          if item['id'] == notice['execution']), None)
            if (child['parent'] != self._agent or ended is None
                    or ended['state'] != 'ended' or ended.get('notification') != 'pending'
                    or ended['session'] != notice['session']
                    or ended['last_message'] != notice['body']):
                return False
        with control._locked(self._agent) as parent:
            if (_running(parent) is not None or parent['retired_at'] is not None
                    or not parent['session']):
                return False
            binding = Binding(Caller('runtime-completion', self._agent), archive)
            run = control._begin(parent, 'receive', '', binding)
            run = replace(run, settings={**run.settings, 'completion_message': dict(notice)})
        return not control._launch(run).failed

    def finished(
        self,
        outcome: str,
        *,
        last_message: str | None = None,
        error: Mapping[str, str] | None = None,
        terminal_confirmed: bool = True,
    ) -> None:
        """End the execution; the Agent enters standby with its Session kept.

        ``outcome`` is ``completed``, ``interrupted`` or ``failed``; ``error``
        keeps the native ``code`` and ``message`` unchanged.
        """
        with self._control._locked(self._agent) as record:
            current = _running(record)
            if current is None or current['id'] != self._execution:
                return
            native = self._control._receivers.get(record['parent'])
            receiver = native[1] if native is not None else self._control.event_receiver
            notice = {'parent': record['parent'], 'agent': record['agent'],
                      'session': current['session'], 'execution': current['id'],
                      'body': last_message, 'outcome': outcome}
            if native is None:
                # A host receiver addresses the creating Main and may announce
                # an end without a body.
                notice.update(creator=dict(record['creator']), error=dict(error) if error else None)
            current.update(
                state="ended", ended_at=_now(), outcome=outcome,
                last_message=last_message, terminal_confirmed=terminal_confirmed,
                error=dict(error) if error else None,
            )
            # A native parent continues with the child's reply, so it needs a
            # body; a host receiver also announces ends without one.
            notify = (receiver is not None and (bool(last_message) or native is None)
                      and needs_parent(outcome, active_members=self._control._active_children(self._agent)))
            if notify:
                # Only a native parent's pending reply hides the body meanwhile.
                current['notification'] = 'pending' if native is not None else 'queueing'
            # Keep the native receiver while this Agent is in standby so its
            # children can continue the retained Session after this turn ends.

        # Durable completion precedes delivery. No Agent lock spans native I/O,
        # and repeated finished() cannot invoke the receiver a second time.
        if notify:
            try:
                # A receiver that only queued the notice for its host returns
                # 'queued': the body stays readable, and wait/status showing it
                # acknowledges the queued notice instead of hiding the result.
                # A receiver that submitted the body natively but lost the
                # acknowledgement returns 'unconfirmed', so it is not shown again.
                accepted = receiver(notice)
                delivery = ('queued' if accepted == 'queued'
                            else 'unconfirmed' if accepted == 'unconfirmed'
                            else 'delivered' if accepted is True else 'unavailable')
            except Exception:
                # A native parent may have received the body before its transport
                # failed: do not re-inject it through wait/status. A host queue
                # that failed keeps the body readable there instead.
                delivery = 'unconfirmed' if native is not None else 'unavailable'
            with self._control._locked(self._agent) as record:
                for ended in record['executions']:
                    if ended['id'] == self._execution:
                        ended['notification'] = delivery
                        break

    def _apply(self, change: Callable[[dict, dict], None]) -> None:
        """Apply ``change`` only while this execution is still the running one."""
        with self._control._locked(self._agent) as record:
            current = _running(record)
            if current is not None and current["id"] == self._execution:
                change(record, current)


def _reply_key(request: Mapping[str, Any]) -> str:
    """Identify one native request by its token, else by its native request ID."""
    return request.get("request_token") or json.dumps(request.get("request_id"))


def _request_message(details: Mapping[str, Any]) -> str:
    """Name a native request without its input, which may hold credentials."""
    method = details.get("method") if isinstance(details.get("method"), str) else "a native request"
    params = details.get("params")
    tool = params.get("tool_name") if isinstance(params, Mapping) else None
    named = f"{method} for {tool}" if isinstance(tool, str) and tool else method
    return (f"Permission request {named} waits for your reply. Read it with requests "
            "and answer once with reply.")


def _send_request_notice(notice: tuple[Callable[[dict], bool], dict] | None) -> None:
    """Deliver a built ``request`` notice with no Agent lock held.

    As for ends, no Agent lock spans the receiver's native I/O. A failed
    delivery leaves the request readable through status and requests.
    """
    if notice is None:
        return
    receiver, document = notice
    try:
        receiver(document)
    except Exception:
        pass


def _unanswered(current: Mapping[str, Any]) -> int:
    """Count retained native requests of an execution that have no reply yet.

    ponytail: a request the Runtime cancels by itself stays counted until the
    execution ends; no cancellation fact is reported to the core yet.
    """
    return sum(_reply_key(request) not in current["replies"] for request in current["requests"])


def _unconfirmed(execution: Mapping[str, Any]) -> bool:
    """Whether an ended execution's end is neither native nor confirmed later."""
    return (execution["state"] == "ended" and execution.get("terminal_confirmed") is False
            and "termination_confirmation" not in execution)


def _running(record: Mapping[str, Any]) -> dict | None:
    """Return the record's running execution, or ``None`` in standby."""
    executions = record["executions"]
    if executions and executions[-1]["state"] == "running":
        return executions[-1]
    return None


class AgentControl:
    """The Task-free ``agents`` backend over one tool data root.

    Parameters
    ----------
    root
        Data root chosen by the caller; created on first use.
    drivers
        Runtime name to the driver that executes it. A Runtime without a
        driver is rejected at ``create``.
    roots
        Optional host policy for callers without an Agent reference:
        ``roots.owns(caller, creator)`` says whether a root created by
        ``creator`` belongs to the verified ``caller`` (for example a later
        Session continuing the same project Main), and
        ``roots.require_control(caller)`` raises :class:`AgentsError` when that
        caller may view but not control. Without it a root caller sees only
        roots it created with the same host and Session.
    request_notices
        Whether a child's permission request (native or ``ask_parent``) also
        notifies its parent once (event ``request``). Off by default, so existing hosts and
        GraphTraj see only ends.
    """

    def __init__(
        self, root: Path, drivers: Mapping[str, RuntimeDriver], *,
        event_receiver: Callable[[dict], bool] | None = None,
        roots: Any = None,
        request_notices: bool = False,
    ) -> None:
        """Bind the data root and the available Runtime drivers."""
        self.root    = Path(root)
        self.drivers = dict(drivers)
        self._held   = threading.local()
        self.event_receiver = event_receiver
        self.roots   = roots
        self.request_notices = request_notices
        self._receivers: dict[str, tuple[str, Callable[[dict], bool]]] = {}

    # -- Backend --------------------------------------------------------

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated ``agents`` action for the bound caller."""
        if action == "create":
            return self.create(arguments["runtime"], arguments["instruction"],
                               binding, name=arguments.get("name"),
                               configuration=arguments.get("configuration"),
                               preset=arguments.get("preset"), model=arguments.get("model"),
                               reasoning_effort=arguments.get("reasoning_effort"),
                               extra_fields=arguments.get("extra_fields"),
                               workspace=arguments.get("workspace"))
        if action == "ask_parent":
            return self.ask_parent(binding.caller, arguments["kind"], arguments["question"],
                                   arguments["timeout_seconds"])
        if action == "status" and "agent" not in arguments:
            return Outcome({"agents": self.hierarchy(binding.caller)})
        try:
            return self._operate_agent(action, arguments, binding)
        except AgentsError as error:
            if error.code != "not-found":
                raise
            raise AgentsError("not-found", error.message + " " + self.reference_hint(
                arguments["agent"], binding.caller)) from None

    def _operate_agent(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one action on the Agent ``arguments`` names."""
        agent = arguments["agent"]
        if action == "status":
            return self._outcome(self._authorized(agent, binding.caller))
        if action == "send":
            if arguments.get("reports_only") is True:
                # This backend cannot keep an Agent to results it already holds.
                raise unavailable("reports_only", "this backend cannot deliver a message without starting new work")
            return self.send(agent, arguments["message"], binding)
        if action == "resume":
            return self.resume(agent, binding, arguments.get("message"))
        if action == "wait":
            return self.wait(agent, binding.caller, arguments["timeout_seconds"])
        if action == "interrupt":
            # In standby the public stop confirms an end that was never
            # confirmed, as confirm_ended describes; otherwise it interrupts.
            with self._locked(agent) as record:
                if _running(record) is None and any(map(_unconfirmed, record["executions"])):
                    return self._confirm_ended(record, binding.caller)
            return self.interrupt(agent, binding.caller)
        if action == "requests":
            return self.requests(agent, binding.caller, arguments.get("execution"))
        if action == "reply":
            return self.reply(agent, binding.caller, arguments["request"], arguments["response"])
        if action == "retire":
            return self.retire(agent, binding.caller)
        raise AgentsError("invalid-input", f"request.action: {action} is not supported")

    # -- Actions ----------------------------------------------------------

    def create(
        self,
        runtime: str,
        instruction: str,
        binding: Binding,
        *,
        name: str | None = None,
        configuration: str | None = None,
        preset: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        extra_fields: Mapping[str, Any] | None = None,
        workspace: str | None = None,
    ) -> Outcome:
        """Register a new Agent under the caller and start its first execution.

        Returns once the driver has started native work; it never waits for
        the Agent's result. ``preset``, ``model`` and ``reasoning_effort`` are
        resolved by :meth:`select`. ``extra_fields`` is a normalized Session
        header container keyed by namespace (``{"<namespace>": <JSON>}``); it
        is kept with the Agent and written when its Session is first archived.
        ``workspace`` (layer 1) must lie inside the calling Agent's own
        workspace, which a child without one inherits; the driver checks it
        against the host's cwd as ``prepare(workspace=)``.
        """
        if extra_fields is not None:
            from agent_swarm.sessions.protocol import validate_extra_fields

            try:
                validate_extra_fields(extra_fields)
            except ValueError:
                raise AgentsError("invalid-input", "request.extra_fields: expected an object keyed by "
                                                   "nonempty namespace names with JSON values") from None
        driver = self.drivers.get(runtime)
        if driver is None:
            raise AgentsError("unsupported-runtime", f"No driver is available for Runtime {runtime!r}.")
        caller   = binding.caller
        self._require_root_control(caller)
        selection = self.select(runtime, preset=preset, model=model, reasoning_effort=reasoning_effort)
        options: dict[str, Any] = {}
        if configuration is not None:
            options["configuration"] = configuration
        if selection is not None:
            if not _accepts(driver.prepare, "selection"):
                raise AgentsError("invalid-config", f"This host's {runtime} driver cannot run a selected "
                                                    "connection, preset, model or reasoning effort.")
            options["selection"] = selection
        inherited = (self._load(caller.agent) or {}).get("workspace") if caller.agent else None
        if workspace is not None and inherited is not None:
            workspace = str(within_workspace(workspace, inherited))
        workspace = workspace if workspace is not None else inherited
        if workspace is not None:
            # A driver that cannot narrow the cwd must not run the child wider.
            if not _accepts(driver.prepare, "workspace"):
                raise unavailable("create", f"this host's {runtime} driver cannot assign a workspace")
            options["workspace"] = Path(workspace)
        # Keep the original call shape for drivers whose users select defaults.
        settings = driver.prepare(runtime, caller, **options)
        json.dumps(settings)

        agent  = "agent-" + uuid.uuid4().hex
        record = {
            "agent":      agent,
            "name":       name or agent,
            "runtime":    runtime,
            "host":       caller.host,
            "parent":     caller.agent,
            "creator":    _scope(caller),
            "session":    None,
            "sessions":   [],
            "settings":   settings,
            "selection":  {name: (selection or {}).get(name) for name in
                           ("preset", "connection", "model", "reasoning_effort")},
            "workspace":  str(Path(workspace).resolve()) if workspace is not None else None,
            "created_at": _now(),
            "retired_at": None,
            "executions": [],
        }
        if extra_fields is not None:
            record["extra_fields"] = json.loads(json.dumps(extra_fields))
        with self._locked(agent, record) as current:
            run = self._begin(current, "create", instruction, binding)
        return self._launch(run)

    def select(
        self,
        runtime: str,
        *,
        preset: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict | None:
        """Resolve ``create``'s choices against ``config.yml``; never substitute.

        ``runtime`` is always given. A preset must use that Runtime; it fills
        ``model`` and ``reasoning_effort`` when they are omitted, and an
        explicit value that differs from the preset's is an error. The
        connection is the preset's, else the only one declared for the
        Runtime; several without a preset are ambiguous. A ``model`` must be
        a candidate ``id`` from :func:`agent_swarm.models.discover_models` (the
        connection's declared ``models``, else the native catalog); a model
        that cannot be verified is an error.
        A ``reasoning_effort`` must be among the model's ``supported_efforts``
        when those are known; otherwise the driver checks it natively.

        Returns ``None`` when nothing is selected (no preset, model, effort or
        declared connection for the Runtime), else ``{"preset", "connection"
        (its name), "model", "reasoning_effort", "provider", "settings" (the
        declared connection entry or None)}``.
        """
        try:
            declared = read_connections(self.root)
        except ValueError as error:
            raise AgentsError("invalid-config", str(error)) from None
        connections = declared["connections"]
        source      = self.root / CONFIG_FILE
        chosen      = {"model": model, "reasoning_effort": reasoning_effort}
        connection  = None
        if preset is not None:
            entry = declared["presets"].get(preset)
            if entry is None:
                raise AgentsError("invalid-preset", f"Preset {preset!r} is not declared in {source}; "
                                                    f"declared: {sorted(declared['presets']) or 'none'}.")
            connection = entry.get("connection")
            uses = connections[connection]["runtime"] if connection else entry["runtime"]
            if uses != runtime:
                raise AgentsError("invalid-preset", f"Preset {preset!r} uses Runtime {uses!r}, "
                                                    f"not the requested {runtime!r}.")
            for field in chosen:
                given, configured = chosen[field], entry.get(field)
                if given is not None and configured is not None and given != configured:
                    raise AgentsError("invalid-" + field.replace("_", "-"),
                                      f"{field} {given!r} contradicts preset {preset!r}, "
                                      f"which sets {configured!r}.")
                chosen[field] = configured if given is None else given
        if connection is None:
            matches = sorted(name for name, entry in connections.items() if entry["runtime"] == runtime)
            if len(matches) > 1:
                raise AgentsError("ambiguous-connection",
                                  f"{source} declares several {runtime} connections {matches}; "
                                  "select one with a preset.")
            connection = matches[0] if matches else None
        settings = connections[connection] if connection else None
        if preset is None and settings is None and model is None and reasoning_effort is None:
            return None

        driver = self.drivers[runtime]
        if settings is not None and hasattr(driver, "require_available"):
            driver.require_available(settings)
        provider = (settings or {}).get("provider")
        if chosen["model"] is not None:
            candidate = self._candidate(runtime, settings, chosen["model"])
            provider  = provider or candidate.get("provider")
            supported = candidate.get("supported_efforts")
            effort    = chosen["reasoning_effort"]
            if effort is not None and supported is not None and effort not in supported:
                raise AgentsError("invalid-reasoning-effort",
                                  f"Model {chosen['model']!r} supports reasoning_effort {supported}, "
                                  f"not {effort!r}.")
        return {"preset": preset, "connection": connection, "provider": provider,
                "settings": deepcopy(settings), **chosen}

    def _candidate(self, runtime: str, settings: Mapping[str, Any] | None, model: str) -> dict:
        """Return the one candidate whose ``id`` is ``model``, or raise ``invalid-model``."""
        settings = settings or {"runtime": runtime}
        where    = f"connection {settings['name']!r}" if "name" in settings else f"the native {runtime} login"
        found    = _discover_models(settings)
        if found.get("status") != "available":
            raise AgentsError("invalid-model",
                              f"Model {model!r} cannot be verified for {where}: {found.get('message')} "
                              f"Declare the connection's models in {self.root / CONFIG_FILE} to choose "
                              "without discovery.")
        matches = [item for item in found["models"] if item["id"] == model]
        if not matches:
            raise AgentsError("invalid-model", f"Model {model!r} is not a candidate of {where}; candidates: "
                                               f"{sorted({item['id'] for item in found['models']}) or 'none'}.")
        if len({item.get("provider") for item in matches}) > 1:
            raise AgentsError("invalid-model", f"Model {model!r} is offered by several providers of {where}; "
                                               "set the connection's provider.")
        return matches[0]

    def require_connections(self) -> None:
        """Check, at host start, every connection ``config.yml`` declares.

        A declared Runtime without a registered driver is ``unsupported-runtime``;
        a driver's ``require_available`` raises ``runtime-unavailable`` when
        that Runtime is not installed or not logged in on this machine.
        """
        try:
            connections = read_connections(self.root)["connections"]
        except ValueError as error:
            raise AgentsError("invalid-config", str(error)) from None
        for name, settings in connections.items():
            driver = self.drivers.get(settings["runtime"])
            if driver is None:
                raise AgentsError("unsupported-runtime", f"Connection {name!r} uses Runtime "
                                                         f"{settings['runtime']!r}, which this host has no driver for.")
            if hasattr(driver, "require_available"):
                driver.require_available(settings)

    def send(self, agent: str, message: str, binding: Binding) -> Outcome:
        """Deliver to the running execution, or continue the Session in standby."""
        with self._locked(agent) as record:
            self._require_control(record, binding.caller)
            current = _running(record)
            if current is None:
                run = self._begin(record, "send", message, binding)
            else:
                return self._deliver(record, current, message)
        return self._launch(run)

    def _deliver(self, record: dict, current: dict, message: str) -> Outcome:
        """Send input into the running execution under the held lock.

        A rejection keeps its receipt and is raised; an unknown result keeps
        its receipt and is never resent.
        """
        if current.get("stop_requested_at") is not None:
            raise AgentsError("stopping", "The Agent is stopping; wait for standby, then send again.")
        if not current["started"]:
            raise AgentsError("starting", "The execution is still starting; send again once it runs.")
        self._require_owner(current)

        receipt = {"at": _now(), "delivery": "submitted"}
        try:
            self._driver(record).deliver(self._run(record, current, message, None), message)
        except AgentsError as error:
            receipt.update(delivery="rejected", error={"code": error.code, "message": error.message})
            current["inputs"].append(receipt)
            raise
        except Exception as error:
            receipt.update(delivery="unknown", error={"code": "delivery-unknown", "message": str(error)})
            current["inputs"].append(receipt)
            return self._outcome(record, failed=True, result={"delivery": receipt})
        current["inputs"].append(receipt)
        return self._outcome(record, result={"delivery": receipt})

    def resume(self, agent: str, binding: Binding, message: str | None = None) -> Outcome:
        """Continue the retained Session; an active Agent keeps its execution."""
        with self._locked(agent) as record:
            self._require_control(record, binding.caller)
            if _running(record) is not None:
                return self._outcome(record, result={"resumed": False, "reason": "already-active"})
            if message is None:
                raise AgentsError("invalid-input", "request.message: required to resume a standby Agent")
            run = self._begin(record, "resume", message, binding)
        return self._launch(run)

    def interrupt(self, agent: str, caller: Caller) -> Outcome:
        """Request a native stop; the Agent enters standby once it ends."""
        with self._locked(agent) as record:
            self._require_control(record, caller)
            current = _running(record)
            if current is None:
                return self._outcome(record, result={"interrupt": "not-running"})
            if current.get("stop_requested_at") is not None:
                return self._outcome(record, result={"interrupt": "already-requested"})
            if not current["started"]:
                raise AgentsError("starting", "The execution is still starting; interrupt once it runs.")
            self._require_owner(current)
            scheduled = self._driver(record).interrupt(self._run(record, current, "", None))
            current.update(stop_requested_at=_now(), stop_scheduled=bool(scheduled))
            return self._outcome(record, result={"interrupt": "requested", "scheduled": bool(scheduled)})

    def wait(self, agent: str, caller: Caller, timeout_seconds: float) -> Outcome:
        """Wait at most ``timeout_seconds`` for standby or an unanswered request.

        An Agent waiting for a native approval does not reach standby by
        itself, so a retained unanswered request also ends the wait; the
        document then carries ``pending_requests``.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            with self._locked(agent) as record:
                self._require_view(record, caller)
                current = _running(record)
                if current is None or _unanswered(current):
                    return self._outcome(record, result={"timed_out": False})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._outcome(record, result={"timed_out": True})
            pause(min(WAIT_INTERVAL_SECONDS, remaining))

    def requests(self, agent: str, caller: Caller, execution: str | None = None) -> Outcome:
        """Return the running execution's pending native requests."""
        with self._locked(agent) as record:
            self._require_control(record, caller)
            current = self._require_execution(record, execution)
            documents = [{**request, "execution": current["id"]} for request in self._pending(record, current)]
            return self._outcome(record, result={"requests": documents})

    def _pending(self, record: dict, current: dict) -> list[dict]:
        """Return the Runtime's pending requests, then the child's own unanswered ones."""
        native = self._driver(record).requests(self._run(record, current, "", None))
        own = [request for request in current["requests"] if request.get("method") == DECISION_METHOD
               and _reply_key(request) not in current["replies"]]
        return [*native, *own]

    def reply(
        self,
        agent: str,
        caller: Caller,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> Outcome:
        """Answer one pending request once; a repeat returns the first receipt.

        The reply is checked against the request as the Runtime (or the child)
        reported it, not the caller's copy: :func:`agent_swarm.approval.check_reply`
        refuses an approval granting more than asked before any driver sees
        it. A child's decision request is answered here and never reaches the
        driver.
        """
        with self._locked(agent) as record:
            self._require_control(record, caller)
            current = self._require_execution(record, request.get("execution"))
            key = _reply_key(request)
            if key in current["replies"]:
                return self._outcome(record, result={**current["replies"][key], "duplicate": True})
            reported = next((item for item in self._pending(record, current) if _reply_key(item) == key), None)
            if reported is None:
                raise AgentsError("invalid-input", "request.request: no such request is pending")
            check_reply(reported, response)
            if reported.get("method") == DECISION_METHOD:
                receipt = {"request_id": None, "reply_status": "answered", "answer": response["answer"]}
            else:
                native = {name: value for name, value in request.items() if name != "execution"}
                receipt = self._driver(record).reply(self._run(record, current, "", None), native, response)
            current["replies"][key] = {"at": _now(), **receipt}
            return self._outcome(record, result=current["replies"][key])

    def _request_notice(self, record: dict, current: dict,
                        details: Mapping[str, Any]) -> tuple[Callable[[dict], bool], dict] | None:
        """Build the parent's one ``request`` notice, if this host wants them."""
        native = self._receivers.get(record["parent"])
        receiver = native[1] if native is not None else self.event_receiver
        if not self.request_notices or receiver is None:
            return None
        notice = {"parent": record["parent"], "agent": record["agent"],
                  "session": current["session"], "execution": current["id"],
                  "body": _request_message(details), "outcome": "request", "request": _reply_key(details)}
        if native is None:
            notice.update(creator=dict(record["creator"]), error=None)
        return receiver, notice

    def ask_parent(self, caller: Caller, kind: str, question: str, timeout_seconds: float) -> Outcome:
        """Ask the calling Agent's direct parent for a decision or resources.

        This is the permission-request kind of parent-child traffic, not a
        call for attention: the request is retained on the caller's running
        execution, so the parent's ``wait`` ends early, the document shows
        ``pending_requests``, and the parent answers once through ``reply``
        with ``{"answer": ...}``. Waits at most ``timeout_seconds``; without an
        answer the result is ``answer: null, timed_out: true``, which grants
        nothing. Asking the same ``kind`` and ``question`` again in the same
        execution continues waiting for (or returns) the same request. A new
        request also notifies the parent once under ``request_notices``.
        """
        if caller.agent is None:
            raise AgentsError("authority-denied", "Only a child Agent can ask its parent; this caller has none.")
        params = {"kind": kind, "question": question}
        notice = None
        with self._locked(caller.agent) as record:
            current = _running(record)
            if current is None:
                raise AgentsError("not-running", "Ask from a running execution of this Agent.")
            request = next((item for item in current["requests"] if item.get("method") == DECISION_METHOD
                            and item["params"] == params), None)
            if request is None:
                request = {"session": current["session"], "execution_id": current["id"], "request_id": None,
                           "request_token": uuid.uuid4().hex, "method": DECISION_METHOD, "params": params}
                current["requests"].append(request)
                notice = self._request_notice(record, current, request)
        _send_request_notice(notice)
        deadline = time.monotonic() + timeout_seconds
        while True:
            with self._locked(caller.agent) as record:
                current = _running(record)
                if current is None or current["id"] != request["execution_id"]:
                    raise AgentsError("stale-execution", "The asking execution has ended; its request was withdrawn.")
                reply = current["replies"].get(request["request_token"])
                answer = reply.get("answer") if reply is not None else None
                if reply is not None or time.monotonic() >= deadline:
                    return self._outcome(record, result={"request": dict(request), "answer": answer,
                                                         "timed_out": reply is None})
            time.sleep(min(WAIT_INTERVAL_SECONDS, max(deadline - time.monotonic(), 0)))

    def retire(self, agent: str, caller: Caller) -> Outcome:
        """Hide a standby Agent from listings; its record and Session stay."""
        with self._locked(agent) as record:
            self._require_view(record, caller)
            if record["retired_at"] is not None:
                return self._outcome(record, result={"retired": True, "duplicate": True})
            self._require_control(record, caller)
            if _running(record) is not None:
                raise AgentsError("active", "Interrupt the Agent and wait for standby before retiring it.")
            record["retired_at"] = _now()
            record["retired_by"] = _scope(caller)
            return self._outcome(record, result={"retired": True})

    def unconfirmed_ends(self, agent: str) -> list[str]:
        """Return the ended executions of ``agent`` whose end is still unconfirmed.

        This only reads; a host uses it to refuse a confirmation it may not make.
        """
        with self._locked(agent) as record:
            return [execution["id"] for execution in record["executions"] if _unconfirmed(execution)]

    def confirm_ended(self, agent: str, caller: Caller, *, by: Mapping[str, Any] | None = None) -> Outcome:
        """Confirm the unconfirmed ends of a standby Agent's executions.

        An execution can end without a native termination event, for example
        when :meth:`_reconcile` finds its owner gone (``terminal_confirmed``
        false). Only the Agent's direct parent, or a root caller for a root
        Agent under the host's control policy, may confirm it, and only after
        the recorded ``worker_pid`` and ``runtime_pid`` are rechecked as gone
        now. A running Agent, or an execution without both process facts,
        is refused and nothing is written. Retired history may be confirmed
        too, since nothing starts. The original end, including its
        ``terminal_confirmed`` false and error, is kept; the confirmation is
        appended to the execution as ``termination_confirmation``. An Agent
        without an unconfirmed end returns an empty ``termination_confirmed``.
        A host that has verified the real caller through its own direct-parent
        check passes that caller's identity as ``by``; the receipt records it.
        """
        with self._locked(agent) as record:
            if _running(record) is not None:
                raise AgentsError("active", "The Agent is running; interrupt it and wait for standby.")
            return self._confirm_ended(record, caller, by)

    def _confirm_ended(self, record: dict, caller: Caller, by: Mapping[str, Any] | None = None) -> Outcome:
        """Implement :meth:`confirm_ended` for a standby record under the held lock."""
        self._require_view(record, caller)
        self._require_root_control(caller)
        if record["parent"] != caller.agent:
            raise AgentsError("authority-denied", "Only the direct parent can confirm an Agent's ended execution.")

        pending = [execution for execution in record["executions"] if _unconfirmed(execution)]
        evidence = {}
        for execution in pending:
            process = execution.get("process", {})
            facts   = {name: process.get(name) for name in ("worker_pid", "runtime_pid")}
            # A missing fact cannot be rechecked, and a live process (or a
            # reused PID) may still run the native Session; both are refused.
            if not all(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
                       for pid in facts.values()):
                raise AgentsError("termination-unconfirmed",
                                  f"Execution {execution['id']} lacks a recorded worker or Runtime process; "
                                  "its end cannot be verified.")
            if any(_alive(pid) for pid in facts.values()) or _group_alive(facts["runtime_pid"]):
                raise AgentsError("termination-unconfirmed",
                                  f"A recorded process of execution {execution['id']} is still running.")
            evidence[execution["id"]] = {**facts, "worker_alive": False, "runtime_alive": False}

        for execution in pending:
            execution["termination_confirmation"] = {
                "at": _now(), "by": dict(by) if by is not None else _scope(caller), "terminal_confirmed": True,
                "evidence": evidence[execution["id"]],
            }
        return self._outcome(record, result={"interrupt": "stopped",
                                             "termination_confirmed": list(evidence)})

    def interrupt_owned(self) -> list[str]:
        """Request a stop of every execution this process owns; host shutdown only.

        A host that is exiting stops the native work it runs itself, whoever
        created the Agent. Executions owned by other processes are untouched.
        Returns the Agents whose execution this process owns.
        """
        owned = []
        for path in sorted((self.root / "control" / "agents").glob("*.json")):
            with self._locked(path.stem) as record:
                current = _running(record)
                if current is None or current["process"].get("worker_pid") != os.getpid():
                    continue
                owned.append(record["agent"])
                if current.get("stop_requested_at") is None and current["started"]:
                    scheduled = self._driver(record).interrupt(self._run(record, current, "", None))
                    current.update(stop_requested_at=_now(), stop_scheduled=bool(scheduled))
        return owned

    def owns_running(self, agent: str) -> bool:
        """Whether this process still owns a running execution of ``agent``."""
        with self._locked(agent) as record:
            current = _running(record)
            return current is not None and current["process"].get("worker_pid") == os.getpid()

    def reference_hint(self, name: str, caller: Caller) -> str:
        """Explain that ``agent`` is a reference, listing visible Agents with that name.

        The text does not depend on whether a hidden Agent has that reference.
        """
        named = sorted(record["agent"] for record in map(self._load, (
            path.stem for path in (self.root / "control" / "agents").glob("*.json")))
            if record is not None and record["name"] == name and record["retired_at"] is None
            and self._can_view(record, caller))
        hint = "`agent` takes the reference returned by create or status, not the readable name."
        return hint + (f" Agents named {name!r}: {', '.join(named)}." if named else "")

    def hierarchy(self, caller: Caller) -> list[dict]:
        """Return the caller's visible descendants nested by true control parent.

        Retired Agents are omitted; a visible child of a retired Agent is
        listed under the nearest visible ancestor and keeps its own
        ``parent`` field.
        """
        records = {}
        for path in sorted((self.root / "control" / "agents").glob("*.json")):
            with self._locked(path.stem) as record:
                if record["retired_at"] is None and self._can_view(record, caller):
                    records[record["agent"]] = record

        nodes = {agent: {**self._document(record), "children": []}
                 for agent, record in records.items()}
        roots = []
        for agent, record in records.items():
            ancestor = record["parent"]
            while ancestor is not None and ancestor not in records:
                parent_record = self._load(ancestor)
                ancestor      = parent_record["parent"] if parent_record else None
            (nodes[ancestor]["children"] if ancestor else roots).append(nodes[agent])
        return roots

    # -- Records ----------------------------------------------------------

    def _path(self, agent: str) -> Path:
        """Return the record path; the reference cannot leave the data root."""
        if (not isinstance(agent, str) or not agent or agent in {'.', '..'}
                or any(character in agent for character in ('/', '\\', '\x00'))):
            raise AgentsError("not-found", f"No Agent {agent!r} exists.")
        return self.root / "control" / "agents" / f"{agent}.json"

    def import_agent(self, record: Mapping[str, Any]) -> dict:
        """Import one stopped, host-verified identity without launching a Runtime.

        Offline migration supplies the existing identity, true parent, native
        references and settings. Retired history stays retired. A running
        execution is refused rather than converted into an idle one. Replays
        must be identical; this API never replaces an existing control record.
        """
        required = {'agent', 'name', 'runtime', 'host', 'parent', 'creator',
                    'session', 'sessions', 'settings', 'created_at', 'retired_at', 'executions'}
        if not required <= record.keys():
            raise AgentsError('invalid-input', 'An imported Agent needs its complete retained identity.')
        if not isinstance(record['settings'], dict) or not isinstance(record['creator'], dict):
            raise AgentsError('invalid-input', 'Imported settings and creator must be mappings.')
        if any(execution.get('state') != 'ended' for execution in record['executions']):
            raise AgentsError('turn-running', 'Only stopped native executions may be imported.')
        agent = record['agent']
        self._path(agent)
        with exclusive(self.root / 'live' / 'agents' / f'{agent}.lock'):
            previous = self._load(agent)
            if previous is not None:
                if previous != record:
                    raise AgentsError('invalid-input', 'Imported Agent conflicts with retained control data.')
                return self._document(previous)
            path = self._path(agent)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.import-')
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(dict(record), stream, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary, path)
        return self._document(record)

    def configure_stopped(self, agent: str, settings: Mapping[str, Any], caller: Caller) -> dict:
        """Replace host-owned continuation settings while retaining identity and memory.

        Migration may relocate a stopped Agent's resources, including retained
        retired history. The verified owning host and original parent must
        match; a live or unconfirmed execution cannot be reconfigured.
        """
        if not isinstance(settings, Mapping):
            raise AgentsError('invalid-input', 'Continuation settings must be a mapping.')
        with self._locked(agent) as record:
            if record['host'] != caller.host or record['parent'] != caller.agent:
                raise AgentsError('not-found', 'Only the owning host and parent can configure this Agent.')
            if any(item.get('state') != 'ended' or _unconfirmed(item)
                   for item in record['executions']):
                raise AgentsError('turn-running', 'Only confirmed stopped Agents may be configured.')
            record['settings'] = deepcopy(dict(settings))
            return self._document(record)

    def _active_children(self, agent: str) -> int:
        """Count this Agent's direct children that still have a running execution."""
        count = 0
        for path in (self.root / 'control' / 'agents').glob('*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if record.get('parent') == agent and _running(record) is not None:
                count += 1
        return count

    def _load(self, agent: str) -> dict | None:
        """Read one record without the lock, or ``None`` when absent."""
        try:
            return json.loads(self._path(agent).read_text(encoding="utf-8"))
        except (AgentsError, FileNotFoundError):
            return None

    @contextmanager
    def _locked(self, agent: str, new: dict | None = None) -> Iterator[dict]:
        """Hold the Agent lock, yield its reconciled record and save changes.

        ``new`` creates the record; otherwise a missing Agent is ``not-found``.
        The record is saved even when the block raises, so a rejected or
        failed control keeps its receipt. A thread that already holds the
        lock, such as a driver reporting from inside ``start``, receives the
        same in-memory record, which the outer holder saves.
        """
        held = self._held.__dict__
        if agent in held:
            yield held[agent]
            return

        path = self._path(agent)
        with exclusive(self.root / "live" / "agents" / f"{agent}.lock"):
            if new is not None:
                record, before = new, None
            else:
                try:
                    before = path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    raise AgentsError("not-found", f"No Agent {agent!r} exists.") from None
                record = json.loads(before)
            self._reconcile(record)
            held[agent] = record
            try:
                yield record
            finally:
                del held[agent]
                text = json.dumps(record, indent=2, sort_keys=True)
                if text != before:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".record-")
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        stream.write(text)
                    os.replace(temporary, path)

    def _reconcile(self, record: dict) -> None:
        """End a running execution whose owning process and Runtime are gone.

        If the Runtime process still lives, the execution stays running with
        a diagnostic, so no second execution can start in the same Session.
        """
        current = _running(record)
        if current is None or _alive(current["process"].get("worker_pid")):
            return
        if _alive(current["process"].get("runtime_pid")):
            current["diagnostic"] = "owner-exited; the Runtime process is still running"
            return
        current.update(
            state="ended", ended_at=_now(), outcome="failed", terminal_confirmed=False,
            error={"code": "owner-exited",
                   "message": "The process owning this execution exited before reporting its end."},
        )

    # -- Authority --------------------------------------------------------

    def _top(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the highest recorded ancestor of ``record``, itself included."""
        seen = {record["agent"]}
        while record["parent"] is not None and record["parent"] not in seen:
            parent = self._load(record["parent"])
            if parent is None:
                break
            seen.add(parent["agent"])
            record = parent
        return record

    def _can_view(self, record: Mapping[str, Any], caller: Caller) -> bool:
        """Return whether ``record`` descends from the caller's verified identity.

        An Agent caller sees Agents whose parent chain reaches it. A caller
        without an Agent reference sees only roots it created itself with the
        same host and Session; having no parent grants no wider authority.
        """
        if caller.agent is not None:
            seen, current = set(), record
            while current is not None and current["agent"] not in seen:
                if current["parent"] == caller.agent:
                    return True
                seen.add(current["agent"])
                current = self._load(current["parent"]) if current["parent"] else None
            return False
        top = self._top(record)
        if top["parent"] is not None:
            return False
        if top["creator"] == _scope(caller):
            return True
        return self.roots is not None and bool(self.roots.owns(caller, top["creator"]))

    def _require_view(self, record: Mapping[str, Any], caller: Caller) -> None:
        """Reject a caller outside the Agent's true hierarchy as ``not-found``."""
        if not self._can_view(record, caller):
            raise AgentsError("not-found", f"No Agent {record['agent']!r} exists.")

    def _require_control(self, record: Mapping[str, Any], caller: Caller) -> None:
        """Require visibility, the host's control policy and a record that is not retired."""
        self._require_view(record, caller)
        self._require_root_control(caller)
        if record["retired_at"] is not None:
            raise AgentsError("retired", "The Agent is retired; its record is kept as history.")

    def _require_root_control(self, caller: Caller) -> None:
        """Apply the host's control policy to a caller without an Agent reference."""
        if caller.agent is None and self.roots is not None:
            self.roots.require_control(caller)

    def _authorized(self, agent: str, caller: Caller) -> dict:
        """Return the record for a caller allowed to view it."""
        with self._locked(agent) as record:
            self._require_view(record, caller)
            return record

    @staticmethod
    def _require_owner(current: Mapping[str, Any]) -> None:
        """Control a running execution only from the process that owns it."""
        owner = current["process"].get("worker_pid")
        if owner != os.getpid():
            raise AgentsError("not-owned", f"The execution is owned by process {owner}; "
                                           "control it from that host.")

    def _require_execution(self, record: Mapping[str, Any], execution: str | None) -> dict:
        """Return the running execution, rejecting a named stale one."""
        current = _running(record)
        if current is None:
            raise AgentsError("not-running", "The Agent is in standby; no native request is pending.")
        if execution is not None and execution != current["id"]:
            raise AgentsError("stale-execution", "The request belongs to an execution that has ended.")
        if not current["started"]:
            raise AgentsError("starting", "The execution is still starting.")
        self._require_owner(current)
        return current

    # -- Executions -------------------------------------------------------

    def _driver(self, record: Mapping[str, Any]) -> RuntimeDriver:
        """Return the driver of the record's Runtime."""
        driver = self.drivers.get(record["runtime"])
        if driver is None:
            raise AgentsError("unsupported-runtime", f"No driver is available for Runtime {record['runtime']!r}.")
        return driver

    def _run(
        self,
        record: Mapping[str, Any],
        current: Mapping[str, Any],
        message: str,
        archive: SessionArchive | None,
    ) -> Run:
        """Describe one execution of ``record`` for its driver."""
        directory = self.root / "native" / record["agent"]
        directory.mkdir(parents=True, exist_ok=True)
        agent, execution = record['agent'], current['id']

        def call(request: dict) -> AgentsResult:
            """Bind this existing execution after the Runtime verifies transport ownership."""
            try:
                with self._locked(agent) as owner:
                    active = _running(owner)
                    if active is None or active['id'] != execution:
                        raise AgentsError('stale-execution', 'This native execution no longer owns its callback.')
                    self._require_owner(active)
                    caller = Caller('runtime-mcp', agent, session=owner['session'], runtime=owner['runtime'])
                # Do not hold the caller's record lock over a finite wait or
                # child launch; native completion must be able to report.
                return bind(self, caller, archive=archive)(request)
            except AgentsError as error:
                return AgentsResult({'error': {'code': error.code, 'message': error.message}}, failed=True)

        return Run(
            agent=record["agent"], execution=current["id"], runtime=record["runtime"],
            settings=record["settings"], message=message, session=current["resumed_session"],
            directory=directory, archive=archive,
            events=ExecutionEvents(self, record["agent"], current["id"]),
            call=call, extra_fields=record.get("extra_fields"),
        )

    def _begin(self, record: dict, operation: str, message: str, binding: Binding) -> Run:
        """Record a new running execution of a standby Agent under the held lock.

        The execution is current, and therefore blocks any second start,
        before the lock is released and :meth:`_launch` calls the driver.
        """
        if record["retired_at"] is not None:
            raise AgentsError("retired", "The Agent is retired; its record is kept as history.")
        if record["executions"] and record["session"] is None:
            last = record["executions"][-1]
            evidence = last.get("process", {}).get("runtime_exit") or {}
            # Retry only a proven pre-prompt startup failure. Keep the original
            # execution and its terminal uncertainty; this is not reconciliation.
            retryable = (last["state"] == "ended" and last.get("outcome") == "failed"
                         and evidence.get("prompt_started") is False
                         and evidence.get("native_session_bound") is False
                         and evidence.get("wrapper_exited") is True
                         and evidence.get("owned_process_group_exited") is True)
            if not retryable:
                raise AgentsError("no-session", "No native Session was established; "
                                                "safe startup retry evidence is unavailable.")

        # Archiving follows the tool's own setting; an unbound archive is reported.
        from agent_swarm.sessions.archive import ConfiguredSessionArchive

        archive = None
        if read_config(self.root)["save_normalized_sessions"]:
            archive = binding.archive or ConfiguredSessionArchive(self.root, **read_config(self.root))
        current = {
            "id":              uuid.uuid4().hex,
            "operation":       operation,
            "state":           "running",
            "started_at":      _now(),
            "resumed_session": record["session"],
            "session":         None,
            "process":         {"worker_pid": os.getpid(), "owned_at": _now()},
            "inputs":          [],
            "requests":        [],
            "replies":         {},
            "started":         False,
            "archive":         ("bound" if archive is not None else
                                "unbound" if read_config(self.root)["save_normalized_sessions"] else "off"),
        }
        self._driver(record)
        record["executions"].append(current)
        return self._run(record, current, message, archive)

    def _launch(self, run: Run) -> Outcome:
        """Call the driver outside the lock, so its own reports can proceed.

        A start failure ends the execution with the driver's native code and
        message; the Agent stays in standby.
        """
        failure = None
        try:
            self.drivers[run.runtime].start(run)
        except Exception as error:
            failure = ({"code": error.code, "message": error.message} if isinstance(error, AgentsError)
                       else {"code": "start-failed", "message": str(error)})
        if failure is not None:
            run.events.finished("failed", error=failure)
        else:
            run.events._apply(lambda record, current: current.update(started=True))
        with self._locked(run.agent) as record:
            return self._outcome(record, failed=failure is not None)

    # -- Documents --------------------------------------------------------

    @staticmethod
    def _document(record: Mapping[str, Any]) -> dict:
        """Return the readable state of one Agent; diagnostics are extra fields."""
        current = _running(record)
        ended   = [execution for execution in record["executions"] if execution["state"] == "ended"]
        last    = ended[-1] if ended else None
        document = {
            "agent":   record["agent"],
            "name":    record["name"],
            "runtime": record["runtime"],
            **{name: (record.get("selection") or {}).get(name)
               for name in ("preset", "connection", "model", "reasoning_effort")},
            "workspace": record.get("workspace"),
            "state":   ACTIVE if current is not None else STANDBY,
            "parent":  record["parent"],
            "creator": dict(record["creator"]),
            "host":    record["host"],
            "session": record["session"],
        }
        if current is not None:
            document["execution"] = current["id"]
            if current.get("stop_requested_at") is not None:
                document["stopping"] = True
            if current.get("diagnostic"):
                document["diagnostic"] = current["diagnostic"]
            if _unanswered(current):
                document["pending_requests"] = _unanswered(current)
        if last is not None:
            document["last_result"] = {name: last.get(name) for name in (
                "id", "outcome", "last_message", "error", "terminal_confirmed", "ended_at")}
            if "termination_confirmation" in last:
                document["last_result"]["termination_confirmation"] = deepcopy(last["termination_confirmation"])
            runtime_exit = last.get("process", {}).get("runtime_exit")
            if runtime_exit is not None:
                document["last_result"]["runtime_exit"] = deepcopy(runtime_exit)
            if last.get('notification'):
                document['last_result']['notification'] = last['notification']
                if last['notification'] in ('pending', 'delivered', 'unconfirmed'):
                    document['last_result']['last_message'] = None
        if record["retired_at"] is not None:
            document["retired_at"] = record["retired_at"]
        return document

    def _outcome(
        self,
        record: Mapping[str, Any],
        *,
        failed: bool = False,
        result: Mapping[str, Any] | None = None,
    ) -> Outcome:
        """Shape the contract outcome with the Agent's current references."""
        executions = record["executions"]
        return Outcome(
            {**self._document(record), **(result or {})},
            agent=record["agent"], session=record["session"],
            execution=executions[-1]["id"] if executions else None, failed=failed,
        )
