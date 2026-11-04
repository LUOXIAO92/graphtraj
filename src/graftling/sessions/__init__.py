"""Built-in optional Session protocol, JSONL archive and native collectors.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from graftling import _lazy_names

__getattr__ = _lazy_names({
    'ConfiguredSessionArchive': ('graftling.sessions.archive', 'ConfiguredSessionArchive'),
    'JsonlSessionStore': ('graftling.sessions.archive', 'JsonlSessionStore'),
    'SessionArchive': ('graftling.sessions.archive', 'SessionArchive'),
    'archive_path': ('graftling.sessions.archive', 'archive_path'),
    'INITIAL_COLLECTION_TYPE': ('graftling.sessions.protocol', 'INITIAL_COLLECTION_TYPE'),
    'SESSION_FORMAT_VERSION': ('graftling.sessions.protocol', 'SESSION_FORMAT_VERSION'),
    'append_stream_record': ('graftling.sessions.protocol', 'append_stream_record'),
    'native_record': ('graftling.sessions.protocol', 'native_record'),
    'retain_native': ('graftling.sessions.protocol', 'retain_native'),
    'snapshot_event': ('graftling.sessions.protocol', 'snapshot_event'),
    'upgrade_event': ('graftling.sessions.protocol', 'upgrade_event'),
    'upgrade_header': ('graftling.sessions.protocol', 'upgrade_header'),
    'validate_header': ('graftling.sessions.protocol', 'validate_header'),
    'validate_session': ('graftling.sessions.protocol', 'validate_session'),
    'CodexJsonlArchive': ('graftling.sessions.codex', 'CodexJsonlArchive'),
    'NativeInputError': ('graftling.sessions.codex', 'NativeInputError'),
    'rollout_record': ('graftling.sessions.codex', 'rollout_record'),
    'CodexHistoryArchive': ('graftling.sessions.codex_history', 'CodexHistoryArchive'),
    'codex_attachments': ('graftling.sessions.codex_values', 'codex_attachments'),
    'DshArchive': ('graftling.sessions.dsh', 'DshArchive'),
    'attachment_refs': ('graftling.sessions.dsh', 'attachment_refs'),
    'attempt_usage': ('graftling.sessions.dsh', 'attempt_usage'),
    'collect_jsonl': ('graftling.sessions.dsh', 'collect_jsonl'),
    'DshLiveFrames': ('graftling.sessions.dsh_live', 'DshLiveFrames'),
    'PiArchive': ('graftling.sessions.pi', 'PiArchive'),
    'import_native': ('graftling.sessions.migration', 'import_native'),
    'import_sqlite': ('graftling.sessions.migration', 'import_sqlite'),
    'verify_sqlite': ('graftling.sessions.migration', 'verify_sqlite'),
})

__all__ = [
    'ConfiguredSessionArchive', 'JsonlSessionStore', 'SessionArchive',
    'archive_path', 'INITIAL_COLLECTION_TYPE', 'SESSION_FORMAT_VERSION',
    'append_stream_record', 'native_record', 'retain_native', 'snapshot_event',
    'upgrade_event', 'upgrade_header', 'validate_header', 'validate_session',
    'CodexJsonlArchive', 'NativeInputError', 'rollout_record',
    'CodexHistoryArchive', 'codex_attachments', 'DshArchive', 'attachment_refs',
    'attempt_usage', 'collect_jsonl', 'DshLiveFrames', 'PiArchive',
    'import_native', 'import_sqlite', 'verify_sqlite',
]
