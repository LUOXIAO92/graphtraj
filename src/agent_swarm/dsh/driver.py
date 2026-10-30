"""Run explicit native DSH settings through the independent Agents contract."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Callable, Mapping

from agent_swarm import AgentsError, Caller, Run
from agent_swarm.control import require_available, within_workspace
from .execution import DshExecution
from .settings import prepare

# Native DSH effort levels; a model's own list may be narrower.
EFFORTS = ('off', 'low', 'high', 'max')


def selected(configuration: Mapping[str, Any], selection: Mapping[str, Any]) -> dict:
    """Apply one create selection to the host's DSH settings.

    A selected connection replaces the host's native home, endpoint and
    credential reference together, so a key never reaches another endpoint.
    """
    config = dict(configuration)
    if selection.get('provider') not in (None, 'deepseek-official'):
        raise AgentsError('invalid-config', 'This DSH driver runs the deepseek-official provider only, '
                                            f"not {selection['provider']!r}.")
    connection = selection.get('settings')
    if connection is not None:
        for key in ('runtime_home', 'base_url', 'api_key_env', 'model_source'):
            config.pop(key, None)
        config.update({key: connection[name] for key, name in (
            ('runtime_home', 'home'), ('base_url', 'base_url'), ('api_key_env', 'api_key_env'))
            if name in connection})
        if 'models' in connection:
            # A declared model is announced to DSH rather than taken from its catalog.
            config['model_source'] = 'manual'
    if selection.get('model') is not None:
        config['model'] = selection['model']
    effort = selection.get('reasoning_effort')
    if effort is not None:
        if effort not in EFFORTS:
            raise AgentsError('invalid-reasoning-effort',
                              f'DSH takes reasoning_effort {list(EFFORTS)}, not {effort!r}.')
        config['reasoning_effort'] = effort
    return config


class DshDriver:
    """Native DSH control, with optional host function/collection binding.

    ``configure`` supplies host-owned capabilities to an invocation before it
    starts. The native owner itself does not discover a Task, role, Git tree,
    GraphTraj installation or archive. Plain control needs no configure hook.
    """

    def __init__(
        self,
        cwd: Path,
        configuration: Mapping[str, Any],
        *,
        configure: Callable[[DshExecution, Run], None] | None = None,
    ) -> None:
        """Freeze caller-provided native settings; do not start a service."""
        self.cwd = Path(cwd)
        self.configuration = deepcopy(dict(configuration))
        self.configure = configure
        self.turns: dict[str, DshExecution] = {}
        self.lock = threading.Lock()

    def prepare(self, runtime: str, caller: Caller, *, selection: Mapping[str, Any] | None = None,
                workspace: Path | None = None) -> dict:
        """Validate explicit DSH configuration, independently of caller roles.

        ``selection`` is the create's resolved connection, model and effort.
        ``workspace`` replaces the host cwd, and with it the native sandbox's
        workspace root; the permission mode stays as configured.
        """
        if runtime != 'dsh':
            raise AgentsError('unsupported-runtime', 'This driver runs DSH only.')
        config = self.configuration if selection is None else selected(self.configuration, selection)
        return prepare(config, self.cwd if workspace is None else within_workspace(workspace, self.cwd))

    def require_available(self, connection: Mapping[str, Any]) -> None:
        """Refuse a connection whose DSH is not installed, or whose named key is unset.

        ponytail: DSH's own login files are not documented to agents, so a
        connection without ``api_key_env`` leaves the login check to DSH's start.
        """
        home = Path(connection.get('home') or os.environ.get('DSH_HOME') or Path.home() / '.dsh')
        require_available(connection, executable=self.configuration.get('executable') or shutil.which('dsh'),
                          home=home, logins=None)

    def start(self, run: Run) -> None:
        """Return after native binding, retaining ownership until actual stop."""
        ready = threading.Event()
        failure = []

        def created(session: str, pid: int) -> None:
            """Publish the exact native Session before model work begins."""
            run.events.session(session)
            run.events.process(runtime_pid=pid)

        turn = DshExecution(dict(run.settings), run.message, run.directory,
                            lambda session, pid: ready.set(), created,
                            run.directory / 'trace.jsonl', run.session)
        from .binding import bind_run

        bind_run(turn, run)
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        if self.configure is not None:
            self.configure(turn, run)
        if run.archive is not None and turn.archive is None:
            from agent_swarm.sessions.dsh import DshArchive

            turn.archive = DshArchive(run.archive, resumed=run.session is not None,
                                      extra_fields=run.extra_fields)
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

        threading.Thread(target=own, name=f'dsh-{run.agent}').start()
        ready.wait()
        if failure:
            error = failure[0]
            raise AgentsError(getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), str(error))

    def _turn(self, run: Run) -> DshExecution:
        """Return only this process's owner for the specified execution."""
        with self.lock:
            turn = self.turns.get(run.execution)
        if turn is None:
            raise AgentsError('not-owned', 'This host does not own the DSH execution.')
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
