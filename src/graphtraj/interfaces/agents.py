"""GraphTraj as a consumer of the independent ``agents`` control core.

Ordinary Agents are created and controlled by :class:`agent_swarm.AgentControl`
over the tool's own data root ``<project>/.graphtraj/swarm``, with GraphTraj's
:class:`~graphtraj.execution.agent_driver.AdapterDriver` running the native
Runtime. No Task, Team, Round or Worldline event is needed for any action.

Task member Sessions created by GraphTraj delivery keep their Runner aliases
and existing controls for status, interrupt, requests, reply and retire; their
continuation stays GraphTraj policy (``send_instruction`` with Worldline
causes). Caller identity stays with the existing bindings: the native callback
scope or the calling process tree resolved by ``caller_alias``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from agent_swarm import (
    AgentControl,
    AgentsError,
    AgentsResult,
    Binding,
    Caller,
    Outcome,
    bind,
    default_config,
    read_config,
    unavailable,
)

from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.sessions.archive import JsonlSessionStore, SessionArchive


# Core Agent references; anything else is a Runner alias of a Task member.
AGENT_PREFIX = "agent-"

# Existing GraphTraj features whose permission check each action reuses at
# the Codex dynamicTools boundary. Actions without a feature need none there;
# read-only native helpers are refused them by that boundary.
ACTION_FEATURES = {
    "status":    "alias_status",
    "interrupt": "interrupt",
    "requests":  "pending_requests",
    "reply":     "reply_to_request",
    "retire":    "retire",
}

# Task member continuation and waiting remain GraphTraj delivery policy.
TASK_SESSION_MISSING = {
    "send":   "Task member Sessions continue through GraphTraj send_instruction with "
              "Worldline causes; ordinary Agents created by agents accept send directly.",
    "resume": "Task member Sessions continue through GraphTraj send_instruction with "
              "Worldline causes; ordinary Agents created by agents accept resume directly.",
    "wait":   "a finite wait on a Task member alias is not provided; ordinary Agents "
              "created by agents accept wait directly.",
}


def swarm_root(root: Path) -> Path:
    """Return the ``agents`` tool's data root inside a GraphTraj project."""
    return root / ".graphtraj" / "swarm"


class ConfiguredSessionArchive(SessionArchive):
    """Use the independent tool's current choices for every archive operation.

    A Runtime receives this through Run.archive when collection is enabled at
    activation. Disabling saving stops subsequent writes without deleting the
    archive or changing the Runtime's native Session.
    """

    def store(self, session_id: str, *, historical: bool = False) -> JsonlSessionStore | None:
        """Reload tool-owned settings before acquiring a collection capability."""
        choices = read_config(self.root)
        self.save_normalized_sessions = choices['save_normalized_sessions']
        self.backfill_history = choices['backfill_history']
        return super().store(session_id, historical=historical)


def configured_archive(root: Path) -> ConfiguredSessionArchive:
    """Bind GraphTraj to the tool-owned archive choices without overriding users."""
    directory = swarm_root(root)
    default_config(directory, save_normalized_sessions=True)
    return ConfiguredSessionArchive(directory, **read_config(directory))


class GraphTrajAgents:
    """Run ``agents`` actions through the core, keeping Task member controls.

    ``root`` is the trusted project location supplied by the host and
    ``cwd`` the working directory new Agents run in. At first use GraphTraj
    turns normalized Session archiving on through the tool's public
    configuration, keeping any explicit choice already made.
    """

    def __init__(self, root: Path, cwd: Path | None = None) -> None:
        """Bind the project, the core data root and the Adapter driver."""
        from graphtraj.execution.agent_driver import SUPPORTED_RUNTIMES, AdapterDriver

        self.root    = root
        driver       = AdapterDriver(root, cwd or root)
        self.control = AgentControl(swarm_root(root), {name: driver for name in SUPPORTED_RUNTIMES})
        default_config(swarm_root(root), save_normalized_sessions=True)

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated action, translating GraphTraj rejections."""
        agent = arguments.get("agent")
        try:
            if action == "create" or (agent or "").startswith(AGENT_PREFIX):
                return self.control.operate(action, arguments, binding)
            if action == "status" and agent is None:
                return self._hierarchy(binding)
            if action in TASK_SESSION_MISSING:
                raise unavailable(action, TASK_SESSION_MISSING[action])
            return self._operate(action, arguments)
        except (RunnerError, RuntimeAdapterError) as error:
            raise AgentsError(error.code, error.message) from None
        except ValueError as error:
            raise AgentsError("invalid-input", str(error)) from None

    def _hierarchy(self, binding: Binding) -> Outcome:
        """Return the caller's Agents and, separately, its Task member Sessions."""
        from graphtraj.execution.runner_status import status_tree

        agents   = self.control.operate("status", {}, binding)
        if (binding.caller.agent or '').startswith(AGENT_PREFIX):
            # A core identity has no legacy Runner alias or Task participation.
            return agents
        sessions = status_tree(self.root)
        return Outcome({**agents.result, "task_sessions": sessions.document},
                       failed=not sessions.succeeded)

    def _operate(self, action: str, arguments: Mapping[str, Any]) -> Outcome:
        """Dispatch a Task member alias to its existing control function."""
        from graphtraj.execution.runner_control import (
            interrupt_session,
            pending_requests,
            reply_to_request,
        )
        from graphtraj.execution.runner_retirement import retire_session
        from graphtraj.execution.runner_status import status_aliases

        agent = arguments["agent"]

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


def agents_callback(
    root: Path,
    caller: Caller,
    cwd: Path | None = None,
) -> Callable[[Any], AgentsResult]:
    """Return the ``agents`` function bound to GraphTraj and a verified caller."""
    backend = GraphTrajAgents(root, cwd)
    archive = configured_archive(root)
    return bind(backend, caller, archive=archive)


def run_agents_feature(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> Any:
    """Serve ``agents`` as a gateway feature for CLI, MCP and local tool hosts.

    The caller is the identity the existing binding already resolves for this
    call (native callback scope, calling process tree, or a verified native
    Main Session), never an argument. A call with no verified identity is
    refused rather than sharing one anonymous root scope with other callers.
    New Agents run in the call's working directory.
    """
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.interfaces.tools import ToolResult
    from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory

    working = cwd or Path.cwd()
    root    = discover_project_root(working)
    alias   = caller_alias(discover_runner_directory(root))
    if alias is None:
        return ToolResult({"action": arguments.get("action"), "error": {
            "code":    "authority-unavailable",
            "message": "agents needs a verified caller: a managed Session or a verified native "
                       "Main Session. This call has neither.",
        }}, failed=True)
    caller = Caller("graphtraj-gateway", str(alias))
    result = agents_callback(root, caller, working)(dict(arguments))
    return ToolResult(result.document, failed=result.failed)
