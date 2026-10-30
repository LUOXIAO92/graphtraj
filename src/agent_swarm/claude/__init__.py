"""Independent Claude Code SDK control.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from agent_swarm import _lazy_names

from .driver import ClaudeDriver

__getattr__ = _lazy_names({
    'ClaudeExecution': ('agent_swarm.claude.execution', 'ClaudeExecution'),
    'collect_hook_event': ('agent_swarm.claude.collection', 'collect_hook_event'),
    'hook_source': ('agent_swarm.claude.collection', 'hook_source'),
    'NativeCalls': ('agent_swarm.claude.native_host', 'NativeCalls'),
    'claude_host_plugin': ('agent_swarm.claude.plugin', 'claude_host_plugin'),
    'REFUSAL_FILE': ('agent_swarm.claude.host', 'REFUSAL_FILE'),
    'claim_channel': ('agent_swarm.claude.host', 'claim_channel'),
    'context_endpoint': ('agent_swarm.claude.host', 'context_endpoint'),
    'ended_by_claude': ('agent_swarm.claude.host', 'ended_by_claude'),
    'log_replaced_channel': ('agent_swarm.claude.host', 'log_replaced_channel'),
    'require_free_channel': ('agent_swarm.claude.host', 'require_free_channel'),
    'serve_refusal': ('agent_swarm.claude.host', 'serve_refusal'),
})

__all__ = [
    'ClaudeDriver', 'ClaudeExecution', 'collect_hook_event', 'hook_source',
    'NativeCalls', 'REFUSAL_FILE', 'claim_channel', 'context_endpoint',
    'ended_by_claude', 'log_replaced_channel', 'require_free_channel',
    'serve_refusal', 'claude_host_plugin',
]
