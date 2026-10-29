"""Pi control with explicitly resolved native settings and no Task lookup."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Mapping

from agent_swarm import AgentsError, Caller, Run
from agent_swarm.control import require_available, within_workspace
from agent_swarm.runtime import RuntimeAdapterError
from .execution import PiExecution

# Native Pi thinking levels; a model's own list may be narrower.
EFFORTS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh')


def selected(request: Mapping[str, Any], selection: Mapping[str, Any]) -> dict:
    """Apply one create selection to the host's Pi launch request.

    The host resolved the network destination for its own provider, so
    another provider, or an endpoint without a provider API, is refused here
    rather than launched under the wrong grants.
    """
    request = deepcopy(dict(request))
    if selection.get('provider') not in (None, request['provider']):
        raise AgentsError('invalid-config', f"This Pi host resolved provider {request['provider']!r}; "
                                            f"it cannot launch provider {selection['provider']!r}.")
    connection = selection.get('settings')
    if connection is not None:
        if 'base_url' in connection:
            raise AgentsError('invalid-config', 'A Pi connection cannot set base_url here; '
                                                "declare the endpoint in Pi's own models.json.")
        request.pop('api_key_env', None)
        if 'api_key_env' in connection:
            request['api_key_env'] = connection['api_key_env']
        if 'home' in connection:
            request['agent_dir'] = connection['home']
    if selection.get('model') is not None:
        request['model'] = selection['model']
    effort = selection.get('reasoning_effort')
    if effort is not None:
        if effort not in EFFORTS:
            raise AgentsError('invalid-reasoning-effort',
                              f'Pi takes reasoning_effort {list(EFFORTS)}, not {effort!r}.')
        request['reasoning_effort'] = effort
    return request


class PiDriver:
    """Bind a host-prepared Pi launch request to the independent control core.

    The host resolves model/provider, resource references and native isolation
    before binding. This driver retains that exact request for continuation;
    it does not discover GraphTraj configuration, Tasks, reports or Git.
    """

    def __init__(self, request: dict) -> None:
        """Keep a detached, already validated native launch configuration."""
        self.request = deepcopy(request)
        self.turns: dict[str, PiExecution] = {}
        self.lock = threading.Lock()

    def prepare(self, runtime: str, caller: Caller, *, selection: Mapping[str, Any] | None = None,
                workspace: Path | None = None) -> dict:
        """Return the chosen native configuration without reading project state.

        ``selection`` is the create's resolved connection, model and effort.
        ``workspace`` replaces the host worktree as cwd and sandbox grant root;
        every other read, write and network grant stays as resolved.
        """
        if runtime != 'pi':
            raise AgentsError('unsupported-runtime', 'PiDriver only runs Pi.')
        request = deepcopy(self.request) if selection is None else selected(self.request, selection)
        if workspace is not None:
            request['worktree_path'] = str(within_workspace(workspace, self.request['worktree_path']))
        return {'adapter_request': request, 'evidence': {}, 'cwd': request['worktree_path']}

    def require_available(self, connection: Mapping[str, Any]) -> None:
        """Refuse a connection whose Pi is not installed or not logged in."""
        home = Path(connection.get('home') or os.environ.get('PI_CODING_AGENT_DIR')
                    or Path.home() / '.pi/agent')
        require_available(connection, executable=self.request.get('executable') or shutil.which('pi'),
                          home=home, logins=('auth.json',))

    def start(self, run: Run) -> None:
        """Return after native Session binding, retaining ownership until actual stop."""
        ready = threading.Event()
        failure: list[BaseException] = []

        def created(session: str, pid: int) -> None:
            """Publish the exact native Session before model work begins."""
            run.events.session(session)
            run.events.process(runtime_pid=pid)

        turn = PiExecution(dict(run.settings['adapter_request']), run.message, run.directory,
                           lambda session, pid: ready.set(), created,
                           run.directory / 'trace.jsonl', run.session)
        turn.archive = run.archive
        turn.agent = run.agent
        turn.agent_call = run.call
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        turn._record_process = lambda pid, outcome=None: (
            run.events.process(runtime_pid=pid) if outcome is None else run.events.process(runtime_exit=outcome))
        with self.lock:
            self.turns[run.execution] = turn

        def own() -> None:
            """Report native completion only after confirmed native settlement."""
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

        threading.Thread(target=own, name=f'pi-{run.agent}').start()
        ready.wait()
        if failure:
            error = failure[0]
            raise AgentsError(getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), str(error))

    def _operate(self, run: Run, **request: Any) -> dict:
        """Apply one native operation to this process's owner of ``run``."""
        with self.lock:
            turn = self.turns.get(run.execution)
        if turn is None:
            raise AgentsError('not-owned', 'This host does not own the Pi execution.')
        try:
            return turn.operate({**request, 'session': turn.session, 'execution_id': turn.execution_id})
        except RuntimeAdapterError as error:
            raise AgentsError(error.code, error.message) from None

    def deliver(self, run: Run, message: str) -> None:
        """Queue input into the same active native Session."""
        self._operate(run, operation='send', instruction=message)

    def interrupt(self, run: Run) -> bool:
        """Request native cancellation; the owner confirms actual quiescence."""
        with self.lock:
            turn = self.turns.get(run.execution)
        if turn is None:
            raise AgentsError('not-owned', 'This host does not own the Pi execution.')
        return turn.terminate()

    def requests(self, run: Run) -> list[dict]:
        """Expose pending native dialogs without answering them."""
        return self._operate(run, operation='requests')['requests']

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Return one explicit reply through the native dialog binding."""
        return self._operate(run, operation='reply', request_token=request.get('request_token'),
                             response=dict(response))
