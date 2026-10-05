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
    interrupt_session,
    pending_requests,
    reply_to_request,
    read_session_reports,
    submit_session_report,
    send_instruction,
)
from graphtraj.execution.runner_launch import launch_swarm, launch_swarm_file
from graphtraj.execution.runner_status import status_aliases, status_tree
from graphtraj.graph.delivery_state import apply_delivery_state_request
from graphtraj.graph.delivery_worldline import (
    append_project_worldline_event,
    read_worldline,
)
from graphtraj.graph.ticket_graph import (
    read_graph,
    register_ticket,
    revise_tickets,
    update_ticket_state,
)
from graphtraj.teams.ticket_integration import integrate_ticket
from graphtraj.workspace.git_repository import GitRepositoryError
from graphtraj.workspace.project_initialization import (
    ProjectSetupError,
    existing_source_repository,
    plan_project_setup,
    require_source_repository,
)

_ISSUE_PROPERTIES = {
    "ticket_id":         {"type": "string"},
    "ticket_name":       {"type": "string"},
    "source":            {"type": "string"},
    "title":             {"type": "string"},
    "body":              {"type": "string"},
    "dependencies":      {"type": "array", "items": {"type": "string"}},
}
_ISSUE_SCHEMA = {
    "type":                 "object",
    "properties":           _ISSUE_PROPERTIES,
    "required":             sorted(_ISSUE_PROPERTIES),
    "additionalProperties": False,
}
_REVISED_TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        **_ISSUE_PROPERTIES,
        "active":      {"type": "boolean"},
        "replaced_by": {"type": "array", "items": {"type": "string"}},
    },
    "required":             sorted({*_ISSUE_PROPERTIES, "active", "replaced_by"}),
    "additionalProperties": False,
}
_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "product_preserving":  {"const": True},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_refs":       {
            "type": "array", "minItems": 1, "items": {"type": "string"},
        },
        "tickets":             {
            "type": "array", "minItems": 1, "items": _REVISED_TICKET_SCHEMA,
        },
    },
    "required":             [
        "product_preserving", "caused_by_event_ids", "evidence_refs", "tickets",
    ],
    "additionalProperties": False,
}
_STATE_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id":           {"type": "string"},
        "status":              {"type": "string"},
        "active_team_ordinal": {"type": ["integer", "null"]},
        "worktree":            {"type": ["string", "null"]},
        "branch":              {"type": ["string", "null"]},
        "current_candidate":   {"type": ["string", "null"]},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_refs":       {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "ticket_id", "status", "active_team_ordinal", "worktree", "branch",
        "current_candidate", "caused_by_event_ids", "evidence_refs",
    ],
    "additionalProperties": False,
}
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
        "ticket_id":   {"type": "string"},
        "ticket_name": {"type": "string"},
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
_SEND_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":               {"type": "string"},
        "instruction":         {"type": "string"},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "reports_only":        {"type": "boolean", "default": False,
                                "description": "Collect existing reports without sampling the Ticket budget."},
    },
    "required":             ["alias", "instruction"],
    "additionalProperties": False,
}
_CONTINUE_SCHEMA = {
    "type": "object",
    "properties": {
        "ticket_id":           {"type": "string"},
        "caused_by_event_ids": {"type": "array", "items": {"type": "string"}},
        "budget_only":         {"type": "boolean", "default": False,
                                "description": "Restore budget permission without executing old Sessions."},
    },
    "required":             ["ticket_id", "caused_by_event_ids"],
    "additionalProperties": False,
}
_REQUESTS_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":        {"type": "string"},
        "execution_id": {"type": ["string", "null"],
                         "description": "Reject a mapping that has moved to another execution."},
    },
    "required":             ["alias"],
    "additionalProperties": False,
}
_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "alias":    {"type": "string"},
        "request":  {"type": "object"},
        "response": {"type": "object", "description": "Explicit native response as a JSON object."},
    },
    "required":             ["alias", "request", "response"],
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
        "ticket_id":          {"type": "string"},
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
    "required":             ["ticket_id", "validation_command"],
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
    """Return the current Ticket DAG and readiness view for the project."""

    configuration = load_project_configuration(cwd or Path.cwd())
    return ToolResult(read_graph(configuration.state))


