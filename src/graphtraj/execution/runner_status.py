"""Alias-local observation for completed and active Runtime execution."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Sequence, Tuple

import yaml

from graphtraj.workspace.git_repository import GitRepositoryError, SourceRepository
from graphtraj.execution.runner_models import RunnerError, StatusResponse
from graphtraj.execution.runner_connection import session_operation
from graphtraj.execution.runner_heartbeat import ownership_is_held, read_heartbeat
from graphtraj.execution.runner_process import process_ancestors
from graphtraj.execution.runner_transport import valid_terminal_launch_failure
from graphtraj.runtimes import runtime_adapter
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError
from graphtraj.workspace.runner_project import discover_runner_directory


_runtime_caller: ContextVar[tuple[Path, str | None] | None] = ContextVar('runtime_caller', default=None)


@contextmanager
def runtime_caller(runner_directory: Path, identity: str | None) -> Iterator[None]:
    """Scope a GraphTraj alias received from its owned host callback.

    This is not a model input. Adapters bind registered aliases; temporary
    native helpers receive an unregistered sentinel, never their native ID.
    ``None`` is reserved for explicit trusted human access.
    """
    token = _runtime_caller.set((runner_directory.resolve(), identity))
    try:
        yield
    finally:
        _runtime_caller.reset(token)


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
    "parent_connection",
)


def conflicting_binding_field(
    recorded: Mapping[str, Any], requested: Mapping[str, Any]
) -> str | None:
    """Return the first binding field the request would change, if any."""

    for field in (*SESSION_BINDING_FIELDS, "purpose"):
        if requested.get(field) != recorded.get(field):
            return field
    return None


def caller_alias(runner_directory: Path) -> str | None:
    """Resolve a bound Agent alias, or an unowned human CLI process.

    A private callback supplies its GraphTraj alias. An isolated Runtime CLI
    can also resolve its live Worker ancestry. Shared host processes require a
    per-caller channel and cannot select an alias from a PID. Request fields,
    native conversation handles and environment labels grant no authority.
    """
    native = _runtime_caller.get()
    if native is not None:
        if native[0] != runner_directory.resolve():
            raise _authority_denied()
        if native[1] is None:
            return None  # Explicit trusted human context, never a native Main.
        return native[1]
    return process_caller_alias(runner_directory, os.getpid())


def process_caller_alias(runner_directory: Path, pid: int) -> str | None:
    """Resolve an OS-observed process through the existing live ownership records.

    Transport hosts must obtain ``pid`` from the kernel, never request fields.
    """
    owners = _live_session_owners(runner_directory)
    if not owners:
        return None
    for pid in process_ancestors(pid):
        if pid in owners and owners[pid] is None:
            raise RunnerError('authority-denied', 'A shared host requires a bound Agent call channel.')
        alias = owners.get(pid)
        if alias is not None:
            return alias
    return None


def _live_session_owners(runner_directory: Path) -> Dict[int, str | None]:
    """Map each live Session's recorded process identifiers to its alias.

    Liveness is the ownership lock the recorded Worker still holds, so an
    identifier the operating system later handed to an unrelated process
    cannot present an earlier owner's lock.
    """
    session_root = runner_directory / "sessions"
    try:
        if session_root.is_symlink() or not session_root.is_dir():
            return {}
        aliases = sorted(os.listdir(session_root))
    except OSError as error:
        # Inaccessible ownership records do not establish a Main caller.
        raise RunnerError(
            "authority-denied",
            "Caller identity cannot be verified because Session records are inaccessible.",
        ) from error
    owners: Dict[int, str | None] = {}
    for alias in aliases:
        try:
            mapping, session_directory = read_alias_mapping(runner_directory, alias)
        except RunnerError:
            continue
        if not ownership_is_held(session_directory, mapping["worker_pid"]):
            continue
        # A shared host process cannot identify which of its Agents called.
        for pid in {mapping["runtime_pid"], mapping["worker_pid"]}:
            if mapping.get("hosted") or (pid in owners and owners[pid] != alias):
                owners[pid] = None
            else:
                owners[pid] = alias
    return owners


def is_direct_owner(caller: str | None, mapping: Mapping[str, Any]) -> bool:
    """Return whether one caller directly owns the Agent this mapping records.

    A Session directly owns the children the Runner recorded with it as their
    parent. An ordinary human CLI caller has no live Session owner and
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

    An Agent addresses itself and its recorded direct children. Registered
    Main uses its own alias; human callers address top-level Sessions recorded
    without a parent. A message, an approval query, an
    approval reply and a created child Batch all use this one judgement.
    """
    caller = caller_alias(runner_directory)
    if caller == alias or is_direct_owner(caller, mapping):
        return
    raise _authority_denied()


def require_task_authority(
    state_directory: Path,
    runner_directory: Path,
    ticket_id: str,
    alias: str,
    operation: str,
) -> dict[str, Any]:
    """Authorize a task operation against the actual Session and current Team.

    Submission belongs to the member itself; acceptance and member registration
    belong to its real direct parent (including a top-level caller). Registration
    may precede membership, but never the Runner's Session binding. This is the
    common authorization check, not a submission or acceptance state transition.
    Role names and caller-supplied identity fields confer no authority.
    """
    from graphtraj.graph.delivery_state import read_team
    from graphtraj.graph.ticket_graph import _load_states

    mapping, _ = read_alias_mapping(runner_directory, alias)
    if mapping["ticket_id"] != ticket_id:
        raise _authority_denied()
    record = _load_states(state_directory / "tickets").get(ticket_id)
    if record is None:
        raise _authority_denied()
    directory, ticket = record
    if ticket["active_team_ordinal"] != mapping["team_generation"]:
        raise _authority_denied()
    team = read_team(directory / "teams" / str(mapping["team_generation"]) / "team.yml")
    if team["status"] != "active":
        raise _authority_denied()
    members = {member["session_ref"] for member in team["members"].values()}
    if operation != "register-member" and alias not in members:
        raise _authority_denied()
    caller = caller_alias(runner_directory)
    if operation == "submit" and caller == alias:
        return mapping
    if operation in {"accept", "integrate", "register-member"} and is_direct_owner(caller, mapping):
        return mapping
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
    from graphtraj.runtimes import runtime_adapter
    from graphtraj.runtimes.replacement import caller_runtime

    caller = caller_alias(runner_directory)
    if is_direct_owner(caller, mapping):
        return None
    runtime = (
        read_alias_mapping(runner_directory, caller)[0]["runtime"]
        if caller is not None else caller_runtime()
    )
    try:
        execute = runtime_adapter.native_replacement_approval(runtime)
    except runtime_adapter.RuntimeAdapterError as error:
        if error.code == "RUNTIME_UNSUPPORTED":
            raise _replacement_denied() from error
        raise RunnerError("native-approval-unavailable", error.message) from error
    if execute is None:
        return None
    if command is None:
        raise _replacement_denied()
    result = execute(command)
    if not isinstance(result, dict):
        raise RunnerError("operation-failed", "The native replacement returned no result.")
    return result


def require_stopped_subtree(runner_directory: Path, alias: str) -> None:
    """Require terminal execution for the target and every recorded descendant."""
    # The target must always be an established, valid Session. Other allocated
    # directories may precede launch or retain a confirmed startup failure.
    mappings = {alias: read_alias_mapping(runner_directory, alias)}
    for path in [*(runner_directory / "sessions").iterdir(), *retained_session_directories(runner_directory)]:
        name = path.parent.name if path.name == "runner" else path.name
        if name == alias:
            continue
        if not path.is_dir() and not path.is_symlink():
            continue
        if (_unstarted_allocation(path) or _terminal_unestablished_launch(path)
                or _unestablished_root_launch(path)):
            continue
        mappings[name] = read_alias_mapping(runner_directory, name)
    pending = [alias]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        mapping, directory = mappings[current]
        if _status_session(mapping, directory, current, respond_to_abnormal=False)["activity"] != "idle":
            raise RunnerError(
                "replacement-not-stopped",
                "The target and all descendants must be stopped before replacement.",
            )
        pending.extend(
            name for name, (child, _) in mappings.items()
            if child.get("parent") == current
        )


def require_execution_allowed(
    runner_directory: Path, alias: str, mapping: Mapping[str, Any],
) -> None:
    """Reject work in a stopped subtree, including a not-yet-created child.

    The caller holds the execution startup lock until input is delivered or
    the new native execution is recorded. A stop stays bound to the old
    entity; replacing it never clears its descendants' prohibition.
    """
    current: str | None = alias
    seen: set[str] = set()
    while current is not None and current not in seen:
        seen.add(current)
        record_file = session_record_directory(runner_directory, current) / "session.yml"
        if record_file.is_file() and yaml.safe_load(record_file.read_text()).get("retirement"):
            raise RunnerError("session-retired", f"{alias} belongs to retired subtree {current}.")
        stop_file = session_record_directory(runner_directory, current) / "stop.yml"
        if stop_file.exists() and yaml.safe_load(stop_file.read_text()).get("resumed") is not True:
            raise RunnerError(
                "subtree-stopped", f"{alias} belongs to stopped subtree {current}.",
            )
        parent = mapping.get("parent")
        current = parent if isinstance(parent, str) else None
        if current is not None:
            mapping, _ = read_alias_mapping(runner_directory, current)


def _unstarted_allocation(directory: Path) -> bool:
    """Recognize only the empty records written before a launch request existed.

    Runner writes launch.yml before starting a Worker. Any other entry, link,
    or nonempty event record makes ownership uncertain and needs validation.
    """
    if directory.is_symlink():
        return False
    entries = list(directory.iterdir())
    return not entries or (
        len(entries) == 1
        and entries[0].name == "events.jsonl"
        and not entries[0].is_symlink()
        and entries[0].is_file()
        and entries[0].stat().st_size == 0
    )


def unestablished_execution_allocation(directory: Path) -> bool:
    """Whether retained lifecycle facts confirm no execution identity was established.

    Unlike the subtree-only root-launch exemption, a pending launch is not
    sufficient here. Native host/checker associations also prohibit exclusion.
    """
    if (directory.is_symlink() or not directory.is_dir()
            or os.path.lexists(directory / 'native.yml')):
        return False
    return _unstarted_allocation(directory) or _terminal_unestablished_launch(directory)


def _unestablished_root_launch(directory: Path) -> bool:
    """Exclude an authoritative root allocation without certifying it stopped.

    Runner retains launch parentage before native creation. An explicit root
    cannot descend from the valid target. Missing parentage or any established
    identity still requires strict mapping validation.
    """
    if directory.is_symlink() or any(
        os.path.lexists(directory / name)
        for name in ("mapping.yml", "session.yml", "native-session.yml", "execution.yml")
    ):
        return False
    launch_file = directory / "launch.yml"
    if launch_file.is_symlink() or not launch_file.is_file():
        return False
    try:
        launch = yaml.safe_load(launch_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return (
        isinstance(launch, dict) and launch.get("operation") == "launch"
        and isinstance(launch.get("mapping"), dict)
        and launch["mapping"].get("alias") == directory.name
        and "parent" in launch["mapping"] and launch["mapping"]["parent"] is None
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
    which is a human CLI caller, observes recorded top-level Sessions and
    their subtrees. Each node keeps its ``parent`` and ``children`` names and the
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
        entries = sorted(set(os.listdir(session_root)) | {
            directory.parent.name for directory in retained_session_directories(runner_directory)
        })
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
        status["operation_total"] = _operation_total(mapping)
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
    mapping: Dict[str, Any],
    session_directory: Path,
    alias: str,
    *,
    respond_to_abnormal: bool = True,
) -> Dict[str, str]:
    """Read execution activity, optionally handling abnormality during observation."""
    identity = {"alias": alias}
    if mapping.get("hosted"):
        record = yaml.safe_load((session_directory / "session.yml").read_text())
        return {**identity, "purpose": mapping["purpose"], "parent": mapping["parent"],
                "activity": "running" if ownership_is_held(session_directory, mapping["worker_pid"]) else "idle",
                "retired": bool(record.get("retirement"))}
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
        unresponsive = _unresponsive_status(mapping, session_directory)
        if unresponsive["activity"] == "abnormal" and respond_to_abnormal:
            # The judged abnormality is answered here, as part of the judgement
            # the Runner already makes: the Session's direct parent is notified
            # and its subtree stops, both without the lost Agent forwarding
            # anything (T9c). Imported here because the control operations read
            # this module for the judgment they repeat.
            from graphtraj.execution.runner_control import respond_to_abnormal_session

            respond_to_abnormal_session(alias, session_directory, unresponsive)
        return {**identity, **unresponsive}
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


def _operation_total(mapping: Mapping[str, Any]) -> int:
    """Return one Session's operation count from its selected Runtime Adapter.

    The selected Runtime Adapter interprets its own native records, so this
    count stays Runtime-specific without status reaching into any one
    Runtime's event shapes. A Runtime whose Adapter cannot be selected is
    reported as unsupported for this alias; a record the Adapter cannot read
    remains a diagnostic failure rather than a successful count of zero.
    """
    try:
        adapter = runtime_adapter.select_runtime_adapter(mapping["runtime"])
        return adapter.operation_total(
            Path(mapping["trace_file"]), mapping["session"]
        )
    except RuntimeAdapterError as error:
        if error.code == "RUNTIME_UNSUPPORTED":
            raise RunnerError("RUNTIME_UNSUPPORTED", error.message) from error
        raise _diagnostic_failure() from error


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


def retained_session_directories(runner_directory: Path) -> list[Path]:
    """Locate retired Session records within the existing durable Ticket Traces."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.workspace.runner_project import discover_project_root

    try:
        configuration = load_project_configuration(discover_project_root(runner_directory))
    except (OSError, ValueError, RunnerError):
        return []
    return [directory for directory in (configuration.state / "tickets").glob("*/teams/*/traces/*/runner")
            if (directory / "session.yml").is_file()]


