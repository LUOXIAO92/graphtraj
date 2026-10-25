"""The registrable ``agents`` function: description, validation and dispatch.

A host registers :func:`tool_descriptor` as one model-callable function and
binds :func:`bind` to the caller it has already verified and to a control
backend. The model supplies only the request object; it never names its own
identity, permissions, working directory or task context.

This module imports nothing from GraphTraj. Task, Team, Round, Worldline,
budget, report and Worktree policy stay with the consumer, which applies them
before or after calling the bound function.

Return and wait boundary
------------------------
``create`` returns as soon as the backend has registered the Agent and its
reference; it never waits for the Agent's work. Only ``wait`` blocks, and only
for the explicit positive finite ``timeout_seconds`` it carries. No other
action carries or implies a wait. A host whose transport has its own deadline
checks it at that host's registration.

Result document
---------------
Every successful call returns::

    {"action": ..., "agent": ..., "session": ..., "execution": ...,
     "message": ..., "result": {...}}

where the four references are the backend's stable identifiers or ``None``.
A rejection returns ``{"action": ..., "error": {"code": ..., "message": ...}}``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from agent_swarm.schema import validate


TOOL_NAME = "agents"

# Required and optional fields of each action. Identity and authority come
# from the host binding, so no action accepts them.
ACTION_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "create":    (frozenset({"runtime", "instruction"}), frozenset({"name", "configuration"})),
    "send":      (frozenset({"agent", "message"}), frozenset({"reports_only"})),
    "status":    (frozenset(), frozenset({"agent"})),
    "wait":      (frozenset({"agent", "timeout_seconds"}), frozenset()),
    "interrupt": (frozenset({"agent"}), frozenset()),
    "resume":    (frozenset({"agent"}), frozenset({"message"})),
    "requests":  (frozenset({"agent"}), frozenset({"execution"})),
    "reply":     (frozenset({"agent", "request", "response"}), frozenset()),
    "retire":    (frozenset({"agent"}), frozenset()),
}

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTION_FIELDS)},
        "agent": {"type": "string",
                  "description": "Target Agent reference returned by create or status."},
        "runtime": {"type": "string", "description": "Runtime that executes the new Agent."},
        "configuration": {"type": "string",
                          "description": "Existing execution configuration reference resolved by the Runtime driver; grants no identity."},
        "instruction": {"type": "string", "description": "First message for the new Agent."},
        "name": {"type": "string", "description": "Readable name; grants no identity."},
        "message": {"type": "string", "description": "Plain-text message for the Agent."},
        "reports_only": {"type": "boolean",
                         "description": "Direct parent only: ask a stopped Task member for reports it "
                                        "already holds; it starts no new work."},
        "timeout_seconds": {"type": "number",
                            "description": "Explicit finite wait in seconds, above 0."},
        "execution": {"type": "string",
                      "description": "Reject requests from a different execution."},
        "request": {"type": "object", "description": "One request document returned by requests."},
        "response": {"type": "object", "description": "Explicit native response object."},
    },
    "required": ["action"],
    "additionalProperties": False,
}

TOOL_DESCRIPTION = (
    "Create child Agents on a Runtime and communicate with them. Actions: create "
    "(returns the new Agent reference without waiting for its work), send, status "
    "(omit agent for your visible hierarchy), wait (explicit finite timeout_seconds), "
    "interrupt (in standby, the direct parent confirms an ended execution whose "
    "recorded processes are verified gone), resume, requests and reply for native "
    "approval or input requests, and retire. Your identity comes from the host."
)


class AgentsError(Exception):
    """A backend or contract rejection with a stable code and readable message."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code machine-readable and the message for the model."""
        super().__init__(message)
        self.code    = code
        self.message = message


@dataclass(frozen=True)
class Caller:
    """The calling Agent as verified by the host, never by model arguments.

    ``host`` names the registration path that verified the caller, for example
    ``"codex-dynamic-tools"``. ``agent`` is the caller's Agent reference, or
    ``None`` for a root caller with no recorded Agent; having no reference
    grants no root authority by itself.
    """

    host: str
    agent: str | None
    session: str | None = None
    runtime: str | None = None


