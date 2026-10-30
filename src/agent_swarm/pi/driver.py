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
from agent_swarm.models import pi_destination
from agent_swarm.runtime import RuntimeAdapterError
from .execution import PiExecution, RPC_SECONDS

# Native Pi thinking levels; a model's own list may be narrower.
EFFORTS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh')


def selected(request: Mapping[str, Any], selection: Mapping[str, Any]) -> dict:
    """Apply one create selection to the host's Pi launch request.

    A selected connection or another provider replaces the host's endpoint
    and key, so a host key never reaches another provider. When the provider,
    model, home or key changes, the network destination is read again from
    Pi's catalog in the selected home; a model without a plain http(s)
    destination is refused rather than launched under the wrong grants.
    """
    host = request
    request = deepcopy(dict(request))
    connection = selection.get('settings')
    if connection is not None and 'base_url' in connection:
        raise AgentsError('invalid-config', 'A Pi connection takes no base_url: config.yml has no provider API. '
                                            "Declare the endpoint as a provider in Pi's own models.json in the "
                                            "connection's home and select that provider and model.")
    provider = selection.get('provider')
    if connection is not None or provider not in (None, request['provider']):
        for field in ('api_key_env', 'base_url', 'provider_api'):
            request.pop(field, None)
    if connection is not None:
        if 'api_key_env' in connection:
            request['api_key_env'] = connection['api_key_env']
        if 'home' in connection:
            request['agent_dir'] = connection['home']
    if provider is not None:
        request['provider'] = provider
    if selection.get('model') is not None:
        request['model'] = selection['model']
    effort = selection.get('reasoning_effort')
    if effort is not None:
        if effort not in EFFORTS:
            raise AgentsError('invalid-reasoning-effort',
                              f'Pi takes reasoning_effort {list(EFFORTS)}, not {effort!r}.')
        request['reasoning_effort'] = effort
    chosen = ('provider', 'model', 'agent_dir', 'api_key_env')
    if not request.get('base_url') and any(request.get(field) != host.get(field) for field in chosen):
        try:
            request['provider_domain'] = pi_destination(
                request['executable'], request['agent_dir'], request['provider'], request['model'],
                request.get('api_key_env'))
        except RuntimeAdapterError as error:
            raise AgentsError('invalid-config', f"{error.message} Provider {request['provider']!r}, "
                                                f"model {request['model']!r}.") from None
    return request


class PiDriver:
    """Bind a host-prepared Pi launch request to the independent control core.

    The host resolves model/provider, resource references and native isolation
    before binding. This driver retains that exact request for continuation;
    it does not discover product configuration or Git.
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

        def framed(notice: Mapping[str, Any]) -> str:
            """Name the child and this parent, as the Claude and Codex bindings do."""
            return f"[agents · {notice['agent']} → {run.agent}]\n{notice['body']}"

        # The child's end that continues this Session is the turn's input.
        notice = run.settings.get('completion_message')
        prompt = framed(notice) if notice else run.message
        turn = PiExecution(dict(run.settings['adapter_request']), prompt, run.directory,
                           lambda session, pid: ready.set(), created,
                           run.directory / 'trace.jsonl', run.session)
        turn.archive = run.archive
        turn.extra_fields = run.extra_fields
        turn.agent = run.agent
        turn.agent_call = run.call
        turn.parent_notice = lambda message, details: (run.events.request(details), {'delivery': 'retained'})[1]
        turn.record_process = lambda pid, outcome=None: (
            run.events.process(runtime_pid=pid) if outcome is None else run.events.process(runtime_exit=outcome))
        if notice:
            turn.unseen.append({'text': prompt, 'notice': notice})

        def receive(event: dict) -> bool | str:
            """Queue into the running turn, or continue the retained Session when nothing reached it."""
            if event['parent'] != run.agent or not event['session']:
                return False
            # Held notices are flushed when start returns, before Pi accepted the prompt.
            turn.accepted.wait(RPC_SECONDS)
            return (turn.send_notice(framed(event), event)
                    or run.events.continue_from_child(event, run.archive))

        run.events.receive_children(receive)
        with self.lock:
            self.turns[run.execution] = turn

        def return_unseen() -> None:
            """Hold again what a stopped turn dropped from Pi's queue, before the end's flush looks."""
            for dropped in turn.take_unseen():
                run.events.return_notice(dropped)

        def own() -> None:
            """Report native completion only after confirmed native settlement."""
            try:
                result = turn.run()
                # A completed turn settled with Pi's queue empty: nothing was dropped.
                if result['outcome'] != 'completed':
                    return_unseen()
                run.events.finished(result['outcome'], last_message=result.get('last_agent_message'))
            except Exception as error:
                failure.append(error)
                return_unseen()
                run.events.finished('failed', error={
                    'code': getattr(error, 'code', 'RUNTIME_WORKER_FAILED'), 'message': str(error),
                }, terminal_confirmed=getattr(error, 'terminal_confirmed', False))
            finally:
                with self.lock:
                    self.turns.pop(run.execution, None)
                turn.accepted.set()
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
