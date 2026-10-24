"""Shared operation definitions and handlers for local GraphTraj callers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from graphtraj.configuration.project_configuration import (
    configuration_exists,
    load_project_configuration,
)
from graphtraj.configuration.project_diagnosis import diagnose_project
from graphtraj.execution.runner_control import (
    read_session_reports,
    submit_session_report,
)
from graphtraj.execution.runner_launch import launch_swarm, launch_swarm_file
from graphtraj.graph.delivery_state import apply_delivery_state_request
from graphtraj.graph.delivery_worldline import (
    append_project_worldline_event,
    read_worldline,
)
from graphtraj.graph.task_graph import (
    read_graph,
    register_task,
    revise_tasks,
    update_task_state,
    complete_task,
)
from graphtraj.teams.task_integration import integrate_task
from graphtraj.workspace.git_repository import GitRepositoryError
from graphtraj.workspace.project_initialization import (
    ProjectSetupError,
    existing_source_repository,
    plan_project_setup,
    require_source_repository,
)

from graphtraj.graph.task_protocol import (
    REGISTER_SCHEMA as _ISSUE_SCHEMA,
    REVISION_SCHEMA as _REVISION_SCHEMA,
    COMPLETE_SCHEMA,
    TASK_SCHEMA,
    STATE_CHANGE_SCHEMA as _STATE_CHANGE_SCHEMA,
)

_EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
_ALIAS_SCHEMA = {
    "type": "object",
    "properties": {"alias": {"type": "string"}},
    "required":             ["alias"],
    "additionalProperties": False,
}
_SWARM_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id":   {"type": "string"},
        "task_name": {"type": "string"},
        "role":        {"type": ["string", "object"]},
        "instruction": {"type": "string"},
    },
    "required":             ["role"],
    "additionalProperties": False,
}
_SWARM_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": _SWARM_TASK_SCHEMA}},
    "required":             ["tasks"],
    "additionalProperties": False,
}
_CONTINUE_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id":           {"type": "string"},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "budget_only":         {"type": "boolean", "default": False,
                                "description": "Restore budget permission without executing old Sessions."},
    },
    "required":             ["task_id", "caused_by_event_ids"],
    "additionalProperties": False,
}
_PROJECT_SETUP_SCHEMA = {
    "type": "object",
    "properties": {
        "source_repository": {"type": ["string", "null"]},
        "apply":             {"type": "boolean", "default": False},
        "create_dev":        {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}
_WORLDLINE_APPEND_SCHEMA = {
    "type": "object",
    "properties": {"event": {"type": "object"}},
    "required":             ["event"],
    "additionalProperties": False,
}
_DELIVERY_STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "request": {"type": "object"},
        "facts":   {"type": "object"},
    },
    "required":             ["request", "facts"],
    "additionalProperties": False,
}
_INTEGRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id":          {"type": "string"},
        "validation_command": {
            "type": "array", "minItems": 1, "items": {"type": "string"},
        },
        "resolve_conflict":   {"type": ["string", "null"],
                               "description": "Dispatch an explicitly selected role for a retained conflict."},
        "confirmed_commit":   {"type": ["string", "null"],
                               "description": "Confirm the exact committed resolution when adopting an escalated integration."},
        "role":               {"type": ["string", "object", "null"],
                               "description": "Explicit configured role reference or inline YAML role definition for conflict work."},
    },
    "required":             ["task_id", "validation_command"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ToolResult:
    """One tool's structured document and whether the operation failed."""

    document: dict[str, Any]
    failed: bool = False


@dataclass(frozen=True)
class Tool:
    """One operation's stable name, schema, handler and optional method material.

    ``manual_ref`` identifies caller-managed text; registering or executing an
    operation does not read it. A ``None`` handler marks a method-only feature:
    it carries guidance and no executable action. ``examples`` holds structured
    argument examples.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., ToolResult] | None
    manual_ref: str | None = None
    examples: tuple[dict[str, Any], ...] = ()
    cli_path: tuple[str, ...] = ()
    cli_parameters: dict[str, tuple[str, str]] = field(default_factory=dict)


TOOLS: dict[str, Tool] = {}

def register_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler: Callable[..., ToolResult] | None,
    *,
    manual_ref: str | None = None,
    examples: tuple[dict[str, Any], ...] = (),
) -> None:
    """Bind an operation and optional manual reference/examples to its schema."""
    TOOLS[name] = Tool(name, description, input_schema, handler, manual_ref, examples)


def read_current_graph(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Return the current Task DAG and readiness view for the project.

    The current view defaults to the calling Session's own Task; Main, the
    human desktop and helper forks have none and see the whole project's open work.
    """
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import caller_alias, read_alias_mapping
    from graphtraj.workspace.runner_project import discover_runner_directory

    if arguments.get("schema", False):
        return ToolResult(TASK_SCHEMA)
    configuration = load_project_configuration(cwd or Path.cwd())
    view          = arguments.get("view", "current")
    task_id       = arguments.get("task_id")
    if view == "current" and task_id is None:
        runner = discover_runner_directory(configuration.harness_root)
        caller = caller_alias(runner)
        try:
            if caller is not None:
                task_id = read_alias_mapping(runner, caller)[0]["task_id"]
        except RunnerError as error:
            # Helper and checker forks act for a caller without their own Task.
            if error.code != "alias-not-found":
                raise
    return ToolResult(read_graph(
        configuration.state, view, task_id, arguments.get("details", []),
    ))


