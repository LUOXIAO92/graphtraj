"""DSH native capabilities with no GraphTraj dependency.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from graftling import _lazy_names

from .errors import DshError
from .service import DshService
from .driver import DshDriver

__getattr__ = _lazy_names({
    'DshExecution': ('graftling.dsh.execution', 'DshExecution'),
    'bind_run': ('graftling.dsh.binding', 'bind_run'),
    'session_context': ('graftling.dsh.binding', 'session_context'),
    'dsh_version_refusal': ('graftling.dsh.settings', 'dsh_version_refusal'),
})

__all__ = [
    'DshError', 'DshService', 'DshDriver', 'DshExecution', 'bind_run',
    'session_context', 'dsh_version_refusal',
]
