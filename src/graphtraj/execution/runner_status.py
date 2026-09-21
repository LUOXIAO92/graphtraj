"""Alias-local observation for completed and active Runtime execution."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import yaml

from graphtraj.configuration.project_roles import ProjectRolesError
from graphtraj.workspace.git_repository import GitRepositoryError, SourceRepository
from graphtraj.execution.runner_models import RunnerError, StatusResponse
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_heartbeat import ownership_is_held, read_heartbeat
from graphtraj.execution.runner_process import process_ancestors
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, review_role_request
from graphtraj.workspace.runner_project import discover_runner_directory


# One Agent alias. A current alias names the Ticket, its whole-Team handover
# generation counted from zero, the configured role and the entity, joined by
# '-' with '_' inside a word group; the entity name after '@' may be any
# non-English name. A retained alias keeps its historical Team suffix, role
# marker and ordinal, so existing Sessions stay locatable. Whitespace, a path
# separator, a doubled dot and a separator inside the entity name are rejected.
ALIAS = re.compile(
    r"^(?!.*\.\.)"
    r"(?:[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*-handover[0-9]+-[A-Za-z0-9_]+@\w+"
    r"|[A-Za-z0-9._%-]+@[ldmjserx][1-9][0-9]*)$"
)
TERMINAL_OUTCOMES = frozenset({"completed", "interrupted", "runtime-error"})
SESSION_MAPPING_FIELDS = frozenset(
    {
        "alias",
        "runtime",
        "session",
        "ticket_id",
        "team_generation",
        "role",
        "parent",
        "retained_batch_file",
        "worktree_path",
        "trace_file",
        "worker_pid",
        "runtime_pid",
    }
)
# The Runner's own record of one Agent Entity and its direct parent. The native
# Session is bound once from the Runtime handle; these fields are established
# with it and a later launch input or request may not change them.
SESSION_BINDING_FIELDS = (
    "alias",
    "runtime",
    "ticket_id",
    "team_generation",
    "role",
    "parent",
)


def conflicting_binding_field(
    recorded: Mapping[str, Any], requested: Mapping[str, Any]
) -> str | None:
    """Return the first binding field the request would change, if any."""

    for field in SESSION_BINDING_FIELDS:
        if requested.get(field) != recorded.get(field):
            return field
    return None


def caller_alias(runner_directory: Path) -> str | None:
    """Return the alias of the live Session that owns the calling process.

    A control request identifies itself by the process tree it runs in, never
    by a value it carries. The Runner records each Session's Worker and native
    Runtime process identifiers in its own mapping, and the Worker holds its
    ownership lock for as long as it owns that Session, so the caller is the
    Session whose recorded owner is a live ancestor of this process. When Main
    or the user calls, no live Session owns the process and the result is
    ``None``.

    Neither a projected environment variable nor a request field can establish
    or raise this identity: a missing, forged or copied value is simply not
    consulted. Host isolation from a caller that leaves its own process tree is
    the separate boundary owned by T3c.
    """
    owners = _live_session_owners(runner_directory)
    if not owners:
        return None
    for pid in process_ancestors(os.getpid()):
        alias = owners.get(pid)
        if alias is not None:
            return alias
    return None


def _live_session_owners(runner_directory: Path) -> Dict[int, str]:
    """Map each live Session's recorded process identifiers to its alias.

    Liveness is the ownership lock the recorded Worker still holds, so an
    identifier the operating system later handed to an unrelated process
    cannot present an earlier owner's lock.
    """
    session_root = runner_directory / "sessions"
    if session_root.is_symlink() or not session_root.is_dir():
        return {}
    try:
        aliases = sorted(os.listdir(session_root))
    except OSError:
        return {}
    owners: Dict[int, str] = {}
    for alias in aliases:
        try:
            mapping, session_directory = read_alias_mapping(runner_directory, alias)
        except RunnerError:
            continue
        if not ownership_is_held(session_directory, mapping["worker_pid"]):
            continue
        owners.setdefault(mapping["runtime_pid"], alias)
        owners.setdefault(mapping["worker_pid"], alias)
    return owners


def is_direct_owner(caller: str | None, mapping: Mapping[str, Any]) -> bool:
    """Return whether one caller directly owns the Agent this mapping records.

    A Session directly owns the children the Runner recorded with it as their
    parent. A caller with no live Session owner is Main or the user, which
    directly owns the top-level Sessions the Runner recorded without a parent;
    a sibling, a grandchild or another branch stays outside that relation. The
    recorded parent alone decides, so no request field and no projected
    environment value can widen the relation.
    """
    parent = mapping.get("parent")
    if caller is None:
        return parent is None
    return parent == caller


def require_direct_authority(
    runner_directory: Path, alias: str, mapping: Mapping[str, Any]
) -> None:
    """Refuse ordinary control of a target outside the caller's direct relation.

    A Session addresses itself and its recorded direct children. Main and the
    user, which have no live Session owner, address the top-level Sessions the
    Runner recorded without a parent. A message, an approval query, an
    approval reply and a created child Batch all use this one judgement.
    """
    caller = caller_alias(runner_directory)
    if caller == alias or is_direct_owner(caller, mapping):
        return
    raise _authority_denied()


def require_descendant_authority(
    runner_directory: Path, alias: str, mapping: Mapping[str, Any]
) -> None:
    """Refuse interruption of a target outside the caller's own descent.

    This is the one control exception: a caller may interrupt the subtree it
    owns without an intermediary Agent responding. It grants no message,
    approval or replacement authority.
    """
    caller = caller_alias(runner_directory)
    if caller is None or caller == alias:
        return
    seen = {alias}
    parent = mapping.get("parent")
    while isinstance(parent, str) and parent not in seen:
        if parent == caller:
            return
        seen.add(parent)
        parent = read_alias_mapping(runner_directory, parent)[0].get("parent")
    raise _authority_denied()


def require_replacement_authority(
    runner_directory: Path,
    alias: str,
    mapping: Mapping[str, Any],
    *,
    harness_root: Path,
) -> None:
    """Authorize one replacement, directly or by this request's own review.

    The target's recorded direct parent replaces it, and Main or the user
    replaces a top-level Session recorded without a parent. Every other caller
    is over level: the entry asks the approval route that caller's own mapped
    role configures to review this exact request, and the replacement continues
    only on an explicit ``accept``. The ``--actor`` value, a request field and
    every projected environment value take no part in this judgement.
    """
    caller = caller_alias(runner_directory)
    if is_direct_owner(caller, mapping):
        return
    _require_reviewed_replacement(runner_directory, harness_root, caller, alias, mapping)


def _require_reviewed_replacement(
    runner_directory: Path,
    harness_root: Path,
    caller: str | None,
    alias: str,
    mapping: Mapping[str, Any],
) -> None:
    """Continue one over-level replacement only with this request's approval.

    The review is the caller's own Runtime asking its own reviewer for this one
    request, bound to the caller and the target seat it names: a role's own
    provider route, or a hosted role's host review. A refusal, a cancellation,
    no answer, a failing route or a decision this Runtime cannot obtain all end
    in a refusal, and no failure escapes as an exception. A caller with no live
    Session owner is Main or the user, which has no mapped role to review with:
    the user's own window belongs to a running Session's Runtime, which the
    Runner cannot open from here, so such a request is refused rather than
    continued unreviewed.
    """
    if caller is None:
        raise _replacement_denied(
            "a caller without a live Session has no mapped role to review it"
        )
    caller_mapping, _ = read_alias_mapping(runner_directory, caller)
    role_reference = caller_mapping.get("role_reference") or caller_mapping["role"]
    context = {
        "request_id": uuid.uuid4().hex,
        "operation": "replace-session",
        "caller_alias": caller,
        "caller_role": caller_mapping["role"],
        "target_alias": alias,
        "target_role": mapping["role"],
        "target_ticket_id": mapping["ticket_id"],
        "target_team_generation": mapping["team_generation"],
        "target_parent_alias": mapping.get("parent"),
        "allowed_decisions": ["accept", "decline"],
    }
    try:
        decision = review_role_request(harness_root, role_reference, context)
    except ProjectRolesError as error:
        raise RunnerError(
            "invalid-config",
            "The caller's role cannot be resolved for review, so the "
            "replacement was not executed.",
        ) from error
    except RuntimeAdapterError as error:
        if error.code == "RUNTIME_REQUEST_UNHANDLED":
            raise _replacement_denied(
                "the caller's Runtime reviews this on the user's own window, "
                "which cannot be opened for this request"
            ) from error
        # The review was attempted and produced no decision. This is not a
        # refusal by the review, so it keeps its own outcome instead of being
        # reported as a denied request.
        raise RunnerError(
            "operation-failed",
            "The Runtime approval for this replacement could not be obtained, "
            "so the replacement was not executed.",
        ) from error
    if decision.get("decision") != "accept":
        raise _replacement_denied("the Runtime review did not accept it")


def status_aliases(
    aliases: Sequence[str],
    cwd: Path,
    *,
    operation_total: bool = False,
    baseline: str | None = None,
    candidate: str | None = None,
) -> StatusResponse:
    """Read exactly the supplied durable aliases; never discover a Run."""

    if (baseline is None) != (candidate is None):
        raise RunnerError(
            "invalid-input",
            "Git diagnostics require both --baseline and --candidate.",
        )
    runner_directory = discover_runner_directory(cwd)
    caller = caller_alias(runner_directory)
    results = []
    errors = []
    for alias in aliases:
        try:
            results.append(
                _status_alias(
                    runner_directory,
                    alias,
                    caller=caller,
                    operation_total=operation_total,
                    baseline=baseline,
                    candidate=candidate,
                )
            )
        except RunnerError as error:
            results.append({"alias": alias, "error": error.as_document()})
            errors.append(error)
    return StatusResponse(
        document={"aliases": results},
        succeeded=not errors,
        errors=tuple(errors),
    )


def _status_alias(
    runner_directory: Path,
    alias: str,
    *,
    caller: str | None,
    operation_total: bool,
    baseline: str | None,
    candidate: str | None,
) -> Dict[str, Any]:
    mapping, session_directory = read_alias_mapping(runner_directory, alias)
    # A cross-level observation keeps only the coarse activity, for an Agent
    # caller and for a caller with no live Session owner alike.
    if caller != alias and not is_direct_owner(caller, mapping):
        return _status_summary(mapping, session_directory, alias)
    status = _status_session(mapping, session_directory, alias)
    if operation_total:
        status["operation_total"] = _operation_total(
            Path(mapping["trace_file"]), mapping["session"]
        )
    if baseline is not None and candidate is not None:
        status["diff"] = _commit_diff(
            Path(mapping["worktree_path"]), baseline, candidate
        )
    return status


def _status_session(
    mapping: Dict[str, Any], session_directory: Path, alias: str
) -> Dict[str, str]:
    identity = {"alias": alias}
    if "execution_id" in mapping:
        identity.update(session=mapping["session"], execution_id=mapping["execution_id"])
    execution_file = session_directory / "execution.yml"
    if os.path.lexists(str(execution_file)):
        return {
            **identity, "activity": "idle",
            "last_outcome": read_terminal_outcome(execution_file),
        }
    try:
        status = session_operation(mapping, "status")
    except RunnerError:
        # Completion can close the socket between the file read and the request.
        if execution_file.is_file():
            return {**identity, "activity": "idle",
                    "last_outcome": read_terminal_outcome(execution_file)}
        return {
            **identity,
            **_unresponsive_status(mapping, session_directory),
        }
    if "last_outcome" in mapping and "last_outcome" not in status:
        status["last_outcome"] = mapping["last_outcome"]
    return {**identity, **status}


def _status_summary(
    mapping: Dict[str, Any], session_directory: Path, alias: str
) -> Dict[str, Any]:
    """Return only the coarse activity of a Session outside the caller's branch.

    A cross-level observation exposes neither the private native Session
    identity nor Session diagnostics, so the caller cannot read another
    branch's execution or evidence through status.
    """
    status = _status_session(mapping, session_directory, alias)
    summary = {"alias": alias, "activity": status["activity"]}
    if "last_outcome" in status:
        summary["last_outcome"] = status["last_outcome"]
    return summary


def _unresponsive_status(
    mapping: Dict[str, Any], session_directory: Path
) -> Dict[str, Any]:
    """Judge one execution whose Worker did not answer a control request.

    The judgement combines the control response with the recorded heartbeat,
    the ownership lock the recorded Worker still holds and any terminal
    record. No single signal decides: a heartbeat's age, silence in the native
    Trace, a process identifier that resolves or even one that the operating
    system handed to an unrelated process are never taken alone as proof that
    the execution lives or died.

    Returns
    -------
    ``activity: unreachable`` while the recorded owner still holds its
    ownership lock, so the execution cannot be confirmed; ``activity:
    abnormal`` when that owner is gone, including after its identifier was
    reused, and no terminal record was published. A heartbeat that names this
    Worker adds ``heartbeat_at``, the last moment it held the execution.
    """
    activity = "abnormal"
    if ownership_is_held(session_directory, mapping["worker_pid"]):
        activity = "unreachable"
    heartbeat = read_heartbeat(session_directory)
    if heartbeat is not None and heartbeat["worker_pid"] == mapping["worker_pid"]:
        return {"activity": activity, "heartbeat_at": heartbeat["updated_at"]}
    return {"activity": activity}


def _operation_total(trace_file: Path, session: str) -> int:
    """Count one native Codex tool request for each call ID in one Session."""

    try:
        text = trace_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise _diagnostic_failure() from error
    # The Runtime appends to the linked native file, so a running Session can
    # end with a record that is not written completely yet.
    records = text.splitlines() if text.endswith("\n") else text.splitlines()[:-1]
    calls = set()
    try:
        for record in records:
            item = json.loads(record)
            if item.get("type") != "response_item":
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            item_type = payload.get("type")
            if item_type in {"function_call", "custom_tool_call"}:
                request_id = payload.get("call_id")
            elif item_type in {"local_shell_call", "tool_search_call"}:
                request_id = payload.get("call_id") or payload.get("id")
            elif item_type in {"web_search_call", "image_generation_call"}:
                request_id = payload.get("id")
            else:
                continue
            if isinstance(request_id, str) and request_id:
                calls.add((session, request_id))
    except (TypeError, json.JSONDecodeError) as error:
        raise _diagnostic_failure() from error
    return len(calls)


def _commit_diff(worktree: Path, baseline: str, candidate: str) -> Dict[str, Any]:
    """Read one resulting Git change without recording a diagnostic."""

    try:
        repository = SourceRepository.from_root(worktree)
        resolved_baseline = repository.resolved_commit(baseline)
        resolved_candidate = repository.resolved_commit(candidate)
        entries = repository.diff_numstat(resolved_baseline, resolved_candidate)
        files = [_numstat_file(entry) for entry in entries.split(b"\0") if entry]
    except (GitRepositoryError, UnicodeError, ValueError) as error:
        raise _diagnostic_failure() from error
    return {
        "baseline": resolved_baseline,
        "candidate": resolved_candidate,
        "files": files,
    }


def _numstat_file(entry: bytes) -> Dict[str, Any]:
    additions, deletions, path = entry.split(b"\t", maxsplit=2)
    return {
        "path": path.decode(errors="replace"),
        "additions": None if additions == b"-" else int(additions),
        "deletions": None if deletions == b"-" else int(deletions),
    }


def read_alias_mapping(
    runner_directory: Path, alias: str
) -> Tuple[Dict[str, Any], Path]:
    if not ALIAS.fullmatch(alias):
        raise _alias_not_found()
    session_root = runner_directory / "sessions"
    session_directory = session_root / alias
    mapping_file = session_directory / "mapping.yml"
    if session_root.is_symlink():
        raise _invalid_mapping()
    if not session_root.is_dir() or not os.path.lexists(str(session_directory)):
        raise _alias_not_found()
    if session_directory.is_symlink() or not session_directory.is_dir():
        raise _invalid_mapping()
    if mapping_file.is_symlink() or not mapping_file.is_file():
        raise _invalid_mapping()
    try:
        mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _invalid_mapping() from error
    if not _valid_mapping(mapping, alias):
        raise _invalid_mapping()
    return mapping, session_directory


def is_session_mapping(mapping: Mapping[str, Any]) -> bool:
    return "run_id" not in mapping and SESSION_MAPPING_FIELDS.issubset(mapping)


def _valid_mapping(mapping: object, alias: str) -> bool:
    if not isinstance(mapping, dict):
        return False
    return is_session_mapping(mapping) and _valid_session_mapping(mapping, alias)


def _valid_session_mapping(mapping: Dict[str, Any], alias: str) -> bool:
    if mapping["alias"] != alias:
        return False
    string_fields = SESSION_MAPPING_FIELDS - {
        "team_generation", "parent", "worker_pid", "runtime_pid"
    }
    if any(
        not isinstance(mapping[field], str) or not mapping[field]
        for field in string_fields
    ):
        return False
    if mapping["parent"] is not None and not isinstance(mapping["parent"], str):
        return False
    if "last_outcome" in mapping and (
        not isinstance(mapping["last_outcome"], str)
        or mapping["last_outcome"] not in TERMINAL_OUTCOMES
    ):
        return False
    return (
        isinstance(mapping["team_generation"], int)
        and not isinstance(mapping["team_generation"], bool)
        and mapping["team_generation"] > 0
        and all(
            isinstance(mapping[field], int)
            and not isinstance(mapping[field], bool)
            and mapping[field] > 0
            for field in ("worker_pid", "runtime_pid")
        )
    )


def read_terminal_outcome(turn_file: Path) -> str:
    if turn_file.is_symlink() or not turn_file.is_file():
        raise _invalid_activity()
    try:
        turn = yaml.safe_load(turn_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise _invalid_activity() from error
    if (
        not isinstance(turn, dict)
        or not isinstance(turn.get("outcome"), str)
        or turn["outcome"] not in TERMINAL_OUTCOMES
    ):
        raise _invalid_activity()
    return turn["outcome"]


def _authority_denied() -> RunnerError:
    return RunnerError(
        "authority-denied",
        "Only the target's direct parent may control this Session.",
    )


def _replacement_denied(detail: str) -> RunnerError:
    """Return the refusal for one replacement this caller may not perform."""

    return RunnerError(
        "authority-denied",
        "Replacement refused: {0}. Only the target's recorded direct parent "
        "may replace it, and an over-level request continues only when its "
        "Runtime approval accepts that request.".format(detail),
    )


def _alias_not_found() -> RunnerError:
    return RunnerError("alias-not-found", "The requested Engineer alias was not found.")


def _invalid_mapping() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Engineer alias mapping is invalid."
    )


def _invalid_activity() -> RunnerError:
    return RunnerError(
        "operation-failed",
        "The requested Engineer alias has no valid Runtime execution or terminal outcome.",
    )


def _diagnostic_failure() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Session diagnostics could not be read."
    )
