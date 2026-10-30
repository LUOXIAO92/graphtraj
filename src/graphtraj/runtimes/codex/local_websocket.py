"""Resolve the project-selected native connection."""
from pathlib import Path
from agent_swarm import RuntimeAdapterError
from agent_swarm.codex import project_access, validate_connection

def configured_connection(cwd: Path, home: str) -> dict | None:
    """Read the owning Harness configuration, never connection fields from events."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.workspace.runner_project import discover_project_root

    try:
        root = discover_project_root(cwd)
    except RunnerError as error:
        if error.code == 'PROJECT_NOT_FOUND':
            return None
        raise
    value = validate_connection((load_project_configuration(root).codex or {}).get('local_websocket'))
    if value is None or str(cwd.absolute()) not in value['worktrees']:
        return None
    if home != value['codex_home']:
        raise RuntimeAdapterError('authority-denied', 'Configured WebSocket belongs to another Codex home.')
    return value
