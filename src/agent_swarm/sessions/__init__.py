"""Built-in optional Session protocol, JSONL archive and native collectors.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from agent_swarm import _lazy_names

__getattr__ = _lazy_names({
    'ConfiguredSessionArchive': ('agent_swarm.sessions.archive', 'ConfiguredSessionArchive'),
    'JsonlSessionStore': ('agent_swarm.sessions.archive', 'JsonlSessionStore'),
    'SessionArchive': ('agent_swarm.sessions.archive', 'SessionArchive'),
    'archive_path': ('agent_swarm.sessions.archive', 'archive_path'),
    'INITIAL_COLLECTION_TYPE': ('agent_swarm.sessions.protocol', 'INITIAL_COLLECTION_TYPE'),
    'SESSION_FORMAT_VERSION': ('agent_swarm.sessions.protocol', 'SESSION_FORMAT_VERSION'),
    'append_stream_record': ('agent_swarm.sessions.protocol', 'append_stream_record'),
    'native_record': ('agent_swarm.sessions.protocol', 'native_record'),
    'retain_native': ('agent_swarm.sessions.protocol', 'retain_native'),
    'snapshot_event': ('agent_swarm.sessions.protocol', 'snapshot_event'),
    'upgrade_event': ('agent_swarm.sessions.protocol', 'upgrade_event'),
    'upgrade_header': ('agent_swarm.sessions.protocol', 'upgrade_header'),
    'validate_header': ('agent_swarm.sessions.protocol', 'validate_header'),
    'validate_session': ('agent_swarm.sessions.protocol', 'validate_session'),
    'CodexJsonlArchive': ('agent_swarm.sessions.codex', 'CodexJsonlArchive'),
    'NativeInputError': ('agent_swarm.sessions.codex', 'NativeInputError'),
    'rollout_record': ('agent_swarm.sessions.codex', 'rollout_record'),
    'CodexHistoryArchive': ('agent_swarm.sessions.codex_history', 'CodexHistoryArchive'),
    'codex_attachments': ('agent_swarm.sessions.codex_values', 'codex_attachments'),
    'DshArchive': ('agent_swarm.sessions.dsh', 'DshArchive'),
    'attachment_refs': ('agent_swarm.sessions.dsh', 'attachment_refs'),
    'attempt_usage': ('agent_swarm.sessions.dsh', 'attempt_usage'),
    'collect_jsonl': ('agent_swarm.sessions.dsh', 'collect_jsonl'),
    'DshLiveFrames': ('agent_swarm.sessions.dsh_live', 'DshLiveFrames'),
    'PiArchive': ('agent_swarm.sessions.pi', 'PiArchive'),
    'import_native': ('agent_swarm.sessions.migration', 'import_native'),
    'import_sqlite': ('agent_swarm.sessions.migration', 'import_sqlite'),
    'verify_sqlite': ('agent_swarm.sessions.migration', 'verify_sqlite'),
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
