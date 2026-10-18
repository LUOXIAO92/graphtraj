"""Bind a Task-free DSH execution to the common Agents function handler."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

from agent_swarm import AgentControl, Caller, Run, bind

from graphtraj.execution.runner_connection import worker_connection
from graphtraj.execution.runner_process import process_ancestors
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError

if TYPE_CHECKING:
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.runtimes.dsh.execution import DshExecution


def bind_agents(turn: DshExecution, run: Run, driver: AdapterDriver) -> None:
    """Attach a host-owned function channel without Runner or Task identity.

    The existing pipe authenticates the writer PID. Only the owned DSH service
    and its descendants can use this execution's channel; tool arguments never
    select the caller. Native permissions remain enforced by DSH.
    """
    from graphtraj.execution.agent_driver import SUPPORTED_RUNTIMES
    from graphtraj.interfaces.agents import swarm_root

    control = AgentControl(swarm_root(driver.root), {name: driver for name in SUPPORTED_RUNTIMES})

    @contextmanager
    def connection(directory: Path) -> Iterator[str]:
        """Serve Agents calls while this exact native service remains owned."""
        directory.mkdir(parents=True, exist_ok=True)

        def authenticate(pid: int) -> None:
            """Reject any writer outside this native service's process ancestry."""
            service = turn.service
            process = service.process if service is not None else None
            if process is None or process.poll() is not None or process.pid not in process_ancestors(pid):
                raise RuntimeAdapterError('authority-denied', 'The writer does not belong to this DSH execution.')

        def operate(document: dict) -> dict:
            """Dispatch the registered function through the shared validator."""
            request = document.get('request', {})
            if request.get('action') != 'execute' or request.get('feature') != 'agents':
                raise RuntimeAdapterError('operation-unavailable', 'This DSH host exposes only agents.')
            caller = Caller('dsh-native-tool', run.agent, turn.session, 'dsh')
            result = bind(control, caller, archive=run.archive)(request.get('arguments'))
            return {'document': result.document, 'failed': result.failed}

        with worker_connection(directory, operate, authenticate=authenticate) as address:
            yield address

    turn.host_connection = connection
    turn.agents_only = True
    if run.archive is not None:
        from graphtraj.runtimes.dsh.collection import DshArchive

        turn.archive = DshArchive(run.archive, resumed=run.session is not None)
