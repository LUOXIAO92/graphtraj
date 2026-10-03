"""Own Pi's persistent stdio transport for one Runner execution."""

from __future__ import annotations

from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import uuid

from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, SessionStarted


INFORMATION = {'notify', 'setStatus', 'setWidget', 'setTitle', 'set_editor_text'}
DIALOGS = {'select', 'confirm', 'input', 'editor'}


class PiManagedExecution:
    """Keep native identity, input and queue-aware stopping on one owned pipe."""

    def __init__(
        self,
        request: dict,
        prompt: str,
        directory: Path,
        started: SessionStarted,
        created: SessionStarted,
        trace_file: Path,
        expected_session: str | None,
    ) -> None:
        """Capture the retained Context without launching a process."""
        self.request = copy.deepcopy(request)
        self.prompt = prompt
        self.directory = directory
        self.started = started
        self.created = created
        self.trace = trace_file
        self.expected = expected_session
        self.session: str | None = None
        self._execution_id = uuid.uuid4().hex
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue()
        self.responses: dict[str, queue.Queue] = {}
        self.pending: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.stopping = threading.Event()
        self.done = threading.Event()
        self.outcome: dict | None = None
        self.transport_closed = threading.Event()
        self.prompt_started = False
        self.stderr_reader: threading.Thread | None = None

    @property
    def execution_id(self) -> str:
        """Return this invocation's correlated Pi prompt request ID."""
        return self._execution_id

    def _send(self, document: dict) -> None:
        """Serialize writes; no model arguments can address another pipe."""
        with self.write_lock:
            if self.proc is None or self.proc.poll() is not None:
                raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Pi transport is closed.')
            try:
                self.proc.stdin.write(json.dumps(document) + '\n')
                self.proc.stdin.flush()
            except (OSError, ValueError) as error:
                raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Pi input pipe failed.') from error

    def _rpc(self, kind: str, *, identity: str | None = None, **arguments: object) -> dict:
        """Correlate receipt separately from task completion."""
        if self.transport_closed.is_set():
            raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Pi transport closed before ' + kind + '.',
                                      terminal_confirmed=False)
        identity = identity or uuid.uuid4().hex
        reply: queue.Queue = queue.Queue()
        self.responses[identity] = reply
        try:
            self._send({'id': identity, 'type': kind, **arguments})
            response = reply.get(timeout=30)
            if not response.get('success'):
                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                          'Pi ' + kind + ' failed: ' + str(response.get('error', 'transport closed')))
            return response.get('data', {})
        except queue.Empty as error:
            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Pi did not acknowledge ' + kind + '.') from error
        finally:
            self.responses.pop(identity, None)

    def _read(self) -> None:
        """Drain replies and native events continuously, including idle dialogs."""
        assert self.proc is not None
        with (self.trace.with_suffix('.pi') / 'rpc.jsonl').open('a', encoding='utf-8') as log:
            try:
                for line in self.proc.stdout:
                    log.write(line)
                    log.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        self.events.put({'type': 'transport_error'})
                        break
                    if not isinstance(event, dict):
                        self.events.put({'type': 'transport_error'})
                        break
                    if event.get('type') == 'extension_ui_request' and event.get('method') not in INFORMATION:
                        if self.session is None:
                            self.events.put({'type': 'startup_interaction', 'event': event})
                            for target in list(self.responses.values()):
                                target.put({'success': False, 'error': 'Pi needs a native startup interaction before Session binding.'})
                        else:
                            try:
                                self._interaction(event)
                            except RuntimeAdapterError as error:
                                self.events.put({'type': 'interaction_error', 'error': error})
                        continue
                    target = self.responses.get(event.get('id')) if event.get('type') == 'response' else None
                    if target is not None:
                        target.put(event)
                    else:
                        self.events.put(event)
            finally:
                self.transport_closed.set()
                for target in list(self.responses.values()):
                    target.put({'success': False, 'error': 'transport closed'})
                self.events.put({'type': 'transport_error'})

    def _prepare(self, address: str) -> tuple[list[str], dict]:
        """Project native asb fields and preserve user resources through references."""
        request = self.request
        worktree = Path(request['worktree_path']).resolve()
        root = Path(request['harness_root']).resolve()
        # This directory belongs to retained Trace evidence, not disposable Worker state.
        native = self.trace.with_suffix('.pi')
        native.mkdir(parents=True, exist_ok=True)
        source = Path(request['agent_dir'])
        agent = native / 'agent'
        agent.mkdir(exist_ok=True)
        read = [str(worktree), str(native), address, request['docs_directory'],
                str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve()),
                str(Path(__file__).resolve().parents[2]), *request['resources']]
        write = [str(native), address]
        for name in ('settings.json', 'models.json', 'auth.json', 'trust.json', 'keybindings.json', 'npm', 'extensions',
                     'skills', 'prompts', 'themes', 'mcp.json', 'AGENTS.md',
                     'AGENTS.override.md', 'AGENTS.MD', 'CLAUDE.md', 'CLAUDE.MD', 'SYSTEM.md', 'APPEND_SYSTEM.md'):
            original = source / name
            link = agent / name
            if original.exists():
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(original)
                read.append(str(original.resolve()))
        if request['worktree_access'] == 'write':
            write.extend((str(worktree), request['git_common_directory']))
        read.extend(request['reports'])
        resources = (worktree / '.agents', worktree / 'AGENTS.md', worktree / 'CONTEXT.md', worktree / 'docs')
        read.extend(str(p.resolve()) for p in resources if p.exists())
        policy = {
            'network': {'allowedDomains': ['api.deepseek.com', 'openrouter.ai'], 'deniedDomains': []},
            'filesystem': {
                'denyRead': [str(root / '.graphtraj'), str(root / '.codex'),
                             str(Path.home() / '.codex'), str(source), request['state_directory']],
                'allowRead': read,
                'allowWrite': write,
                'denyWrite': [str(source), str(root / '.graphtraj/config.yml'),
                              str(root / '.graphtraj/roles.yml'),
                              request['docs_directory'],
                              str(Path(sys.prefix).resolve()), str(Path(__file__).resolve().parents[2]),
                              str(Path(request['git_common_directory']) / 'config'),
                              str(Path(request['git_common_directory']) / 'hooks'),
                              *(str(p.resolve()) for p in resources if p.exists())],
            },
        }
        # Grants are native filesystem rules, never a command/path-filter hook.
        policy_file = self.directory / 'pi-policy.json'
        policy_file.write_text(json.dumps(policy), encoding='utf-8')
        instructions = native / 'role-instructions.txt'
        instructions.write_text(request['instructions'], encoding='utf-8')
        native_trace = native / 'session.jsonl'
        if self.expected and not native_trace.is_file():
            raise RuntimeAdapterError('RUNTIME_SESSION_NOT_RESUMABLE', 'Pi native Session file is missing.')
        argv = [request['executable'], '--mode', 'rpc', '--provider', request['provider'],
                '--model', request['model'], '--session', str(native_trace),
                '--append-system-prompt', str(instructions)]
        if request.get('reasoning_effort'):
            argv += ['--thinking', request['reasoning_effort']]
        spec = self.directory / 'pi-process.json'
        spec.write_text(json.dumps({'policy': str(policy_file), 'argv': argv}), encoding='utf-8')
        env = dict(os.environ)
        # Do not forward Runner bookkeeping as model-declared authority. The only
        # child operation address is authenticated by the existing hosted CLI.
        for key in tuple(env):
            if key.startswith('GRAPHTRAJ_'):
                del env[key]
        env.update({'PATH': str(Path(sys.executable).parent) + os.pathsep + request['sandbox_path'],
                    'PI_CODING_AGENT_DIR': str(agent),
                    'GRAPHTRAJ_CLI_CONNECTION': address, 'GRAPHTRAJ_HARNESS_ROOT': str(root),
                    'PI_ASB_NO_ALIAS_PROMPT': '1'})
        key = request.get('api_key_env')
        native_key = {'deepseek': 'DEEPSEEK_API_KEY', 'openrouter': 'OPENROUTER_API_KEY'}.get(request['provider'])
        if key and native_key and key in os.environ:
            env[native_key] = os.environ[key]
        # Pi's native find accepts an existing fd on PATH; do not download it or
        # alter the user's installation to populate the isolated cache.
        fd = source / 'bin/fd'
        if fd.is_file():
            env['PATH'] += os.pathsep + str(fd.parent)
            policy['filesystem']['allowRead'].append(str(fd.resolve()))
            policy_file.write_text(json.dumps(policy), encoding='utf-8')
        self.native_trace = native_trace
        return [request['sandbox_python'], str(Path(__file__).with_name('launch.py')), str(spec)], env

    def _retain_trace(self) -> None:
        """Link the native file without normalizing timestamps or encrypted fields."""
        if self.native_trace.is_file() and not self.trace.is_symlink():
            self.trace.unlink(missing_ok=True)
            self.trace.symlink_to(self.native_trace)

    def run(self) -> dict:
        """Bind real Pi identity before task input, then observe native settlement."""
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features

        reader = None
        with ExitStack() as resources:
            address = resources.enter_context(cli_connection(
                Path(self.request['harness_root']), self.directory.name, native_operation_features()))
            argv, env = self._prepare(address)
            stderr = resources.enter_context((self.directory / 'stderr.log').open('a', encoding='utf-8'))
            stderr_offset = stderr.tell()
            try:
                self.proc = subprocess.Popen(argv, cwd=self.request['worktree_path'], env=env,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             text=True, bufsize=1, start_new_session=True)

                def retain_stderr() -> None:
                    """Keep private log files host-side; Node must be able to stat its stdio."""
                    assert self.proc is not None
                    for line in self.proc.stderr:
                        stderr.write(line)
                        stderr.flush()

                self.stderr_reader = threading.Thread(target=retain_stderr, daemon=True)
                self.stderr_reader.start()
                reader = threading.Thread(target=self._read, daemon=True)
                reader.start()
                state = self._rpc('get_state')
                self.session = state.get('sessionId')
                if not isinstance(self.session, str) or not self.session:
                    raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Pi did not return a native Session.')
                if self.expected and self.session != self.expected:
                    raise RuntimeAdapterError('RUNTIME_SESSION_NOT_RESUMABLE', 'Pi resumed a different native Session.')
                if state.get('sessionFile') != str(self.native_trace):
                    raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Pi did not bind the requested native Session file.')
                model = state.get('model', {})
                if (model.get('provider'), model.get('id')) != (self.request['provider'], self.request['model']):
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Pi selected a different provider/model.')
                write_yaml_durably(self.directory / 'session.yml', {
                    'session': self.session, 'rollout_path': str(self.native_trace), 'model': model,
                    'runtime_version': self.request['version'],
                })
                self.created(self.session, self.proc.pid)
                with self.lock:
                    if self.stopping.is_set():
                        return self._result('interrupted', None)
                    self.started(self.session, self.proc.pid)
                disposition = self._rpc('prompt', identity=self.execution_id, message=self.prompt)
                if disposition.get('disposition') != 'started':
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Pi task prompt did not start a run.')
                self.prompt_started = True
                if self.stopping.is_set():
                    self._interrupt()
                last = None
                failure = None
                native_aborted = False
                while True:
                    event = self.events.get()
                    self._retain_trace()
                    kind = event.get('type')
                    if kind == 'transport_error':
                        raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Pi closed before confirmed settlement.')
                    if kind == 'interaction_error':
                        raise event['error']
                    if kind == 'extension_ui_request':
                        self._interaction(event)
                    if kind == 'message_end':
                        message = event.get('message', {})
                        if message.get('role') == 'assistant':
                            last = '\n'.join(p.get('text', '') for p in message.get('content', [])
                                             if isinstance(p, dict) and p.get('type') == 'text')
                            if message.get('stopReason') == 'error':
                                failure = str(message.get('errorMessage', 'Pi provider failed.'))
                            else:
                                failure = None
                            native_aborted = message.get('stopReason') == 'aborted'
                    if kind == 'agent_settled':
                        with self.lock:
                            state = self._rpc('get_state')
                            if state.get('isStreaming') or state.get('isCompacting') or state.get('pendingMessageCount'):
                                continue
                            if failure and not self.stopping.is_set():
                                raise RuntimeAdapterError('RUNTIME_PROVIDER_FAILED', failure)
                            return self._result('interrupted' if self.stopping.is_set() or native_aborted else 'completed', last)
            finally:
                original_error = sys.exc_info()[1]
                # Native abort owns tools/queues. Closing the transport and reaping
                # this exact process follows it, and never targets another Session.
                native_idle = self.outcome is not None
                try:
                    if self.proc is not None and self.proc.poll() is None:
                        if not self.done.is_set():
                            try:
                                self._interrupt()
                                state = self._rpc('get_state')
                                if state.get('isStreaming') or state.get('isCompacting') or state.get('pendingMessageCount'):
                                    raise RuntimeAdapterError('RUNTIME_SHUTDOWN_FAILED', 'Pi still has pending work.',
                                                              terminal_confirmed=False)
                                native_idle = True
                            except RuntimeAdapterError:
                                # Reap our transport below, but do not mistake that
                                # for confirmation that detached tools have stopped.
                                native_idle = False
                        self.proc.stdin.close()
                        try:
                            self.proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(self.proc.pid, signal.SIGTERM)
                            try:
                                self.proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                os.killpg(self.proc.pid, signal.SIGKILL)
                                self.proc.wait(timeout=5)
                    if self.proc is not None and not native_idle:
                        raise self._shutdown_failure(original_error, stderr_offset)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise self._shutdown_failure(original_error or error, stderr_offset) from error
                finally:
                    if self.stderr_reader is not None:
                        self.stderr_reader.join(timeout=5)
                    if reader is not None:
                        reader.join(timeout=5)
                    if hasattr(self, 'native_trace'):
                        self._retain_trace()
                    self.done.set()

    def _shutdown_failure(self, cause: BaseException | None, stderr_offset: int) -> RuntimeAdapterError:
        """Expose this launch's cause through Runner without certifying native stop."""
        if self.stderr_reader is not None:
            self.stderr_reader.join(timeout=5)
        details = 'Pi native stop is unconfirmed.'
        if cause is not None:
            details += f' Original error [{getattr(cause, "code", type(cause).__name__)}]: {cause}'
        if self.proc is not None:
            details += f' Native process exit: {self.proc.poll()}.'
        # Startup stderr is otherwise unreachable when no Session mapping could
        # be bound. Do not expose older executions or task-generated stderr.
        if not self.prompt_started:
            try:
                with (self.directory / 'stderr.log').open('rb') as stream:
                    stream.seek(stderr_offset)
                    diagnostic = stream.read(8192).decode('utf-8', errors='replace')
                if diagnostic.strip():
                    details += '\nStartup stderr: ' + diagnostic.strip()
            except OSError:
                details += ' Startup stderr unavailable.'
        for name, value in os.environ.items():
            if value and (name == self.request.get('api_key_env')
                          or any(part in name.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))):
                details = details.replace(value, '[REDACTED]')
        details = re.sub(r'(?i)(bearer\s+)[^\s"\']+', r'\1[REDACTED]', details)
        details = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', details)
        details = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[REDACTED]', details)
        return RuntimeAdapterError('RUNTIME_SHUTDOWN_FAILED', details, terminal_confirmed=False)

    def _result(self, outcome: str, last: str | None) -> dict:
        """Publish a terminal result only after native idle and empty queue."""
        self.outcome = {'outcome': outcome, 'session_id': self.session,
                        'execution_id': self.execution_id, 'last_agent_message': last}
        self.done.set()
        return self.outcome

    def _interaction(self, event: dict) -> None:
        """Retain information and route actual native dialogs to the direct parent."""
        from graphtraj.execution.runner_control import notify_direct_parent

        method = event.get('method')
        if method in INFORMATION:
            return
        if method not in DIALOGS:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unsupported Pi UI method: ' + str(method))
        token = uuid.uuid4().hex
        details = {'session': self.session, 'execution_id': self.execution_id,
                   'request_id': event['id'], 'request_token': token,
                   'method': 'pi/' + method, 'params': event}
        self.pending[token] = details

        def notify() -> None:
            """Notify through the existing parent execution without granting consent."""
            try:
                receipt = notify_direct_parent(self.directory, 'Pi child requires a native reply:\n' + json.dumps(details), details)
                if receipt is not None and receipt.get('delivery') not in {'received', 'no-direct-parent'}:
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Pi dialog notification was not delivered.')
            except Exception:
                self.events.put({'type': 'interaction_error', 'error': RuntimeAdapterError(
                    'RUNTIME_REQUEST_FAILED', 'Pi native dialog could not reach its direct parent.')})

        threading.Thread(target=notify, daemon=True).start()

    def _interrupt(self) -> None:
        """Clear pending work before abort; an ACK alone never publishes completion."""
        with self.lock:
            self.stopping.set()
            for details in list(self.pending.values()):
                self._send({'type': 'extension_ui_response', 'id': details['request_id'], 'cancelled': True})
            self.pending.clear()
            self._rpc('clear_queue')
            self._rpc('abort')

    def terminate(self) -> bool:
        """Retain a stop even before Session startup; do not claim terminal state."""
        self.stopping.set()
        if self.proc is None or self.session is None:
            return False

        def stop() -> None:
            """Request native cancellation while the owner keeps draining events."""
            try:
                self._interrupt()
            except RuntimeAdapterError:
                pass

        threading.Thread(target=stop, daemon=True).start()
        return True

    def operate(self, request: dict) -> dict:
        """Control only this bound Session/execution using Runner's existing server."""
        with self.lock:
            if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                raise RuntimeAdapterError('operation-failed', 'Pi execution is not owned.')
            operation = request.get('operation')
            if operation == 'status':
                return ({'activity': 'idle', 'last_outcome': self.outcome['outcome']} if self.outcome else
                        {'activity': 'running', **({'waiting_for': 'runtime-request'} if self.pending else {})})
            if operation == 'requests':
                return {'requests': list(self.pending.values()) if not self.done.is_set() else []}
            if self.done.is_set():
                raise RuntimeAdapterError('operation-failed', 'Pi execution has ended.')
            if operation == 'reply':
                details = self.pending.get(request.get('request_token'))
                response = request.get('response')
                if details is None or not isinstance(response, dict) or not response or set(response) - {'value', 'confirmed', 'cancelled'}:
                    raise RuntimeAdapterError('invalid-input', 'Supply an explicit reply to a pending Pi dialog.')
                if (any(key in response and not isinstance(response[key], bool) for key in ('confirmed', 'cancelled'))
                        or ('value' in response and not isinstance(response['value'], str))):
                    raise RuntimeAdapterError('invalid-input', 'Pi dialog values must have their native types.')
                self._send({'type': 'extension_ui_response', **response, 'id': details['request_id']})
                del self.pending[request['request_token']]
                return {'request_id': details['request_id'], 'reply_status': 'submitted'}
            if operation == 'send':
                if self.stopping.is_set():
                    raise RuntimeAdapterError('operation-failed', 'Pi is stopping; input was not queued.')
                if not self.prompt_started:
                    raise RuntimeAdapterError('operation-failed', 'Pi is still accepting its initial prompt.')
                # Native prompt queues during streaming and starts a run if Pi
                # settled before Runner consumed its final event. Bare steer
                # would leave an idle Session with an undelivered queue.
                self._rpc('prompt', message=request['instruction'], streamingBehavior='steer')
                return {}
            if operation != 'interrupt':
                raise RuntimeAdapterError('invalid-input', 'Unknown Pi operation.')
        self._interrupt()
        if not self.done.wait(timeout=30) or not self.outcome or self.outcome['outcome'] != 'interrupted':
            raise RuntimeAdapterError('operation-failed', 'Pi interruption is not yet confirmed.', terminal_confirmed=False)
        return {}
