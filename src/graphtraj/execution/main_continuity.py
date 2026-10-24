"""Project Main continuity shared by every Runtime that can host Main.

A project has one Main working state: the Main-owned root Agents, their
recursive hierarchy, pending notices and results and the current summary
scope. Each verified external Main Session (Codex, Claude Code, Pi or DSH)
continues that state instead of starting an empty one. This module keeps the
only continuity record and the single decision point for who may control it::

    <runner>/main-sessions/continuity.jsonl   append-only control claims
    <runner>/main-sessions/inbox/<key>.jsonl  notices for the Claude Main host

A claim is a new associated record. It never rewrites a historical parent,
a member identity, a Session binding or a native log. Runtime entries supply
an already verified native connection; nothing here verifies identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from graphtraj import file_lock
from graphtraj.execution.runner_models import RunnerError


# Claude Code continues Main at the first control call of each host process
# (the mod's session.start precedes the MCP owner and carries no claim). Its
# host states per call whether this Session's first control may claim.
_claimable: ContextVar[Callable[[], None] | None] = ContextVar('main_claimable', default=None)


def _directory(runner: Path) -> Path:
    """Return the existing per-project Main storage directory."""
    return runner / 'main-sessions'


def _same(record: Mapping[str, Any], runtime: str, session: str) -> bool:
    """Whether one record names this native Main Session."""
    return record.get('runtime') == runtime and record.get('session') == session


def claims(runner: Path) -> list[dict]:
    """Return every control claim in order; the last one is the current Main."""
    path = _directory(runner) / 'continuity.jsonl'
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def current_main(runner: Path) -> dict | None:
    """Return the Main Session currently holding control, or ``None`` if unclaimed."""
    recorded = claims(runner)
    return recorded[-1] if recorded else None


def claim_main(runner: Path, connection: Mapping[str, Any], entry: str) -> dict:
    """Record that this verified Main Session continues the project's Main.

    A repeated claim by the current Main adds nothing. ``entry`` names the
    real native boundary (for example ``codex:SessionStart:resume``).
    """
    directory = _directory(runner)
    directory.mkdir(parents=True, exist_ok=True)
    runtime, session = connection['runtime'], connection['session']
    with (directory / 'continuity.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        previous = current_main(runner)
        if previous is not None and _same(previous, runtime, session):
            return previous
        record = {
            'at':         time.time(),
            'runtime':    runtime,
            'session':    session,
            'entry':      entry,
            # The verified native locator only; never configuration or credentials.
            'connection': {key: value for key, value in connection.items() if isinstance(value, str)},
            'previous':   ({'runtime': previous['runtime'], 'session': previous['session']}
                           if previous is not None else None),
        }
        with (directory / 'continuity.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
    if previous is not None:
        _transfer_notices(runner, previous, record)
    return record


def main_sessions(runner: Path) -> set[str]:
    """Return every native Session that has been this project's verified Main.

    Claims and existing Main completion bindings both count; checker records
    below a binding never do. Historical records are read, never changed.
    """
    import yaml

    sessions = {record['session'] for record in claims(runner)}
    for path in _directory(runner).glob('finalize_*/session.yml'):
        try:
            binding = yaml.safe_load(path.read_text(encoding='utf-8'))
            sessions.add(binding['session'])
        except (OSError, yaml.YAMLError, TypeError, KeyError) as error:
            # An unreadable Main binding must not hide its members or let its
            # Session past the single-controller check.
            raise RunnerError('authority-unavailable', f'Main binding {path} is unreadable: {error}') from error
    return sessions


@contextmanager
def claimable(on_claim: Callable[[], None] | None) -> Iterator[None]:
    """Let this call's first control claim Main for a host without entry events."""
    token = _claimable.set(on_claim)
    try:
        yield
    finally:
        _claimable.reset(token)