def register_current_task(arguments: Mapping[str, Any]) -> ToolResult:
    """Register one accepted Task definition in the project graph."""

    configuration = load_project_configuration(Path.cwd())
    directory = register_task(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult({"task_directory": str(directory)})


def revise_current_tasks(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one validated product-preserving Task Graph revision."""

    configuration = load_project_configuration(Path.cwd())
    recorded = revise_tasks(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult(recorded)


def complete_current_task(arguments: Mapping[str, Any]) -> ToolResult:
    """Record independent task acceptance without manufacturing file delivery."""
    configuration = load_project_configuration(Path.cwd())
    return ToolResult(complete_task(configuration.state, configuration.harness_root, arguments))


def update_current_task_state(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one evidence-backed current Task state transition."""

    configuration = load_project_configuration(Path.cwd())
    recorded = update_task_state(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult(recorded)


def backup_current_task(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Publish one local Task to its explicitly mapped GitHub Issue."""
    from graphtraj.graph.github_backup import backup_task

    configuration = load_project_configuration(cwd or Path.cwd())
    document, failed = backup_task(
        configuration.state,
        _string_argument(arguments, "task_id"),
        _string_argument(arguments, "repository"),
        arguments.get("host") or "github.com",
        arguments.get("confirm_remote"),
    )
    return ToolResult(document, failed=failed)


def preview_or_apply_project_setup(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Preview or apply setup from explicit inputs instead of CLI prompts."""

    root = (cwd or Path.cwd()).resolve()
    supplied = arguments.get("source_repository")
    if supplied is not None and not isinstance(supplied, str):
        raise ValueError("source_repository must be a string or null")
    apply_setup = _boolean_argument(arguments, "apply")
    create_dev = _boolean_argument(arguments, "create_dev")
    try:
        source_repository = None
        if not configuration_exists(root):
            source_repository = (
                require_source_repository(root, Path(supplied))
                if supplied is not None
                else existing_source_repository(root)
            )
            if source_repository is None:
                raise ProjectSetupError("Setup could not select a Source Repository.")
        plan = plan_project_setup(root, source_repository)
        preview = plan.preflight()
        document = {
            "actions": [
                {"disposition": action.disposition, "description": action.description}
                for action in preview.actions
            ],
            "proposed_base": plan.proposed_base,
            "applied":       False,
        }
        if not apply_setup:
            return ToolResult(document)
        if plan.proposed_base is not None and not create_dev:
            raise ProjectSetupError(
                "Applying setup must explicitly confirm creating dev from {0}.".format(
                    plan.proposed_base
                )
            )
        result = plan.apply()
    except (ProjectSetupError, GitRepositoryError) as error:
        raise ValueError(str(error)) from error
    document.update({
        "applied":              True,
        "integration_worktree": str(result.integration_worktree),
        "integration_action":   result.integration_action,
        "completed_actions":    list(result.completed_actions),
    })
    return ToolResult(document)


def diagnose_current_project(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Report configuration and reusable-role diagnostics for the project."""

    diagnosis = diagnose_project(cwd or Path.cwd())
    return ToolResult(
        {
            "roles_checked":    diagnosis.roles_checked,
            "role_diagnostics": list(diagnosis.role_diagnostics),
        },
        failed=not diagnosis.succeeded,
    )


def append_worldline_event(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Append one explicit durable fact supplied as the same event mapping."""

    event = arguments.get("event")
    if not isinstance(event, dict):
        raise ValueError("event file must contain one mapping")
    configuration = load_project_configuration(cwd or Path.cwd())
    recorded = append_project_worldline_event(
        configuration.state, configuration.harness_root, event
    )
    return ToolResult(recorded)


def read_project_worldline(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Return the project's complete Worldline as one event sequence."""

    configuration = load_project_configuration(cwd or Path.cwd())
    events = read_worldline(configuration.state, configuration.harness_root)
    return ToolResult({"events": events})


def apply_state_request(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Validate and atomically apply one semantic state request with its facts."""

    configuration = load_project_configuration(cwd or Path.cwd())
    recorded = apply_delivery_state_request(
        configuration.state,
        configuration.harness_root,
        arguments.get("request"),
        arguments.get("facts"),
    )
    return ToolResult(recorded)


def integrate_current_task(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Merge or recover an accepted Task under its actual task authority."""

    validation_command = arguments.get("validation_command")
    if not isinstance(validation_command, list) or any(
        not isinstance(argument, str) for argument in validation_command
    ):
        raise ValueError("validation_command must be a list of strings")
    try:
        configuration = load_project_configuration(cwd or Path.cwd())
        result = integrate_task(
            configuration,
            _string_argument(arguments, "task_id"),
            tuple(validation_command),
            _optional_string_argument(arguments, "resolve_conflict"),
            arguments.get("role"),
            _optional_string_argument(arguments, "confirmed_commit"),
        )
    except GitRepositoryError as error:
        raise ValueError(str(error)) from error
    failed = result["status"] != "integrated" and not (
        result["status"] == "resolving-integration" and result.get("resolution")
    )
    return ToolResult(result, failed=failed)


def read_parent_status(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Observe only the caller root's recorded Runtime host parent."""
    from graphtraj.execution.parent_status import parent_status

    result = parent_status(cwd or Path.cwd(), arguments.get('timeout_seconds', 0),
                           include_hooks=arguments.get('include_hooks', False))
    return ToolResult(result, failed=result['outcome'] in {'timeout', 'error'})


register_tool(
    'parent_status',
    'Read a root Agent\'s recorded owning host activity and latest turn metadata, optionally '
    'waiting a finite interval for native idle within the caller\'s remaining execution budget. '
    'No input is sent. Main cannot wait on itself.',
    {'type': 'object', 'properties': {
        'include_hooks': {'type': 'boolean', 'default': False,
                          'description': 'Read owning Codex source and hooks/list; retain hook notifications during the existing wait. Does not replay past events or expose an active-registry snapshot.'},
        'timeout_seconds': {'type': 'number', 'default': 0,
                            'description': 'Zero reads once; a finite positive timeout waits for idle. Choose within the remaining execution budget.'},
    }, 'additionalProperties': False},
    read_parent_status, manual_ref='manuals/task-delivery/guide.md',
)


def _string_argument(arguments: Mapping[str, Any], name: str) -> str:
    """Return one required string argument without restating the operation."""

    value = arguments.get(name)
    if not isinstance(value, str):
        raise ValueError("{0} must be a string".format(name))
    return value


def _optional_string_argument(
    arguments: Mapping[str, Any], name: str
) -> str | None:
    """Return one optional string argument, or None when it was not supplied."""

    value = arguments.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError("{0} must be a string".format(name))
    return value


def _string_list_argument(
    arguments: Mapping[str, Any], name: str
) -> tuple[str, ...]:
    """Return one optional list of strings; the operation owns its own rules."""

    value = arguments.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError("{0} must be a list of strings".format(name))
    return tuple(value)


def _boolean_argument(arguments: Mapping[str, Any], name: str) -> bool:
    """Return one optional flag, defaulting to the operation's plain behavior."""

    value = arguments.get(name, False)
    if not isinstance(value, bool):
        raise ValueError("{0} must be a boolean".format(name))
    return value


def launch_swarm_tool(
    arguments: Mapping[str, Any],
    *,
    cwd: Path | None = None,
    input_file: Path | None = None,
) -> ToolResult:
    """Activate one swarm input; the returned identity stays owned.

    The calling Session's Task and the registered Task state supply the
    identity each task does not repeat.
    """

    # The CLI retains the original file, including comments and formatting.
    response = (
        launch_swarm_file(input_file, cwd or Path.cwd())
        if input_file is not None
        else launch_swarm(dict(arguments), cwd or Path.cwd())
    )
    return ToolResult(response.document, failed=not response.succeeded)


def continue_task_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Restore task budget permission, optionally without executing old Sessions."""

    from graphtraj.teams.team_round import continue_stopped_task

    return ToolResult(
        continue_stopped_task(
            _string_argument(arguments, "task_id"),
            _string_list_argument(arguments, "caused_by_event_ids"),
            cwd or Path.cwd(),
            budget_only=_boolean_argument(arguments, "budget_only"),
        )
    )


def read_session_archive(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Read a bounded canonical Session page through existing Runner authority."""
    from graphtraj.sessions.query import read_session

    return ToolResult(read_session(cwd or Path.cwd(), arguments['session_id'],
                                   arguments.get('after', -1), arguments.get('limit', 200)))


register_tool(
    "session_read",
    "Read a project-local canonical Session, ordered events and durable unfinished output. "
    "Verified project callers, including Main and other Agents, read the project's linked Sessions with "
    "credentials and control material redacted; no messaging or control is provided.",
    {"type": "object", "properties": {
        "session_id": {"type": "string"}, "after": {"type": "integer"},
        "limit": {"type": "integer"},
    }, "required": ["session_id"], "additionalProperties": False},
    read_session_archive,
    manual_ref="manuals/task-delivery/guide.md",
)


def read_desktop_activity(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Expose the native human monitor without widening Agent report access."""
    from graphtraj.execution.desktop_activity import observe

    return ToolResult(observe(cwd or Path.cwd(), arguments.get('task_id'),
                              arguments.get('alias'), arguments.get('cursor')))


register_tool(
    "desktop_activity",
    "Read associated Main Sessions, actual project members and bounded native Chat/usage records. "
    "Omit task_id to list project sources in the human desktop. "
    "Verified project callers read project members and Main with credentials redacted; no messaging or control is provided.",
    {"type": "object", "properties": {
        "task_id": {"type": "string"}, "alias": {"type": "string"},
        "cursor": {"type": "string"},
    }, "additionalProperties": False},
    read_desktop_activity,
    manual_ref="manuals/task-delivery/guide.md",
    examples=({"task_id": "1"},),
)


register_tool(
    "task_graph",
    "Read the current Task DAG, states and dependency readiness for the project "
    "in the server working directory from its light index. The default view expands "
    "open work in the caller's scope and folds completed history; request view full, "
    "another task_id, or details explicitly. Equivalent to `graphtraj task graph`.",
    {"type": "object", "properties": {
        "schema":  {"type": "boolean", "default": False},
        "view":    {"enum": ["current", "full"], "default": "current",
                    "description": "current expands open work in scope and folds history; full lists every Task."},
        "task_id": {"type": "string",
                    "description": "Scope of the current view; defaults to the caller's own Task."},
        "details": {"type": "array", "items": {"type": "string"},
                    "description": "Tasks whose full definitions and execution facts to include."},
    }, "additionalProperties": False},
    read_current_graph,
    manual_ref="manuals/task-breakdown/guide.md",
    examples=({},),
)
def read_task_members(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """List member Agents of current summary Tasks or of one chosen summary."""
    from graphtraj.execution.desktop_activity import task_members

    return ToolResult(task_members(cwd or Path.cwd(), arguments.get("summary_task_id")))


register_tool(
    "task_members",
    "List the Agents participating in the current unfinished summary Tasks and their "
    "recursive child Tasks, with actual Agent parents and active/standby state. Supply "
    "summary_task_id to read one summary's members, including completed and retired "
    "history. Reading changes no identity or state. Equivalent to `graphtraj task members`.",
    {"type": "object", "properties": {
        "summary_task_id": {"type": "string",
                            "description": "Summary Task to read instead of the current ones."},
    }, "additionalProperties": False},
    read_task_members,
    manual_ref="manuals/task-delivery/guide.md",
    examples=({}, {"summary_task_id": "1"}),
)
register_tool(
    "task_register",
    "Register one accepted Task definition with its dependencies. Equivalent to "
    "`graphtraj task register --task-file`.",
    _ISSUE_SCHEMA,
    register_current_task,
    manual_ref="manuals/task-breakdown/guide.md",
    examples=(
        {
            "schema_version": 2,
            "task_id":    "1",
            "parent_id": None,
            "disposition": "active",
            "replaced_by": [],
            "retirement_reason": None,
            "task_name":  "paper-summary",
            "source":       "local:paper-1",
            "title":        "Summarize the first paper",
            "body":         "Read the paper and deliver a cited summary with links to related papers.",
            "dependencies": [],
        },
    ),
)
register_tool(
    "task_revise",
    "Apply one validated product-preserving Task graph revision and return its "
    "recorded causal event. Equivalent to `graphtraj task revise`.",
    _REVISION_SCHEMA,
    revise_current_tasks,
    manual_ref="manuals/task-breakdown/guide.md",
)
register_tool(
    "task_complete",
    "Complete a task with its own acceptance reason and existing evidence, without file delivery.",
    COMPLETE_SCHEMA,
    complete_current_task,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "task_update",
    "Apply one evidence-backed Task state transition and return its recorded "
    "causal event. Equivalent to `graphtraj task update`.",
    _STATE_CHANGE_SCHEMA,
    update_current_task_state,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "task_backup",
    "Back up one local Task to its mapped GitHub Issue, creating the Issue once. "
    "Publishing is one-way: remote edits are reported as a conflict with their "
    "differences and never change the local Task. Equivalent to `graphtraj task backup`.",
    {"type": "object", "properties": {
        "task_id":    {"type": "string"},
        "repository": {"type": "string", "description": "GitHub repository as owner/name."},
        "host":       {"type": "string", "default": "github.com",
                       "description": "GitHub host used by the installed gh login."},
        "confirm_remote": {
            "type": ["string", "null"],
            "description": "remote_digest from a reported conflict. Supply it after reviewing "
                           "the differences and revising the local Task through Task operations "
                           "when needed; publishes the local Task over exactly that remote copy.",
        },
    }, "required": ["task_id", "repository"], "additionalProperties": False},
    backup_current_task,
    manual_ref="manuals/task-delivery/guide.md",
    examples=({"task_id": "42", "repository": "owner/name"},),
)
register_tool(
    "project_setup",
    "Initialize GraphTraj in the current existing Git repository. Equivalent to "
    "`graphtraj setup`.",
    _PROJECT_SETUP_SCHEMA,
    preview_or_apply_project_setup,
    manual_ref="manuals/setup-project/guide.md",
    examples=(
        {"source_repository": "./source", "apply": False, "create_dev": False},
    ),
)
register_tool(
    "project_doctor",
    "Report configuration and roles from the active Harness Project context. "
    "Equivalent to `graphtraj doctor`.",
    _EMPTY_SCHEMA,
    diagnose_current_project,
    manual_ref="manuals/setup-project/guide.md",
)
register_tool(
    "worldline_append",
    "Append one explicit durable fact from a YAML file. Equivalent to "
    "`graphtraj worldline append --event-file`.",
    _WORLDLINE_APPEND_SCHEMA,
    append_worldline_event,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "worldline_read",
    "Read the complete Worldline as chronological JSONL. Equivalent to "
    "`graphtraj worldline read`.",
    _EMPTY_SCHEMA,
    read_project_worldline,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "worldline_render",
    "Render a ledger-shaped YAML view without persisting it. Equivalent to "
    "`graphtraj worldline render`.",
    _EMPTY_SCHEMA,
    read_project_worldline,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "delivery_state_apply",
    "Validate and atomically apply one semantic state request. Equivalent to "
    "`graphtraj delivery-state apply`.",
    _DELIVERY_STATE_SCHEMA,
    apply_state_request,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "task_integrate",
    "Merge or recover an accepted Task under its actual task authority. "
    "Equivalent to `graphtraj task integrate`.",
    _INTEGRATE_SCHEMA,
    integrate_current_task,
    manual_ref="manuals/task-delivery/guide.md",
)

register_tool(
    "swarm",
    "Activate the roles this swarm input selects and return each Agent's alias, "
    "so later calls query, steer and continue it by that alias rather than by "
    "another launch input. Equivalent to `agent-runner --swarm-input`.",
    _SWARM_SCHEMA,
    launch_swarm_tool,
    manual_ref="manuals/task-delivery/guide.md",
)


register_tool(
    "continue",
    "Restore a sampled stopped task budget and resume original roots by default; "
    "budget_only leaves old Sessions stopped for a later ordinary swarm dispatch. Equivalent to "
    "`agent-runner continue`.",
    _CONTINUE_SCHEMA,
    continue_task_execution,
    manual_ref="manuals/task-delivery/guide.md",
    examples=(
        {
            "task_id":           "paper-1",
            "caused_by_event_ids": ["<actual-authorization-event-id>"],
            "budget_only":         True,
        },
    ),
)




def recover_execution(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Prepare native approval or retry the same applied recovery."""
    from graphtraj.execution.approved_recovery import approved_recovery

    result = approved_recovery(dict(arguments), cwd or Path.cwd())
    return ToolResult(result, failed=result['recovery_status'] in {
        'stale', 'resume-stale', 'resume-failed',
    })


register_tool(
    'approved_recovery',
    'Recover the original Session within existing authority. New spending '
    'requires the selected reviewer; refusal or review failure applies nothing. '
    'The same call applies the reviewed change and continues with explicit scope. '
    'Retry with alias and retry_event_id never adds time twice. '
    'Equivalent to `agent-runner recover`.',
    {'type': 'object', 'properties': {
        'alias': {'type': 'string'},
        'reason': {'type': 'string'},
        'instruction': {'type': 'string'},
        'allowed_scope': {'type': 'string'},
        'forbidden_scope': {'type': 'string'},
        'caused_by_event_ids': {'type': 'array', 'items': {'type': 'string'}},
        'additional_minutes': {'type': 'number', 'description': 'Explicit time increment; preserves original clock and randomized allowance.'},
        'restore_active': {'type': 'boolean', 'description': 'Correct Task/Team administrative state and reopen the same Round for authorized work.'},
        'resume': {'type': 'boolean', 'description': 'Resume the original Session after repair (default true). False applies administrative repair without changing stops or sending input.'},
        'retry_event_id': {'type': 'string', 'description': 'Applied recovery event; retry continuation without another repair.'},
    }, 'required': ['alias'], 'additionalProperties': False},
    recover_execution, manual_ref='manuals/task-delivery/guide.md',
)


_ROLE_EDGE_PROPERTIES = {
    "parent": {"type": "string"},
    "child":  {"type": "string"},
}
_ROLE_ORGANIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "expected_revision": {"type": "string", "description": "Revision returned by preview; reject a draft based on older configuration."},
        "change": {
            "type": "object",
            "description": "Explicit preset and dispatch-edge change; omit for a side-effect-free preview.",
            "properties": {
                "unset_fields": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
                "rename_presets": {"type": "object", "additionalProperties": {"type": "string"}},
                "role_tree": {"type": "object", "description": "Complete nested dispatch tree; reviewed and saved atomically with preset changes."},
                "set_presets": {
                    "type": "object",
                    "description": "Exact preset reference to settings; a declared preset merges, a new reference is added.",
                    "additionalProperties": {"type": "object"},
                },
                "remove_presets": {
                    "type": "array", "minItems": 1, "items": {"type": "string"},
                },
                "add_edges": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object", "properties": _ROLE_EDGE_PROPERTIES,
                        "required": ["parent", "child"], "additionalProperties": False,
                    },
                },
                "remove_edges": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object", "properties": _ROLE_EDGE_PROPERTIES,
                        "required": ["parent", "child"], "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def runtime_connections(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Manage user connections through the same public host and native review seam."""
    from graphtraj.configuration.runtime_connections import manage_connections

    return ToolResult(manage_connections(dict(arguments), cwd=cwd or Path.cwd()))


register_tool(
    'runtime_connections',
    'Read, preview, save or discover user Runtime/provider/model connections. '
    'Save requires expected_revision and native host review. Discovery never runs inference; '
    'account access remains unknown. Secrets are never returned.',
    {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['read', 'preview', 'save', 'discover']},
        'catalog': {'type': 'object', 'description':
            'Complete version: 1 catalog. runtimes maps names to runtime (codex/pi/dsh/claude), '
            'optional absolute home, and providers. Each provider has models and optional '
            'base_url, api_key_env (variable name), and Pi api. models maps reference keys '
            'to id, source (manual/native), optional alias and supported_efforts. '
            'Project roles select connection: runtime-name/provider-name/model-key.'},
        'expected_revision': {'type': 'string', 'description': 'Exact revision returned by read; required to save.'},
        'runtime': {'type': 'string', 'description': 'Configured runtime entry name to query for discovery.'},
    }, 'additionalProperties': False},
    runtime_connections, manual_ref='manuals/setup-project/guide.md',
    examples=({'action': 'read'},),
)


def organize_roles(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Preview child role presets and dispatch edges, or apply one approved change."""
    from graphtraj.execution.role_organization import organize_child_roles

    return ToolResult(organize_child_roles(arguments, cwd=cwd or Path.cwd()))


register_tool(
    'role_organization',
    'Read the declared child role presets and direct dispatch edges, or apply one '
    'explicit change with the selected reviewer\'s decision. Omit change for a '
    'side-effect-free preview. The same call obtains authorization and writes the '
    'reviewed document; refusal, an unavailable reviewer or a target changed after '
    'review leaves roles.yml untouched. A preset keeps its existing `instructions` '
    'UTF-8 file reference and may add inline `system_prompt` and `developer_prompt` '
    'text. Codex keeps system_prompt and developer_prompt in separate native '
    'instruction layers. Pi and DSH merge authored developer content, with an '
    'explanatory label, into their system instruction channel; this does not '
    'create a separate native developer priority. The existing instructions '
    "file uses the selected Runtime's instruction channel. Authored role prompts "
    'are not passed as task text. Equivalent to '
    '`graphtraj roles organize`.',
    _ROLE_ORGANIZATION_SCHEMA,
    organize_roles, manual_ref='manuals/task-delivery/guide.md',
    examples=(
        {},
        {"change": {"set_presets": {"reviewer": {"runtime": "codex", "model": "review-model"}}}},
        {"change": {"add_edges": [{"parent": "team_leader", "child": "reviewer"}]}},
        {"change": {"set_presets": {"coding_team.engineer": {
            "system_prompt": "Check the accepted specification before changing source."}}}},
    ),
)


def read_reports(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Read retained project development reports under the verified caller identity."""
    return ToolResult(read_session_reports(_string_argument(arguments, 'alias'), cwd or Path.cwd()))


register_tool('session_reports', "Read project Session reports and retained result submissions without changing authorship or control.",
              _ALIAS_SCHEMA, read_reports, manual_ref='manuals/task-delivery/guide.md')


def submit_report(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Submit the current Session's assigned report through the shared operation."""
    return ToolResult(submit_session_report(_string_argument(arguments, 'name'),
                                           _string_argument(arguments, 'text'), cwd or Path.cwd(),
                                           notify_parent=_boolean_argument(arguments, 'notify_parent')))


register_tool('submit_report', 'Write your own assigned report by filename (for example report.md). '
              'Set notify_parent to also notify your direct parent, continuing its turn.',
              {'type': 'object', 'properties': {
                  'name': {'type': 'string'}, 'text': {'type': 'string'},
                  'notify_parent': {'type': 'boolean', 'default': False,
                                    'description': 'Notify your direct parent of the written report, '
                                                   'which it reads through session_reports; the result '
                                                   'carries the delivery receipt.'},
              }, 'required': ['name', 'text'], 'additionalProperties': False}, submit_report,
              manual_ref='manuals/task-delivery/guide.md')


def submit_result(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Submit a versioned result using the authenticated Session context."""
    from graphtraj.execution.runner_results import submit_session_result

    if set(arguments) - {'commit', 'result_refs', 'evidence_refs', 'completion', 'unresolved'}:
        raise ValueError('Unknown result submission fields.')
    return ToolResult(submit_session_result(
        _string_argument(arguments, 'commit'),
        _string_list_argument(arguments, 'result_refs'),
        _string_list_argument(arguments, 'evidence_refs'),
        _string_argument(arguments, 'completion'),
        _string_list_argument(arguments, 'unresolved'),
        cwd or Path.cwd(),
    ))


register_tool('submit_result',
              'Submit your committed task result and retain its evidence. Equivalent to agent-runner submit-result.',
              {'type': 'object', 'properties': {
                  'commit': {'type': 'string'},
                  'result_refs': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}},
                  'evidence_refs': {'type': 'array', 'items': {'type': 'string'}},
                  'completion': {'type': 'string'},
                  'unresolved': {'type': 'array', 'items': {'type': 'string'}},
              }, 'required': ['commit', 'result_refs', 'completion'], 'additionalProperties': False},
              submit_result, manual_ref='manuals/task-delivery/guide.md',
              examples=({
                  'commit':      '<committed-result-version>',
                  'result_refs': ['summary.md'],
                  'completion':  'The cited summary and related-paper links are complete.',
              },))


def decide_result(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Accept or reject an identified submission as its authorized caller."""
    from graphtraj.execution.runner_results import decide_session_result

    if set(arguments) - {'submission_id', 'commit', 'decision', 'reason', 'evidence_refs'}:
        raise ValueError('Unknown result decision fields.')
    return ToolResult(decide_session_result(
        _string_argument(arguments, 'submission_id'),
        _string_argument(arguments, 'commit'),
        _string_argument(arguments, 'decision'),
        _string_argument(arguments, 'reason'),
        _string_list_argument(arguments, 'evidence_refs'), cwd or Path.cwd(),
    ))


register_tool('decide_result',
              'Accept or reject a submitted result with reasons and evidence. Equivalent to agent-runner decide-result.',
              {'type': 'object', 'properties': {
                  'submission_id': {'type': 'string'}, 'commit': {'type': 'string'},
                  'decision': {'type': 'string', 'enum': ['accepted', 'rejected']},
                  'reason': {'type': 'string'},
                  'evidence_refs': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}},
              }, 'required': ['submission_id', 'commit', 'decision', 'reason', 'evidence_refs'],
               'additionalProperties': False}, decide_result,
              manual_ref='manuals/task-delivery/guide.md')


def retain_evidence(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Retain untracked Worktree files for an existing submission as its owner."""
    from graphtraj.execution.runner_results import retain_submission_evidence

    if set(arguments) - {'submission_id', 'evidence_refs'}:
        raise ValueError('Unknown retained evidence fields.')
    return ToolResult(retain_submission_evidence(
        _string_argument(arguments, 'submission_id'),
        _string_list_argument(arguments, 'evidence_refs'), cwd or Path.cwd(),
    ))


register_tool('retain_evidence',
              'Retain untracked files still only in the submitting member\'s Worktree for an existing '
              'result submission, without another submission or decision. Only the member\'s direct '
              'owner may call it; session_reports then lists the retained copies.',
              {'type': 'object', 'properties': {
                  'submission_id': {'type': 'string'},
                  'evidence_refs': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'},
                                    'description': 'Paths relative to the submitting member\'s Worktree.'},
              }, 'required': ['submission_id', 'evidence_refs'], 'additionalProperties': False},
              retain_evidence, manual_ref='manuals/task-delivery/guide.md')



def replace_session_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Replace a stopped member using the existing real-caller authorization."""
    from graphtraj.teams.team_replacement import replace_session

    result = replace_session(
        _string_argument(arguments, "alias"),
        _optional_string_argument(arguments, "actor"),
        _string_list_argument(arguments, "caused_by_event_ids"),
        cwd or Path.cwd(),
    )
    return ToolResult(result, failed="error" in result)


def cleanup_task_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Return the existing cleanup result without changing its safety checks."""
    from graphtraj.execution.runner_cleanup import cleanup_task

    response = cleanup_task(cwd or Path.cwd(), _string_argument(arguments, "task_id"))
    return ToolResult(response.document, failed=not response.succeeded)


def run_codex_main(
    arguments: Mapping[str, Any],
    *,
    cwd: Path | None = None,
    execute: Callable[[Path, str, str | None], dict[str, Any]] | None = None,
) -> ToolResult:
    """Run Codex Main through the host's native request/response transport.

    The executor is supplied by the host, never by operation arguments. The
    CLI owns stdin replies, cancellation, and the existing run_main binding.
    """
    from graphtraj.execution.runner_models import RunnerError

    if execute is None:
        raise RunnerError("unsupported-operation", "Codex Main requires agent-runner main.")
    return ToolResult(execute(
        cwd or Path.cwd(),
        _string_argument(arguments, "instruction"),
        _optional_string_argument(arguments, "resume"),
    ))


register_tool(
    "replace",
    "Replace one stopped actual member while preserving its Team and evidence. "
    "The recorded direct parent or native user approval authorizes replacement. "
    "The target and all descendants must already be stopped.",
    {
        "type": "object",
        "properties": {
            "alias": {"type": "string"},
            "actor": {"type": ["string", "null"], "enum": ["main", "user", None],
                      "description": "Retained caller label; this option grants no replacement authority."},
            "caused_by_event_ids": {"type": "array", "minItems": 1,
                                    "items": {"type": "string"}},
        },
        "required": ["alias", "caused_by_event_ids"],
        "additionalProperties": False,
    },
    replace_session_execution,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "cleanup",
    "Clean up one safely integrated task by stable identity.",
    {"type": "object", "properties": {"task_id": {"type": "string"}},
     "required": ["task_id"], "additionalProperties": False},
    cleanup_task_execution,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "main",
    "Run an isolated Main turn using the user's native Runtime settings. Codex only; "
    "agent-runner main supplies native requests on stderr and replies on stdin.",
    {"type": "object", "properties": {
        "instruction": {"type": "string"},
        "resume": {"type": ["string", "null"],
                   "description": "Main record returned by a previous completed invocation."},
    }, "required": ["instruction"], "additionalProperties": False},
    run_codex_main,
    manual_ref="manuals/task-delivery/guide.md",
)


def run_agents(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Run the independent ``agents`` function for the caller already bound here."""
    from graphtraj.interfaces.agents import run_agents_feature

    return run_agents_feature(arguments, cwd=cwd)


def _agents_row() -> tuple[str, str, dict[str, Any]]:
    """Reuse the independent function's own name, description and schema."""
    from agent_swarm import tool_descriptor

    descriptor = tool_descriptor()
    return descriptor["name"], descriptor["description"], descriptor["input_schema"]


# No delivered method guide describes agents; its own description is the reference.
register_tool(*_agents_row(), run_agents)


# CLI names and decoding are presentation metadata, not another parameter schema.
# Unlisted parameters use their Python name and Click's existing scalar/repeated form.
# The JSON list is the CLI form; the hidden repeated singular flag stays
# accepted for existing callers but is not documented.
_CAUSED_BY = {"caused_by_event_ids": ("caused_by_event_ids", "json"),
              "legacy_caused_by_event_ids": ("caused_by_event_ids", "value")}
_CLI = {
    "task_graph": (("graphtraj", "task", "graph"), {}),
    "task_members": (("graphtraj", "task", "members"), {}),
    "task_register": (("graphtraj", "task", "register"), {"task_file": ("", "yaml")}),
    "task_revise": (("graphtraj", "task", "revise"), {"revision_file": ("", "yaml")}),
    "task_complete": (("graphtraj", "task", "complete"), {"completion_file": ("", "yaml")}),
    "task_update": (("graphtraj", "task", "update"), {"state_file": ("", "yaml")}),
    "task_backup": (("graphtraj", "task", "backup"), {}),
    "project_setup": (("graphtraj", "setup"), {}),
    "project_doctor": (("graphtraj", "doctor"), {}),
    "worldline_append": (("graphtraj", "worldline", "append"), {"event_file": ("event", "yaml")}),
    "worldline_read": (("graphtraj", "worldline", "read"), {}),
    "worldline_render": (("graphtraj", "worldline", "render"), {}),
    "delivery_state_apply": (("graphtraj", "delivery-state", "apply"), {
        "request_file": ("request", "yaml"), "facts_file": ("facts", "yaml"),
    }),
    "task_integrate": (("graphtraj", "task", "integrate"), {"role": ("role", "yaml-value")}),
    "parent_status": (("agent-runner", "parent-status"), {}),
    "swarm": (("agent-runner", "--swarm-input"), {"swarm_input": ("", "yaml")}),
    "approved_recovery": (("agent-runner", "recover"), _CAUSED_BY),
    "continue": (("agent-runner", "continue"), _CAUSED_BY),
    "session_reports": (("agent-runner", "reports"), {}),
    "submit_report": (("agent-runner", "submit-report"), {}),
    "submit_result": (("agent-runner", "submit-result"), {}),
    "decide_result": (("agent-runner", "decide-result"), {}),
    "retain_evidence": (("agent-runner", "retain-evidence"), {}),
    "replace": (("agent-runner", "replace"), _CAUSED_BY),
    "runtime_connections": (("graphtraj", "connections"), {"catalog_file": ("catalog", "yaml")}),
    "role_organization": (("graphtraj", "roles", "organize"), {"change_file": ("change", "yaml")}),
    "cleanup": (("agent-runner", "cleanup"), {}),
    "main": (("agent-runner", "main"), {"instruction_file": ("instruction", "text")}),
}
for _name, (_path, _parameters) in _CLI.items():
    TOOLS[_name] = replace(TOOLS[_name], cli_path=_path, cli_parameters=_parameters)



def bind_main_finalize(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Bind the root caller's actual host without accepting model identity fields."""
    from graphtraj.execution.main_finalize import bind_main_finalize as bind

    return ToolResult(bind(_string_argument(arguments, 'summary_issue'), cwd or Path.cwd(),
                           paused=arguments.get('paused')))


register_tool(
    'bind_main_finalize',
    'Bind Main completion checking to the current host and return its hook configuration.',
    {'type': 'object', 'properties': {
        'summary_issue': {'type': 'string'},
        'paused': {'type': 'boolean', 'description':
                   'Record an explicit user pause or resume of implementation; omit to retain it. '
                   'Only the owning Main may change it. Notifications never resume paused work.'},
     }, 'required': ['summary_issue'], 'additionalProperties': False},
    bind_main_finalize,
    manual_ref="manuals/task-delivery/guide.md",
)
TOOLS['bind_main_finalize'] = replace(
    TOOLS['bind_main_finalize'], cli_path=('graphtraj', 'bind-finalize'),
)


# Method-only features carry the guide's own frontmatter description and no
# executable action. Their identifiers are the delivered guide directory names,
# so the registry stays the only catalog of feature identifiers.
METHOD_FEATURES = (
    ("setup-project", "Establish a project's GraphTraj paths, task tracker, available "
     "execution resources and shared conventions while preserving existing choices."),
    ("task-breakdown", "Break an agreed goal into independently verifiable tasks, "
     "recursively sizing them for available resources and connecting the results each "
     "task needs."),
    ("task-delivery", "Coordinate accepted tasks through dispatch, result submission, "
     "acceptance, integration and recovery."),
    ("research", "Investigate a factual question across relevant primary sources and "
     "deliver an evidence-based answer with citations, limitations and unresolved "
     "uncertainty."),
    ("concept-clarification", "Clarify ambiguous terminology, concept boundaries and "
     "relationships using concrete scenarios and the project's accepted meanings. Use "
     "when shared understanding needs to change or become explicit."),
)

METHOD_FEATURE_NAMES = tuple(name for name, _ in METHOD_FEATURES)

for _feature, _description in METHOD_FEATURES:
    register_tool(
        _feature,
        _description,
        _EMPTY_SCHEMA,
        None,
        manual_ref="manuals/{0}/guide.md".format(_feature),
    )
