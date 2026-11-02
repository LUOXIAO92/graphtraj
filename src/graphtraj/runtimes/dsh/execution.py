"""GraphTraj lifecycle hooks around the independent DSH execution owner."""

from pathlib import Path
import re
import sys
from typing import Callable

from agent_swarm.dsh import DshExecution as NativeDshExecution
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.dsh.service import DshService
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


def _member_git_roots(worktree: str, common_directory: str) -> list[str]:
    """Return the directories one member needs to commit in its own linked Worktree.

    These are its own admin directory, the object store, and the directories
    holding its branch's ref and reflog. ``config``, ``hooks``, ``packed-refs``,
    other admin directories and other ref namespaces stay outside, because a
    sandboxed member could otherwise run code outside its sandbox through Git.

    The member can rewrite ``<worktree>/.git`` and, through this grant, its own
    admin directory. So nothing here reads the Worktree's pointer, and the branch
    must have the shape Runner gives every Task (``agent/<task>-<name>``): a
    rewritten ``HEAD`` cannot aim a later launch's grant at another namespace.
    Anything else, including a detached ``HEAD``, grants nothing.

    Parameters
    ----------
    worktree:
        The member's Worktree, as Runner recorded it.
    common_directory:
        The Git common directory Runner recorded at preflight.

    Returns
    -------
    list[str]
        Existing physical directories, as DSH requires, or an empty list.
    """
    common = Path(common_directory).resolve()
    member = Path(worktree).resolve()

    # Compare the directory holding each recorded ``.git``, never ``.git`` itself:
    # a member can make its own ``.git`` a symlink to another Worktree's.
    try:
        admins = [admin for admin in (common / 'worktrees').iterdir()
                  if (admin / (admin / 'gitdir').read_text(encoding='utf-8').strip()).parent.resolve() == member]
        if len(admins) != 1:
            return []
        head = (admins[0] / 'HEAD').read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return []
    if re.fullmatch(r'ref: refs/heads/agent/[^/]+', head) is None:
        return []

    # Packed refs can leave these absent, and DSH refuses a missing directory.
    # The member cannot replace them: their parents stay outside its grant.
    branches = [common / 'refs/heads/agent', common / 'logs/refs/heads/agent']
    try:
        for directory in branches:
            directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    roots = [admins[0], common / 'objects', *branches]
    return [str(root) for root in roots] if all(root.resolve() == root for root in roots) else []


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
        from agent_swarm.dsh import session_context

        def record_session(session: str, pid: int) -> None:
            """Retain GraphTraj's Session receipt before publishing its binding."""
            write_yaml_durably(directory / 'session.yml', {'session': session, 'runtime': 'dsh'})
            created(session, pid)

        # This Session reaches its host through GRAPHTRAJ_CLI_CONNECTION, which only
        # this entry reads, and its tasks tool exists only here. -I keeps the member's
        # writable Worktree, the MCP working directory, off the import path.
        mcp = {'command': str(Path(sys.executable).absolute()), 'args': ['-I', '-m', 'graphtraj.interfaces.mcp']}
        super().__init__({**request, 'plugin': str(Path(__file__).with_name('tool.mjs')), 'mcp': mcp},
                         prompt, directory, started, record_session, trace_file, expected_session)
        self.service_type = DshService
        self.host_connection = lambda channel: cli_connection(
            Path(request['harness_root']), directory.name, native_operation_features(), directory=channel,
            native_context=lambda: session_context(self),
        )
        self.parent_notice = lambda notice, details: notify_direct_parent(directory, notice, details)
        from agent_swarm.sessions import DshArchive
        from graphtraj.interfaces.agents import configured_archive, graphtraj_fields, mapped_task_ids

        self.archive = DshArchive(configured_archive(Path(request['harness_root'])),
                                  resumed=expected_session is not None,
                                  extra_fields=graphtraj_fields(str(request['harness_root']), directory.name,
                                                                mapped_task_ids(directory)))

    def prepare_launch(self) -> dict[str, str]:
        """Add GraphTraj's native plugin environment to the generic profile."""
        # A launch record older than this field grants nothing extra.
        if self.request['sandbox'] == 'workspace-write' and self.request.get('git_common_directory'):
            self.request['additional_writable_roots'] = _member_git_roots(
                self.request['worktree_path'], self.request['git_common_directory'],
            )
        environment = super().prepare_launch()
        environment.update({
            'GRAPHTRAJ_DSH_PACKAGE': self.request['package'],
            'GRAPHTRAJ_DSH_TOOL': self.request['tool'],
            'GRAPHTRAJ_HARNESS_ROOT': self.request['harness_root'],
        })
        # This execution owns JSONL collection; the plugin must not collect a
        # second SQLite body for the same native Session.
        environment['GRAPHTRAJ_DSH_AGENTS_ONLY'] = '1'
        return environment
