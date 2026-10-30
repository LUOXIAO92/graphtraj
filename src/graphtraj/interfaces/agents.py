"""GraphTraj as a consumer of the independent ``agents`` control core.

Ordinary Agents are created and controlled by :class:`agent_swarm.AgentControl`
over the tool's own data root ``<project>/.graphtraj/swarm``, with GraphTraj's
:class:`~graphtraj.execution.agent_driver.AdapterDriver` running the native
Runtime. No Task, Team, Round or Worldline event is needed for any action.

Task member Sessions created by GraphTraj delivery keep their Runner aliases,
identities, memory and real parents. ``agents`` controls them with the same
actions as ordinary Agents through their existing native Session controls;
GraphTraj delivery applies its own Task policy, such as recording Worldline
causes, before calling the same continuation. Caller identity stays with the
existing bindings: the native callback scope or the calling process tree
resolved by ``caller_alias``.
"""

from __future__ import annotations

import time
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
    explicit_choices,
    read_config,
)

from graphtraj.execution.runner_models import RunnerError
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from agent_swarm.calls import CallCancelled, pause
from agent_swarm.sessions.archive import ConfiguredSessionArchive


# Core Agent references; anything else is a Runner alias of a Task member.
AGENT_PREFIX = "agent-"

# Polling interval of a finite wait on a Task member Session.
WAIT_INTERVAL_SECONDS = 0.2


PREVIEW_CHARACTERS = 200


