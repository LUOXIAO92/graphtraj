"""Shared approval rules: review decisions and parent replies.

Layer 4 (parent fallback) of the approval layers is the same for every
Runtime:

- :func:`parse_decision` reads one review decision document (``PUBLIC_API.md``
  section 6) strictly. Anything else is a failed review: the call is refused
  and goes to the direct parent. Only ``allow`` lets a call run.
- :func:`check_reply` is applied by ``AgentControl.reply`` before a parent's
  answer reaches any driver. A parent may decline anything and may approve
  at most what the request asked.

agents applies no safety rule of its own to the content of a request; see
section 6 for what safety rests on.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from agent_swarm.tool import AgentsError


DECISIONS = ("allow", "deny", "escalate")

# The method of a child's own decision or resource request (section 4).
DECISION_METHOD = "agents/decision"
DECISION_KINDS = ("decision", "resources")


def parse_decision(answer: Any) -> dict:
    """Return a reviewer's decision document, or the failed review it amounts to.

    ``answer`` is the reviewer's JSON text, or an already decoded object. The
    document must be exactly one object with ``decision`` (``allow``,
    ``deny`` or ``escalate``) and a non-empty ``reason``, nothing else. Any
    other shape is a failed review: ``{"decision": "escalate", "reason":
    "Failed review: ..."}``, which refuses the call and goes to the parent.
    """
    if isinstance(answer, (str, bytes, bytearray)):
        try:
            answer = json.loads(answer, object_pairs_hook=_unique, parse_constant=_constant)
        except ValueError as error:
            return review_failed(f"the answer is not one JSON object ({error})")
    if not isinstance(answer, dict):
        return review_failed("the answer is not a JSON object")
    if set(answer) != {"decision", "reason"}:
        return review_failed("the document must hold exactly decision and reason")
    decision, reason = answer["decision"], answer["reason"]
    if not isinstance(decision, str) or decision not in DECISIONS:
        return review_failed(f"decision must be one of {', '.join(DECISIONS)}")
    if not isinstance(reason, str) or not reason.strip():
        return review_failed("reason must be a non-empty string")
    return {"decision": decision, "reason": reason}


def review_failed(why: str) -> dict:
    """Return the decision of a review that failed (error, timeout or bad answer)."""
    return {"decision": "escalate", "reason": "Failed review: " + why}


def approves(request: Mapping[str, Any], response: Mapping[str, Any]) -> bool:
    """Whether a native response lets the requested operation proceed.

    Only explicit native refusals count as declining; any other answer is
    treated as releasing the request.
    """
    method = str(request.get("method") or "")
    if response.get("behavior") == "deny" or response.get("decision") in ("decline", "cancel", "reject"):
        return False
    if response.get("action") in ("decline", "cancel") or response.get("cancelled") is True:
        return False
    if response.get("confirmed") is False or response.get("success") is False:
        return False
    if method == "item/permissions/requestApproval" and response.get("permissions") == {}:
        return False
    return True


def exceeds(request: Mapping[str, Any], response: Mapping[str, Any]) -> str | None:
    """Return why an approving response grants more than the request asked.

    ``None`` when it grants at most the request. Checked per Runtime form:
    Claude may not substitute another tool input; Codex may approve only this
    one request (not the Session, not a policy amendment) and only the
    permissions requested; a Pi selection must be one of the offered options.
    """
    method = str(request.get("method") or "")
    params = request.get("params") if isinstance(request.get("params"), Mapping) else {}
    if method == "claude/can_use_tool":
        if "updatedInput" in response and response["updatedInput"] != params.get("input"):
            return "The reply replaces the requested tool input."
    elif method.endswith("/requestApproval") and method != "item/permissions/requestApproval":
        if "decision" in response and response["decision"] != "accept":
            return "The reply approves more than this one request; answer accept or decline."
    elif method == "item/permissions/requestApproval":
        if response.get("permissions") != params.get("permissions") or response.get("scope") not in (None, "turn"):
            return "The reply grants other permissions, or for longer, than the request asked."
    elif method == "pi/select":
        options = params.get("options")
        if "value" in response and isinstance(options, list) and response["value"] not in options:
            return "The reply selects a value the dialog did not offer."
    return None


def check_reply(request: Mapping[str, Any], response: Mapping[str, Any]) -> None:
    """Refuse a parent reply that releases more than the parent may.

    ``request`` is the pending request as the Runtime (or the child's own
    decision request) reported it, never the parent's copy. A declining reply
    always passes; an approving one that grants more than asked raises
    ``authority-denied``.
    A decision request takes exactly ``{"answer": "<non-empty text>"}``.
    """
    if request.get("method") == DECISION_METHOD:
        answer = response.get("answer")
        if set(response) != {"answer"} or not isinstance(answer, str) or not answer.strip():
            raise AgentsError("invalid-input", 'request.response: a decision request takes {"answer": "<text>"}')
        return
    if not approves(request, response):
        return
    excess = exceeds(request, response)
    if excess is not None:
        raise AgentsError("authority-denied", excess + " A parent releases at most what the request asked.")


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    """Decode one JSON object, refusing a repeated field."""
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"repeated field {key!r}")
        document[key] = value
    return document


def _constant(name: str) -> Any:
    """Refuse NaN and Infinity, which are not JSON."""
    raise ValueError(f"{name} is not JSON")
