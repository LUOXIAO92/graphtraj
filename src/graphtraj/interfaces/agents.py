"""GraphTraj's control backend for the independent ``agents`` function.

The independent ``agent_swarm`` contract validates the model request and owns
the result shape; this backend maps each action onto GraphTraj's existing
Session control. Caller identity stays with the existing bindings: the native
callback scope or the calling process tree resolved by ``caller_alias``.
Authority, permissions and approval routes are unchanged.

Actions whose existing GraphTraj control still requires a Task, Team or
Worldline event return an explicit ``not-implemented`` rejection that names
the missing step, rather than inventing Task context for an ordinary call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from agent_swarm import (
    AgentsError,
    AgentsResult,
    Binding,
    Caller,
    Outcome,
    bind,
    unavailable,
)

from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


# Existing GraphTraj features whose permission check each action reuses.
# Actions without control here have no feature and stay not-implemented.
ACTION_FEATURES = {
    "status":    "alias_status",
    "interrupt": "interrupt",
    "requests":  "pending_requests",
    "reply":     "reply_to_request",
    "retire":    "retire",
}

# Concrete missing control steps, reported to the caller as-is.
MISSING = {
    "create": "launch without a Task is missing; execution/runner_launch.launch_swarm "
              "requires a registered Task and configured role.",
    "send":   "send without Worldline is missing; execution/runner_control.send_instruction "
              "requires causal Project Worldline event IDs and an active Team.",
    "resume": "resume without Worldline is missing; execution/runner_control.send_instruction "
              "requires causal Project Worldline event IDs and an active Team.",
    "wait":   "a finite per-Agent wait is missing; execution/parent_status only observes "
              "a root caller's own host.",
}


class GraphTrajAgents:
    """Run ``agents`` actions through GraphTraj's existing Session control.

    ``root`` is the trusted project location supplied by the host. The caller
    identity is already bound by the surrounding host scope; ``binding`` is
    carried for the contract and never widens that identity.
    """

    def __init__(self, root: Path) -> None:
        """Bind the trusted project location chosen by the host."""
        self.root = root

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated action, translating GraphTraj rejections."""
        if action in MISSING:
            raise unavailable(action, MISSING[action])
        try:
            return self._operate(action, arguments)
        except (RunnerError, RuntimeAdapterError) as error:
            raise AgentsError(error.code, error.message) from None
        except ValueError as error:
            raise AgentsError("invalid-input", str(error)) from None

    def _operate(self, action: str, arguments: Mapping[str, Any]) -> Outcome:
        """Dispatch to the existing control function for ``action``."""
        from graphtraj.execution.runner_control import (
            interrupt_session,
            pending_requests,
            reply_to_request,
        )
        from graphtraj.execution.runner_retirement import retire_session
        from graphtraj.execution.runner_status import status_aliases, status_tree

        agent = arguments.get("agent")
        if action == "status" and agent is None:
            response = status_tree(self.root)
            return Outcome(response.document, failed=not response.succeeded)

        # References are read before the action because retirement moves the
        # record; they are returned only when the action itself succeeds.
        session, execution = self._references(agent)
        if action == "status":
            response = status_aliases([agent], self.root)
            result, failed = response.document, not response.succeeded
        elif action == "interrupt":
            result, failed = interrupt_session(agent, self.root), False
        elif action == "requests":
            result = pending_requests(agent, self.root, execution_id=arguments.get("execution"))
            failed = False
        elif action == "reply":
            result = reply_to_request(agent, arguments["request"], arguments["response"], self.root)
            failed = False
        else:
            result, failed = retire_session(agent, self.root), False
        return Outcome(result, agent=agent, session=session, execution=execution, failed=failed)

    def _references(self, agent: str) -> tuple[str | None, str | None]:
        """Return the target's native Session and current execution, if mapped.

        An allocation that has not produced a Session mapping yet has neither
        reference; the action itself still decides whether it may proceed.
        """
        from graphtraj.execution.runner_status import read_alias_mapping
        from graphtraj.workspace.runner_project import discover_runner_directory

        try:
            mapping, _ = read_alias_mapping(discover_runner_directory(self.root), agent)
        except RunnerError:
            return None, None
        return mapping.get("session"), mapping.get("execution_id")


def agents_callback(root: Path, caller: Caller) -> Callable[[Any], AgentsResult]:
    """Return the ``agents`` function bound to GraphTraj and a verified caller."""
    return bind(GraphTrajAgents(root), caller)


def run_agents_feature(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> Any:
    """Serve ``agents`` as a gateway feature for CLI, MCP and local tool hosts.

    The caller is the identity the existing binding already resolves for this
    call (native callback scope or calling process tree), never an argument.
    """
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.interfaces.tools import ToolResult
    from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory

    root   = discover_project_root(cwd or Path.cwd())
    caller = Caller("graphtraj-gateway", caller_alias(discover_runner_directory(root)))
    result = agents_callback(root, caller)(dict(arguments))
    return ToolResult(result.document, failed=result.failed)
