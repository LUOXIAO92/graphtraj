"""Run explicit native DSH settings through the independent Agents contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
from typing import Any, Callable, Mapping

from agent_swarm import AgentsError, Caller, Run
from .execution import DshExecution
from .settings import prepare


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

    def prepare(self, runtime: str, caller: Caller) -> dict:
        """Validate explicit DSH configuration, independently of caller roles."""
        if runtime != 'dsh':
            raise AgentsError('unsupported-runtime', 'This driver runs DSH only.')
        return prepare(self.configuration, self.cwd)

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
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        if self.configure is not None:
            self.configure(turn, run)
        if run.archive is not None and turn.archive is None:
            raise AgentsError('archive-unavailable', 'Bind the DSH collector for the supplied archive.')
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