def register_current_ticket(arguments: Mapping[str, Any]) -> ToolResult:
    """Register one accepted Ticket definition in the project graph."""

    configuration = load_project_configuration(Path.cwd())
    directory = register_ticket(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult({"ticket_directory": str(directory)})


def revise_current_tickets(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one validated product-preserving Task Graph revision."""

    configuration = load_project_configuration(Path.cwd())
    recorded = revise_tickets(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult(recorded)


def update_current_ticket_state(arguments: Mapping[str, Any]) -> ToolResult:
    """Apply one evidence-backed current Ticket state transition."""

    configuration = load_project_configuration(Path.cwd())
    recorded = update_ticket_state(
        configuration.state, configuration.harness_root, arguments
    )
    return ToolResult(recorded)


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


def integrate_current_ticket(
    arguments: Mapping[str, Any], *, cwd: Path | None = None
) -> ToolResult:
    """Merge or recover an accepted Ticket under its actual task authority."""

    validation_command = arguments.get("validation_command")
    if not isinstance(validation_command, list) or any(
        not isinstance(argument, str) for argument in validation_command
    ):
        raise ValueError("validation_command must be a list of strings")
    try:
        configuration = load_project_configuration(cwd or Path.cwd())
        result = integrate_ticket(
            configuration,
            _string_argument(arguments, "ticket_id"),
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


def read_alias_status(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Report the requested Session aliases, or the visible Session tree."""

    aliases = arguments.get("aliases")
    operation_total = bool(arguments.get("operation_total", False))
    baseline = arguments.get("baseline")
    candidate = arguments.get("candidate")
    if aliases is None:
        response = status_tree(
            cwd or Path.cwd(),
            operation_total=operation_total,
            baseline=baseline,
            candidate=candidate,
        )
    else:
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) for alias in aliases
        ):
            raise ValueError("aliases must be a list of Session alias strings")
        response = status_aliases(
            aliases,
            cwd or Path.cwd(),
            operation_total=operation_total,
            baseline=baseline,
            candidate=candidate,
        )
    return ToolResult(response.document, failed=not response.succeeded)


