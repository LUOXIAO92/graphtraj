"""Authorized reads of project-local Session archives through the shared gateway."""
from pathlib import Path
from contextlib import ExitStack

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.desktop_activity import human_observer
from graphtraj.execution.runner_status import project_redact, require_project_reader
from graphtraj.sessions.storage import SessionStore, session_path
from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from graphtraj.workspace.runner_project import discover_runner_directory


def read_session(cwd: Path, session_id: str, after: int = -1, limit: int = 200) -> dict:
    """Read final events and a recoverable draft under existing activity authority.

    Human observers are bound to their project. Any verified project caller,
    including Main under its native identity, reads the project's linked
    Sessions with credentials and control material redacted. Agent IDs and
    Task IDs in content grant nothing; no caller supplies a filesystem path.
    Native IDs select the latest linked project Session; explicit project IDs
    continue to select their own retained history across native boundaries.
    """
    from graphtraj.interfaces.desktop_host import owns_project

    runner = discover_runner_directory(cwd)
    window = human_observer.get() and owns_project(cwd)
    # Project development history crosses Agents and models under the
    # caller's real identity; an unknown native source is refused, never human.
    if not window:
        require_project_reader(runner)

    configuration = load_project_configuration(cwd)
    from graphtraj.interfaces.agents import swarm_root

    root = swarm_root(configuration.harness_root)
    normalized = archive_path(root, session_id)
    if not normalized.is_file():
        # A native Session ID such as CODEX_THREAD_ID selects its retained archive.
        archive = SessionArchive(root)
        for runtime in ('codex', 'claude', 'pi', 'dsh'):
            header = archive.native_header(runtime, session_id)
            if header:
                session_id = header['id']
                normalized = archive_path(root, session_id)
                break
    with ExitStack() as resources:
        if normalized.is_file():
            store = JsonlSessionStore(normalized)
        else:
            if (configuration.harness_root / '.graphtraj/core/config.yml').exists():
                raise ValueError('Canonical JSONL Session is unavailable; legacy backups are not a query fallback.')
            # Unmigrated history remains readable before the explicit partition.
            store = resources.enter_context(SessionStore(session_path(configuration.state, session_id), readonly=True))
            store.db.execute('BEGIN')
        header = store.header
        if header['id'] != session_id:
            raise ValueError('Session archive identity does not match its location.')
        page = store.page(after, limit)
        legacy = store.legacy() if isinstance(store, JsonlSessionStore) else None
        if legacy:
            retained = [event for event in legacy['events'] if event['seq'] > after]
            legacy.update(events=retained[:limit], has_more=len(retained) > limit,
                          after=retained[min(len(retained), limit) - 1]['seq'] if retained else after,
                          native_order_verified=False)
        result = {'header': header, **page, 'pending': store.pending(),
                  **({'legacy': legacy} if legacy else {})}
        return result if window else project_redact(result)