def require_control(runner: Path, connection: Mapping[str, Any] | None) -> None:
    """Refuse control from a Main Session another Main has continued.

    This is the single-controller decision point, confirmed by the user:
    Main is the one central dispatcher. Reads never come here. A human CLI call has no
    native connection and keeps its existing authority. Before any claim
    exists the project keeps its previous single-Main behavior.

    Raises
    ------
    RunnerError
        ``main-continued`` naming the current Main and how to take control back.
    """
    if not isinstance(connection, Mapping) or not isinstance(connection.get('session'), str):
        return
    runtime, session = connection.get('runtime'), connection['session']
    current = current_main(runner)
    on_claim = _claimable.get()
    if current is not None and _same(current, runtime, session):
        if on_claim is not None:
            on_claim()  # This process entered as the current Main.
        return
    if on_claim is not None:
        claim_main(runner, connection, f'{runtime}:first-control')
        on_claim()
        return
    if current is None or session not in main_sessions(runner):
        # Not a project Main (for example a native helper): its own authority decides.
        return
    at = time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(current['at']))
    raise RunnerError(
        'main-continued',
        f'This Main Session ({runtime} {session}) was continued by {current["runtime"]} '
        f'Session {current["session"]} at {at}; its later control calls are refused. '
        'Status remains readable. To continue Main here, re-enter it: start or resume this Session '
        '(Codex SessionStart, Pi session_start, DSH agent/created) or, for Claude Code, use it in a new '
        'Claude Code process; the same Claude Code process cannot take control back.',
    )


def route_notice(runner: Path, connection: Mapping[str, Any]) -> Mapping[str, Any]:
    """Address a notice for any earlier Main to the Main currently in control.

    The recorded owner of a member is unchanged; only delivery follows the
    continuation. A connection that is not a Main Session is returned as is.
    A current Main whose Runtime cannot receive host events yet (Pi, DSH)
    keeps the existing delivery to the recorded owner, so nothing is lost.
    """
    current = current_main(runner)
    session = connection.get('session')
    if (current is None or _same(current, connection.get('runtime'), session)
            or current['runtime'] not in RECEIVING_RUNTIMES
            or session not in main_sessions(runner)):
        return connection
    return {**current['connection'], 'runtime': current['runtime'], 'session': current['session']}


def recorded_by_main(runner: Path, recorded: Mapping[str, Any]) -> bool:
    """Whether a root's recorded creator or owner is any verified project Main Session.

    Every verified Main reads these roots as the project's Main working state.
    """
    return recorded.get('agent') is None and recorded.get('session') in main_sessions(runner)


def owns_main_root(runner: Path, recorded: Mapping[str, Any], connection: Mapping[str, Any]) -> bool:
    """Whether a root recorded under ``recorded`` Main belongs to ``connection``'s Main.

    The exact recorded owner always matches. The current Main also continues
    roots that any earlier verified Main Session recorded.
    """
    keys = ('runtime', 'session', 'codex_home')
    if all(recorded.get(key) == connection.get(key) for key in keys):
        return True
    current = current_main(runner)
    return (current is not None and _same(current, connection.get('runtime'), connection.get('session'))
            and recorded.get('session') in main_sessions(runner))


# Main Runtimes whose Adapter delivers host events to a continuing Main.
RECEIVING_RUNTIMES = frozenset({'codex', 'claude'})


def _inbox(runner: Path, runtime: str, session: str) -> Path:
    """Return one pull-only Main host's notice queue."""
    key = hashlib.sha256((runtime + ':' + session).encode()).hexdigest()
    return _directory(runner) / 'inbox' / (key + '.jsonl')