def session_record_directory(runner_directory: Path, alias: str) -> Path:
    """Resolve an active entity or its retained Trace records without a new registry."""
    active = runner_directory / "sessions" / alias
    if active.exists():
        return active
    for directory in retained_session_directories(runner_directory):
        if directory.parent.name == alias:
            return directory
    return active


def read_alias_mapping(
    runner_directory: Path, alias: str
) -> Tuple[Dict[str, Any], Path]:
    """Read a registered host or member binding, including retained retirement evidence."""
    if not ALIAS.fullmatch(alias):
        raise _alias_not_found()
    session_root = runner_directory / "sessions"
    session_directory = session_record_directory(runner_directory, alias)
    mapping_file = session_directory / "mapping.yml"
    if session_root.is_symlink():
        raise _invalid_mapping()
    if not session_root.is_dir() or not os.path.lexists(str(session_directory)):
        raise _alias_not_found()
    if session_directory.is_symlink() or not session_directory.is_dir():
        raise _invalid_mapping()
    if mapping_file.is_symlink():
        raise _invalid_mapping()
    try:
        if mapping_file.is_file():
            mapping = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
        else:
            record = yaml.safe_load((session_directory / "session.yml").read_text(encoding="utf-8"))
            mapping = record["retirement"]["mapping"]
    except (OSError, UnicodeError, KeyError, TypeError, yaml.YAMLError) as error:
        raise _invalid_mapping() from error
    if not _valid_mapping(mapping, alias):
        raise _invalid_mapping()
    return mapping, session_directory


