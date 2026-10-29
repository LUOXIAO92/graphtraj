"""Run explicit native Claude settings through the independent Agents contract."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Callable, Mapping

from agent_swarm import AgentsError, Caller, Run
from agent_swarm.control import require_available
from .execution import ClaudeExecution
from .settings import current_cli, prepare

# Native Claude effort levels; a model's own list may be narrower.
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')


def selected(configuration: Mapping[str, Any], selection: Mapping[str, Any]) -> dict:
    """Apply one create selection to the host's Claude settings.

    A selected connection replaces the host's native home, endpoint and
    credential reference together, so a key never reaches another endpoint.
    Claude has no native provider setting; a connection's ``provider`` only
    names its models.
    """
    config = dict(configuration)
    connection = selection.get('settings')
    if connection is not None:
        for key in ('runtime_home', 'base_url', 'api_key_env'):
            config.pop(key, None)
        config.update({key: connection[name] for key, name in (
            ('runtime_home', 'home'), ('base_url', 'base_url'), ('api_key_env', 'api_key_env'))
            if name in connection})
    if selection.get('model') is not None:
        config['model'] = selection['model']
    effort = selection.get('reasoning_effort')
    if effort is not None:
        if effort not in EFFORTS:
            raise AgentsError('invalid-reasoning-effort',
                              f'Claude takes reasoning_effort {list(EFFORTS)}, not {effort!r}.')
        config['reasoning_effort'] = effort
    return config


class ClaudeDriver:
    """Native Claude control, with optional host function/collection binding.

    ``configure`` supplies host-owned capabilities to an invocation before it
    starts. The native owner itself does not discover a Task, role, Git tree,
    GraphTraj installation or archive. Plain control needs no configure hook.
    """

    def __init__(
        self,
        cwd: Path,
        configuration: Mapping[str, Any],
        *,
        configure: Callable[[ClaudeExecution, Run], None] | None = None,
    ) -> None:
        """Freeze caller-provided native settings; do not start a service."""
        self.cwd = Path(cwd)
        self.configuration = deepcopy(dict(configuration))
        self.configure = configure
        self.turns: dict[str, ClaudeExecution] = {}
        self.lock = threading.Lock()

    def prepare(self, runtime: str, caller: Caller, *, configuration: str | None = None,
                selection: Mapping[str, Any] | None = None) -> dict:
        """Validate explicit Claude configuration, independently of caller roles.

        ``selection`` is the create's resolved connection, model and effort.
        """
        if configuration is not None:
            raise AgentsError('invalid-config', 'This host uses its explicitly supplied Claude configuration.')
        if runtime != 'claude':
            raise AgentsError('unsupported-runtime', 'This driver runs Claude only.')
        config = self.configuration if selection is None else selected(self.configuration, selection)
        return prepare(config, self.cwd)

    def require_available(self, connection: Mapping[str, Any]) -> None:
        """Refuse a connection whose Claude Code is not installed or not logged in."""
        executable = self.configuration.get('executable') or shutil.which('claude')
        native = Path.home() / '.local/bin/claude'
        if executable is None and native.is_file():
            executable = str(native)
        explicit = connection.get('home') or os.environ.get('CLAUDE_CONFIG_DIR')
        home = Path(explicit or Path.home() / '.claude')
        # The account record sits beside the default home; the token may be in a keychain.
        logins = ('.credentials.json', '.claude.json') if explicit else ('.credentials.json', '../.claude.json')
        require_available(connection, executable=executable, home=home, logins=logins)

    def start(self, run: Run) -> None:
        """Return after native binding, retaining ownership until actual stop."""
        ready = threading.Event()
        failure = []

        def created(session: str, pid: int) -> None:
            """Publish the exact native Session before model work begins."""
            run.events.session(session)
            run.events.process(runtime_pid=pid)

        settings = dict(run.settings)
        if run.session is not None:
            # A resume runs the current CLI: an update removes the versioned
            # binary that the first execution resolved.
            settings['executable'], settings['version'] = current_cli(self.configuration.get('executable'))
        turn = ClaudeExecution(settings, run.message, run.directory,
                            lambda session, pid: ready.set(), created,
                            run.directory / 'trace.jsonl', run.session)
        from .binding import bind_run

        bind_run(turn, run)
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        if self.configure is not None:
            self.configure(turn, run)
        with self.lock:
            self.turns[run.execution] = turn

        def own() -> None:
            """Report native completion only after service and disk settlement."""
            try:
                result = turn.run()
                run.events.finished(result['outcome'], last_message=result.get('last_agent_message'))
            except Exception as error:
                failure.append(error)
                run.events.finished('failed', error={
                    'code': getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), 'message': str(error),
                }, terminal_confirmed=getattr(error, 'terminal_confirmed', False))
            finally:
                with self.lock:
                    self.turns.pop(run.execution, None)
                ready.set()

        threading.Thread(target=own, name=f'claude-{run.agent}').start()
        ready.wait()
        if failure:
            error = failure[0]
            raise AgentsError(getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), str(error))

    def _turn(self, run: Run) -> ClaudeExecution:
        """Return only this process's owner for the specified execution."""
        with self.lock:
            turn = self.turns.get(run.execution)
        if turn is None:
            raise AgentsError('not-owned', 'This host does not own the Claude execution.')
        return turn

    def deliver(self, run: Run, message: str) -> None:
        """Submit input to the same active native Session."""
        turn = self._turn(run)
        turn.operate({'operation': 'send', 'session': turn.session,
                      'execution_id': turn.execution_id, 'instruction': message})

    def interrupt(self, run: Run) -> bool:
        """Request cancellation; the owner confirms actual native quiescence."""
        return self._turn(run).terminate()

    def requests(self, run: Run) -> list[dict]:
        """Expose pending native approval requests without answering them."""
        turn = self._turn(run)
        return turn.operate({'operation': 'requests', 'session': turn.session,
                             'execution_id': turn.execution_id})['requests']

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Return one explicit decision through the native request binding."""
        turn = self._turn(run)
        return turn.operate({'operation': 'reply', 'session': turn.session,
                             'execution_id': turn.execution_id, 'request_token': request.get('request_token'),
                             'response': dict(response)})
