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
        """Default to a Runner execution that may read the GraphTraj package.

        A Runner execution archives into the project archive under its mapped
        Task; the agents driver replaces ``archive`` and ``extra_fields``.
        """
        super().__init__(*arguments)
        self.independent = False
        self.packages.append(str(Path(__file__).resolve().parents[2]))

        import yaml
        from agent_swarm import default_config
        from agent_swarm.sessions.archive import SessionArchive
        from graphtraj.interfaces.agents import mapped_task_ids, swarm_root

        mapping_file = self.directory / 'mapping.yml'
        mapping = yaml.safe_load(mapping_file.read_text()) if mapping_file.is_file() else {}
        root    = swarm_root(Path(self.request['harness_root']))
        self.archive       = SessionArchive(root, **default_config(root, save_normalized_sessions=True))
        self.runner_mapped = bool(mapping)
        # Without a mapping the Agent is named by its native Session, known at run().
        self.runner_alias  = mapping.get('alias')
        self.runner_tasks  = mapped_task_ids(self.directory)

    def _archive_collector(self, header: dict, native: dict):
        """Name a Runner execution's Agent and source once its native Session is known.

        The agents driver path keeps the fields it bound and archives as a child.
        """
        if self.independent:
            self.archive_source = 'child'
        else:
            from graphtraj.interfaces.agents import graphtraj_fields

            self.archive_source = 'member' if self.runner_mapped else None
            self.extra_fields   = graphtraj_fields(self.request['harness_root'],
                                                   self.runner_alias or self.session, self.runner_tasks)
        return super()._archive_collector(header, native)

    def _record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Publish through the Worker's bound process observer."""
        record_runtime_process(pid, outcome)

    def _notify_parent(self, message: str, details: dict) -> dict | None:
        """Use the agents driver's notice, else Runner's direct parent."""
        if self.parent_notice is not None:
            return self.parent_notice(message, details)
        from graphtraj.execution.runner_control import notify_direct_parent

        return notify_direct_parent(self.directory, message, details)
