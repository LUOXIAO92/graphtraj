"""Bind Claude SDK/MCP and child notifications to the existing Agents execution."""
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from agent_swarm import Run
from agent_swarm.connection import agents_connection
from agent_swarm.process import authenticate_process
from .execution import ClaudeExecution


def bind_run(turn: ClaudeExecution, run: Run) -> None:
    """Use the core's existing identity and exact native process ownership."""
    if run.call is None:
        raise ValueError('Claude needs its owning Agents callback.')
    turn.configure_independent(archive=run.archive, agents_callback=run.call)
    if 'completion_message' in run.settings:
        notice = run.settings['completion_message']
        turn.prompt = f"[agents · {notice['agent']} → {run.agent}]\n{notice['body']}"

    @contextmanager
    def connection(directory: Path) -> Iterator[str]:
        """Authenticate CLI/MCP processes beneath the still-owned native CLI."""
        with agents_connection(directory, run.call,
                               lambda pid: authenticate_process(turn.proc, pid)) as address:
            yield address

    def receive(event: dict) -> bool:
        """Deliver once to the running parent, or continue its retained Session."""
        if event['parent'] != run.agent or not event['session']:
            return False
        with turn.lock:
            active = turn.accepting and not turn.stopping.is_set() and not turn.done.is_set()
            if active:
                turn.operate({'operation': 'send', 'session': turn.session,
                              'execution_id': turn.execution_id,
                              'instruction': f"[agents · {event['agent']} → {run.agent}]\n{event['body']}"})
                return True
        return run.events.continue_from_child(event, run.archive)

    turn.host_connection = connection
    run.events.receive_children(receive)