def queue_notice(runner: Path, connection: Mapping[str, Any], event: Mapping[str, Any]) -> dict:
    """Durably queue one notice for the Claude Main host, under the queue lock."""
    path = _inbox(runner, connection['runtime'], connection['session'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'at': time.time(), 'event': dict(event)}, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    return {'accepted': True, 'delivery': 'queued-for-main-host'}


def pending_notices(runner: Path, runtime: str, session: str) -> tuple[list[dict], int]:
    """Return this Main Session's unacknowledged notices and the position after them.

    Nothing is consumed: call :func:`acknowledge_notices` with the position
    only after the notices reached the Main.
    """
    path = _inbox(runner, runtime, session)
    if not path.exists():
        return [], 0
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        lines = path.read_text(encoding='utf-8').splitlines()
        cursor = path.with_suffix('.cursor')
        seen = int(cursor.read_text()) if cursor.exists() else 0
    return [json.loads(line) for line in lines[seen:]], len(lines)


def acknowledge_notices(runner: Path, runtime: str, session: str, position: int) -> None:
    """Atomically record that notices before ``position`` reached the Main."""
    path = _inbox(runner, runtime, session)
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        cursor = path.with_suffix('.cursor')
        if position > (int(cursor.read_text()) if cursor.exists() else 0):
            temporary = cursor.with_suffix('.cursor-new')
            temporary.write_text(str(position))
            os.replace(temporary, cursor)


def _transfer_notices(runner: Path, previous: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    """Hand the earlier Main's undelivered queued notices to the continuing Main.

    The queue exists only for a Claude Main. A continuing Claude Main receives
    them in its own queue; another Runtime keeps them in the earlier queue,
    readable as history (see the reported gap).
    """
    if previous['runtime'] != 'claude' or current['runtime'] != 'claude':
        return
    notices, position = pending_notices(runner, previous['runtime'], previous['session'])
    for notice in notices:
        queue_notice(runner, current, notice['event'])
    if notices:
        acknowledge_notices(runner, previous['runtime'], previous['session'], position)


class MainRoots:
    """``agents`` root policy: every verified Main continues the project's Main roots.

    Hosts construct root callers (no Agent reference, with a Session) only
    after verifying a native Main, so this policy only widens which existing
    Main-created roots such a caller sees, and applies :func:`require_control`.
    """

    def __init__(self, runner: Path) -> None:
        """Bind the project's Runner records."""
        self.runner = runner

    def owns(self, caller: Any, creator: Mapping[str, Any]) -> bool:
        """Whether a root created by ``creator`` belongs to the project Main."""
        return (caller.agent is None and isinstance(caller.session, str)
                and recorded_by_main(self.runner, creator))

    def require_control(self, caller: Any) -> None:
        """Refuse control from a continued Main with the shared explanation."""
        from agent_swarm import AgentsError

        from graphtraj.execution.runner_connection import current_parent_connection

        if caller.session is None:
            return
        # Claim with the host's full connection, so notices can reach it.
        host = current_parent_connection()
        connection = (host if isinstance(host, Mapping) and host.get('session') == caller.session
                      else {'runtime': caller.runtime, 'session': caller.session})
        try:
            require_control(self.runner, connection)
        except RunnerError as error:
            raise AgentsError(error.code, error.message) from None


# Task features that only read, plus features with their own Main policy:
# ``agents`` applies MainRoots and ``bind_main_finalize`` keeps a Main's own
# binding and pause. Every other executable feature is control.
READ_FEATURES = frozenset({
    'agents', 'alias_status', 'bind_main_finalize', 'desktop_activity', 'parent_status',
    'pending_requests', 'project_doctor', 'session_read', 'session_reports',
    'task_graph', 'task_members', 'worldline_read', 'worldline_render',
})


def require_feature_control(feature: str, cwd: Path | None) -> None:
    """Apply :func:`require_control` to a Main caller's Task control feature.

    Managed members keep their own authority and are never gated here; a
    human CLI call has no native connection and is unchanged.
    """
    if feature in READ_FEATURES:
        return
    from graphtraj.execution.runner_connection import current_parent_connection
    from graphtraj.execution.runner_status import caller_alias
    from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, current_host_connection
    from graphtraj.workspace.runner_project import discover_runner_directory

    try:
        runner = discover_runner_directory(cwd or Path.cwd())
        if caller_alias(runner) is not None:
            return  # A member or native helper keeps its own authority.
    except RunnerError:
        return  # Identity failures stay with the feature's own authorization.
    connection = current_parent_connection()
    if not isinstance(connection, Mapping):
        try:
            connection = current_host_connection()
        except RuntimeAdapterError:
            return
    require_control(runner, connection)
