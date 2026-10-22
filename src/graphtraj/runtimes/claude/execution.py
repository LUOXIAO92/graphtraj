"""GraphTraj policy and optional archives for the shared Claude native owner."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile

from agent_swarm.claude.execution import ClaudeExecution as NativeClaudeExecution
from graphtraj.runtimes.runtime_adapter import record_runtime_process


class ClaudeExecution(NativeClaudeExecution):
    """Supply project resources and Runner services to the same native transport."""

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
        # Project development records stay readable for diagnosis across
        # Agents; control channels, Runtime homes and credentials stay denied.
        records = [request['state_directory'], str(root / '.graphtraj/runner')]
        denied_read = [str(root / '.graphtraj/cli'),
                       str(root / '.codex'), str(Path.home() / '.codex'), str(home)]
        denied_write = [*records, *map(str, resources), request['docs_directory'], str(home),
                        str(root / '.graphtraj/config.yml'), str(root / '.graphtraj/roles.yml'),
                        str(Path(request['git_common_directory']) / 'config'),
                        str(Path(request['git_common_directory']) / 'hooks'),
                        str(worktree / '.claude'), str(worktree / '.state'),
                        str(worktree / 'CONTEXT.md'), str(worktree / 'docs'), str(worktree / 'AGENTS.md'),
                        str(worktree / '.agents')]
        if request['worktree_access'] == 'read':
            denied_write.append(str(worktree))
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
                'deny': [rule for p in denied_read for rule in (f'Read(/{p})', f'Read(/{p}/**)')]
                        + [rule for p in denied_write for rule in (f'Edit(/{p})', f'Edit(/{p}/**)')]
                        + (['Edit', 'Write', 'NotebookEdit'] if request['worktree_access'] == 'read' else []),
                # Native additional working directories are writable sandbox
                # roots. Read-only resources belong solely in allowRead below.
                'additionalDirectories': [],
            },
            'sandbox': {
                'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                'autoAllowBashIfSandboxed': False, 'excludedCommands': [],
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
        return settings, {'mcpServers': {}} if self.independent else mcp

    def _parent_notice(self, message: str, details: dict) -> dict:
        """Deliver a native request to the Runner's actual direct parent."""
        from graphtraj.execution.runner_control import notify_direct_parent

        return notify_direct_parent(self.directory, message, details)

    def _collect_child(self, event: dict) -> None:
        """Collect native helpers only for the existing managed archive path."""
        if not self.independent:
            from graphtraj.runtimes.claude.collection import collect_hook

            collect_hook(event, Path(self.request['worktree_path']))

    def _collection_store(self, resources: ExitStack) -> None:
        """Open thread-affine legacy storage in the thread that consumes it."""
        if not self.independent:
            from graphtraj.sessions.storage import SessionStore

            self.collector.store = resources.enter_context(SessionStore(self.collector.store.path))

    def _collector(self, resources: ExitStack):
        """Provide the project's existing optional or managed collector."""
        provider = self.request.get('provider', 'native')
        if provider == 'native' and not self.request.get('base_url'):
            provider = 'anthropic'
        if self.independent:
            from graphtraj.runtimes.claude.jsonl import ClaudeJsonlCollector

            return ClaudeJsonlCollector(self.archive, self.native_id, self.directory.name,
                                       Path(self.request['worktree_path']), self.execution_id,
                                       provider=provider, resumed=self.expected is not None)
        from graphtraj.runtimes.claude.collection import open_archive, StreamCollector
        from graphtraj.sessions.storage import StreamWriter

        task_id = os.environ.get('GRAPHTRAJ_TASK_ID')
        archive = resources.enter_context(open_archive(
            Path(self.request['state_directory']), Path(self.request['harness_root']),
            self.native_id, self.directory.name, source='managed',
            task_ids=[task_id] if task_id else []))
        if archive.pending():
            StreamWriter(archive, archive.pending()['source']).finish(content=[], interrupted=True)
        return StreamCollector(archive, self.execution_id, self.request['model'], provider)

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
