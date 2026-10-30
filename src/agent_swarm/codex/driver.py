"""Run captured Codex settings through the independent Agent control contract."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Callable, Mapping

from agent_swarm import AgentsError, Caller, Run
from agent_swarm.control import require_available, within_workspace
from agent_swarm.runtime import RuntimeAdapterError
from .context import restore_codex_context
from .managed_session import CodexManagedExecution


# Public calls may bind fresh consumer instances in the same owning process.
_TURNS: dict[str, CodexManagedExecution] = {}
_TURNS_LOCK = threading.Lock()

# Native Codex effort levels; a model's own list may be narrower.
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh')


def _select(settings: dict, parameters: dict, selection: Mapping[str, Any]) -> None:
    """Apply one create selection to captured Codex settings in place.

    A selected connection replaces the host's native home, endpoint and
    credential reference together, so a key never reaches another endpoint.
    """
    connection = selection.get('settings')
    config = parameters['config']
    if connection is not None:
        settings['connection'] = {key: connection[name] for key, name in (
            ('runtime_home', 'home'), ('base_url', 'base_url'), ('api_key_env', 'api_key_env'))
            if name in connection}
        if 'provider' in connection:
            config['model_provider'] = connection['provider']
    if selection.get('model') is not None:
        parameters['model'] = selection['model']
    effort = selection.get('reasoning_effort')
    if effort is not None:
        if effort not in EFFORTS:
            raise AgentsError('invalid-reasoning-effort',
                              f'Codex takes reasoning_effort {list(EFFORTS)}, not {effort!r}.')
        config['model_reasoning_effort'] = effort


class CodexDriver:
    """Own native Codex turns, using host-selected Run.settings.

    Settings contain the existing adapter_request, evidence and connection
    documents. The host resolves settings before binding this driver; no role,
    Task, Git tree or GraphTraj installation is consulted. A consumer may
    supply its existing execution subclass to bind optional archive/review policy.
    """

    def __init__(
        self,
        settings: Mapping[str, Any] | None = None,
        *,
        execution: Callable[..., CodexManagedExecution] = CodexManagedExecution,
    ) -> None:
        """Capture explicit native settings without starting a Runtime."""
        self.settings = deepcopy(dict(settings)) if settings is not None else None
        self.execution = execution

    def prepare(self, runtime: str, caller: Caller, *, configuration: str | None = None,
                selection: Mapping[str, Any] | None = None, workspace: Path | None = None) -> dict:
        """Validate retained native values, with native auto review as the default.

        ``selection`` is the create's resolved connection, model and effort.
        ``workspace`` narrows the captured worktree to the child's cwd; the
        permission profiles, approval settings and network stay as captured.
        """
        if runtime != 'codex':
            raise AgentsError('unsupported-runtime', 'This driver runs Codex only.')
        if self.settings is None or configuration is not None:
            raise AgentsError('invalid-config', 'The host must supply captured Codex settings.')
        settings = deepcopy(self.settings)
        try:
            context = restore_codex_context(settings['adapter_request'], settings.get('evidence', {}))
            request = context.launch_document()['adapter_request']
            parameters = request['session_parameters']
            if workspace is not None:
                request['worktree_path'] = parameters['cwd'] = str(within_workspace(workspace, request['worktree_path']))
            config = parameters['config']
            if 'approvalsReviewer' not in parameters and 'approvals_reviewer' not in config:
                config['approvals_reviewer'] = 'auto_review'
            config['features'] = {**config.get('features', {}), 'exec_permission_approvals': True}
            if selection is not None:
                _select(settings, parameters, selection)
            settings['adapter_request'] = request
            settings.setdefault('evidence', {})
        except (KeyError, RuntimeAdapterError) as error:
            raise AgentsError('invalid-config', str(error)) from error
        return settings

    def require_available(self, connection: Mapping[str, Any]) -> None:
        """Refuse a connection whose Codex is not installed or not logged in."""
        home = Path(connection.get('home') or os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        require_available(connection, executable=shutil.which('codex'), home=home, logins=('auth.json',))

    def start(self, run: Run) -> None:
        """Return at native startup while one owner retains execution until close."""
        ready = threading.Event()
        failure: list[Exception] = []

        def created(session: str, pid: int) -> None:
            """Record native identity before any model input can run."""
            run.events.session(session)
            run.events.process(runtime_pid=pid)

        options = {'connection': run.settings.get('connection', {}), 'agent_call': run.call,
                   'archive': run.archive, 'extra_fields': run.extra_fields}
        if self.execution is not CodexManagedExecution:
            options.update(independent=True)
        turn = self.execution(dict(run.settings['adapter_request']), run.message, run.directory,
                              lambda session, pid: ready.set(), dict(run.settings.get('evidence', {})),
                              trace_file=run.directory / 'trace.jsonl', expected_session=run.session,
                              session_created=created, **options)
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        with _TURNS_LOCK:
            _TURNS[run.execution] = turn

        def own() -> None:
            """Report native completion only after the owning connection closes."""
            try:
                result = turn.run()
                run.events.finished(result['outcome'], last_message=result.get('last_agent_message'),
                                    error=result.get('error'),
                                    terminal_confirmed=result.get('terminal_confirmed', True))
            except Exception as error:
                failure.append(error)
                run.events.finished('failed', error={
                    'code': getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), 'message': str(error),
                }, terminal_confirmed=getattr(error, 'terminal_confirmed', False))
            finally:
                with _TURNS_LOCK:
                    _TURNS.pop(run.execution, None)
                ready.set()

        threading.Thread(target=own, name=f'codex-{run.agent}').start()
        ready.wait()
        if failure:
            error = failure[0]
            raise AgentsError(getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), str(error))

    def _turn(self, run: Run) -> CodexManagedExecution:
        """Return only this process's native owner for the given execution."""
        with _TURNS_LOCK:
            turn = _TURNS.get(run.execution)
        if turn is None:
            raise AgentsError('not-owned', 'This process does not own the native execution.')
        return turn

    def _operate(self, run: Run, **request: Any) -> dict:
        """Target the exact native Session and turn retained by the owner."""
        turn = self._turn(run)
        try:
            return turn.operate({**request, 'session': turn.session, 'execution_id': turn.execution_id})
        except RuntimeAdapterError as error:
            raise AgentsError(error.code, error.message) from error

    def deliver(self, run: Run, message: str) -> None:
        """Deliver ordinary text into the active native turn."""
        self._operate(run, operation='send', instruction=message)

    def interrupt(self, run: Run) -> bool:
        """Request interruption, leaving terminal confirmation to the owner."""
        return self._turn(run).terminate()

    def requests(self, run: Run) -> list[dict]:
        """Return pending native requests without answering them."""
        return self._operate(run, operation='requests')['requests']

    def reply(self, run: Run, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
        """Send one explicit response to the retained native request."""
        return self._operate(run, operation='reply', request_token=request.get('request_token'),
                             response=dict(response))
