"""Own Claude Code's official stream-JSON control transport for one invocation."""
from __future__ import annotations

from contextlib import ExitStack, nullcontext
from concurrent.futures import Future
import copy
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Callable

from agent_swarm import AgentsResult
from agent_swarm.discovery import handle_request as discover_agents
from agent_swarm.mcp import tool_documents
from graphtraj.sessions.archive import SessionArchive
from graphtraj.runtimes.claude.history import read_records

from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError, SessionStarted, record_runtime_process
from graphtraj.runtimes.claude.diagnostics import (
    launch_projection, model_projection, native_projection, warning_projection,
)


class ClaudeExecution:
    """Keep native permissions, registration and terminal evidence on one pipe."""

    # Optional (message, details) -> receipt replacing the Runner parent notice.
    parent_notice = None

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
        # Native control requests in arrival order, answered ahead of the
        # collection backlog; ``events`` still archives them in native order.
        self.controls: queue.Queue = queue.Queue()
        self.prompt_received: dict[str, tuple[float, float]] = {}
        self.pending: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.stopping = threading.Event()
        self.done = threading.Event()
        self.termination_checked = threading.Event()
        self.outcome: dict | None = None
        self.terminal_confirmed = False
        self.accepting = True
        self.sent = 0
        self.input_ids: set[str] = set()
        self.transcript: Path | None = None
        self.results = 0
        self.echoes = 0
        self.native_state: str | None = None
        self.drained_native_state: str | None = None
        self.stdout_eof = False
        self.stderr_eof = False
        self.task_released = False
        self.independent = False
        self.archive: SessionArchive | None = None
        self.agents_callback: Callable[[dict], AgentsResult] | None = None
        self.collector = None
        self.collection: queue.Queue = queue.Queue()
        self.collection_failure: Exception | None = None
        self.sdk_tools_listed = False
        self.sdk_calls: dict[str, tuple[dict, Future]] = {}
        self.displayed: set[tuple[str, str]] = set()
        self.diagnostics = {'session_id': self.native_id, 'execution_id': self.execution_id,
                            'launch': 'unknown', 'popen_returned': False,
                            'initialize': {'reason': 'unknown'}, 'system_init': {'reason': 'unknown'},
                            'warnings': []}

    def configure_independent(
        self,
        *,
        archive: SessionArchive | None,
        agents_callback: Callable[[dict], AgentsResult],
    ) -> None:
        """Bind the core's archive choice and verified caller before starting."""
        if self.proc is not None:
            raise ValueError('Claude execution is already started.')
        self.independent = True
        self.archive = archive
        self.agents_callback = agents_callback

    def _sdk_message(self, event: dict) -> None:
        """Serve the official SDK's in-process MCP transport on the owned pipe."""
        request = event['request']
        if request.get('server_name') != 'agents' or self.agents_callback is None:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unknown SDK MCP server.')
        message = request.get('message', {})

        def respond() -> None:
            """Keep long tool calls off the pipe reader so interruption stays live."""
            try:
                method = message.get('method')
                params = message.get('params', {})
                if method == 'initialize':
                    result = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                              'capabilities': {'tools': {}}, 'serverInfo': {'name': 'agents', 'version': '1'}}
                elif method == 'tools/list':
                    result = {'tools': tool_documents()}
                    self.sdk_tools_listed = True
                elif method == 'tools/call' and params.get('name') == 'agents':
                    if self.session is None or self.stopping.is_set():
                        raise ValueError('Claude caller is not bound to an active execution.')
                    value = self._agents_call(message)
                    result = {'content': [{'type': 'text', 'text': json.dumps(value.document, ensure_ascii=False)}],
                              'structuredContent': value.document, 'isError': value.failed}
                elif method in {'ping', 'notifications/initialized', 'notifications/cancelled'}:
                    result = {}
                else:
                    response = {'jsonrpc': '2.0', 'id': message.get('id'),
                                'error': {'code': -32601, 'message': 'Unsupported MCP method.'}}
                    self._reply(event['request_id'], {'mcp_response': response})
                    return
                response = {'jsonrpc': '2.0', 'id': message.get('id'), 'result': result}
                self._reply(event['request_id'], {'mcp_response': response} if 'id' in message else {})
            except Exception as error:
                if not self.stopping.is_set() and not self.done.is_set():
                    self.events.put({'type': 'transport_error', 'exception': type(error).__name__})

        threading.Thread(target=respond, daemon=True).start()

    def _agents_call(self, message: dict) -> AgentsResult:
        """Reuse the exact native tool-call receipt on transport retransmission."""
        if 'id' not in message:
            raise ValueError('An SDK tool call needs a JSON-RPC request identity.')
        key = json.dumps(message['id'])
        with self.lock:
            prior = self.sdk_calls.get(key)
            if prior is None:
                future = Future()
                self.sdk_calls[key] = (copy.deepcopy(message), future)
            else:
                original, future = prior
                if original != message:
                    raise ValueError('SDK request identity was reused with different arguments.')
        if prior is None:
            try:
                future.set_result(discover_agents(message.get('params', {}).get('arguments', {}),
                                                  self.agents_callback))
            except BaseException as error:
                future.set_exception(error)
                raise
        return future.result()

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

    def _save_diagnostics(self) -> None:
        """Persist only this execution's allowlisted diagnostic snapshot."""
        with self.lock:
            write_yaml_durably(self.directory / f'claude-diagnostics-{self.execution_id}.yml', self.diagnostics)

    def _diagnostic_warning(self, source: str, text: object) -> None:
        """Retain at most eight fixed warning labels, with no native free text."""
        with self.lock:
            for label in warning_projection(text):
                record = {'source': source, 'category': label}
                if record not in self.diagnostics['warnings'] and len(self.diagnostics['warnings']) < 8:
                    self.diagnostics['warnings'].append(record)
                    self._save_diagnostics()

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
        message = {'type': 'user', 'session_id': self.native_id,
                   'message': {'role': 'user', 'content': text}, 'parent_tool_use_id': None,
                   'uuid': str(uuid.uuid4())}
        self.input_ids.add(message['uuid'])
        self._send(message)
        self.events.put({**message, 'graphtraj_direction': 'sent'})
        self.sent += 1

    def _collect(self) -> None:
        """Archive native records in arrival order, off the protocol loop.

        Each message record makes the collector re-read the transcript and
        rewrite the archive, which grows with the Session. A native hook waits
        only 30 s, so the run loop keeps answering hooks while this thread
        collects. The first failure is kept for the run loop to raise.
        """
        # dev's managed archive uses a thread-affine SQLite connection.
        # Each phase opens its own connection; only collection writes while
        # this thread is alive, and finalization runs after it has joined.
        with ExitStack() as stores:
            if not self.independent:
                from graphtraj.sessions.storage import SessionStore

                self.collector.store = stores.enter_context(SessionStore(self.collector.store.path))
            pending = []
            batches = 0
            elapsed = 0.0
            while True:
                item = pending.pop() if pending else self.collection.get()
                if item is None:
                    return
                if self.collection_failure is not None:
                    continue
                began = time.monotonic()
                progress = {'batches': batches, 'elapsed_seconds': elapsed,
                            'batch_started_at': time.time(), 'batch_complete': False}
                try:
                    with self.lock:
                        self.diagnostics['collection_progress'] = progress
                        self._save_diagnostics()
                    if item[0] == 'bind':
                        self.collector.bind(item[1], item[2])
                    else:
                        records = [(item[1], item[2])]
                        # Read one archive snapshot for the already received batch,
                        # not once per fragment. Binding and end remain ordered.
                        for _ in range(self.collection.qsize()):
                            following = self.collection.get_nowait()
                            if following is None or following[0] != 'event':
                                pending.append(following)
                                break
                            records.append((following[1], following[2]))
                        if self.independent:
                            self.collector.accept_batch(records)
                        else:
                            for record, position in records:
                                self.collector.accept(record, position)
                except Exception as error:
                    self.collection_failure = error
                finally:
                    batches += 1
                    elapsed += time.monotonic() - began
                    with self.lock:
                        self.diagnostics['collection_progress'] = {
                            **progress, 'batches': batches, 'elapsed_seconds': elapsed,
                            'batch_complete': True, 'queued_records': self.collection.qsize(),
                        }
                        try:
                            self._save_diagnostics()
                        except Exception as error:
                            if self.collection_failure is None:
                                self.collection_failure = error

    def _absorbed_inputs(self) -> int:
        """Count sent inputs that the native CLI absorbed into a running turn.

        Such an input gets no result of its own, and its stream echo and the
        result's ``queued_turn_count`` are not reliably present. The transcript
        records each absorption as a queue removal with reason
        ``absorbed_mid_turn``, naming the input's UUID directly or through
        the delivery ID of its ``queued_command`` attachment.
        """
        if self.transcript is None:
            return 0
        try:
            records = read_records(self.transcript, self.session)
        except (OSError, ValueError):
            return 0

        sources = {}
        for record in records:
            attachment = record.get('attachment')
            if isinstance(attachment, dict) and attachment.get('type') == 'queued_command':
                sources[attachment.get('delivery_id')] = attachment.get('source_uuid')

        absorbed = set()
        for record in records:
            if (record.get('type') == 'queue-operation' and record.get('operation') == 'remove'
                    and record.get('reason') == 'absorbed_mid_turn'):
                source = record.get('commandUuid') or sources.get(record.get('deliveryId'))
                if source in self.input_ids:
                    absorbed.add(source)
        return len(absorbed)

    def _prepare(self, address: str | None) -> tuple[list[str], dict]:
        """Use native restricted mode and mandatory sandboxing without bypass flags."""
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
        if self.independent:
            mcp = {'mcpServers': {}}
        if request.get('permission_mode') is not None:
            settings['permissions']['defaultMode'] = request['permission_mode']
        argv = [request['executable'], '--print', '--verbose', '--input-format', 'stream-json',
                '--output-format', 'stream-json', '--include-partial-messages',
                # Native echoes stay in the Trace. One observed run echoed mid-turn
                # input when it joined the running turn, before that turn's result.
                '--replay-user-messages',
                '--permission-prompt-tool', 'stdio',
                '--restricted', '--strict-mcp-config',
                '--mcp-config', json.dumps(mcp), '--settings', json.dumps(settings),
                '--tools', 'Bash,Read,Write,Edit,Glob,Grep', '--model', request['model'],
                '--append-system-prompt', request['instructions'],
                '--resume' if self.expected else '--session-id', self.native_id]
        if request['reasoning_effort'] is not None:
            argv += ['--effort', request['reasoning_effort']]
        if request.get('permission_mode') is not None:
            argv += ['--permission-mode', request['permission_mode']]
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GRAPHTRAJ_')}
        environment.update(CLAUDE_CODE_SDK_READS_SESSION_STATE='1',
                           CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1')
        scrub_key = 'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'
        scrub_source = 'environment' if scrub_key in environment else 'default'
        environment.setdefault(scrub_key, '0' if request.get('permission_mode') == 'auto' else '1')
        # Claude 2.1.299 Ne(value): trim/lowercase, then membership in these
        # four values. Other strings are false, not invalid configuration.
        scrub_enabled = environment[scrub_key].strip().lower() in {'1', 'true', 'yes', 'on'}
        self.diagnostics['subprocess_environment_scrub'] = {
            'source': scrub_source, 'requested_enabled': scrub_enabled,
        }
        if request.get('permission_mode') == 'auto' and scrub_enabled:
            self._save_diagnostics()
            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                      'Requested auto conflicts with explicit Claude subprocess scrub.')
        if address:
            environment['GRAPHTRAJ_CLI_CONNECTION'] = address
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
            with (nullcontext(None) if self.independent else self.trace.open('a', encoding='utf-8')) as trace:
                for line in self.proc.stdout:
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError('object')
                    except ValueError as error:
                        # Only the failure class is kept, never the native line.
                        self.events.put({'type': 'transport_error', 'exception': type(error).__name__})
                        return
                    # Partial text is compacted in the canonical archive, not copied
                    # to a second permanent per-fragment transport log.
                    if trace is not None and event.get('type') != 'stream_event':
                        trace.write(line)
                        trace.flush()
                    if event.get('type') == 'system' and event.get('subtype') == 'session_state_changed':
                        self.drained_native_state = event.get('state')
                    if (event.get('type') == 'control_request'
                            and event.get('request', {}).get('callback_id') == 'graphtraj_start'):
                        self.prompt_received[event['request_id']] = (time.monotonic(), time.time())
                    self.events.put(event)
                    if event.get("type") in ("control_request", "control_cancel_request"):
                        self.controls.put(event)
                self.stdout_eof = True
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
        if native.get('transcript_path'):
            self.transcript = Path(native['transcript_path'])
        if self.independent and self.transcript is not None:
            self.collection.put(('bind', self.transcript, set(self.input_ids)))
        write_yaml_durably(self.directory / 'session.yml', {
            'session': self.session, 'rollout_path': native.get('transcript_path'),
            'runtime_version': self.request['version'], 'source': native.get('source'),
            'configured_model': self.request['model'], 'configured_effort': self.request['reasoning_effort'],
            'native_init': getattr(self, 'native_init', None),
            'permissions': self.permission_evidence(),
        })
        assert self.proc is not None
        self.created(self.session, self.proc.pid)
        if self.stopping.is_set():
            raise RuntimeAdapterError('RUNTIME_EXECUTION_INTERRUPTED', 'Claude startup was interrupted.')
        self.started(self.session, self.proc.pid)

    def _control_event(self, event: dict) -> None:
        """Answer one native control request or cancellation."""
        if event.get('type') == 'control_request':
            request = event.get('request', {})
            if request.get('subtype') == 'mcp_message' and self.independent:
                self._sdk_message(event)
            elif (self.independent and request.get('subtype') == 'hook_callback'
                  and request.get('callback_id') == 'graphtraj_agents_display'):
                from graphtraj.runtimes.claude.display import display_response

                self._reply(event['request_id'], display_response(request['input'], self.displayed))
            elif request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'graphtraj_start':
                began = time.monotonic()
                received, received_at = self.prompt_received.pop(event['request_id'])
                self._bind(request)
                self._reply(event['request_id'], {})
                self.task_released = True
                # These are host observations, not native message timestamps.
                # Keep the latest prompt's queue and handler costs separate.
                with self.lock:
                    self.diagnostics['prompt_hook'] = {
                        'received_at': received_at, 'replied_at': time.time(),
                        'queue_seconds': began - received,
                        'handler_seconds': time.monotonic() - began,
                    }
                    self._save_diagnostics()
            elif request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'graphtraj_collect_child':
                from graphtraj.runtimes.claude.collection import collect_hook

                if not self.independent:
                    collect_hook(request['input'], Path(self.request['worktree_path']))
                self._reply(event['request_id'], {})
            elif request.get('subtype') == 'can_use_tool':
                self._permission(event)
            else:
                raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unknown Claude control request.')
        else:
            self.prompt_received.pop(event.get('request_id'), None)
            with self.lock:
                self.pending = {key: value for key, value in self.pending.items()
                                if value['request_id'] != event.get('request_id')}

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
            """Deliver without blocking the pipe that must still accept interruption.

            A parent whose turn just settled refuses input until its terminal
            record lets the next execution resume it, so ``not-delivered`` is
            retried while this request is still pending, as Codex and DSH do.
            The request stays pending and is never answered here.
            """
            message = 'Claude requires a native permission reply:\n' + json.dumps(details)
            while True:
                with self.lock:
                    if token not in self.pending or self.stopping.is_set():
                        return
                try:
                    # A Task-free owner retains the request with its own control
                    # record instead of a Runner parent notice.
                    receipt = (self.parent_notice(message, details) if self.parent_notice is not None
                               else notify_direct_parent(self.directory, message, details))
                except Exception as error:
                    self.events.put({'type': 'notification_error', 'exception': type(error).__name__,
                                     'delivery': None})
                    return
                if receipt is None or receipt.get('delivery') in {'received', 'no-direct-parent', 'retained'}:
                    return
                time.sleep(1)

        threading.Thread(target=notify, daemon=True).start()

    def run(self) -> dict:
        """Own startup, work and cleanup; publish completion only after process exit."""
        from graphtraj.interfaces.hosted_cli import cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features
        from graphtraj.runtimes.activity import redact
        from graphtraj.runtimes.claude.collection import open_archive, StreamCollector

        last = None
        result_error = None
        reader = None
        stderr_reader = None
        collecting = None
        failure = None
        with ExitStack() as resources:
            # Runner supplies Task context before the native registration hook;
            # mapping.yml does not exist until that hook has been acknowledged.
            task_id = os.environ.get('GRAPHTRAJ_TASK_ID')
            provider = self.request.get('provider', 'native')
            if provider == 'native' and not self.request.get('base_url'):
                provider = 'anthropic'
            if self.independent:
                from graphtraj.runtimes.claude.jsonl import ClaudeJsonlCollector

                collector = ClaudeJsonlCollector(self.archive, self.native_id, self.directory.name,
                                                Path(self.request['worktree_path']), self.execution_id,
                                                provider=provider, resumed=self.expected is not None)
            else:
                archive = resources.enter_context(open_archive(
                    Path(self.request['state_directory']), Path(self.request['harness_root']),
                    self.native_id, self.directory.name, source='managed',
                    task_ids=[task_id] if task_id else []))
                if archive.pending():
                    from graphtraj.sessions.storage import StreamWriter

                    StreamWriter(archive, archive.pending()['source']).finish(content=[], interrupted=True)
                collector = StreamCollector(archive, self.execution_id, self.request['model'], provider)
            self.collector = collector
            source_position = 0
            channel_directory = None
            if not self.independent and (Path(self.request['harness_root']) / '.graphtraj').resolve().is_relative_to(
                    Path(self.request['worktree_path']).resolve()):
                # Root launches deny writes throughout private state, including
                # the usual CLI directory. Keep only this authenticated channel
                # in a temporary directory, with its normal scoped grant.
                channel_directory = Path(resources.enter_context(
                    tempfile.TemporaryDirectory(prefix='graphtraj-claude-')))
            address = None if self.independent else resources.enter_context(cli_connection(
                Path(self.request['harness_root']), self.directory.name, native_operation_features(),
                directory=channel_directory))
            stderr = resources.enter_context((self.directory / 'stderr.log').open('a', encoding='utf-8'))
            try:
                collecting = threading.Thread(target=self._collect, daemon=True)
                collecting.start()
                argv, environment = self._prepare(address)
                if self.stopping.is_set():
                    raise RuntimeAdapterError('RUNTIME_EXECUTION_INTERRUPTED', 'Claude stopped before process creation.')
                self.diagnostics['launch'] = launch_projection(argv)
                self._save_diagnostics()
                self.proc = subprocess.Popen(argv, cwd=self.request['worktree_path'], env=environment,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             text=True, bufsize=1, start_new_session=True)
                self.diagnostics['popen_returned'] = True
                self._save_diagnostics()
                record_runtime_process(self.proc.pid)

                def drain_stderr() -> None:
                    """Keep native stderr host-owned and separate from conversation records."""
                    assert self.proc is not None
                    for line in self.proc.stderr:
                        stderr.write(line)
                        stderr.flush()
                        self._diagnostic_warning('stderr', line)
                    self.stderr_eof = True

                stderr_reader = threading.Thread(target=drain_stderr, daemon=True)
                stderr_reader.start()
                reader = threading.Thread(target=self._read, daemon=True)
                reader.start()
                initialization = self._control('initialize', **({'sdkMcpServers': ['agents']} if self.independent else {}), hooks={
                    'UserPromptSubmit': [{'matcher': None, 'hookCallbackIds': ['graphtraj_start']}],
                    'SubagentStop': [{'matcher': None, 'hookCallbackIds': ['graphtraj_collect_child']}],
                    **({'PostToolUse': [{'matcher': 'mcp__agents__agents',
                                         'hookCallbackIds': ['graphtraj_agents_display']}]}
                       if self.independent else {}),
                })
                startup_deadline = time.monotonic() + 45
                stop_deadline = None
                last_echo = last_result = 0
                queued_turns = None
                answered: set[int] = set()
                while True:
                    if self.stopping.is_set() and stop_deadline is None:
                        stop_deadline = time.monotonic() + 5
                    if stop_deadline is not None and time.monotonic() >= stop_deadline:
                        break
                    if self.collection_failure is not None:
                        raise self.collection_failure
                    if self.session is None and time.monotonic() >= startup_deadline:
                        raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude did not attest startup within 45 seconds.')
                    # A later prompt waits on its UserPromptSubmit hook for
                    # only 30 s, while collection rewrites the durable archive
                    # for each streamed fragment ahead of it. Once bound, answer
                    # native requests first; ``events`` still archives them in
                    # native order and skips the answered ones.
                    while self.session is not None:
                        try:
                            control = self.controls.get_nowait()
                        except queue.Empty:
                            break
                        if id(control) in answered:
                            answered.remove(id(control))
                        else:
                            answered.add(id(control))
                            self._control_event(control)
                    try:
                        event = self.events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    source_position += 1
                    if event.get('type') != 'eof':
                        self.collection.put(('event', event, source_position))
                    kind = event.get('type')
                    if kind in ('warning', 'error') or (
                            kind == 'system' and event.get('subtype') in ('warning', 'error')):
                        self._diagnostic_warning('native_event', event.get('message'))
                    if kind == 'control_response':
                        response = event.get('response', {})
                        if response.get('request_id') == initialization:
                            with self.lock:
                                self.diagnostics['initialize'] = native_projection(response.get('response') or {})
                                self.diagnostics['initialize']['control_status'] = (
                                    response['subtype'] if response.get('subtype') in ('success', 'error') else 'unknown')
                                self._save_diagnostics()
                            self._diagnostic_warning('initialize', response.get('error'))
                            if response.get('subtype') != 'success':
                                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude initialization failed.')
                            if response.get('response', {}).get('hooks_applied') is not True:
                                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude did not install the registration hook.')
                            with self.lock:
                                if not self.stopping.is_set():
                                    self._prompt(self.prompt)
                    elif kind in ('control_request', 'control_cancel_request'):
                        if id(event) in answered:
                            answered.remove(id(event))
                        else:
                            answered.add(id(event))
                            self._control_event(event)
                    elif kind == 'system' and event.get('subtype') == 'init':
                        if event.get('session_id') != self.native_id or event.get('model') != self.request['model']:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude selected a different Session or model.')
                        if self.independent and (not self.sdk_tools_listed
                                or 'mcp__agents__agents' not in event.get('tools', [])):
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                                      'Claude did not register the bound agents SDK function.')
                        self.native_init = event
                        with self.lock:
                            self.diagnostics['system_init'] = native_projection(event)
                            self.diagnostics['system_init']['model'] = model_projection(event.get('model'))
                            self._save_diagnostics()
                        if self.session is not None:
                            observed = yaml_document(self.directory / 'session.yml')
                            observed['native_init'] = event
                            observed['permissions'] = self.permission_evidence()
                            write_yaml_durably(self.directory / 'session.yml', observed)
                        requested_mode = self.request.get('permission_mode')
                        if requested_mode is not None and self.permission_evidence()['matches_request'] is not True:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                                      'Claude did not confirm the requested permission mode.')
                    elif kind == 'system' and event.get('subtype') == 'session_state_changed':
                        self.native_state = event.get('state')
                    elif kind == 'result':
                        self._diagnostic_warning('result', event.get('result'))
                        for native_error in (event.get('errors') or [])[:8]:
                            self._diagnostic_warning('result', native_error)
                        if event.get('session_id') != self.session:
                            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude result has a different Session.')
                        self.results += 1
                        last_result = source_position
                        queued_turns = event.get('queued_turn_count')
                        last = event.get('result') or last
                        if event.get('is_error'):
                            result_error = redact(str(event.get('errors') or event.get('result') or event.get('subtype')))
                    elif kind == 'assistant' and event.get('parent_tool_use_id') is None:
                        model = event.get('message', {}).get('model')
                        if model is not None and model != '<synthetic>' and not event.get('error') and model != self.request['model']:
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude changed the configured model.')
                        last = '\n'.join(block.get('text', '') for block in event.get('message', {}).get('content', [])
                                         if block.get('type') == 'text') or last
                    elif kind == 'user' and event.get('isReplay') is True:
                        # Native echo of sent input. In one observed run, input sent
                        # mid-turn was echoed when it joined that turn, before its result.
                        self.echoes += 1
                        last_echo = source_position
                    elif kind in {'transport_error', 'notification_error'}:
                        cause = ', '.join(f'{key}={event[key]}' for key in ('exception', 'delivery')
                                          if event.get(key) is not None)
                        raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED',
                                                  f'Claude transport or permission delivery failed ({kind}'
                                                  + (f'; {cause}' if cause else '') + ').')
                    elif kind == 'eof':
                        if self.stopping.is_set():
                            break
                        if self.results < self.sent or not self.session:
                            raise RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED', 'Claude exited before a native terminal result.')
                        break
                    with self.lock:
                        # Input joined to a running turn shares its single result.
                        # It is settled by its echo before that result with no
                        # queued turn reported, or by the transcript's record of
                        # its absorption once native idle. A missing count is
                        # not assumed.
                        settled = self.results >= self.sent or (
                            self.echoes >= self.sent and last_result > last_echo and queued_turns == 0) or (
                            self.native_state == 'idle'
                            and self.results + self._absorbed_inputs() >= self.sent)
                        if self.results and settled and self.native_state == 'idle':
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
                process_group_closed = self.terminal_confirmed
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
                if self.proc is not None:
                    # Keep the owner's separate observations: the native idle
                    # event may arrive while _close drains after the loop ends.
                    termination = {
                        'session': self.session, 'execution_id': self.execution_id,
                        'runtime_pid': self.proc.pid, 'worker_pid': os.getpid(),
                        'process_group_closed': process_group_closed,
                        'runtime_exit_code': self.proc.poll(),
                        'stdout_eof': self.stdout_eof, 'stderr_eof': self.stderr_eof,
                        'pipes_closed': pipes_drained and self.proc.stdout.closed and self.proc.stderr.closed,
                        'native_idle': self.drained_native_state == 'idle',
                    }
                    write_yaml_durably(self.directory / f'claude-termination-{self.execution_id}.yml', termination)
                    self.diagnostics['termination'] = termination
                # A runtime killed after its stop window never reports idle. Its
                # exit, closed group and drained pipes confirm termination; idle
                # is still required while the runtime could continue.
                unsettled = self.task_released and self.native_state != 'idle'
                exited = (process_group_closed and self.proc is not None
                          and self.proc.poll() is not None)
                if unsettled and exited and pipes_drained and failure is None and not self.stopping.is_set():
                    failure = RuntimeAdapterError('RUNTIME_TRANSPORT_FAILED',
                                                  'Claude exited before native settlement.')
                if not pipes_drained or unsettled and not exited:
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
                # Physical stopping is independent of the retained archive.
                # Keep the Worker occupied until collection finishes, so no
                # resume or replacement can overlap its remaining writes.
                self.diagnostics['collection'] = 'pending'
                self._save_diagnostics()
                self.termination_checked.set()
                if collecting is not None:
                    # Records already handed over are archived before closing.
                    self.collection.put(None)
                    archive_wait = time.monotonic()
                    collecting.join()
                    self.diagnostics['collection_join_seconds'] = time.monotonic() - archive_wait
                    if not self.independent:
                        from graphtraj.sessions.storage import SessionStore

                        collector.store = resources.enter_context(SessionStore(collector.store.path))
                    if self.collection_failure is not None and failure is None:
                        failure = RuntimeAdapterError('RUNTIME_ARCHIVE_FAILED', str(self.collection_failure))
                try:
                    if pipes_drained:
                        while not self.events.empty():
                            event = self.events.get_nowait()
                            source_position += 1
                            if event.get('type') != 'eof':
                                collector.accept(event, source_position,
                                                 **({'defer': not self.events.empty()} if self.independent else {}))
                        collector.close()
                    else:
                        if self.independent:
                            collector.flush()
                        elif collector.writer:
                            collector.writer.checkpoint()
                except Exception as error:
                    failure = RuntimeAdapterError('RUNTIME_ARCHIVE_FAILED', str(error))
                self.diagnostics['collection'] = ('failed' if self.collection_failure is not None
                                                  or getattr(failure, 'code', None) == 'RUNTIME_ARCHIVE_FAILED'
                                                  else 'complete')
                self._save_diagnostics()
                if failure is None and self.session is not None:
                    self.outcome = {'outcome': 'interrupted' if self.stopping.is_set() else 'completed',
                                    'terminal_confirmed': self.terminal_confirmed,
                                    'session_id': self.session, 'execution_id': self.execution_id,
                                    'permissions': self.permission_evidence(),
                                    'last_agent_message': last}
                self.done.set()
        if failure is not None:
            if isinstance(failure, RuntimeAdapterError):
                failure.terminal_confirmed = self.terminal_confirmed or self.proc is None
            raise failure
        if self.outcome is None:
            raise RuntimeAdapterError('RUNTIME_SESSION_MISSING', 'Claude ended without a registered Session.')
        return self.outcome

    def permission_evidence(self) -> dict:
        """Distinguish retained selection from the mode actually reported by Claude."""
        observed = getattr(self, 'native_init', {}).get('permissionMode')
        if observed not in ('default', 'manual', 'auto', 'acceptEdits', 'plan', 'dontAsk', 'bypassPermissions'):
            observed = 'unknown'
        requested = self.request.get('permission_mode')
        return {
            'requested': requested,
            'source': self.request.get('permission_mode_source', 'unknown'),
            'observed': observed,
            'observed_source': 'system/init' if observed != 'unknown' else 'unknown',
            'matches_request': (None if requested is None or observed == 'unknown' else
                                requested == ('default' if observed == 'manual' else observed)),
        }

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
                if self.termination_checked.is_set() and not self.done.is_set():
                    return {'activity': 'running', 'waiting_for': 'archive',
                            'native_terminal_confirmed': self.terminal_confirmed}
                return ({'activity': 'idle', 'last_outcome': self.outcome['outcome']} if self.outcome else
                        {'activity': 'running', **({'waiting_for': 'runtime-request'} if self.pending else {})})
            if operation == 'requests':
                return {'requests': list(self.pending.values()) if not self.done.is_set() else []}
            if (operation == 'send' and not self.accepting
                    and not self.stopping.is_set() and self.session is not None):
                raise RuntimeAdapterError('runtime-input-closed', 'Claude finished accepting input for this execution.')
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
        if not self.termination_checked.wait(timeout=30) or not self.terminal_confirmed:
            raise RuntimeAdapterError('operation-failed', 'Claude interruption is not yet confirmed.', terminal_confirmed=False)
        return {}


def yaml_document(path: Path) -> dict:
    """Read this owner's retained native identity document."""
    import yaml

    return yaml.safe_load(path.read_text())
