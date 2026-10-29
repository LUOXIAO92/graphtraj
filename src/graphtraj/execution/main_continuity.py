"""Project Main continuity shared by every Runtime that can host Main.

A project has one Main working state: the Main-owned root Agents, their
recursive hierarchy, pending notices and results and the current summary
scope. Each verified external Main Session (Codex, Claude Code, Pi or DSH)
continues that state instead of starting an empty one. This module keeps the
only continuity record and the single decision point for who may control it::

    <runner>/main-sessions/continuity.jsonl   append-only control claims
    <runner>/main-sessions/inbox/<key>.jsonl  notices for a pull-only Main host,
                                              or handed over to a Codex Main
    <runner>/main-sessions/inbox/<key>.receipts  time up to which a Codex Main's
                                              retained receipts were shown

A claim is a new associated record. It never rewrites a historical parent,
a member identity, a Session binding or a native log. Runtime entries supply
an already verified native connection; nothing here verifies identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
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


def _unclaimed_codex_entry(runner: Path, runtime: Any, session: str) -> dict | None:
    """Return a Codex Main binding whose native entry never continued Main.

    Codex continues at SessionStart, and its native hook Session identifies
    that entry (caller identity has already matched it to the live thread). A
    binding whose entry recorded no claim (one written by an installation
    before continuity existed) continues Main at its first control.
    Once that hook Session has claimed, it is refused after another Main
    continues until Codex starts or resumes it again.
    """
    import yaml

    if runtime != 'codex':
        return None
    key = hashlib.sha256(('codex:' + session).encode()).hexdigest()
    path = _directory(runner) / ('finalize_' + key) / 'session.yml'
    if not path.is_file():
        return None
    connection = yaml.safe_load(path.read_text(encoding='utf-8'))['connection']
    hook = connection.get('hook_session')
    if not isinstance(hook, str) or any(
            _same(record, 'codex', session) and record['connection'].get('hook_session') == hook
            for record in claims(runner)):
        return None
    return {**connection, 'runtime': 'codex', 'session': session}


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
    entry = _unclaimed_codex_entry(runner, runtime, session)
    if entry is not None:
        claim_main(runner, entry, 'codex:first-control')
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
    A pull-only Main host (Claude Code, Pi, DSH) reads this project's queue,
    so its address also names ``runner``.
    """
    current = current_main(runner)
    session = connection.get('session')
    if not (current is None or _same(current, connection.get('runtime'), session)
            or current['runtime'] not in RECEIVING_RUNTIMES
            or session not in main_sessions(runner)):
        connection = {**current['connection'], 'runtime': current['runtime'], 'session': current['session']}
    if connection.get('runtime') in QUEUED_RUNTIMES:
        connection = {**connection, 'runner': str(runner)}
    return connection


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
RECEIVING_RUNTIMES = frozenset({'codex', 'claude', 'pi', 'dsh'})

# Main hosts without a push channel: their notices wait in the project's
# durable queue until the host's own entry delivers and acknowledges them.
QUEUED_RUNTIMES = frozenset({'claude', 'pi', 'dsh'})


def _inbox(runner: Path, runtime: str, session: str) -> Path:
    """Return one pull-only Main host's notice queue."""
    key = hashlib.sha256((runtime + ':' + session).encode()).hexdigest()
    return _directory(runner) / 'inbox' / (key + '.jsonl')


def _write_cursor(cursor: Path, position: int) -> None:
    """Atomically replace one queue cursor."""
    temporary = cursor.with_suffix('.cursor-new')
    temporary.write_text(str(position))
    os.replace(temporary, cursor)


def _ended(path: Path) -> set[str]:
    """Executions whose end this Main already saw in a wait or status result."""
    try:
        return set(path.with_suffix('.ended').read_text(encoding='utf-8').split())
    except FileNotFoundError:
        return set()


