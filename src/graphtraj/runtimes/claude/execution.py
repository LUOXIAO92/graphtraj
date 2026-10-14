"""Own Claude Code's official stream-JSON control transport for one invocation."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid

from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, SessionStarted, record_runtime_process


class ClaudeExecution:
    """Keep native permissions, registration and terminal evidence on one pipe."""

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
        """Capture inputs; process creation belongs exclusively to run()."""
        self.request = copy.deepcopy(request)
        self.prompt = prompt
        self.directory = directory
        self.started = started
        self.created = created
        self.trace = trace_file
        self.expected = expected_session
        self.session: str | None = None
        self.native_id = expected_session or str(uuid.uuid4())
        self._execution_id = uuid.uuid4().hex
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue()
        self.pending: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.stopping = threading.Event()
        self.done = threading.Event()
        self.outcome: dict | None = None
        self.terminal_confirmed = False
        self.accepting = True
        self.sent = 0
        self.results = 0
        self.native_state: str | None = None
        self.task_released = False

    @property
    def execution_id(self) -> str:
        """Return the exact Worker invocation identity before native registration."""
        return self._execution_id

    def _send(self, document: dict) -> None:
        """Serialize protocol writes to the owned process only."""
        with self.write_lock:
            try:
                if self.proc is None or self.proc.poll() is not None:
                    raise OSError('closed')
                self.proc.stdin.write(json.dumps(document) + '\n')
                self.proc.stdin.flush()
            except (OSError, ValueError) as error:
                raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Claude input pipe is closed.') from error

    def _control(self, subtype: str, **fields: object) -> str:
        """Send one official SDK control request; an ACK is not completion."""
        identity = uuid.uuid4().hex
        self._send({'type': 'control_request', 'request_id': identity,
                    'request': {'subtype': subtype, **fields}})
        return identity

    def _reply(self, identity: str, response: dict) -> None:
        """Return a correlated native hook or permission response."""
        self._send({'type': 'control_response', 'response': {
            'subtype': 'success', 'request_id': identity, 'response': response,
        }})

    def _prompt(self, text: str) -> None:
        """Queue a native user message while counting each expected result."""
        self._send({'type': 'user', 'session_id': self.native_id,
                    'message': {'role': 'user', 'content': text}, 'parent_tool_use_id': None})
        self.sent += 1

    def _prepare(self, address: str) -> tuple[list[str], dict]:
        """Use native restricted mode and mandatory sandboxing without bypass flags."""
        request = self.request
        worktree = Path(request['worktree_path']).resolve()
        root = Path(request['harness_root']).resolve()
        home = Path(request['runtime_home']).resolve()
        resources = [p.resolve() for p in (worktree / 'docs', worktree / 'CONTEXT.md',
                                           worktree / 'AGENTS.md', worktree / '.agents') if p.exists()]
        resources.extend(Path(path).resolve() for path in request['resources'])
        denied_read = [request['state_directory'], str(root / '.graphtraj/runner'),
                       str(root / '.graphtraj/cli'),
                       str(root / '.codex'), str(Path.home() / '.codex'), str(home)]
        denied_write = [*map(str, resources), request['docs_directory'], str(home),
                        str(root / '.graphtraj/config.yml'), str(root / '.graphtraj/roles.yml'),
                        str(Path(request['git_common_directory']) / 'config'),
                        str(Path(request['git_common_directory']) / 'hooks'),
                        str(worktree / '.claude'), str(worktree / '.state'),
                        str(worktree / 'CONTEXT.md'), str(worktree / 'docs'), str(worktree / 'AGENTS.md'),
                        str(worktree / '.agents')]
        if request['worktree_access'] == 'read':
            denied_write.append(str(worktree))
        settings = {
            'permissions': {
                'defaultMode': 'default', 'blockReadsOutsideWorkingDirectories': True,
                'deny': [rule for p in denied_read for rule in (f'Read(/{p})', f'Read(/{p}/**)')]
                        + [rule for p in denied_write for rule in (f'Edit(/{p})', f'Edit(/{p}/**)')]
                        + (['Edit', 'Write', 'NotebookEdit'] if request['worktree_access'] == 'read' else []),
                'additionalDirectories': [str(p) for p in resources if p.is_dir()],
            },
            'sandbox': {
                'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                'autoAllowBashIfSandboxed': False, 'excludedCommands': [],
                'filesystem': {
                    'denyRead': [str(root / '.graphtraj'), *denied_read],
                    'allowRead': [str(worktree), address, request['git_common_directory'], *map(str, resources),
                                  str(Path(sys.prefix).resolve()), str(Path(__file__).resolve().parents[2])],
                    'allowWrite': [address] + ([request['git_common_directory']]
                                              if request['worktree_access'] == 'write' else []),
                    'denyWrite': denied_write,
                },
            },
        }
        # The MCP process uses the same PID-authenticated hosted CLI as native Bash.
        mcp = {'mcpServers': {'graphtraj': {
            'command': sys.executable, 'args': ['-m', 'graphtraj.interfaces.mcp'],
            'env': {'GRAPHTRAJ_CLI_CONNECTION': address},
        }}}
        argv = [request['executable'], '--print', '--verbose', '--input-format', 'stream-json',
                '--output-format', 'stream-json', '--include-partial-messages',
                '--permission-prompt-tool', 'stdio',
                '--permission-mode', 'default', '--restricted', '--strict-mcp-config',
                '--mcp-config', json.dumps(mcp), '--settings', json.dumps(settings),
                '--tools', 'Bash,Read,Write,Edit,Glob,Grep', '--model', request['model'],
                '--append-system-prompt', request['instructions'],
                '--resume' if self.expected else '--session-id', self.native_id]
        if request['reasoning_effort'] is not None:
            argv += ['--effort', request['reasoning_effort']]
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GRAPHTRAJ_')}
        environment.update(GRAPHTRAJ_CLI_CONNECTION=address, CLAUDE_CODE_SDK_READS_SESSION_STATE='1',
                           CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1', CLAUDE_CODE_SUBPROCESS_ENV_SCRUB='1')
        if request.get('explicit_runtime_home'):
            environment['CLAUDE_CONFIG_DIR'] = str(home)
        if request['reasoning_effort'] is not None:
            environment['CLAUDE_CODE_EFFORT_LEVEL'] = request['reasoning_effort']
        if request.get('base_url'):
            environment['ANTHROPIC_BASE_URL'] = request['base_url']
        else:
            environment.pop('ANTHROPIC_BASE_URL', None)
        if request.get('api_key_env'):
            from graphtraj.runtimes.runtime_adapter import credential_environment

            for key in ('ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN'):
                environment.pop(key, None)
            environment['ANTHROPIC_API_KEY'] = credential_environment(request['api_key_env'])[request['api_key_env']]
        # Persist only nonsecret settings and exact native launch inputs.
        write_yaml_durably(self.directory / 'claude-settings.yml', settings)
        return argv, environment

    def _read(self) -> None:
        """Retain native records unchanged, including unknown fields and failures."""
        assert self.proc is not None
        try:
            with self.trace.open('a', encoding='utf-8') as trace:
                for line in self.proc.stdout:
                    trace.write(line)
                    trace.flush()
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError('object')
                    except ValueError:
                        self.events.put({'type': 'transport_error'})
                        return
                    self.events.put(event)
        finally:
            self.events.put({'type': 'eof'})

    def _bind(self, event: dict) -> None:
        """Register only a real native startup identity before releasing its hook."""
        native = event.get('input', {})
        if (native.get('hook_event_name') != 'UserPromptSubmit'
                or native.get('session_id') != self.native_id):
            raise RuntimeAdapterError('RUNTIME_SESSION_NOT_RESUMABLE', 'Claude startup identity differs from requested Session.')
        if self.session is not None:
            return
        self.session = native['session_id']
        write_yaml_durably(self.directory / 'session.yml', {
            'session': self.session, 'rollout_path': native.get('transcript_path'),
            'runtime_version': self.request['version'], 'source': native.get('source'),
            'configured_model': self.request['model'], 'configured_effort': self.request['reasoning_effort'],
            'native_init': getattr(self, 'native_init', None),
        })
        assert self.proc is not None
        self.created(self.session, self.proc.pid)
        if self.stopping.is_set():
            raise RuntimeAdapterError('RUNTIME_EXECUTION_INTERRUPTED', 'Claude startup was interrupted.')
        self.started(self.session, self.proc.pid)

    def _permission(self, event: dict) -> None:
        """Send the native request to the direct parent without deciding consent."""
        from graphtraj.execution.runner_control import notify_direct_parent

        if self.session is None:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Claude requested permission before binding.')
        token = uuid.uuid4().hex
        details = {'session': self.session, 'execution_id': self.execution_id,
                   'request_id': event['request_id'], 'request_token': token,
                   'method': 'claude/can_use_tool', 'params': event['request']}
        with self.lock:
            self.pending[token] = details

        def notify() -> None:
            """Deliver without blocking the pipe that must still accept interruption."""
            try:
                receipt = notify_direct_parent(self.directory, 'Claude requires a native permission reply:\n'
                                               + json.dumps(details), details)
                if receipt is not None and receipt.get('delivery') not in {'received', 'no-direct-parent'}:
                    raise ValueError('delivery')
            except Exception:
                self.events.put({'type': 'notification_error'})

        threading.Thread(target=notify, daemon=True).start()

    def run(self) -> dict:
        """Own startup, work and cleanup; publish completion only after process exit."""
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features
        from graphtraj.runtimes.activity import redact

        last = None
        result_error = None
        reader = None
        stderr_reader = None
        failure = None
        with ExitStack() as resources:
            address = resources.enter_context(cli_connection(
                Path(self.request['harness_root']), self.directory.name, native_operation_features()))
            argv, environment = self._prepare(address)
            stderr = resources.enter_context((self.directory / 'stderr.log').open('a', encoding='utf-8'))
            try:
                if self.stopping.is_set():
                    raise RuntimeAdapterError('RUNTIME_EXECUTION_INTERRUPTED', 'Claude stopped before process creation.')
                self.proc = subprocess.Popen(argv, cwd=self.request['worktree_path'], env=environment,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             text=True, bufsize=1, start_new_session=True)
                record_runtime_process(self.proc.pid)

                def drain_stderr() -> None:
                    """Keep native stderr host-owned and separate from conversation records."""
                    assert self.proc is not None
                    for line in self.proc.stderr:
                        stderr.write(line)
                        stderr.flush()

                stderr_reader = threading.Thread(target=drain_stderr, daemon=True)
                stderr_reader.start()
                reader = threading.Thread(target=self._read, daemon=True)
                reader.start()
                initialization = self._control('initialize', hooks={
                    'UserPromptSubmit': [{'matcher': None, 'hookCallbackIds': ['graphtraj_start']}],
                })
                startup_deadline = time.monotonic() + 45
                stop_deadline = None
                while True:
                    if self.stopping.is_set() and stop_deadline is None:
                        stop_deadline = time.monotonic() + 5
                    if stop_deadline is not None and time.monotonic() >= stop_deadline:
                        break
                    if self.session is None and time.monotonic() >= startup_deadline:
                        raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude did not attest startup within 45 seconds.')
                    try:
                        event = self.events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    kind = event.get('type')
                    if kind == 'control_response':
                        response = event.get('response', {})
                        if response.get('request_id') == initialization:
                            if response.get('subtype') != 'success':
                                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude initialization failed.')
                            if response.get('response', {}).get('hooks_applied') is not True:
                                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude did not install the registration hook.')
                            with self.lock:
                                if not self.stopping.is_set():
                                    self._prompt(self.prompt)
                    elif kind == 'control_request':
                        request = event.get('request', {})
                        if request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'graphtraj_start':
                            self._bind(request)
                            self._reply(event['request_id'], {})
                            self.task_released = True
                        elif request.get('subtype') == 'can_use_tool':
                            self._permission(event)
                        else:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unknown Claude control request.')
                    elif kind == 'control_cancel_request':
                        with self.lock:
                            self.pending = {key: value for key, value in self.pending.items()
                                            if value['request_id'] != event.get('request_id')}
                    elif kind == 'system' and event.get('subtype') == 'init':
                        if event.get('session_id') != self.native_id or event.get('model') != self.request['model']:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude selected a different Session or model.')
                        self.native_init = event
                        if self.session is not None:
                            observed = yaml_document(self.directory / 'session.yml')
                            observed['native_init'] = event
                            write_yaml_durably(self.directory / 'session.yml', observed)
                    elif kind == 'system' and event.get('subtype') == 'session_state_changed':
                        self.native_state = event.get('state')
                    elif kind == 'result':
                        if event.get('session_id') != self.session:
                            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude result has a different Session.')
                        self.results += 1
                        last = event.get('result') or last
                        if event.get('is_error'):
                            result_error = redact(str(event.get('errors') or event.get('result') or event.get('subtype')))
                    elif kind == 'assistant' and event.get('parent_tool_use_id') is None:
                        model = event.get('message', {}).get('model')
                        if model is not None and model != '<synthetic>' and not event.get('error') and model != self.request['model']:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude changed the configured model.')
                        last = '\n'.join(block.get('text', '') for block in event.get('message', {}).get('content', [])
                                         if block.get('type') == 'text') or last
                    elif kind in {'transport_error', 'notification_error'}:
                        raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Claude transport or permission delivery failed.')
                    elif kind == 'eof':
                        if self.stopping.is_set():
                            break
                        if self.results < self.sent or not self.session:
                            raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Claude exited before a native terminal result.')
                        break
                    with self.lock:
                        if self.results and self.results >= self.sent and self.native_state == 'idle':
                            self.accepting = False
                            break
                if result_error and not self.stopping.is_set():
                    raise RuntimeAdapterError('RUNTIME_PROVIDER_FAILED', result_error)
            except BaseException as error:
                failure = error
            finally:
                with self.lock:
                    self.accepting = False
                try:
                    self._close()
                except RuntimeAdapterError as error:
                    failure = error
                if reader is not None:
                    reader.join(timeout=5)
                if stderr_reader is not None:
                    stderr_reader.join(timeout=5)
                pipes_drained = all(thread is None or not thread.is_alive()
                                    for thread in (reader, stderr_reader))
                if self.proc is not None and pipes_drained:
                    for stream in (self.proc.stdout, self.proc.stderr):
                        if stream is not None:
                            stream.close()
                if not pipes_drained or self.task_released and self.native_state != 'idle':
                    self.terminal_confirmed = False
                    failure = RuntimeAdapterError(
                        'RUNTIME_SHUTDOWN_FAILED',
                        'Claude native settlement or pipe closure is unconfirmed.'
                        + (f' Original failure: {failure}' if failure is not None else ''),
                        terminal_confirmed=False,
                    )
                if self.proc is not None:
                    record_runtime_process(self.proc.pid, {'terminal_confirmed': self.terminal_confirmed,
                                                          'runtime_exit_code': self.proc.poll()})
                if failure is None and self.session is not None:
                    self.outcome = {'outcome': 'interrupted' if self.stopping.is_set() else 'completed',
                                    'terminal_confirmed': self.terminal_confirmed,
                                    'session_id': self.session, 'execution_id': self.execution_id,
                                    'last_agent_message': last}
                self.done.set()
        if failure is not None:
            if isinstance(failure, RuntimeAdapterError):
                failure.terminal_confirmed = self.terminal_confirmed or self.proc is None
            raise failure
        if self.outcome is None:
            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude ended without a registered Session.')
        return self.outcome

    def _close(self) -> None:
        """Reap the owned process group, including tools; never equate ACK with exit."""
        if self.proc is None:
            self.terminal_confirmed = True
            return
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # A normal CLI exit may leave a background Bash child. The entire
            # owned group must disappear before Runner may release the Worker.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    continue
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try:
                        os.killpg(self.proc.pid, 0)
                    except ProcessLookupError:
                        self.terminal_confirmed = True
                        return
                    time.sleep(0.02)
            self.proc.wait(timeout=5)
            try:
                os.killpg(self.proc.pid, 0)
            except ProcessLookupError:
                self.terminal_confirmed = True
            if not self.terminal_confirmed:
                raise OSError('owned process group remains')
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeAdapterError('RUNTIME_SHUTDOWN_FAILED', 'Claude termination is unconfirmed.',
                                      terminal_confirmed=False) from error

    def terminate(self) -> bool:
        """Retain cancellation immediately; run() alone establishes termination."""
        with self.lock:
            self.stopping.set()
            self.accepting = False
            if self.proc is None or self.proc.poll() is not None:
                return False
            try:
                for details in list(self.pending.values()):
                    self._reply(details['request_id'], {'behavior': 'deny', 'message': 'Execution interrupted.', 'interrupt': True})
                self.pending.clear()
                self._control('interrupt')
            except RuntimeAdapterError:
                return False
            return True

    def operate(self, request: dict) -> dict:
        """Apply Runner controls only to the bound native Session and invocation."""
        with self.lock:
            if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                raise RuntimeAdapterError('operation-failed', 'Claude execution is not owned.')
            operation = request.get('operation')
            if operation == 'status':
                return ({'activity': 'idle', 'last_outcome': self.outcome['outcome']} if self.outcome else
                        {'activity': 'running', **({'waiting_for': 'runtime-request'} if self.pending else {})})
            if operation == 'requests':
                return {'requests': list(self.pending.values()) if not self.done.is_set() else []}
            if self.done.is_set():
                raise RuntimeAdapterError('operation-failed', 'Claude execution has ended.')
            if operation == 'reply':
                details = self.pending.get(request.get('request_token'))
                response = request.get('response')
                if (details is None or not isinstance(response, dict)
                        or response.get('behavior') not in {'allow', 'deny'}
                        or set(response) - {'behavior', 'updatedInput', 'message', 'interrupt'}
                        or ('updatedInput' in response and not isinstance(response['updatedInput'], dict))
                        or ('message' in response and not isinstance(response['message'], str))
                        or ('interrupt' in response and not isinstance(response['interrupt'], bool))):
                    raise RuntimeAdapterError('invalid-input', 'Supply an explicit native allow/deny response.')
                response = dict(response)
                if response['behavior'] == 'allow':
                    response.setdefault('updatedInput', details['params']['input'])
                else:
                    response.setdefault('message', 'Permission denied by parent.')
                self._reply(details['request_id'], response)
                del self.pending[request['request_token']]
                return {'request_id': details['request_id'], 'reply_status': 'submitted'}
            if operation == 'send':
                if not self.accepting or self.stopping.is_set() or self.session is None:
                    raise RuntimeAdapterError('operation-failed', 'Claude is not accepting input.')
                self._prompt(request['instruction'])
                return {}
            if operation != 'interrupt':
                raise RuntimeAdapterError('invalid-input', 'Unknown Claude operation.')
        self.terminate()
        if not self.done.wait(timeout=30) or not self.terminal_confirmed:
            raise RuntimeAdapterError('operation-failed', 'Claude interruption is not yet confirmed.', terminal_confirmed=False)
        return {}


def yaml_document(path: Path) -> dict:
    """Read this owner's retained native identity document."""
    import yaml

    return yaml.safe_load(path.read_text())
