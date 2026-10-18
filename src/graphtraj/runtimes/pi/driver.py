"""Pi control with explicitly resolved native settings and no Task lookup."""
from copy import deepcopy

from agent_swarm import AgentsError, Caller
from graphtraj.execution.agent_driver import AdapterDriver


class PiDriver(AdapterDriver):
    """Bind a host-prepared Pi launch request to the independent control core.

    The host resolves model/provider, resource references and native isolation
    before binding. This driver retains that exact request for continuation;
    it does not discover GraphTraj configuration, Tasks, reports or Git.
    """

    def __init__(self, request: dict) -> None:
        """Keep a detached, already validated native launch configuration."""
        self.request = deepcopy(request)

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Return the chosen native configuration without reading project state."""
        if runtime != 'pi':
            raise AgentsError('unsupported-runtime', 'PiDriver only runs Pi.')
        return {'adapter_request': deepcopy(self.request), 'evidence': {},
                'cwd': self.request['worktree_path']}