def queue_notice(runner: Path, connection: Mapping[str, Any], event: Mapping[str, Any]) -> dict:
    """Durably queue one notice for a pull-only Main host, under the queue lock.

    A notice with a stable ``id`` (execution, event and any request) is
    queued once: a retried delivery of the same event adds nothing.
    """
    from agent_swarm.notices import notice_id

    path = _inbox(runner, connection['runtime'], connection['session'])
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = event.get('id') or notice_id(
        event.get('execution'), event.get('event'), event.get('request_id'))
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        if identity is not None and path.exists() and any(
                json.loads(line).get('id') == identity
                for line in path.read_text(encoding='utf-8').splitlines() if line.strip()):
            return {'accepted': True, 'delivery': 'queued-for-main-host'}
        # Every queued notice has an id, so a failed push can return it.
        record = {'at': time.time(), 'event': dict(event), 'id': identity or uuid.uuid4().hex}
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    return {'accepted': True, 'delivery': 'queued-for-main-host'}


def claim_notices(runner: Path, runtime: str, session: str) -> list[dict]:
    """Atomically take this Main Session's undelivered notices.

    Every reader (a tool result, the host's push, a native entry) claims under
    the queue lock, so one notice is handed to one reader only. An end the
    Main already saw through ``wait`` or ``status`` is skipped. A reader that
    could not deliver returns its notices with :func:`requeue_notices`.
    """
    path = _inbox(runner, runtime, session)
    if not path.exists():
        return []
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        lines = path.read_text(encoding='utf-8').splitlines()
        cursor = path.with_suffix('.cursor')
        seen = int(cursor.read_text()) if cursor.exists() else 0
        if seen >= len(lines):
            return []
        ended = _ended(path)
        _write_cursor(cursor, len(lines))
    return [notice for notice in map(json.loads, lines[seen:]) if not _shown(notice, ended)]


def _shown(notice: Mapping[str, Any], ended: set[str]) -> bool:
    """Whether a queued end notice names an end the Main already saw."""
    from agent_swarm.notices import END_EVENTS

    return notice['event'].get('execution') in ended and notice['event'].get('event') in END_EVENTS


def shown_ends(result: Mapping[str, Any]) -> list[str]:
    """Executions whose end one ``agents`` wait or status result shows.

    A core Agent in standby shows its last result; an idle Task member names
    its last execution. A running execution's end is not shown yet.
    """
    aliases = result.get('aliases')
    member = aliases[0] if isinstance(aliases, list) and aliases else result
    if isinstance(result.get('last_result'), Mapping) and result.get('state') == 'standby':
        return [result['last_result'].get('id')]
    if isinstance(member, Mapping) and member.get('activity') == 'idle':
        return [member.get('execution_id')]
    return []


