"""GraphTraj lifecycle hooks around the independent DSH execution owner."""

from pathlib import Path
from typing import Callable

from agent_swarm.dsh.execution import (
    DshExecution as NativeDshExecution,
    _dump_profile_patches,
    _load_installed_patches,
    _deployment_agent_preset,
    _PatchLoader,
)
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.dsh.service import DshService
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


class DshExecution(NativeDshExecution):
    """Keep GraphTraj preparation and delivery hooks outside native control."""

    error_type = RuntimeAdapterError
    connection_env = 'GRAPHTRAJ_CLI_CONNECTION'
    agents_only = False

    def __init__(
        self,
        request: dict,
        prompt: str,
        directory: Path,
        started: Callable[[str, int], None],
        created: Callable[[str, int], None],
        trace_file: Path,
        expected_session: str | None,
    ) -> None:
        """Attach the existing GraphTraj binding without changing native settings."""
        from graphtraj.execution.runner_control import notify_direct_parent
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features
        from agent_swarm.dsh.binding import session_context

        def record_session(session: str, pid: int) -> None:
            """Retain GraphTraj's Session receipt before publishing its binding."""
            write_yaml_durably(directory / 'session.yml', {'session': session, 'runtime': 'dsh'})
            created(session, pid)

        super().__init__({**request, 'plugin': str(Path(__file__).with_name('tool.mjs'))},
                         prompt, directory, started, record_session, trace_file, expected_session)
        self.service_type = DshService
        self.host_connection = lambda channel: cli_connection(
            Path(request['harness_root']), directory.name, native_operation_features(), directory=channel,
            native_context=lambda: session_context(self),
        )
        self.parent_notice = lambda notice, details: notify_direct_parent(directory, notice, details)
        from agent_swarm.sessions.dsh import DshArchive
        from graphtraj.interfaces.agents import configured_archive

        self.archive = DshArchive(configured_archive(Path(request['harness_root'])),
                                  resumed=expected_session is not None)

    def _prepare(self) -> dict[str, str]:
        """Add GraphTraj's native plugin environment to the generic profile."""
        environment = super()._prepare()
        environment.update({
            'GRAPHTRAJ_DSH_PACKAGE': self.request['package'],
            'GRAPHTRAJ_DSH_TOOL': self.request['tool'],
            'GRAPHTRAJ_HARNESS_ROOT': self.request['harness_root'],
        })
        # This execution owns JSONL collection; the plugin must not collect a
        # second SQLite body for the same native Session.
        environment['GRAPHTRAJ_DSH_AGENTS_ONLY'] = '1'
        return environment
