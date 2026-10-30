"""Task member executions recorded and controlled through the ``agents`` core.

The Runner Worker owns one native execution. It hosts
:class:`agent_swarm.AgentControl` over the tool's data root with a driver
around the turn it already runs, so the core records the Agent, its native
Session and the execution, and only the owning Worker controls it. GraphTraj
keeps the returned Agent reference in the member's mapping as its Task
participation; Task, budget, report and registration policy stay in the
Worker job. Mappings recorded before this reference keep their existing path.
"""

from __future__ import annotations

from graphtraj.configuration.project_configuration import runner_project_root

from pathlib import Path
import hashlib
import threading
from typing import Any, Mapping

from agent_swarm import DECISION_METHOD, AgentControl, AgentsError, Binding, Caller, Run

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, RuntimeTurn


# The registration path that verifies Task member callers: GraphTraj checks
# Runner ownership, Worldline causes and budget before any core action.
TASK_HOST = "graphtraj-tasks"

# Runner terminal outcomes and the core's names for them.
FINISHED = {"completed": "completed", "interrupted": "interrupted", "runtime-error": "failed"}


class WorkerDriver:
    """The ``RuntimeDriver`` for the one native turn this Worker owns.

    ``start`` only binds the core's execution to the turn; the Worker runs it
    and reports its facts through the bound ``Run.events``.
    """

    def __init__(self, turn: RuntimeTurn, alias: str) -> None:
        """Bind the Worker's native turn and the member's Runner alias."""
        self.turn  = turn
        self.alias = alias
        self.run: Run | None = None

    def prepare(self, runtime: str, caller: Caller, *, configuration: str | None = None) -> dict:
        """Retain only the Runner alias; the Worker job holds the launch settings."""
        return {"alias": self.alias}

    def start(self, run: Run) -> None:
        """Bind the execution the Worker is about to run."""
        self.run = run

    def deliver(self, run: Run, message: str) -> None:
        """Send input into the running native turn."""
        self._operate(operation="send", instruction=message)

    def interrupt(self, run: Run) -> bool:
        """Stop the native turn with the owner's own termination confirmation."""
        self._operate(operation="interrupt")
        return True

    def requests(self, run: Run) -> list[dict]:
        """Return the native requests still pending."""
        return self._operate(operation="requests")["requests"]

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Submit one explicit native reply."""
        return self._operate(operation="reply", request_token=request.get("request_token"),
                             response=dict(response))

    def _operate(self, **request: Any) -> dict:
        """Apply one Adapter operation to the exact Session and invocation."""
        try:
            return self.turn.operate({**request, "session": self.turn.session,
                                      "execution_id": self.turn.execution_id})
        except RuntimeAdapterError as error:
            raise AgentsError(error.code, error.message) from None


class NoNativeRequests:
    """Driver for reading a member's own requests; the turn reports the Runtime's."""

    def requests(self, run: Run) -> list[dict]:
        """Report none, so this read never waits on the native turn under the Agent lock."""
        return []


class TaskAgent:
    """The core execution of one Task member run by this Worker."""

    def __init__(self, root: Path, runtime: str, driver: WorkerDriver, caller: Caller) -> None:
        """Bind the project's core data root, the Worker driver and the verified caller."""
        from graphtraj.interfaces.agents import swarm_root

        self.control = AgentControl(swarm_root(root), {runtime: driver})
        self.own_requests = AgentControl(swarm_root(root), {runtime: NoNativeRequests()})
        self.driver  = driver
        self.binding = Binding(caller)
        self.input_lock = threading.Lock()
        # This execution's ask_parent requests already answered, for a repeated reply.
        self.answered: set[str] = set()

    @property
    def run(self) -> Run:
        """Return the core execution bound to this Worker's turn."""
        assert self.driver.run is not None
        return self.driver.run

    def operate(self, request: Mapping[str, Any]) -> dict:
        """Serve a Runner control request through the core.

        Input and stops are the core's actions; the core's stop runs the
        owner's confirmed native interruption. Native requests and replies keep
        the owner's exact one-time semantics and go to the turn directly. The
        member's own ``ask_parent`` requests are the core's: they are listed
        after the native ones and answered there, and no Runtime sees them.
        """
        operation = request.get("operation")
        agent     = self.run.agent
        try:
            if operation == "send":
                # Only the running execution takes input here; a continuation
                # after its end is a new execution owned by another Worker.
                with self.input_lock:
                    if self.control.operate("status", {"agent": agent}, self.binding).result["state"] != "active":
                        raise AgentsError("runtime-input-closed", "The member execution has ended without taking this input.")
                    outcome = self.control.send(agent, request["instruction"], self.binding)
                    if outcome.failed:
                        raise AgentsError("delivery-unknown", "The member input delivery is unconfirmed.")
                return {}
            if operation == "interrupt":
                stopped = self.control.interrupt(agent, self.binding.caller).result["interrupt"]
                if stopped == "requested":
                    return {}
                # A repeated stop, or one after the end, keeps the owner's confirmation.
            if operation == "reply" and self._is_decision(request.get("request_token")):
                return self._answer(request["request_token"], request["response"])
        except AgentsError as error:
            raise RuntimeAdapterError(error.code, error.message) from None
        answer = self.driver.turn.operate(dict(request))
        if operation == "requests":
            return {**answer, "requests": [*answer["requests"], *self._decisions()]}
        return answer

    def _decisions(self) -> list[dict]:
        """Return the unanswered ``ask_parent`` requests as the Runner addresses them.

        The Runner checks a reply against its own Session and execution
        identifiers, so the core's execution ID is replaced by the turn's.
        """
        try:
            pending = self.own_requests.requests(self.run.agent, self.binding.caller).result["requests"]
        except AgentsError:
            return []
        return [{**{name: value for name, value in item.items() if name != "execution"},
                 "session": self.driver.turn.session, "execution_id": self.driver.turn.execution_id}
                for item in pending]

    def _is_decision(self, token: object) -> bool:
        """Whether ``token`` names one of this execution's ``ask_parent`` requests."""
        return token in self.answered or any(item["request_token"] == token for item in self._decisions())

    def _answer(self, token: str, response: Mapping[str, Any]) -> dict:
        """Record the parent's answer once; a repeat returns the first receipt."""
        result = self.own_requests.reply(self.run.agent, self.binding.caller, {"request_token": token}, response).result
        self.answered.add(token)
        return {name: result[name] for name in ("at", "request_id", "reply_status", "answer", "duplicate")
                if name in result}

    def finished(self, terminal: Mapping[str, Any]) -> None:
        """Report the Runner's terminal record as the core execution's end."""
        error = terminal.get("error")
        # A send checked as active must not create a second core execution
        # between that check and delivery into this Worker's one native turn.
        with self.input_lock:
            self.run.events.finished(
                FINISHED.get(terminal.get("outcome"), "failed"),
                last_message=terminal.get("last_agent_message"),
                error=dict(error) if isinstance(error, Mapping) else None,
                terminal_confirmed=terminal.get("terminal_confirmed", True) is not False,
            )


