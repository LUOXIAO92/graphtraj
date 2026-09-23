"""Alias-local observation for completed and active Runtime execution."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import yaml

from graphtraj.workspace.git_repository import GitRepositoryError, SourceRepository
from graphtraj.execution.runner_models import RunnerError, StatusResponse
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_heartbeat import ownership_is_held, read_heartbeat
from graphtraj.execution.runner_process import process_ancestors
from graphtraj.execution.runner_transport import valid_terminal_launch_failure
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
    command: Sequence[str] | None = None,
) -> dict | None:
    """Run the specified replacement through the caller's native approval.

    Direct owners and a recorded Runtime without approvals continue locally.
    Otherwise the native execution interface runs the remaining operation;
    its returned document is the replacement result, never an approval record.
    """
    from graphtraj.runtimes.replacement import caller_runtime, execute_replacement

    caller = caller_alias(runner_directory)
    if is_direct_owner(caller, mapping):
        return None
    runtime = (
        read_alias_mapping(runner_directory, caller)[0]["runtime"]
        if caller is not None else caller_runtime()
    )
    # pi deliberately has no native approval mechanism. Unknown Runtime or a
    # missing Codex channel is not evidence of that capability choice.
    if runtime == "pi":
        return None
    if runtime != "codex" or command is None:
        raise _replacement_denied()
    return execute_replacement(command)


def require_stopped_subtree(runner_directory: Path, alias: str) -> None:
    """Require terminal execution for the target and every recorded descendant."""
    # The target must always be an established, valid Session. Other allocated
    # directories may retain a confirmed startup failure without any Session.
    mappings = {alias: read_alias_mapping(runner_directory, alias)}
    for path in (runner_directory / "sessions").iterdir():
        if path.name == alias:
            continue
        if not path.is_dir() and not path.is_symlink():
            continue
        if _terminal_unestablished_launch(path):
            continue
        mappings[path.name] = read_alias_mapping(runner_directory, path.name)
    pending = [alias]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        mapping, directory = mappings[current]
        if _status_session(mapping, directory, current)["activity"] != "idle":
            raise RunnerError(
                "replacement-not-stopped",
                "The target and all descendants must be stopped before replacement.",
            )
        pending.extend(
            name for name, (child, _) in mappings.items()
            if child.get("parent") == current
        )


def _terminal_unestablished_launch(directory: Path) -> bool:
    """Recognize a retained, terminated launch that never established a Session.

    Anything with identity/turn evidence, including a broken link, still needs
    strict mapping validation. Missing or uncertain failure evidence does not
    exempt an allocation from the stopped-subtree check.
    """
    if directory.is_symlink() or any(
        os.path.lexists(directory / name)
        for name in ("mapping.yml", "session.yml", "native-session.yml", "execution.yml")
    ):
        return False
    launch_file = directory / "launch.yml"
    error_file = directory / "launch-error.yml"
    if any(path.is_symlink() or not path.is_file() for path in (launch_file, error_file)):
        return False
    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
        failure = yaml.safe_load(error_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return (
        isinstance(launch, dict)
        and launch.get("operation") == "launch"
        and isinstance(launch.get("mapping"), dict)
        and launch["mapping"].get("alias") == directory.name
        and valid_terminal_launch_failure(failure)
    )


def status_aliases(
    aliases: Sequence[str],
    cwd: Path,
    *,
    operation_total: bool = False,
    baseline: str | None = None,
    candidate: str | None = None,
) -> StatusResponse:
    """Read exactly the supplied durable aliases; never discover a Run."""

    _require_git_pair(baseline, candidate)
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


def status_tree(
    cwd: Path,
    *,
    operation_total: bool = False,
    baseline: str | None = None,
    candidate: str | None = None,
) -> StatusResponse:
    """Return the visible Agent status tree from the Runner's own records.

    Every Session this Runner recorded for the project is enumerated from its
    retained ``sessions/<alias>/mapping.yml`` record, so one query needs no
    alias list and no process identifier, and a later caller reads the same
    tree after a restart.

    Visibility reuses the recorded direct relation unchanged. A live Session
    owns the subtree rooted at itself; a caller with no live Session owner,
    which is Main or the user, owns every recorded top-level Session and its
    subtree. Each node keeps its ``parent`` and ``children`` names and the
    per-Agent detail ``_status_alias`` already allows, so only the caller
    itself and its recorded direct children carry a full status and every
    deeper node keeps the coarse activity and last outcome.

    One unreadable record or one Session whose status cannot be judged adds
    that node's own error and leaves the remaining tree intact. A record with
    no known parent appears at the top level for Main and the user and stays
    out of a Session caller's tree, which the recorded relation defines.
    """
    _require_git_pair(baseline, candidate)
    runner_directory = discover_runner_directory(cwd)
    caller = caller_alias(runner_directory)
    records, failures = _recorded_sessions(runner_directory)

    children: Dict[str, list[str]] = {}
    for alias, mapping in records.items():
        parent = mapping.get("parent")
        if isinstance(parent, str):
            children.setdefault(parent, []).append(alias)
    roots = (
        [alias for alias, mapping in records.items() if mapping.get("parent") is None]
        if caller is None
        else [caller] if caller in records else []
    )

    nodes: list[Dict[str, Any]] = []
    errors: list[RunnerError] = []
    seen: set[str] = set()
    pending = [(alias, None) for alias in reversed(roots)]
    while pending:
        alias, parent = pending.pop()
        # A recorded parent cycle is cut once the walk revisits an alias.
        if alias in seen:
            continue
        seen.add(alias)
        node: Dict[str, Any] = {
            "alias": alias,
            "parent": parent,
            "children": sorted(children.get(alias, ())),
        }
        try:
            node.update(
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
            node["error"] = error.as_document()
            errors.append(error)
        nodes.append(node)
        pending.extend(
            (child, alias) for child in reversed(sorted(children.get(alias, ())))
        )
    if caller is None:
        for alias, error in failures:
            nodes.append(
                {"alias": alias, "parent": None, "children": [],
                 "error": error.as_document()}
            )
            errors.append(error)
    return StatusResponse(
        document={"agents": nodes},
        succeeded=not errors,
        errors=tuple(errors),
    )


def _recorded_sessions(
    runner_directory: Path,
) -> Tuple[Dict[str, Dict[str, Any]], list[Tuple[str, RunnerError]]]:
    """Read every Session record the Runner retains for this project.

    Returns the valid records by alias and the alias of each record that could
    not be read with the error it raised, so one unreadable Session never stops
    the enumeration of the rest.
    """
    session_root = runner_directory / "sessions"
    if session_root.is_symlink() or not session_root.is_dir():
        return {}, []
    try:
        entries = sorted(os.listdir(session_root))
    except OSError:
        return {}, []
    records: Dict[str, Dict[str, Any]] = {}
    failures: list[Tuple[str, RunnerError]] = []
    for alias in entries:
        try:
            records[alias] = read_alias_mapping(runner_directory, alias)[0]
        except RunnerError as error:
            failures.append((alias, error))
    return records, failures


def _require_git_pair(baseline: str | None, candidate: str | None) -> None:
    """Require the two Git diagnostics commits together or not at all."""

    if (baseline is None) != (candidate is None):
        raise RunnerError(
            "invalid-input",
            "Git diagnostics require both --baseline and --candidate.",
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


def owning_execution(
    alias: str,
    session_directory: Path,
    mapping: Mapping[str, Any] | None,
) -> Dict[str, Any] | None:
    """Return the execution that still owns one Session directory, if any.

    One Session directory owns one Agent Entity and at most one live
    execution. The public create claims a directory that records nothing, and
    a continue starts the next execution only after the retained terminal
    record confirms the recorded execution ended. While the recorded owner
    runs, normally waits, or holds its ownership lock without answering a
    control call, that execution still owns the directory and neither entry
    may start another.

    Parameters
    ----------
    alias
        Agent alias of the Session directory being claimed.
    session_directory
        Directory a create or continue would own.
    mapping
        The Session's recorded execution, or ``None`` for a create, which
        claims a directory that records no Session at all.

    Returns
    -------
    The owning execution's status document - ``activity`` plus ``session`` and
    ``execution_id`` when recorded - or ``None`` once the retained terminal
    record confirms the end, or when a create finds the directory free.
    ``activity`` is ``running`` while that owner still answers for the
    execution, ``unreachable`` while it holds its ownership lock without
    answering, ``abnormal`` when that owner is gone without a terminal record,
    and ``recorded`` when a create finds a directory that already holds a
    Session record.
    """
    if mapping is None:
        return {"activity": "recorded"} if os.path.lexists(
            str(session_directory)
        ) else None
    status = _status_session(mapping, session_directory, alias)
    return None if status["activity"] == "idle" else status


def session_occupied(alias: str, owning: Mapping[str, Any] | None) -> RunnerError:
    """Return the refusal a create or continue reports for an owned directory.

    The message names the recorded execution so its caller can still deliver
    to or stop it, and the refusal changes nothing about the Session.
    """
    facts = ""
    if owning is not None and "session" in owning:
        facts = " Recorded session {0}, execution {1}, activity {2}.".format(
            owning["session"], owning.get("execution_id"), owning["activity"]
        )
    return RunnerError(
        "operation-failed",
        "The Session alias {0} still owns a Session record or execution, so no "
        "other execution may start for it.{1}".format(alias, facts),
    )


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


def _replacement_denied() -> RunnerError:
    return RunnerError(
        "authority-denied",
        "Only the target's direct parent may replace it; this caller did not "
        "receive the Runtime's approval for this replacement.",
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
