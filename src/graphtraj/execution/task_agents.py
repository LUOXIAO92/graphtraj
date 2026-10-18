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

from pathlib import Path
from typing import Any, Mapping

from agent_swarm import AgentControl, AgentsError, Binding, Caller, Run

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


class TaskAgent:
    """The core execution of one Task member run by this Worker."""

    def __init__(self, root: Path, runtime: str, driver: WorkerDriver, caller: Caller) -> None:
        """Bind the project's core data root, the Worker driver and the verified caller."""
        from graphtraj.interfaces.agents import swarm_root

        self.control = AgentControl(swarm_root(root), {runtime: driver})
        self.driver  = driver
        self.binding = Binding(caller)

    @property
    def run(self) -> Run:
        """Return the core execution bound to this Worker's turn."""
        assert self.driver.run is not None
        return self.driver.run

    def operate(self, request: Mapping[str, Any]) -> dict:
        """Serve a Runner control request through the core.

        Input and stops are the core's actions; the core's stop runs the
        owner's confirmed native interruption. Native requests and replies keep
        the owner's exact one-time semantics and go to the turn directly.
        """
        operation = request.get("operation")
        agent     = self.run.agent
        try:
            if operation == "send":
                # Only the running execution takes input here; a continuation
                # after its end is a new execution owned by another Worker.
                if self.control.operate("status", {"agent": agent}, self.binding).result["state"] != "active":
                    raise AgentsError("operation-failed", "The member execution has ended.")
                self.control.send(agent, request["instruction"], self.binding)
                return {}
            if operation == "interrupt":
                stopped = self.control.interrupt(agent, self.binding.caller).result["interrupt"]
                if stopped == "requested":
                    return {}
                # A repeated stop, or one after the end, keeps the owner's confirmation.
        except AgentsError as error:
            raise RuntimeAdapterError(error.code, error.message) from None
        return self.driver.turn.operate(dict(request))

    def finished(self, terminal: Mapping[str, Any]) -> None:
        """Report the Runner's terminal record as the core execution's end."""
        error = terminal.get("error")
        self.run.events.finished(
            FINISHED.get(terminal.get("outcome"), "failed"),
            last_message=terminal.get("last_agent_message"),
            error=dict(error) if isinstance(error, Mapping) else None,
            terminal_confirmed=terminal.get("terminal_confirmed", True) is not False,
        )


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
    from graphtraj.execution.runner_status import read_alias_mapping

    parent = mapping.get("parent")
    parent_agent = None
    if isinstance(parent, str):
        parent_agent = read_alias_mapping(runner_directory, parent)[0].get("agent")
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