def _preview(value: Any) -> Any:
    """Bound message bodies in the default listing; an explicit agent shows them."""
    if isinstance(value, dict):
        return {key: (item[:PREVIEW_CHARACTERS] + "…" if isinstance(item, str) and "message" in key
                      and len(item) > PREVIEW_CHARACTERS else _preview(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_preview(item) for item in value]
    return value


def swarm_root(root: Path) -> Path:
    """Return the ``agents`` tool's data root inside a GraphTraj project."""
    return root / ".graphtraj" / "swarm"


# GraphTraj turns saving on only where the user has made no explicit choice.
ARCHIVE_DEFAULTS = {"save_normalized_sessions": True}


def archive_choices(root: Path) -> dict[str, bool]:
    """Return the effective tool-owned archive choices without writing them."""
    return {**read_config(swarm_root(root)), **ARCHIVE_DEFAULTS,
            **explicit_choices(swarm_root(root))}


def configured_archive(root: Path) -> ConfiguredSessionArchive:
    """Bind GraphTraj to the tool-owned archive choices without overriding users."""
    directory = swarm_root(root)
    default_config(directory, **ARCHIVE_DEFAULTS)
    return ConfiguredSessionArchive(directory, **read_config(directory))


# Version of GraphTraj's own ``extra_fields.graphtraj`` header namespace.
EXTRA_FIELDS_VERSION = 1


def graphtraj_fields(
    project_id: str,
    agent_id: str,
    task_ids: list[str] | tuple[str, ...] = (),
    extra_fields: Mapping[str, Any] | None = None,
) -> dict:
    """Return a header ``extra_fields`` container carrying GraphTraj's namespace.

    Other namespaces in ``extra_fields`` are kept unchanged; GraphTraj's own
    association replaces any ``graphtraj`` entry a caller supplied.

    Examples
    --------
    >>> graphtraj_fields('/project', 'agent-1', ['42'])
    {'graphtraj': {'version': 1, 'projectId': '/project', 'agentId': 'agent-1', 'taskIds': ['42']}}
    """
    return {**dict(extra_fields or {}),
            'graphtraj': {'version': EXTRA_FIELDS_VERSION, 'projectId': project_id,
                          'agentId': agent_id, 'taskIds': list(task_ids)}}


def mapped_task_ids(directory: Path) -> list[str]:
    """Return the Task a Runner execution directory's ``mapping.yml`` names, if any."""
    import yaml

    mapping_file = directory / 'mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text()) if mapping_file.is_file() else None
    return [mapping['task_id']] if isinstance(mapping, dict) and mapping.get('task_id') else []


class GraphTrajAgents:
    """Run ``agents`` actions through the core, keeping Task member controls.

    ``root`` is the trusted project location supplied by the host and
    ``cwd`` the working directory new Agents run in. At first use GraphTraj
    turns normalized Session archiving on through the tool's public
    configuration, keeping any explicit choice already made.
    """

    def __init__(self, root: Path, cwd: Path | None = None) -> None:
        """Bind the project, the core data root and the Adapter driver."""
        from graphtraj.configuration.project_configuration import runner_directory
        from graphtraj.execution.agent_driver import SUPPORTED_RUNTIMES, AdapterDriver
        from graphtraj.execution.main_continuity import MainRoots

        self.root    = root
        driver       = AdapterDriver(root, cwd or root)
        # Every verified Main continues the roots of the project's Main, whose
        # claims live in the project's current Runner directory.
        self.control = AgentControl(swarm_root(root), {name: driver for name in SUPPORTED_RUNTIMES},
                                    roots=MainRoots(runner_directory(root)),
                                    event_receiver=self._main_notice)
        default_config(swarm_root(root), save_normalized_sessions=True)

    def _main_notice(self, notice: dict) -> bool | str:
        """Queue the end of a Main-created root Agent for the Main now in control.

        The core calls this only for an end its parent must handle. The notice
        takes the same Runtime Adapter path as a Task member's, so it follows
        Main continuity and is shown once. A Main host with a push channel
        (Codex) receives the parent event itself, so wait/status hide the body.
        """
        from graphtraj.configuration.project_configuration import runner_directory
        from graphtraj.execution.main_continuity import QUEUED_RUNTIMES, current_main, recorded_by_main, route_notice
        from graphtraj.runtimes.runtime_adapter import select_runtime_adapter

        runner = runner_directory(self.root)
        current = current_main(runner)
        if notice['parent'] is not None or current is None or not recorded_by_main(runner, notice['creator']):
            return False
        address = route_notice(runner, {**current['connection'], 'runtime': current['runtime'],
                                        'session': current['session']})
        message = notice['body'] or (notice.get('error') or {}).get('message') or notice['outcome']
        adapter = select_runtime_adapter(current['runtime'])
        if current['runtime'] not in QUEUED_RUNTIMES:
            # A push host accepts only the four-field parent event of a Task member's notice.
            try:
                adapter.send_host_event(address, {'source': 'graphtraj', 'alias': notice['agent'],
                                                  'event': notice['outcome'], 'message': message})
            except RuntimeAdapterError as error:
                if error.code == 'delivery-unconfirmed':
                    return 'unconfirmed'
                raise
            return True
        adapter.send_host_event(address, {
            'source': 'agents', 'alias': notice['agent'], 'event': notice['outcome'],
            'message': message, 'execution': notice['execution']})
        return 'queued'

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated action; an end a Main's wait/status shows is not pushed again."""
        from graphtraj.configuration.project_configuration import runner_directory
        from graphtraj.execution.main_continuity import QUEUED_RUNTIMES, acknowledge_ends, shown_ends

        outcome = self._operate_action(action, arguments, binding)
        caller = binding.caller
        if (action in {"wait", "status"} and arguments.get("agent") is not None and not outcome.failed
                and caller.agent is None and caller.runtime in QUEUED_RUNTIMES and caller.session):
            acknowledge_ends(runner_directory(self.root), caller.runtime, caller.session,
                             shown_ends(outcome.result))
        return outcome

    def _operate_action(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one validated action, translating GraphTraj rejections."""
        agent = arguments.get("agent")
        try:
            member = self._member_alias(agent)
            core = member is None and (action == "create" or (agent or "").startswith(AGENT_PREFIX))
            if not core and action not in {"status", "wait"} and binding.caller.agent is None:
                # A continued Main controls no Task member either.
                self.control.roots.require_control(binding.caller)
            if member is not None:
                # A Task member's core reference uses its existing Session controls.
                outcome = self._operate(action, {**arguments, "agent": member}, binding.caller)
                return Outcome(outcome.result, agent=agent, session=outcome.session,
                               execution=outcome.execution, failed=outcome.failed)
            if action == "create" or (agent or "").startswith(AGENT_PREFIX):
                if arguments.get("reports_only"):
                    raise AgentsError("invalid-input", "request.reports_only: only for a Task member")
                return self.control.operate(action, arguments, binding)
            if action == "status" and agent is None:
                return self._hierarchy(binding)
            return self._operate(action, arguments, binding.caller)
        except (RunnerError, RuntimeAdapterError) as error:
            message = error.message
            if error.code == "alias-not-found" and agent is not None:
                message += " " + self.control.reference_hint(agent, binding.caller)
            raise AgentsError(error.code, message) from None
        except ValueError as error:
            raise AgentsError("invalid-input", str(error)) from None

    def _member_alias(self, agent: str | None) -> str | None:
        """Return the Runner alias a Task member's core Agent record retains.

        The Worker records each Task member under the ``graphtraj-tasks`` host
        with its alias as the only driver setting; any other reference is not
        a Task member.
        """
        import json

        from graphtraj.execution.task_agents import TASK_HOST

        if not (agent or "").startswith(AGENT_PREFIX) or "/" in agent:
            return None
        record = swarm_root(self.root) / "control" / "agents" / f"{agent}.json"
        try:
            document = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        alias = document.get("settings", {}).get("alias") if isinstance(document, dict) else None
        return alias if document.get("host") == TASK_HOST and isinstance(alias, str) else None

    def _hierarchy(self, binding: Binding) -> Outcome:
        """Return the caller's own Agents and its real Task member hierarchy.

        A Task member caller adds the Sessions recorded under it. A native
        Main adds the top-level Sessions it dispatched, as recorded by their
        ``parent_connection``, with their subtrees. Each in-scope node keeps
        its own error. Unrelated history is never scanned into this view;
        current Task membership is ``tasks`` task_members.
        """
        from graphtraj.execution.runner_status import one_retained_scan, status_tree

        with one_retained_scan():
            return self._hierarchy_view(binding, status_tree)

    def _hierarchy_view(self, binding: Binding, status_tree: Any) -> Outcome:
        """Build ``_hierarchy`` with retained records read from one shared scan."""
        agents = self.control.operate("status", {}, binding)
        caller = binding.caller
        if (caller.agent or "").startswith(AGENT_PREFIX):
            return agents
        if caller.agent is None:
            if caller.session is None or caller.runtime is None:
                return agents
            sessions = status_tree(self.root, owner_connection={
                "runtime": caller.runtime, "session": caller.session},
                current_members=self._current_members())
        else:
            sessions = status_tree(self.root)
        return Outcome(_preview({**agents.result, "task_sessions": sessions.document}),
                       failed=not sessions.succeeded)

    def _current_members(self) -> set[str]:
        """Return the current seat holders of each unfinished Task's current Team.

        Replaced, handed-over and retired seats stay readable by explicit
        alias, as ``tasks`` task_members with a summary shows them.
        """
        from graphtraj.configuration.project_configuration import load_project_configuration
        from graphtraj.execution.desktop_activity import _task_aliases, registration_order
        from graphtraj.graph.task_graph import _load_states
        from graphtraj.workspace.runner_project import discover_runner_directory

        state = load_project_configuration(self.root).state
        runner = discover_runner_directory(self.root)
        states = _load_states(state / "tasks") if (state / "tasks").is_dir() else {}
        order = registration_order(state) if states else {}
        members: set[str] = set()
        for directory, task in states.values():
            if task.get("status") != "integrated" and task.get("disposition", "active") == "active":
                members |= _task_aliases(directory, task, runner, order)[1]
        return members

    def _operate(self, action: str, arguments: Mapping[str, Any], caller: Caller) -> Outcome:
        """Dispatch a Task member alias to its existing native Session control.

        ``caller`` is the verified caller; a confirmation receipt records it.
        """
        from graphtraj.execution.runner_control import (
            continue_member,
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
        failed = False
        if action == "status":
            response = status_aliases([agent], self.root)
            result, failed = response.document, not response.succeeded
            # A summary-only native caller gets the same references in the
            # envelope as in its status view, not the unrestricted mapping.
            visible = next(iter(result.get('aliases', [])), {})
            session, execution = visible.get('session'), visible.get('execution_id')
        elif action in {"send", "resume"}:
            message = arguments.get("message")
            if message is None:
                raise AgentsError("invalid-input", f"request.message: required to {action} a Task member")
            result = continue_member(agent, message, self.root,
                                     reports_only=arguments.get("reports_only") is True)
        elif action == "wait":
            result, failed = self._wait(agent, arguments["timeout_seconds"])
        elif action == "interrupt":
            result = interrupt_session(agent, self.root, ordinary=True)
            if any(member.get("alias") == agent and member.get("interrupt_status") == "stopped"
                   for member in result.get("members", [])):
                result = {**result, **self._confirm_member_end(agent, caller)}
        elif action == "requests":
            result = pending_requests(agent, self.root, execution_id=arguments.get("execution"))
        elif action == "reply":
            result = reply_to_request(agent, arguments["request"], arguments["response"], self.root)
        else:
            result = retire_session(agent, self.root)
        return Outcome(result, agent=agent, session=session, execution=execution, failed=failed)

    def _confirm_member_end(self, alias: str, caller: Caller) -> dict:
        """Confirm unconfirmed ends of a stopped Task member's core executions.

        The Runner's interrupt admits any ancestor, but only the member's
        direct parent, or Main and the user for a top-level member, may confirm
        (``is_direct_owner``); another caller is refused like the core path and
        nothing is written. The core then rechecks each recorded process under
        the member's recorded parent, as the Worker records it
        (``begin_task_agent``), and the receipt records the verified caller.
        Returns the confirmed executions, an error document when one cannot be
        verified, or nothing when no end needs confirming.
        """
        import json

        from agent_swarm.control import _scope
        from graphtraj.execution.runner_status import caller_alias, is_direct_owner, read_alias_mapping
        from graphtraj.execution.task_agents import TASK_HOST
        from graphtraj.workspace.runner_project import discover_runner_directory

        runner = discover_runner_directory(self.root)
        mapping = read_alias_mapping(runner, alias)[0]
        reference = mapping.get("agent")
        if (not isinstance(reference, str) or self._member_alias(reference) != alias
                or not self.control.unconfirmed_ends(reference)):
            return {}
        if not is_direct_owner(caller_alias(runner), mapping):
            raise AgentsError("authority-denied", "Only the direct parent can confirm an Agent's ended execution.")
        parent = json.loads((swarm_root(self.root) / "control" / "agents" / f"{reference}.json")
                            .read_text(encoding="utf-8"))["parent"]
        try:
            confirmed = self.control.confirm_ended(reference, Caller(TASK_HOST, parent),
                                                   by=_scope(caller)).result["termination_confirmed"]
        except AgentsError as error:
            return {"termination_confirmation_error": {"code": error.code, "message": error.message}}
        return {"termination_confirmed": confirmed}

    def _wait(self, agent: str, timeout_seconds: float) -> tuple[dict, bool]:
        """Wait at most ``timeout_seconds`` for an idle member or a pending request.

        While it waits, and briefly after it returns, the member's end is shown
        by this wait, so the Runner keeps that end notice in the records
        instead of also sending it to the waiting parent.
        """
        from graphtraj.execution.runner_control import AWAIT_GRACE_SECONDS, mark_awaited, pending_requests
        from graphtraj.execution.runner_status import read_alias_mapping, status_aliases
        from graphtraj.workspace.runner_project import discover_runner_directory

        try:
            mapping, directory = read_alias_mapping(discover_runner_directory(self.root), agent)
        except RunnerError:
            mapping, directory = {}, None
        execution = mapping.get("execution_id")
        if directory is not None:
            mark_awaited(directory, execution, time.time() + timeout_seconds + AWAIT_GRACE_SECONDS)
        try:
            result, failed = self._wait_idle(agent, timeout_seconds, pending_requests, status_aliases)
        except CallCancelled:
            if directory is not None:
                # No one reads this wait any more, so its parent gets the end notice.
                mark_awaited(directory, None, 0)
            raise
        if directory is not None:
            # Only the execution this wait returned stays covered, and briefly.
            returned = result.get("execution_id") if result.get("activity") == "idle" else execution
            mark_awaited(directory, returned, time.time() + AWAIT_GRACE_SECONDS)
        return result, failed

    def _wait_idle(self, agent: str, timeout_seconds: float, pending_requests: Callable,
                   status_aliases: Callable) -> tuple[dict, bool]:
        """Poll the member until it is idle, has a pending request or the wait ends."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = status_aliases([agent], self.root)
            status   = response.document.get("aliases", [{}])[0]
            if not response.succeeded:
                return response.document, True
            if status.get("activity") == "idle":
                return {**status, "timed_out": False}, False
            if pending_requests(agent, self.root).get("requests"):
                return {**status, "timed_out": False}, False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {**status, "timed_out": True}, False
            pause(min(WAIT_INTERVAL_SECONDS, remaining))

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
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import NativeCaller, caller_alias, runtime_caller_is_bound
    from graphtraj.interfaces.tools import ToolResult
    from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory

    working = cwd or Path.cwd()
    root    = discover_project_root(working)
    runner  = discover_runner_directory(root)
    try:
        alias = caller_alias(runner)
    except RunnerError as error:
        if arguments.get('action') != 'status':
            raise
        # A status query keeps its structured caller verification failure:
        # which stage failed for which requested Agent, never transport detail.
        agent = arguments.get('agent')
        return ToolResult({'action': 'status', 'error': error.as_document(), 'diagnostic': {
            'feature': 'alias_status', 'stage': 'caller_identity',
            'requested_aliases': [agent] if isinstance(agent, str) else None,
            'native_error_code': error.code,
        }}, failed=True)
    caller  = None
    if alias is None and not runtime_caller_is_bound():
        from graphtraj.runtimes.runtime_adapter import current_host_connection

        # caller_alias has already verified the native association. Its None
        # means Main for a bound external root, but human CLI has no connection.
        connection = current_host_connection()
        if connection is not None:
            caller = Caller('graphtraj-gateway', None, session=connection['session'],
                            runtime=connection['runtime'])
    if isinstance(alias, NativeCaller) and alias.connection['runtime'] == 'codex':
        from graphtraj.runtimes.codex.session_entry import owns_native_root

        if owns_native_root(runner, alias.connection):
            caller = Caller('graphtraj-gateway', None, session=str(alias), runtime='codex')
        elif arguments.get('action') != 'status':
            return ToolResult({'error': {'code': 'authority-denied',
                                        'message': 'Native helpers have read-only agents access.'}}, failed=True)
    if alias is None and caller is None:
        return ToolResult({"action": arguments.get("action"), "error": {
            "code":    "authority-unavailable",
            "message": "agents needs a verified caller: a managed Session or a verified native "
                       "Main Session. This call has neither.",
        }}, failed=True)
    if caller is None:
        caller = Caller("graphtraj-gateway", str(alias))
    result = agents_callback(root, caller, working)(dict(arguments))
    return ToolResult(result.document, failed=result.failed)
