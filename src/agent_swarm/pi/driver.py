"""Pi control with explicitly resolved native settings and no Task lookup."""

from __future__ import annotations

from copy import deepcopy
import threading
from typing import Any, Mapping

from agent_swarm import AgentsError, Caller, Run
from agent_swarm.runtime import RuntimeAdapterError
from .execution import PiExecution


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

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Return the chosen native configuration without reading project state."""
        if runtime != 'pi':
            raise AgentsError('unsupported-runtime', 'PiDriver only runs Pi.')
        return {'adapter_request': deepcopy(self.request), 'evidence': {},
                'cwd': self.request['worktree_path']}

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
