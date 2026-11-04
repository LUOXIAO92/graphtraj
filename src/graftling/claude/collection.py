"""Collect a Claude native hook's own transcript into a supplied archive.

The hook event names its transcript; nothing here scans a Runtime home or
discovers a project. Native helper (child) transcripts are scoped to their
parent Session and never become a fork relationship.
"""
from __future__ import annotations

from pathlib import Path

from graftling.sessions.archive import JsonlSessionStore, SessionArchive, archive_path


def hook_source(
    event: dict,
    cwd: Path,
    *,
    native_id: str | None = None,
) -> tuple[str, str, str | None, str]:
    """Validate the exact native hook association without interpreting its history.

    A caller that owns the Session's channel passes its ``native_id``: the event
    must name that Session, and its cwd is not compared because a Bash ``cd``
    moves it. Without one, the event's cwd must equal ``cwd``.

    Returns ``(kind, native_id, child_id, transcript_path)``; ``child_id`` is
    ``None`` for the Session itself.
    """
    expected = native_id
    kind = event.get('hook_event_name')
    if kind not in {'SessionStart', 'Stop', 'StopFailure', 'SessionEnd', 'SubagentStop'}:
        raise ValueError('Unsupported Claude collection hook.')
    native_id = event.get('session_id')
    if not isinstance(native_id, str) or not native_id:
        raise ValueError('Native Session identity is required.')
    child = event.get('agent_id')
    if child is not None and (not isinstance(child, str) or not child):
        raise ValueError('Native child identity must be a nonempty string.')
    if kind == 'SubagentStop' and not child:
        raise ValueError('Native child identity is required.')
    path = event.get('agent_transcript_path' if child else 'transcript_path')
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('The native source must supply its own absolute transcript path.')
    if child and event.get('transcript_path') and Path(path).resolve() == Path(event['transcript_path']).resolve():
        raise ValueError('The parent transcript is not the child transcript.')
    if expected is not None:
        if native_id != expected:
            raise ValueError('Hook Session differs from the owned Session.')
    elif event.get('cwd') and Path(event['cwd']).resolve() != cwd.resolve():
        raise ValueError('Hook working directory differs from collection entry.')
    return kind, native_id, child, path


def collect_hook_event(
    archive: SessionArchive,
    event: dict,
    cwd: Path,
    *,
    extra_fields: dict | None = None,
    native_id: str | None = None,
) -> dict:
    """Collect the hook's associated transcript into ``archive``.

    ``cwd`` is the collection entry, kept in a new header whatever directory the
    event names. ``native_id`` is as in ``hook_source``. ``extra_fields`` is
    written to a newly created header only; an existing archive keeps its
    original header. Returns the archive identity, the native source kind and
    whether anything was saved.
    """
    from graftling.sessions.claude import ClaudeJsonlCollector

    kind, native_id, child, path = hook_source(event, cwd, native_id=native_id)

    # A resumed native Session continues from the boundary its SessionStart recorded.
    retained      = archive.native_header('claude', native_id, agent_id=child)
    history_count = None
    if retained and kind != 'SessionStart':
        previous      = JsonlSessionStore(archive_path(archive.root, retained['id']))
        boundary      = previous.position('claude-hook-boundary')
        history_count = boundary if boundary >= 0 else None

    collector = ClaudeJsonlCollector(archive, native_id, cwd, 'native-hook',
                                     child_id=child, history_count=history_count,
                                     resumed=kind != 'SessionStart' or event.get('source') != 'startup',
                                     extra_fields=extra_fields)
    collector.bind(Path(path))
    store = archive.store(collector.identity) if collector.header is not None else None
    if store is not None:
        if kind == 'SessionStart':
            store.mark_boundary('claude-hook-boundary', collector.history_count)
        position = store.position('native-hook') + 1
        collector.accept(event, position)
        collector.close()
    return {'session_id': collector.identity, 'source': 'child' if child else 'native-session',
            'saved': store is not None}
