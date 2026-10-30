"""Independent native Pi control: RPC owner, extension host and driver.

Public names are listed in ``PUBLIC_API.md`` section 1.3; submodules are internal.
"""
from agent_swarm import _lazy_names

from .driver import PiDriver

__getattr__ = _lazy_names({
    'PiExecution': ('agent_swarm.pi.execution', 'PiExecution'),
    'current_connection': ('agent_swarm.pi.session', 'current_connection'),
    'session_record': ('agent_swarm.pi.session', 'session_record'),
    'session_source': ('agent_swarm.pi.session', 'session_source'),
    'verify_main': ('agent_swarm.pi.session', 'verify_main'),
    'pi_destination': ('agent_swarm.models', 'pi_destination'),
})

__all__ = [
    'PiDriver', 'PiExecution', 'current_connection', 'session_record',
    'session_source', 'verify_main', 'pi_destination',
]
