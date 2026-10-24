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

from agent_swarm.config import read_config
from agent_swarm.locks import exclusive
from agent_swarm.tool import AgentsError, AgentsResult, Binding, Caller, Outcome, SessionArchive, bind


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


class RuntimeDriver(Protocol):
    """Native execution for one or more Runtimes.

    Failures raise :class:`AgentsError` carrying the native code and message.
    """

    def prepare(self, runtime: str, caller: Caller, *, configuration: str | None = None) -> dict:
        """Resolve an optional driver-owned reference into retained JSON settings."""

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
        """Retain that a native request now waits for a reply."""
        self._apply(lambda record, current: current["requests"].append(dict(details)))

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
            receiver = self._control._receivers.get(record['parent'], (None, self._control.event_receiver))[1]
            notice = {'parent': record['parent'], 'agent': record['agent'],
                      'session': current['session'], 'execution': current['id'],
                      'body': last_message, 'outcome': outcome}
            current.update(
                state="ended", ended_at=_now(), outcome=outcome,
                last_message=last_message, terminal_confirmed=terminal_confirmed,
                error=dict(error) if error else None,
            )
            notify = receiver is not None and bool(last_message) and record['parent'] is not None
            if notify:
                current['notification'] = 'pending'
            # Keep the native receiver while this Agent is in standby so its
            # children can continue the retained Session after this turn ends.

        # Durable completion precedes delivery. No Agent lock spans native I/O,
        # and repeated finished() cannot invoke the receiver a second time.
        if notify:
            try:
                delivery = 'delivered' if receiver(notice) is True else 'unavailable'
            except Exception:
                # Delivery may have happened before the transport failed. Do not
                # re-inject the body through wait/status or retry automatically.
                delivery = 'unconfirmed'
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


def _unanswered(current: Mapping[str, Any]) -> int:
    """Count retained native requests of an execution that have no reply yet.

    ponytail: a request the Runtime cancels by itself stays counted until the
    execution ends; no cancellation fact is reported to the core yet.
    """
    return sum(_reply_key(request) not in current["replies"] for request in current["requests"])


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
    """

    def __init__(
        self, root: Path, drivers: Mapping[str, RuntimeDriver], *,
        event_receiver: Callable[[dict], bool] | None = None,
        roots: Any = None,
    ) -> None:
        """Bind the data root and the available Runtime drivers."""
        self.root    = Path(root)
        self.drivers = dict(drivers)
        self._held   = threading.local()
        self.event_receiver = event_receiver
        self.roots   = roots
        self._receivers: dict[str, tuple[str, Callable[[dict], bool]]] = {}

    # -- Backend --------------------------------------------------------

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated ``agents`` action for the bound caller."""
        if action == "create":
            return self.create(arguments["runtime"], arguments["instruction"],
                               binding, name=arguments.get("name"),
                               configuration=arguments.get("configuration"))
        if action == "status" and "agent" not in arguments:
            return Outcome({"agents": self.hierarchy(binding.caller)})

        agent = arguments["agent"]
        if action == "status":
            return self._outcome(self._authorized(agent, binding.caller))
        if action == "send":
            return self.send(agent, arguments["message"], binding)
        if action == "resume":
            return self.resume(agent, binding, arguments.get("message"))
        if action == "wait":
            return self.wait(agent, binding.caller, arguments["timeout_seconds"])
        if action == "interrupt":
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
    ) -> Outcome:
        """Register a new Agent under the caller and start its first execution.

        Returns once the driver has started native work; it never waits for
        the Agent's result.
        """
        driver = self.drivers.get(runtime)
        if driver is None:
            raise AgentsError("unsupported-runtime", f"No driver is available for Runtime {runtime!r}.")
        caller   = binding.caller
        self._require_root_control(caller)
        # Keep the original call shape for drivers whose users select defaults.
        settings = (driver.prepare(runtime, caller) if configuration is None else
                    driver.prepare(runtime, caller, configuration=configuration))
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
            "created_at": _now(),
            "retired_at": None,
            "executions": [],
        }
        with self._locked(agent, record) as current:
            run = self._begin(current, "create", instruction, binding)
        return self._launch(run)

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
            time.sleep(min(WAIT_INTERVAL_SECONDS, remaining))

    def requests(self, agent: str, caller: Caller, execution: str | None = None) -> Outcome:
        """Return the running execution's pending native requests."""
        with self._locked(agent) as record:
            self._require_control(record, caller)
            current = self._require_execution(record, execution)
            pending = self._driver(record).requests(self._run(record, current, "", None))
            documents = [{**request, "execution": current["id"]} for request in pending]
            return self._outcome(record, result={"requests": documents})

    def reply(
        self,
        agent: str,
        caller: Caller,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> Outcome:
        """Answer one native request once; a repeat returns the first receipt."""
        with self._locked(agent) as record:
            self._require_control(record, caller)
            current = self._require_execution(record, request.get("execution"))
            key = _reply_key(request)
            if key in current["replies"]:
                return self._outcome(record, result={**current["replies"][key], "duplicate": True})
            native = {name: value for name, value in request.items() if name != "execution"}
            receipt = self._driver(record).reply(self._run(record, current, "", None), native, response)
            current["replies"][key] = {"at": _now(), **receipt}
            return self._outcome(record, result=current["replies"][key])

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
            if any(item.get('state') != 'ended' or item.get('terminal_confirmed') is False
                   for item in record['executions']):
                raise AgentsError('turn-running', 'Only confirmed stopped Agents may be configured.')
            record['settings'] = deepcopy(dict(settings))
            return self._document(record)

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
            call=call,
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
            runtime_exit = last.get("process", {}).get("runtime_exit")
            if runtime_exit is not None:
                document["last_result"]["runtime_exit"] = deepcopy(runtime_exit)
            if last.get('notification'):
                document['last_result']['notification'] = last['notification']
                if last['notification'] != 'unavailable':
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
