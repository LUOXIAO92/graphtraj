"""GraphTraj's Runner consumer of the independent Pi execution owner."""

from __future__ import annotations

from pathlib import Path

from agent_swarm.pi import PiExecution
from graphtraj.runtimes.runtime_adapter import record_runtime_process


class PiManagedExecution(PiExecution):
    """Add Runner connections, Task notices and archives to the native owner.

    The Task-free agents driver sets ``independent`` and uses the inherited
    native connection; Runner executions keep GraphTraj's hosted CLI.
    """

    def __init__(self, *arguments) -> None:
        """Default to a Runner execution that may read the GraphTraj package.

        A Runner execution archives into the project archive under its mapped
        Task; the agents driver replaces ``archive`` and ``extra_fields``.
        """
        super().__init__(*arguments)
        self.independent = False
        self.packages.append(str(Path(__file__).resolve().parents[2]))

        from agent_swarm import default_config
        from agent_swarm.sessions import SessionArchive
        from graphtraj.interfaces.agents import attachment_private_paths, swarm_root

        project = Path(self.request['harness_root'])
        root = swarm_root(project)
        self.archive = SessionArchive(root, **default_config(root, save_normalized_sessions=True))
        self.archive_private_paths = attachment_private_paths(project, self.request.get('worktree_path'))
        # The agents driver path replaces this with its own receiver.
        self.parent_notice = self._notify_direct_parent

    def prepare_launch(self, address: str | None) -> tuple[list[str], dict]:
        """Supply GraphTraj's paths and destinations through the generic request.

        Every captured member request, including one retained before the
        request became generic, carries the project fields they derive from.
        """
        from graphtraj.runtimes.pi.pi_adapter import member_policy

        self.request.update(member_policy(self.request))
        return super().prepare_launch(address)

    def provider_domain(self, source: Path, provider: str) -> str:
        """Resolve older captured requests from their retained native Home."""
        from graphtraj.runtimes.model_discovery import pi_model_domain

        return pi_model_domain(str(source), provider, self.request['model'], self.request.get('api_key_env'))

    def bind_connection(self):
        """Serve Runner's hosted CLI unless the agents driver owns the call."""
        if self.independent:
            return super().bind_connection()
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features

        return cli_connection(Path(self.request['harness_root']), self.directory.name, native_operation_features())

    def connection_environment(self, address: str) -> dict:
        """Name the hosted CLI for Runner executions."""
        if self.independent:
            return super().connection_environment(address)
        root = Path(self.request['harness_root']).resolve()
        return {'GRAPHTRAJ_CLI_CONNECTION': address, 'GRAPHTRAJ_HARNESS_ROOT': str(root)}

    def archive_collector(self, header: dict, native: dict):
        """Name a Runner execution's Agent and source once its native Session is known.

        The agents driver path keeps the fields it bound and archives as a child.
        """
        if self.independent:
            self.archive_source = 'child'
        else:
            import yaml
            from graphtraj.interfaces.agents import graphtraj_fields, mapped_task_ids

            # The Runner mapping exists by native Session start; without one the
            # Agent is named by its native Session.
            mapping_file = self.directory / 'mapping.yml'
            mapping = yaml.safe_load(mapping_file.read_text()) if mapping_file.is_file() else {}
            self.archive_source = 'member' if mapping else None
            self.extra_fields   = graphtraj_fields(self.request['harness_root'],
                                                   mapping.get('alias', self.session),
                                                   mapped_task_ids(self.directory))
        return super().archive_collector(header, native)

    def record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Publish through the Worker's bound process observer."""
        record_runtime_process(pid, outcome)

    def _notify_direct_parent(self, message: str, details: dict) -> dict | None:
        """Deliver a pending native dialog to Runner's direct parent."""
        from graphtraj.execution.runner_control import notify_direct_parent

        return notify_direct_parent(self.directory, message, details)
