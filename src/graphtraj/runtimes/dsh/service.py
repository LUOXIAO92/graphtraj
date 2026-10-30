"""GraphTraj error contract over the independent DSH native service."""

from agent_swarm.dsh import DshService as NativeDshService
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


class DshService(NativeDshService):
    """Use the common native implementation with GraphTraj's error boundary."""

    error_type = RuntimeAdapterError
