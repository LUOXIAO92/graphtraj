"""GraphTraj policy and optional archives for the shared Claude native owner."""
from __future__ import annotations

from graphtraj.configuration.project_configuration import (
    cli_directory as project_cli_directory,
    configuration_file as project_configuration_file,
    core_directory as project_core_directory,
    runner_directory as project_runner_directory,
)

from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile

from agent_swarm.claude.execution import ClaudeExecution as NativeClaudeExecution
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, record_runtime_process


class ClaudeExecution(NativeClaudeExecution):
    """Supply project resources and Runner services to the same native transport.

    Archiving uses the shared owner's collector. A Runner execution binds the
    project archive and GraphTraj's ``extra_fields.graphtraj`` here; the agents
    driver path replaces both through ``configure_independent``.
    """

    def __init__(self, *arguments) -> None:
        """Bind the project archive and its GraphTraj header fields to a Runner execution."""
        super().__init__(*arguments)
        from graphtraj.interfaces.agents import configured_archive, graphtraj_fields, mapped_task_ids

        self.archive      = configured_archive(Path(self.request['harness_root']))
        self.extra_fields = graphtraj_fields(str(self.request['worktree_path']), self.directory.name,
                                             mapped_task_ids(self.directory))

    def record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Publish native process evidence through the existing Runner binding."""
        record_runtime_process(pid, outcome)

    def _settings(self, address: str | None) -> tuple[dict, dict]:
        """Preserve the project's captured native resource and sandbox settings."""
        request = self.request
        worktree = Path(request['worktree_path']).resolve()
        root = Path(request['harness_root']).resolve()
        home = Path(request['runtime_home']).resolve()
        resources = [p.resolve() for p in (worktree / 'docs', worktree / 'CONTEXT.md',
                                           worktree / 'AGENTS.md', worktree / '.agents') if p.exists()]
        resources.extend(Path(path).resolve() for path in request['resources'])
        from graphtraj.runtimes.codex.access import project_history_files

        history = {path for path in project_history_files(root)
                   if not path.is_relative_to(project_cli_directory(root).resolve())}
        resources.extend(sorted(history))
        # Project development records stay readable for diagnosis across
        # Agents; control channels, Runtime homes and credentials stay denied.
        records = [request['state_directory'], str(project_runner_directory(root))]
        denied_read = [str(project_cli_directory(root)),
                       str(root / '.codex'), str(Path.home() / '.codex'), str(home)]
        native_denied_read = []
        for protected in map(Path, denied_read):
            if not any(path.is_relative_to(protected) for path in history):
                native_denied_read.append(str(protected))
                continue
            # Native Read deny rules override exact file grants. Restricted
            # mode instead confines these reads to the declared history files;
            # sandbox denyRead stays in force with exact allowRead exceptions.
            # Never use this arrangement when a working directory exposes the
            # protected home itself or another part of it.
            if any(path.is_relative_to(protected) or protected.is_relative_to(path)
                   for path in (worktree, *(p for p in resources if p.is_dir()))):
                raise RuntimeAdapterError(
                    'RUNTIME_ACCESS_DENIED',
                    'Exact native history reads require working directories outside protected Runtime homes.',
                )
        denied_write = [*records, *map(str, resources), request['docs_directory'], str(home),
                        str(project_configuration_file(root)), str(project_core_directory(root) / 'roles.yml'),
                        str(Path(request['git_common_directory']) / 'config'),
                        str(Path(request['git_common_directory']) / 'hooks'),
                        str(worktree / '.claude'), str(worktree / '.state'),
                        str(worktree / 'CONTEXT.md'), str(worktree / 'docs'), str(worktree / 'AGENTS.md'),
                        str(worktree / '.agents')]
        if request['worktree_access'] == 'read':
            # Claude also adds the linked repository's common Git directory to
            # its native writable roots. A reader must not mutate shared refs
            # or indexes there; its separate authenticated channel stays writable.
            denied_write.extend((str(worktree), request['git_common_directory']))
        # A project-root cwd must not re-allow its private descendants. Linked
        # Worktrees need only their own exception beneath the denied directory.
        private = root / '.graphtraj'
        worktree_read = [str(worktree)] if worktree.is_relative_to(private) else []
        if private.is_relative_to(worktree):
            denied_write.append(str(private))
        settings = {
            'permissions': {
                'blockReadsOutsideWorkingDirectories': True,
                'allow': [rule for p in (*resources, *records) for rule in (f'Read(/{p})', f'Read(/{p}/**)')],
                'deny': [rule for p in native_denied_read for rule in (f'Read(/{p})', f'Read(/{p}/**)')]
                        + [rule for p in denied_write for rule in (f'Edit(/{p})', f'Edit(/{p}/**)')]
                        + (['Edit', 'Write', 'NotebookEdit'] if request['worktree_access'] == 'read' else []),
                # Startup validates directories in both settings and --add-dir.
                'additionalDirectories': [str(path) for path in resources if path.is_dir()],
            },
            'sandbox': {
                'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                # Every Bash command runs sandboxed with no unsandboxed retry,
                # so ordinary development needs no per-use parent approval.
                'autoAllowBashIfSandboxed': True, 'excludedCommands': [],
                'filesystem': {
                    'denyRead': [str(root / '.graphtraj'), *denied_read],
                    'allowRead': [*worktree_read, *records, *([address] if address else []),
                                  request['git_common_directory'], *map(str, resources),
                                  str(Path(sys.prefix).resolve()), str(Path(__file__).resolve().parents[2])],
                    'allowWrite': ([address] if address else []) + ([request['git_common_directory']]
                                              if request['worktree_access'] == 'write' else []),
                    'denyWrite': denied_write,
                },
            },
        }
        # The MCP process uses the same PID-authenticated hosted CLI as native Bash.
        mcp = {'mcpServers': {'agents': {
            'command': sys.executable, 'args': ['-m', 'graphtraj.runtimes.claude.mcp'],
            'env': {'GRAPHTRAJ_CLI_CONNECTION': address},
        }}}
        if any(path.is_file() and not path.is_relative_to(worktree) for path in resources):
            # The native session settings API applies these exact resource
            # declarations before any prompt. Keep every deny and restriction;
            # a refusal ends startup instead of falling back to a broader root.
            permissions = {**settings['permissions'], 'additionalDirectories': list(map(str, resources))}
            if request.get('permission_mode') is not None:
                permissions['defaultMode'] = request['permission_mode']
            self.resource_settings = {'permissions': permissions}
        return settings, {'mcpServers': {}} if self.independent else mcp

    def _parent_notice(self, message: str, details: dict) -> dict:
        """Deliver a native request to the Runner's actual direct parent."""
        from graphtraj.execution.runner_control import notify_direct_parent

        return notify_direct_parent(self.directory, message, details)

    def _connection(self, resources: ExitStack) -> str | None:
        """Bind Runner tools only for the GraphTraj-managed invocation."""
        if self.independent:
            return super()._connection(resources)
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features

        channel_directory = None
        if (Path(self.request['harness_root']) / '.graphtraj').resolve().is_relative_to(
                Path(self.request['worktree_path']).resolve()):
            channel_directory = Path(resources.enter_context(
                tempfile.TemporaryDirectory(prefix='graphtraj-claude-')))
        return resources.enter_context(cli_connection(
            Path(self.request['harness_root']), self.directory.name, native_operation_features(),
            directory=channel_directory))
