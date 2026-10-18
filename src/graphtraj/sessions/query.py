"""Authorized reads of project-local Session archives through the shared gateway."""
from pathlib import Path
from contextlib import ExitStack

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution.desktop_activity import human_observer
from graphtraj.execution.runner_connection import current_parent_connection
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import (
    NativeCaller, caller_alias, read_alias_mapping, runtime_caller_is_bound,
)
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.sessions.storage import SessionStore, session_path
from graphtraj.sessions.archive import JsonlSessionStore, archive_path
from graphtraj.workspace.runner_project import discover_runner_directory


def read_session(cwd: Path, session_id: str, after: int = -1, limit: int = 200) -> dict:
    """Read final events and a recoverable draft under existing activity authority.

    Human observers are bound to their project. A native Agent must have an
    authenticated Runner mapping, and that mapping must match the archive's
    retained native provenance. Agent IDs and Task IDs in content grant nothing.
    No caller supplies a filesystem path or a claimed role.
    """
    from graphtraj.interfaces.desktop_host import owns_project

    runner = discover_runner_directory(cwd)
    window = human_observer.get() and owns_project(cwd)
    caller = None if window else caller_alias(runner)
    own = None
    if caller is not None and not isinstance(caller, NativeCaller):
        own, _ = read_alias_mapping(runner, caller)
    elif not window and (not human_observer.get() or runtime_caller_is_bound()
                         or current_parent_connection() is not None
                         or caller_runtime() is not None or caller is not None):
        raise RunnerError('authority-denied', 'Session reads require a verified own Session or human project binding.')

    configuration = load_project_configuration(cwd)
    from graphtraj.interfaces.agents import swarm_root

    normalized = archive_path(swarm_root(configuration.harness_root), session_id)
    with ExitStack() as resources:
        if normalized.is_file():
            # JSONL loads the body with its metadata; check the verified native
            # identity before opening a different Agent's conversation.
            if own is not None and session_id != own['runtime'] + ':' + own['session']:
                raise RunnerError('authority-denied', 'Agent archive access is limited to its own verified native Session.')
            store = JsonlSessionStore(normalized)
        else:
            # Other Runtime collectors still use the retained SQLite format.
            store = resources.enter_context(SessionStore(session_path(configuration.state, session_id), readonly=True))
            store.db.execute('BEGIN')
        header = store.header
        native = header.get('graphtraj', {}).get('native', {})
        if own is not None and (native.get('runtime') != own['runtime']
                                or native.get('sessionId') != own['session']
                                or native.get('agentId') is not None):
            raise RunnerError('authority-denied', 'Agent archive access is limited to its own verified native Session.')
        if header['id'] != session_id:
            raise ValueError('Session archive identity does not match its location.')
        return {'header': header, **store.page(after, limit), 'pending': store.pending()}