def notify_parent_of_decision(directory: Path, mapping: Mapping[str, Any], notice: Mapping[str, Any]) -> bool:
    """Send one member ``ask_parent`` notice to its actual direct parent.

    This is the path a member's native request takes, and it names the method
    only, never the question. Delivery may start a stopped parent and retries a
    busy one, so it runs beside the asking call and never takes from its wait.
    An undelivered notice leaves the request readable through ``requests``.
    """
    from graphtraj.execution.runner_control import deliver_parent_event

    identity = {"method": DECISION_METHOD, "session": notice["session"],
                "execution_id": mapping.get("execution_id"), "request_id": notice["request"]}
    threading.Thread(target=deliver_parent_event, args=(directory, notice["body"], identity), daemon=True).start()
    return True


def native_directory(root: Path, alias: str, runtime: str) -> Path:
    """Locate host-owned native files in the tool's data root, independent of Traces."""
    from graphtraj.interfaces.agents import swarm_root

    return swarm_root(root) / 'native' / ('task-' + hashlib.sha256(alias.encode()).hexdigest()) / runtime


def _parent_agent(runner: Path, mapping: Mapping[str, Any]) -> str | None:
    """Resolve a real parent binding, retaining an imported legacy parent's alias."""
    from graphtraj.execution.runner_status import read_alias_mapping

    parent = mapping.get('parent')
    if not isinstance(parent, str):
        return None
    retained = read_alias_mapping(runner, parent)[0]
    # Imported identities deliberately keep their original aliases. A legacy
    # Main may have no core Agent record; its real parent reference still holds.
    return retained.get('agent') or (parent if mapping.get('agent') == mapping.get('alias') else None)


def begin_task_agent(
    root: Path,
    runner_directory: Path,
    operation: str,
    mapping: Mapping[str, Any],
    prompt: str,
    turn: RuntimeTurn,
) -> TaskAgent | None:
    """Create or continue the member's core Agent for this Worker's execution.

    A launch creates the Agent under its actual parent's Agent; a resume
    continues the Agent the mapping already references. A mapping recorded
    before this reference returns ``None`` and keeps its existing path.
    """
    parent_agent = _parent_agent(runner_directory, mapping)
    if operation == "resume" and not mapping.get("agent"):
        return None
    caller = Caller(TASK_HOST, parent_agent)
    agent  = TaskAgent(root, mapping["runtime"], WorkerDriver(turn, mapping["alias"]), caller)
    try:
        if operation == "launch":
            outcome = agent.control.create(mapping["runtime"], prompt, agent.binding, name=mapping["alias"])
        else:
            outcome = agent.control.send(mapping["agent"], prompt, agent.binding)
    except AgentsError as error:
        raise RuntimeAdapterError(error.code, error.message, terminal_confirmed=True) from None
    if outcome.failed or agent.driver.run is None:
        raise RuntimeAdapterError("RUNTIME_WORKER_FAILED", "The core did not start the member execution.",
                                  terminal_confirmed=True)
    return agent


def core_status(runner_directory: Path, mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Read a member's Agent through the core's public status.

    Returns the ``agent`` reference, its ``state`` (``active`` or ``standby``),
    its ``last_result`` and its unanswered ``ask_parent`` count
    (``pending_requests``); the Runner's own activity fields are unchanged.
    """
    from graphtraj.interfaces.agents import swarm_root

    parent_agent = _parent_agent(runner_directory, mapping)
    try:
        outcome = AgentControl(swarm_root(runner_project_root(runner_directory)), {}).operate(
            "status", {"agent": mapping["agent"]}, Binding(Caller(TASK_HOST, parent_agent)))
    except AgentsError as error:
        return {"agent": mapping["agent"], "agent_error": {"code": error.code, "message": error.message}}
    return {"agent": mapping["agent"], "state": outcome.result["state"],
            **{name: outcome.result[name] for name in ("last_result", "pending_requests") if name in outcome.result}}
