"""GraphTraj's Runner consumer of the independent Pi execution owner."""

from __future__ import annotations

from pathlib import Path

from agent_swarm.pi.execution import PiExecution
from graphtraj.runtimes.runtime_adapter import record_runtime_process


class PiManagedExecution(PiExecution):
    """Add Runner connections, Task notices and archives to the native owner.

    The Task-free agents driver sets ``independent`` and uses the inherited
    native connection; Runner executions keep GraphTraj's hosted CLI.
    """

    def __init__(self, *arguments) -> None:
        """Default to a Runner execution that may read the GraphTraj package."""
        super().__init__(*arguments)
        self.independent = False
        self.packages.append(str(Path(__file__).resolve().parents[2]))

    def _provider_domain(self, source: Path, provider: str) -> str:
        """Resolve older captured requests from their retained native Home."""
        from graphtraj.runtimes.model_discovery import pi_model_domain

        return pi_model_domain(str(source), provider, self.request['model'], self.request.get('api_key_env'))

    def _connection(self):
        """Serve Runner's hosted CLI unless the agents driver owns the call."""
        if self.independent:
            return super()._connection()
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features

        return cli_connection(Path(self.request['harness_root']), self.directory.name, native_operation_features())

    def _connection_environment(self, address: str, root: Path) -> dict:
        """Name the hosted CLI for Runner executions."""
        if self.independent:
            return super()._connection_environment(address, root)
        return {'GRAPHTRAJ_CLI_CONNECTION': address, 'GRAPHTRAJ_HARNESS_ROOT': str(root)}

    def _archive_collector(self, header: dict, native: dict):
        """Archive Runner executions under their Task mapping in the project archive."""
        from graphtraj.runtimes.pi.collection import PiArchive

        archive, agent, tasks, source = self.archive, self.agent, [], 'child'
        if not self.independent:
            import yaml
            from agent_swarm import default_config
            from graphtraj.interfaces.agents import swarm_root
            from graphtraj.sessions.archive import SessionArchive

            mapping_file = self.directory / 'mapping.yml'
            mapping = yaml.safe_load(mapping_file.read_text()) if mapping_file.is_file() else {}
            agent = mapping.get('alias', self.session)
            tasks = [mapping['task_id']] if mapping.get('task_id') else []
            source = 'member' if mapping else None
            root = swarm_root(Path(self.request['harness_root']))
            archive = SessionArchive(root, **default_config(root, save_normalized_sessions=True))
        if archive is None:
            return None
        return PiArchive(
            archive, header, agent=agent, project=self.request['harness_root'],
            entries=native['entries'], leaf_id=native['leafId'], source=source, tasks=tasks,
            attachment_root=Path(self.request['worktree_path']),
        )

    def _record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Publish through the Worker's bound process observer."""
        record_runtime_process(pid, outcome)

    def _notify_parent(self, message: str, details: dict) -> dict | None:
        """Use the agents driver's notice, else Runner's direct parent."""
        if self.parent_notice is not None:
            return self.parent_notice(message, details)
        from graphtraj.execution.runner_control import notify_direct_parent

        return notify_direct_parent(self.directory, message, details)