def is_session_mapping(mapping: Mapping[str, Any]) -> bool:
    return "run_id" not in mapping and SESSION_MAPPING_FIELDS.issubset(mapping)


def _valid_mapping(mapping: object, alias: str) -> bool:
    if not isinstance(mapping, dict):
        return False
    if mapping.get("hosted") is True:
        return (mapping.get("alias") == alias and mapping.get("purpose") in {"main", "checker"}
                and isinstance(mapping.get("runtime"), str)
                and isinstance(mapping.get("worker_pid"), int)
                and isinstance(mapping.get("runtime_pid"), int)
                and (mapping.get("parent") is None if mapping["purpose"] == "main"
                     else isinstance(mapping.get("parent"), str)))
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
        or turn.get("terminal_confirmed") is False
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
    return RunnerError("alias-not-found", "The requested Agent alias was not found.")


def _invalid_mapping() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Agent alias mapping is invalid."
    )


def _invalid_activity() -> RunnerError:
    return RunnerError(
        "operation-failed",
        "The requested Agent alias has no valid Runtime execution or terminal outcome.",
    )


def _diagnostic_failure() -> RunnerError:
    return RunnerError(
        "operation-failed", "The requested Session diagnostics could not be read."
    )


def require_host_adoption(runner_directory: Path) -> None:
    """Refuse adopting a Main from an existing Agent's bound execution."""
    bound = _runtime_caller.get()
    if bound is not None and bound[1] is not None:
        raise _authority_denied()
    # Hosted Agents deliberately have no process identity. Their user-owned
    # host can bind another conversation only through explicit native approval.
    owners = _live_session_owners(runner_directory)
    for pid in process_ancestors(os.getpid()):
        if owners.get(pid) is not None:
            raise _authority_denied()


def caller_is_main(runner_directory: Path) -> bool:
    """Whether this bound caller is a registered Main, independently of Runtime handles."""
    alias = caller_alias(runner_directory)
    if alias is None:
        return False
    try:
        return read_alias_mapping(runner_directory, alias)[0].get("purpose") == "main"
    except RunnerError:
        return False


def agent_identity(cwd: Path) -> dict:
    """Return the bound caller's GraphTraj identity, or explicit human access."""
    runner = discover_runner_directory(cwd)
    alias = caller_alias(runner)
    if alias is None:
        return {"access": "human"}
    mapping, directory = read_alias_mapping(runner, alias)
    require_execution_allowed(runner, alias, mapping)
    return {"access": "agent", "alias": alias,
            "purpose": mapping.get("purpose", "member"), "parent": mapping["parent"]}
