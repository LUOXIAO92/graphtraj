"""Shared approval rules: review decisions, high-risk classes and parent replies.

Layer 4 (parent fallback) and layer 5 (high risk) of the approval layers are
the same for every Runtime:

- :func:`parse_decision` reads one review decision document (``PUBLIC_API.md``
  section 6) strictly. Anything else is a failed review: the call is refused
  and goes to the direct parent.
- :func:`decide` applies a decision to the native request it reviewed: only
  ``allow`` runs a call, and never one :func:`high_risk` matches.
- :func:`check_reply` is applied by ``AgentControl.reply`` before a parent's
  answer reaches any driver. A parent may decline anything; it may approve
  only what the request asked, and never a high-risk request.

High-risk class ``credential-egress``
-------------------------------------
The trust boundary is this machine: loopback destinations are inside, every
other host is outside. A request is high risk when its own content (the
command, tool input, arguments and reasons the Runtime reported) names both

1. a credential: a literal secret value (private key block, a token with a
   known issuer prefix, an ``Authorization`` header with a literal value), a
   credential file (SSH private keys, cloud, registry, Git and Runtime login
   files, ``.env`` files), an environment variable whose name marks a secret
   (``*TOKEN*``, ``*SECRET*``, ``*PASSWORD*``, ``*API_KEY*`` ...), or a dump
   of the whole environment piped onward; and
2. a destination outside the boundary: a URL with a non-loopback host, a
   remote ``host:path`` of ``scp``/``rsync``/``sftp``, a host argument of
   ``nc``/``ncat``/``netcat``/``telnet``/``ssh``, ``socat TCP:host:port`` or
   ``/dev/tcp/host/port``.

Limits: the match is textual on one request. It does not see a credential
assembled at run time, encoded, read by a script written earlier, or sent by a
program whose source is not in the request; it does not know a credential's
own issuer, so sending a key even to its issuer is refused; a request that
only names a remote alias (``git push origin``) has no visible destination.
An SSH identity file given with ``-i`` is not counted: it authenticates the
connection and is not sent.
It is a floor no layer can lower, not a substitute for the native sandbox.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Mapping

from agent_swarm.tool import AgentsError


DECISIONS = ("allow", "deny", "escalate")
HIGH_RISK = "high-risk"

# The method of a child's own decision or resource request (section 4).
DECISION_METHOD = "agents/decision"
DECISION_KINDS = ("decision", "resources")

# Identity fields of a request document; they carry no action content.
_IDENTITY = frozenset({"session", "execution_id", "execution", "request_id", "request_token",
                       "method", "high_risk"})

_SECRET_VALUES = (
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a token value", re.compile(r"\b(?:sk|rk)[-_][A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}"
                                 r"|\bgithub_pat_[A-Za-z0-9_]{20,}|\bxox[abposr]-[A-Za-z0-9-]{10,}"
                                 r"|\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}|\bglpat-[A-Za-z0-9_-]{20,}")),
    ("an Authorization header value", re.compile(
        r"(?i)\bauthorization:\s*(?:bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}")),
)
_SECRET_FILES = re.compile(
    r"\.ssh/(?:id_[\w.-]+|[\w.-]*key)\b|\.aws/credentials\b|\.netrc\b|\.git-credentials\b"
    r"|\.docker/config\.json\b|\.kube/config\b|\.npmrc\b|\.pypirc\b|gh/hosts\.yml\b"
    r"|\.config/gcloud/\S*credentials|\bauth\.json\b|\.credentials\.json\b"
    r"|(?:^|[\s/\"'=@<:])\.env(?:\.[\w-]+)*\b")
_SECRET_VARIABLES = re.compile(
    r"\$\{?(\w*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIAL)\w*)\}?",
    re.IGNORECASE)
_ENVIRONMENT_DUMP = re.compile(r"(?:^|[\s;&|(])(?:printenv|env)\s*(?:\||>)")

_URL = re.compile(r"\b(?:https?|ftps?|wss?|sftp|scp|smtp|telnet|ssh)://(?:[^/\s@\"']+@)?"
                  r"(\[[^\]\s]+\]|[^/\s:\"'?#]+)", re.IGNORECASE)
_REMOTE_COPY = re.compile(r"\b(?:scp|rsync|sftp)\b[^\n;|&]*?\s(?:[\w.-]+@)?([A-Za-z0-9][\w.-]*):\S*")
_HOST_ARGUMENT = re.compile(r"\b(?:nc|ncat|netcat|telnet|ssh)\s+(?:-\w+(?:\s+(?!-)\S+)?\s+)*(?:[\w.-]+@)?"
                            r"([A-Za-z0-9][\w.-]*)")
# An SSH identity file authenticates the connection; it is not sent.
_IDENTITY_OPTION = re.compile(r"(\b(?:ssh|scp|sftp)\b[^\n;|&]*?)\s-i\s*\S+")
_SOCKETS = re.compile(r"\bTCP\d?:([^:\s]+):\d+|/dev/(?:tcp|udp)/([^/\s]+)/\d+", re.IGNORECASE)


def parse_decision(answer: Any) -> dict:
    """Return a reviewer's decision document, or the failed review it amounts to.

    ``answer`` is the reviewer's JSON text, or an already decoded object. The
    document must be exactly one object with ``decision`` (``allow``,
    ``deny`` or ``escalate``), a non-empty ``reason`` and optionally
    ``category: high-risk``; ``high-risk`` turns any decision into ``deny``.
    Any other shape is a failed review: ``{"decision": "escalate", "reason":
    "Failed review: ..."}``, which refuses the call and goes to the parent.
    """
    if isinstance(answer, (str, bytes, bytearray)):
        try:
            answer = json.loads(answer, object_pairs_hook=_unique, parse_constant=_constant)
        except ValueError as error:
            return review_failed(f"the answer is not one JSON object ({error})")
    if not isinstance(answer, dict):
        return review_failed("the answer is not a JSON object")
    fields = set(answer)
    if not {"decision", "reason"} <= fields or fields - {"decision", "reason", "category"}:
        return review_failed("the document must hold decision, reason and optionally category, nothing else")
    decision, reason = answer["decision"], answer["reason"]
    if not isinstance(decision, str) or decision not in DECISIONS:
        return review_failed(f"decision must be one of {', '.join(DECISIONS)}")
    if not isinstance(reason, str) or not reason.strip():
        return review_failed("reason must be a non-empty string")
    if "category" in answer:
        if answer["category"] != HIGH_RISK:
            return review_failed(f"category may only be {HIGH_RISK}")
        return {"decision": "deny", "reason": reason, "category": HIGH_RISK}
    return {"decision": decision, "reason": reason}


def review_failed(why: str) -> dict:
    """Return the decision of a review that failed (error, timeout or bad answer)."""
    return {"decision": "escalate", "reason": "Failed review: " + why}


def decide(answer: Any, request: Mapping[str, Any]) -> dict:
    """Apply one review answer to the native request it reviewed.

    Returns the decision document. ``allow`` survives only for a request
    :func:`high_risk` does not match; every other result refuses the call now
    and hands it to the direct parent, which cannot release ``high-risk``.
    """
    decision = parse_decision(answer)
    risk = high_risk(request)
    if risk is not None:
        return {"decision": "deny", "reason": risk["reason"], "category": HIGH_RISK}
    return decision


def high_risk(request: Mapping[str, Any]) -> dict | None:
    """Return the high-risk class a native request falls in, or ``None``.

    The result is ``{"category": "high-risk", "class": "credential-egress",
    "reason": ...}``. The reason names the kind of credential and the
    destination, never the credential's value.
    """
    text = "\n".join(_strings({key: value for key, value in request.items() if key not in _IDENTITY}))
    credential = _credential(_IDENTITY_OPTION.sub(r"\1", text))
    destination = credential and _destination(text)
    if not destination:
        return None
    return {"category": HIGH_RISK, "class": "credential-egress",
            "reason": f"The request sends {credential} to {destination}, outside this machine; "
                      "no approval layer can release it."}


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
    always passes. An approving reply to a :func:`high_risk` request raises
    ``high-risk``; one that grants more than asked raises ``authority-denied``.
    A decision request takes exactly ``{"answer": "<non-empty text>"}``.
    """
    if request.get("method") == DECISION_METHOD:
        answer = response.get("answer")
        if set(response) != {"answer"} or not isinstance(answer, str) or not answer.strip():
            raise AgentsError("invalid-input", 'request.response: a decision request takes {"answer": "<text>"}')
        return
    if not approves(request, response):
        return
    risk = high_risk(request)
    if risk is not None:
        raise AgentsError(HIGH_RISK, risk["reason"] + " Decline it instead.")
    excess = exceeds(request, response)
    if excess is not None:
        raise AgentsError("authority-denied", excess + " A parent releases at most what the request asked.")


