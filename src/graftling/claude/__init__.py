"""Independent Claude Code SDK control.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from graftling import _lazy_names

from .driver import ClaudeDriver

__getattr__ = _lazy_names({
    'ClaudeExecution': ('graftling.claude.execution', 'ClaudeExecution'),
    'collect_hook_event': ('graftling.claude.collection', 'collect_hook_event'),
    'hook_source': ('graftling.claude.collection', 'hook_source'),
    'NativeCalls': ('graftling.claude.native_host', 'NativeCalls'),
    'claude_host_plugin': ('graftling.claude.plugin', 'claude_host_plugin'),
    'kept_host_paths': ('graftling.claude.plugin', 'kept_host_paths'),
    'write_adoption': ('graftling.claude.plugin', 'write_adoption'),
    'REFUSAL_FILE': ('graftling.claude.host', 'REFUSAL_FILE'),
    'claim_channel': ('graftling.claude.host', 'claim_channel'),
    'context_endpoint': ('graftling.claude.host', 'context_endpoint'),
    'ended_by_claude': ('graftling.claude.host', 'ended_by_claude'),
    'log_replaced_channel': ('graftling.claude.host', 'log_replaced_channel'),
    'require_free_channel': ('graftling.claude.host', 'require_free_channel'),
    'serve_refusal': ('graftling.claude.host', 'serve_refusal'),
})

__all__ = [
    'ClaudeDriver', 'ClaudeExecution', 'collect_hook_event', 'hook_source',
    'NativeCalls', 'REFUSAL_FILE', 'claim_channel', 'context_endpoint',
    'ended_by_claude', 'log_replaced_channel', 'require_free_channel',
    'serve_refusal', 'claude_host_plugin', 'kept_host_paths', 'write_adoption',
]