def requeue_notices(runner: Path, runtime: str, session: str, identities: list[str]) -> int:
    """Queue again claimed notices that did not reach the Main; return how many.

    Only notices already in this queue are re-added, by their stable ``id``,
    and one still waiting is never added twice.
    """
    path = _inbox(runner, runtime, session)
    if not path.exists() or not identities:
        return 0
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        lines = path.read_text(encoding='utf-8').splitlines()
        cursor = path.with_suffix('.cursor')
        seen = int(cursor.read_text()) if cursor.exists() else 0
        waiting = {json.loads(line).get('id') for line in lines[seen:]}
        found: dict[str, dict] = {}
        for line in lines[:seen]:
            record = json.loads(line)
            if record.get('id') in identities and record['id'] not in waiting:
                found[record['id']] = record
        with path.open('a', encoding='utf-8') as stream:
            for identity in identities:
                if identity in found:
                    stream.write(json.dumps({**found[identity], 'at': time.time()}, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    return sum(identity in found for identity in identities)


def acknowledge_ends(runner: Path, runtime: str, session: str, executions: list[str]) -> None:
    """Record that this Main saw these executions' ends in a ``wait`` or ``status`` result.

    Their end notices, queued before or after, are no longer pushed.
    """
    executions = [item for item in executions if isinstance(item, str) and item]
    if not executions:
        return
    path = _inbox(runner, runtime, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        new = [item for item in executions if item not in _ended(path)]
        if new:
            with path.with_suffix('.ended').open('a', encoding='utf-8') as stream:
                stream.write(''.join(item + '\n' for item in new))


def queue_host_notice(connection: Mapping[str, Any], event: Mapping[str, Any]) -> dict:
    """Queue a notice for the pull-only Main host whose address names its project.

    This is the ``send_host_event`` of the Claude Code, Pi and DSH Adapters;
    :func:`route_notice` adds ``runner`` to their addresses.
    """
    runner = connection.get('runner')
    if not isinstance(runner, str) or not Path(runner).is_absolute():
        raise RunnerError('operation-unavailable', 'The Main host connection has no project.')
    return queue_notice(Path(runner), connection, event)


def render_notices(notices: list[dict]) -> str:
    """Return queued notices as one plain-text Main input, as the Claude host shows them."""
    return '\n\n'.join(
        f"[GraphTraj notice from {item['event'].get('alias', 'graphtraj')} · {item['event'].get('event', 'event')}]\n"
        f"{item['event'].get('message', json.dumps(item['event'], ensure_ascii=False))}"
        for item in notices
    )


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
        ended = _ended(path)
    return [notice for notice in map(json.loads, lines[seen:])
            if not _shown(notice, ended)], len(lines)


def acknowledge_notices(runner: Path, runtime: str, session: str, position: int) -> None:
    """Atomically record that notices before ``position`` reached the Main."""
    path = _inbox(runner, runtime, session)
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        cursor = path.with_suffix('.cursor')
        if position > (int(cursor.read_text()) if cursor.exists() else 0):
            _write_cursor(cursor, position)


def _transfer_notices(runner: Path, previous: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    """Hand the earlier Main's undelivered notices to the continuing Main, once.

    Notices still in the earlier Main's queue are claimed from it and queued
    for the continuing Main, whichever Runtime: a Codex Main takes its queue
    at its SessionStart. Retained ordinary receipts no Codex hook has shown
    yet, addressed to the earlier Codex Main or to any Codex Main whose roots
    it continued, go to a continuing pull-only Main's queue; a continuing
    Codex Main shows them at its own hook. Either way no earlier Main
    receives them any more.
    """
    for notice in claim_notices(runner, previous['runtime'], previous['session']):
        queue_notice(runner, current, notice['event'])
    if previous['runtime'] != 'codex' or current['runtime'] not in QUEUED_RUNTIMES:
        return
    # Each Codex Main's receipts since its latest claim, after its shown point.
    claimed = {record['session']: record['at'] for record in claims(runner) if record['runtime'] == 'codex'}
    shown = {session: max(receipts_shown(runner, 'codex', session), at) for session, at in claimed.items()}
    handed: dict[str, float] = {}
    for record, notice in retained_receipts(runner):
        session = record['parent_connection']['session']
        if (record.get('held') or record['parent_connection']['runtime'] != 'codex'
                or session not in shown or record['at'] <= shown[session]):
            continue
        queue_notice(runner, current, {**notice, 'execution': record.get('identity', {}).get('execution_id')})
        handed[session] = max(handed.get(session, 0.0), record['at'])
    for session, through in handed.items():
        show_receipts(runner, 'codex', session, through)


def retained_receipts(runner: Path) -> list[tuple[dict, dict]]:
    """Return every retained ordinary receipt addressed to a Main host, with its notice."""
    receipts = []
    for path in sorted((runner / 'sessions').glob('*/parent-notices.jsonl')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
                notice = json.loads(record['notice'])
            except (ValueError, KeyError, TypeError):
                continue
            address = record.get('parent_connection')
            if (record.get('delivery') == 'retained' and isinstance(address, dict)
                    and isinstance(address.get('runtime'), str) and isinstance(address.get('session'), str)):
                receipts.append((record, notice))
    return receipts


def receipts_shown(runner: Path, runtime: str, session: str) -> float:
    """Return the time up to which this Main's retained receipts were shown or handed over."""
    try:
        return float(_inbox(runner, runtime, session).with_suffix('.receipts').read_text())
    except FileNotFoundError:
        return 0.0


def show_receipts(runner: Path, runtime: str, session: str, through: float) -> None:
    """Record that this Main's retained receipts up to ``through`` reached a Main."""
    path = _inbox(runner, runtime, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        if through > receipts_shown(runner, runtime, session):
            _write_cursor(path.with_suffix('.receipts'), through)


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
