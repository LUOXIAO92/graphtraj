"""Transitional ``tasks`` session_read: agents' Session reading in the old page shape."""
from pathlib import Path

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.desktop_activity import human_observer
from graphtraj.execution.runner_status import require_project_reader
from graphtraj.sessions.storage import SessionStore, session_path
from graftling.sessions import find_session, read_events, redact_session
from graphtraj.workspace.runner_project import discover_runner_directory


def read_session(cwd: Path, session_id: str, after: int = -1, limit: int = 200) -> dict:
    """Read final events after ``after`` and the durable draft, as ``tasks`` always has.

    Forwards to agents' ``session_read`` reading with ``content: all`` and the
    slice ``[after + 1:after + 1 + limit]``. Human observers are bound to their
    project and read unredacted. Any verified project caller, including Main
    under its native identity, reads the project's linked Sessions with
    credentials and control material redacted, the same project policy as
    agents' ``session_read``. Agent IDs and Task IDs in content grant nothing;
    no caller supplies a filesystem path. A project not yet migrated to JSONL
    archives still reads its SQLite Session.
    """
    from graphtraj.interfaces.agents import swarm_root
    from graphtraj.interfaces.desktop_host import owns_project

    window = human_observer.get() and owns_project(cwd)
    # Project development history crosses Agents and models under the
    # caller's real identity; an unknown native source is refused, never human.
    if not window:
        require_project_reader(discover_runner_directory(cwd))
    if type(after) is not int or after < -1 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Use after >= -1 and limit between 1 and 1000.')

    configuration = load_project_configuration(cwd)
    store = find_session(swarm_root(configuration.harness_root), session_id)
    if store is None:
        if (configuration.harness_root / '.graphtraj/core/config.yml').exists():
            raise ValueError('Canonical JSONL Session is unavailable; legacy backups are not a query fallback.')
        result = _unmigrated_page(configuration.state, session_id, after, limit)
        return result if window else redact_session(result)

    start, stop = after + 1, after + 1 + limit
    document = read_events(store, start=start, stop=stop, content='all', redacted=not window)
    events = [item['event'] for item in document['events']]
    result = {'header': document['header'], 'events': events,
              'after': events[-1]['seq'] if events else after, 'has_more': stop < document['total'],
              'revision': document['revision'], 'pending': document['pending']}
    legacy = document.get('legacy')
    if legacy:
        total = legacy.pop('total')
        retained = legacy['events']
        legacy.update(has_more=stop < total, after=retained[-1]['seq'] if retained else after,
                      native_order_verified=False)
        result['legacy'] = legacy
    return result


def _unmigrated_page(state: Path, session_id: str, after: int, limit: int) -> dict:
    """Read one page of a SQLite Session from before the explicit partition.

    A bare native ID selects its one runtime-prefixed archive.
    """
    if not session_path(state, session_id).exists():
        prefixed = [runtime + ':' + session_id for runtime in ('codex', 'claude', 'pi', 'dsh')
                    if session_path(state, runtime + ':' + session_id).exists()]
        if len(prefixed) == 1:
            session_id = prefixed[0]
    with SessionStore(session_path(state, session_id), readonly=True) as store:
        store.db.execute('BEGIN')
        header = store.header
        if header['id'] != session_id:
            raise ValueError('Session archive identity does not match its location.')
        return {'header': header, **store.page(after, limit), 'pending': store.pending()}