class SessionArchive(Protocol):
    """Optional normalized Session archive used by the control backend.

    Archiving is off unless an archive is bound. The archive receives an
    already-verified Session header and native-ordered records from the
    Runtime adapter; it does not order, scan or collect by itself. These
    methods match the current ``SessionArchive`` implementation, which keeps
    ``JsonlSessionStore`` and ``ArchiveStream`` underneath.
    """

    def map_session(self, header: dict) -> None:
        """Allow collection for one verified Session header."""

    def collect(
        self,
        session_id: str,
        events: list[dict],
        *,
        source: str,
        position: int,
        historical: bool = False,
    ) -> bool:
        """Publish native-ordered events; return whether anything was saved."""

    def checkpoint(
        self,
        session_id: str,
        event: dict,
        *,
        source: str,
        position: int,
    ) -> bool:
        """Save current partial content; return whether it was saved."""


@dataclass(frozen=True)
class Binding:
    """Host-owned context for one bound function: verified caller and archive."""

    caller: Caller
    archive: SessionArchive | None = None


@dataclass(frozen=True)
class Outcome:
    """A backend's answer: stable references plus its readable result fields."""

    result: dict[str, Any] = field(default_factory=dict)
    agent: str | None = None
    session: str | None = None
    execution: str | None = None
    message: str | None = None
    failed: bool = False


class Backend(Protocol):
    """Control implementation that performs one validated action.

    ``arguments`` holds only the action's own fields. ``create`` must return
    once the Agent is registered; ``wait`` must return within
    ``timeout_seconds``. Rejections raise :class:`AgentsError`.
    """

    def operate(self, action: str, arguments: Mapping[str, Any], binding: Binding) -> Outcome:
        """Perform one action for the bound caller."""


@dataclass(frozen=True)
class AgentsResult:
    """One call's structured document and whether it failed."""

    document: dict[str, Any]
    failed: bool = False


def tool_descriptor() -> dict[str, Any]:
    """Return the function description a host registers as ``agents``."""
    return {
        "name":         TOOL_NAME,
        "description":  TOOL_DESCRIPTION,
        "input_schema": INPUT_SCHEMA,
    }


def unavailable(action: str, missing: str) -> AgentsError:
    """Name a control capability the backend does not provide yet.

    ``missing`` states the concrete missing step so callers see the gap
    instead of a silent fallback to another entry.
    """
    return AgentsError("not-implemented", f"{action} is not available: {missing}")


def validate_request(request: Any) -> tuple[str, dict[str, Any]]:
    """Check one model request and return its action and own arguments.

    Raises
    ------
    AgentsError
        With code ``invalid-input`` naming the first offending field.
    """
    try:
        validate(request, INPUT_SCHEMA, "request")
    except ValueError as error:
        raise AgentsError("invalid-input", str(error)) from None

    action              = request["action"]
    required, optional  = ACTION_FIELDS[action]
    arguments           = {name: value for name, value in request.items() if name != "action"}

    for name in sorted(arguments.keys() - required - optional):
        raise AgentsError("invalid-input", f"request.{name}: not valid for {action}")
    for name in sorted(required - arguments.keys()):
        raise AgentsError("invalid-input", f"request.{name}: required")
    for name, value in arguments.items():
        if isinstance(value, str) and not value.strip():
            raise AgentsError("invalid-input", f"request.{name}: must not be empty")

    if action == "wait":
        timeout = arguments["timeout_seconds"]
        if not (math.isfinite(timeout) and timeout > 0):
            raise AgentsError("invalid-input", "request.timeout_seconds: must be finite and above 0")
    return action, arguments


def bind(
    backend: Backend,
    caller: Caller,
    *,
    archive: SessionArchive | None = None,
) -> Any:
    """Return the ``agents`` callback for one host-verified caller.

    Parameters
    ----------
    backend
        Control implementation performing validated actions.
    caller
        Identity the host verified at its own boundary.
    archive
        Optional normalized Session archive; ``None`` keeps archiving off.

    Returns
    -------
    Callable[[Any], AgentsResult]
        Takes only the model request object.
    """
    if not isinstance(caller, Caller) or not isinstance(caller.host, str) or not caller.host:
        raise TypeError("The host must supply its verified Caller.")
    binding = Binding(caller, archive)

    def call(request: Any) -> AgentsResult:
        """Validate, dispatch and shape one model request."""
        action = request.get("action") if isinstance(request, dict) else None
        try:
            action, arguments = validate_request(request)
            outcome           = backend.operate(action, arguments, binding)
        except AgentsError as error:
            return AgentsResult(
                {"action": action, "error": {"code": error.code, "message": error.message}},
                failed=True,
            )
        return AgentsResult({
            "action":    action,
            "agent":     outcome.agent,
            "session":   outcome.session,
            "execution": outcome.execution,
            "message":   outcome.message,
            "result":    dict(outcome.result),
        }, failed=outcome.failed)

    return call