def _strings(value: Any) -> list[str]:
    """Return every string leaf of ``value``; a list of strings is one command line."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(item, str) for item in value):
            return [" ".join(value)]
        return [text for item in value for text in _strings(item)]
    return []


def _credential(text: str) -> str | None:
    """Name the first kind of credential ``text`` mentions, without its value."""
    for kind, pattern in _SECRET_VALUES:
        if pattern.search(text):
            return kind
    found = _SECRET_FILES.search(text)
    if found:
        return f"the credential file {found.group(0).strip(chr(32) + '/=@<' + chr(34) + chr(39))}"
    found = _SECRET_VARIABLES.search(text)
    if found:
        return f"the secret variable {found.group(1)}"
    if _ENVIRONMENT_DUMP.search(text):
        return "the whole environment"
    return None


def _destination(text: str) -> str | None:
    """Name the first destination outside this machine that ``text`` sends to."""
    hosts = [match.group(1) for match in _URL.finditer(text)]
    hosts += [match.group(1) for pattern in (_REMOTE_COPY, _HOST_ARGUMENT) for match in pattern.finditer(text)]
    hosts += [match.group(1) or match.group(2) for match in _SOCKETS.finditer(text)]
    for host in hosts:
        if not _loopback(host):
            return f"host {host}"
    return None


def _loopback(host: str) -> bool:
    """Whether ``host`` names this machine."""
    name = host.strip("[]").lower().rstrip(".")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


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