def read_parent_status(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Observe only the caller root's recorded Runtime host parent."""
    from graphtraj.execution.parent_status import parent_status

    result = parent_status(cwd or Path.cwd(), arguments.get('timeout_seconds', 0))
    return ToolResult(result, failed=result['outcome'] in {'timeout', 'error'})


register_tool(
    'parent_status',
    'Read a root Agent\'s recorded owning host activity and latest turn metadata, optionally '
    'waiting a finite interval for native idle within the caller\'s remaining execution budget. '
    'No input is sent. Main cannot wait on itself.',
    {'type': 'object', 'properties': {
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

    The calling Session's Ticket and the registered Ticket state supply the
    identity each task does not repeat.
    """

    # The CLI retains the original file, including comments and formatting.
    response = (
        launch_swarm_file(input_file, cwd or Path.cwd())
        if input_file is not None
        else launch_swarm(dict(arguments), cwd or Path.cwd())
    )
    return ToolResult(response.document, failed=not response.succeeded)


def send_session_instruction(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Steer an active execution or continue an idle mapped Session.

    ``reports_only`` resumes the Session to return evidence it already holds
    without sampling the Ticket budget, so a report collection cannot repeat a
    sampled stop or deliver another stop instruction.
    """

    return ToolResult(
        send_instruction(
            _string_argument(arguments, "alias"),
            _string_argument(arguments, "instruction"),
            cwd or Path.cwd(),
            _string_list_argument(arguments, "caused_by_event_ids"),
            reports_only=_boolean_argument(arguments, "reports_only"),
        )
    )


def interrupt_session_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Stop a descendant subtree and return each member confirmation."""

    return ToolResult(
        interrupt_session(_string_argument(arguments, "alias"), cwd or Path.cwd())
    )


def continue_ticket_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Restore task budget permission, optionally without executing old Sessions."""

    from graphtraj.teams.team_round import continue_stopped_ticket

    return ToolResult(
        continue_stopped_ticket(
            _string_argument(arguments, "ticket_id"),
            _string_list_argument(arguments, "caused_by_event_ids"),
            cwd or Path.cwd(),
            budget_only=_boolean_argument(arguments, "budget_only"),
        )
    )


def read_pending_requests(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Query the mapped execution's native requests without consuming them."""

    return ToolResult(
        pending_requests(
            _string_argument(arguments, "alias"),
            cwd or Path.cwd(),
            execution_id=_optional_string_argument(arguments, "execution_id"),
        )
    )


def answer_pending_request(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Submit an explicit reply to one request returned by the query path."""

    request = arguments.get("request")
    response = arguments.get("response")
    if not isinstance(request, dict) or not isinstance(response, dict):
        raise ValueError("request and response must be JSON objects")
    return ToolResult(
        reply_to_request(
            _string_argument(arguments, "alias"), request, response, cwd or Path.cwd()
        )
    )


register_tool(
    "ticket_graph",
    "Read the current Ticket DAG, states and dependency readiness for the project "
    "in the server working directory. Equivalent to `graphtraj ticket graph`.",
    _EMPTY_SCHEMA,
    read_current_graph,
    manual_ref="manuals/task-breakdown/guide.md",
    examples=({},),
)
register_tool(
    "ticket_register",
    "Register one accepted Ticket definition with its dependencies. Equivalent to "
    "`graphtraj ticket register --ticket-file`.",
    _ISSUE_SCHEMA,
    register_current_ticket,
    manual_ref="manuals/task-breakdown/guide.md",
    examples=(
        {
            "ticket_id":    "paper-1",
            "ticket_name":  "paper-summary",
            "source":       "local:paper-1",
            "title":        "Summarize the first paper",
            "body":         "Read the paper and deliver a cited summary with links to related papers.",
            "dependencies": [],
        },
    ),
)
register_tool(
    "ticket_revise",
    "Apply one validated product-preserving Ticket graph revision and return its "
    "recorded causal event. Equivalent to `graphtraj ticket revise`.",
    _REVISION_SCHEMA,
    revise_current_tickets,
    manual_ref="manuals/task-breakdown/guide.md",
)
register_tool(
    "ticket_update",
    "Apply one evidence-backed Ticket state transition and return its recorded "
    "causal event. Equivalent to `graphtraj ticket update`.",
    _STATE_CHANGE_SCHEMA,
    update_current_ticket_state,
    manual_ref="manuals/task-delivery/guide.md",
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
    "ticket_integrate",
    "Merge or recover an accepted Ticket under its actual task authority. "
    "Equivalent to `graphtraj ticket integrate`.",
    _INTEGRATE_SCHEMA,
    integrate_current_ticket,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "alias_status",
    "Read the explicitly supplied Session aliases, including their Runtime "
    "activity and last outcome, or omit `aliases` for the Session tree this "
    "caller may see. Equivalent to `agent-runner status`.",
    {
        "type": "object",
        "properties": {
            "aliases":         {"type": "array", "items": {"type": "string"}},
            "operation_total": {"type": "boolean", "default": False,
                                "description": "Report native tool requests once by native identifier."},
            "baseline":        {"type": ["string", "null"]},
            "candidate":       {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    },
    read_alias_status,
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
    "send_instruction",
    "Steer an active execution or continue an idle mapped Session using unique "
    "causal Project Worldline event IDs. Equivalent to `agent-runner send`.",
    _SEND_SCHEMA,
    send_session_instruction,
    manual_ref="manuals/task-delivery/guide.md",
    examples=(
        {
            "alias":       "<returned-agent-alias>",
            "instruction": "Preserve the completed summary and include the source links.",
        },
    ),
)
register_tool(
    "interrupt",
    "Stop a descendant subtree and prevent further work while preserving its "
    "Sessions. Returns each member confirmation. Equivalent to `agent-runner interrupt`.",
    _ALIAS_SCHEMA,
    interrupt_session_execution,
    manual_ref="manuals/task-delivery/guide.md",
)
register_tool(
    "continue",
    "Restore a sampled stopped task budget and resume original roots by default; "
    "budget_only leaves old Sessions stopped for a later ordinary swarm dispatch. Equivalent to "
    "`agent-runner continue`.",
    _CONTINUE_SCHEMA,
    continue_ticket_execution,
    manual_ref="manuals/task-delivery/guide.md",
    examples=(
        {
            "ticket_id":           "paper-1",
            "caused_by_event_ids": ["<actual-authorization-event-id>"],
            "budget_only":         True,
        },
    ),
)
register_tool(
    "pending_requests",
    "Query the mapped execution's pending native approval or user-input requests, "
    "including the identity required to reply. Equivalent to `agent-runner "
    "requests`.",
    _REQUESTS_SCHEMA,
    read_pending_requests,
    manual_ref="manuals/task-delivery/guide.md",
    examples=(
        {"alias": "<returned-agent-alias>"},
    ),
)
register_tool(
    "reply_to_request",
    "Return the explicit native reply for one request document obtained from "
    "`pending_requests`. Equivalent to `agent-runner reply`.",
    _REPLY_SCHEMA,
    answer_pending_request,
    manual_ref="manuals/task-delivery/guide.md",
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
        'restore_active': {'type': 'boolean', 'description': 'Correct Ticket/Team administrative state and reopen the same Round for authorized work.'},
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
    'text. Pi and DSH deliver only the system prompt layer; Codex delivers '
    '`system_prompt` as base instructions and `developer_prompt` as developer '
    'instructions. Content for a layer the selected Runtime does not expose is '
    'refused at launch instead of being passed as task text. Equivalent to '
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
    """Read the declared reports of an authorized direct child."""
    return ToolResult(read_session_reports(_string_argument(arguments, 'alias'), cwd or Path.cwd()))


register_tool('session_reports', "Read your or your direct child's reports and retained result submissions.",
              _ALIAS_SCHEMA, read_reports, manual_ref='manuals/task-delivery/guide.md')


def submit_report(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Submit the current Session's assigned report through the shared operation."""
    return ToolResult(submit_session_report(_string_argument(arguments, 'name'),
                                           _string_argument(arguments, 'text'), cwd or Path.cwd()))


register_tool('submit_report', 'Write your own assigned report by filename (for example report.md).',
              {'type': 'object', 'properties': {'name': {'type': 'string'}, 'text': {'type': 'string'}},
               'required': ['name', 'text'], 'additionalProperties': False}, submit_report,
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


def retire_session_execution(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Retire a stopped subtree's target, preserving its Session and Worktree."""
    from graphtraj.execution.runner_retirement import retire_session

    return ToolResult(retire_session(_string_argument(arguments, "alias"), cwd or Path.cwd()))


def cleanup_ticket_execution(
    arguments: Mapping[str, Any], *, cwd: Path | None = None,
) -> ToolResult:
    """Return the existing cleanup result without changing its safety checks."""
    from graphtraj.execution.runner_cleanup import cleanup_ticket

    response = cleanup_ticket(cwd or Path.cwd(), _string_argument(arguments, "ticket_id"))
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
    "retire",
    "Retire one member after its entire subtree stops; preserve Sessions, evidence and Worktree.",
    {"type": "object", "properties": {"alias": {"type": "string"}},
     "required": ["alias"], "additionalProperties": False},
    retire_session_execution,
    manual_ref="manuals/task-delivery/guide.md",
)
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
    "Clean up one safely integrated ticket by stable identity.",
    {"type": "object", "properties": {"ticket_id": {"type": "string"}},
     "required": ["ticket_id"], "additionalProperties": False},
    cleanup_ticket_execution,
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


# CLI names and decoding are presentation metadata, not another parameter schema.
# Unlisted parameters use their Python name and Click's existing scalar/repeated form.
_CLI = {
    "ticket_graph": (("graphtraj", "ticket", "graph"), {}),
    "ticket_register": (("graphtraj", "ticket", "register"), {"ticket_file": ("", "yaml")}),
    "ticket_revise": (("graphtraj", "ticket", "revise"), {"revision_file": ("", "yaml")}),
    "ticket_update": (("graphtraj", "ticket", "update"), {"state_file": ("", "yaml")}),
    "project_setup": (("graphtraj", "setup"), {}),
    "project_doctor": (("graphtraj", "doctor"), {}),
    "worldline_append": (("graphtraj", "worldline", "append"), {"event_file": ("event", "yaml")}),
    "worldline_read": (("graphtraj", "worldline", "read"), {}),
    "worldline_render": (("graphtraj", "worldline", "render"), {}),
    "delivery_state_apply": (("graphtraj", "delivery-state", "apply"), {
        "request_file": ("request", "yaml"), "facts_file": ("facts", "yaml"),
    }),
    "ticket_integrate": (("graphtraj", "ticket", "integrate"), {"role": ("role", "yaml-value")}),
    "alias_status": (("agent-runner", "status"), {}),
    "parent_status": (("agent-runner", "parent-status"), {}),
    "swarm": (("agent-runner", "--swarm-input"), {"swarm_input": ("", "yaml")}),
    "send_instruction": (("agent-runner", "send"), {"caused_by_event_id": ("caused_by_event_ids", "value")}),
    "interrupt": (("agent-runner", "interrupt"), {}),
    "approved_recovery": (("agent-runner", "recover"), {"caused_by_event_id": ("caused_by_event_ids", "value")}),
    "continue": (("agent-runner", "continue"), {"caused_by_event_id": ("caused_by_event_ids", "value")}),
    "pending_requests": (("agent-runner", "requests"), {}),
    "reply_to_request": (("agent-runner", "reply"), {
        "request_file": ("request", "yaml"), "response": ("response", "json"),
    }),
    "session_reports": (("agent-runner", "reports"), {}),
    "submit_report": (("agent-runner", "submit-report"), {}),
    "submit_result": (("agent-runner", "submit-result"), {}),
    "decide_result": (("agent-runner", "decide-result"), {}),
    "retire": (("agent-runner", "retire"), {}),
    "replace": (("agent-runner", "replace"), {"caused_by_event_id": ("caused_by_event_ids", "value")}),
    "role_organization": (("graphtraj", "roles", "organize"), {"change_file": ("change", "yaml")}),
    "cleanup": (("agent-runner", "cleanup"), {}),
    "main": (("agent-runner", "main"), {"instruction_file": ("instruction", "text")}),
}
for _name, (_path, _parameters) in _CLI.items():
    TOOLS[_name] = replace(TOOLS[_name], cli_path=_path, cli_parameters=_parameters)



def bind_main_finalize(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> ToolResult:
    """Bind the root caller's actual host without accepting model identity fields."""
    from graphtraj.execution.main_finalize import bind_main_finalize as bind

    return ToolResult(bind(_string_argument(arguments, 'summary_issue'), cwd or Path.cwd()))


register_tool(
    'bind_main_finalize',
    'Bind Main completion checking to the current host and return its hook configuration.',
    {'type': 'object', 'properties': {'summary_issue': {'type': 'string'}},
     'required': ['summary_issue'], 'additionalProperties': False},
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
