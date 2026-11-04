"""GraphTraj archive policy around the independent DSH execution binding."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from graftling import Run
from graftling.dsh import bind_run

if TYPE_CHECKING:
    from graphtraj.execution.agent_driver import AdapterDriver
    from graphtraj.runtimes.dsh.execution import DshExecution


def bind_agents(turn: DshExecution, run: Run, driver: AdapterDriver) -> None:
    """Reuse the core callback; add only GraphTraj's optional archive consumer."""
    bind_run(turn, run)
    turn.agents_only = True
    # The child's agents tool must reach the channel bind_run serves, so its calls run in
    # this owner as the child. GraphTraj's own entry reads only GRAPHTRAJ_CLI_CONNECTION;
    # without it, it ran the call inside the MCP server, as the member, with an
    # environment DSH had stripped of every key (440).
    turn.request['mcp'] = {'command': str(Path(sys.executable).absolute()), 'args': ['-I', '-m', 'graftling.mcp']}
    if run.archive is not None:
        from graftling.sessions import DshArchive

        from graphtraj.interfaces.agents import graphtraj_fields

        turn.archive = DshArchive(run.archive, resumed=run.session is not None,
                                  extra_fields=graphtraj_fields(str(driver.root), run.agent,
                                                                extra_fields=run.extra_fields))
