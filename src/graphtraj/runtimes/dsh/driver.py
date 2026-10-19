"""GraphTraj archive policy around the independent DSH execution binding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_swarm import Run
from agent_swarm.dsh.binding import bind_run

if TYPE_CHECKING:
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.runtimes.dsh.execution import DshExecution


def bind_agents(turn: DshExecution, run: Run, driver: AdapterDriver) -> None:
    """Reuse the core callback; add only GraphTraj's optional archive consumer."""
    bind_run(turn, run)
    turn.agents_only = True
    if run.archive is not None:
        from agent_swarm.sessions.dsh import DshArchive

        turn.archive = DshArchive(run.archive, resumed=run.session is not None)
