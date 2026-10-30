"""Own Claude Code's official stream-JSON control transport for one invocation."""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from concurrent.futures import Future
import copy
import hashlib
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

from agent_swarm import AgentsResult, __version__
from agent_swarm.approval import REVIEW_METHOD, parse_decision, review_failed
from agent_swarm.discovery import handle_request as discover_agents
from agent_swarm.mcp import tool_documents
from agent_swarm import SessionArchive
from agent_swarm.sessions.claude_history import read_records
from .support import write_yaml_durably, credential_environment, redact

from agent_swarm.runtime import RuntimeAdapterError, SessionStarted
from .diagnostics import (
    launch_projection, model_projection, native_projection, warning_projection,
)

# Claude Code's limit for a UserPromptSubmit hook callback reply.
PROMPT_HOOK_LIMIT_SECONDS = 30
# The child's channel to its parent, limited by agents' own authority checks.
# Reviewing it would block ask_parent and status when the reviewer is down.
AGENTS_TOOL = 'mcp__agents__agents'
# A PreToolUse hook that misses its timeout is non-blocking, so the host answers first.
REVIEW_HOOK_MIN_SECONDS = 600
REVIEW_HOOK_MARGIN_SECONDS = 60


class ClaudeExecution:
    """Keep native permissions, registration and terminal evidence on one pipe."""

    # Optional (message, details) -> receipt replacing the Runner parent notice.
    parent_notice = None
    host_connection = None

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
        # Wall seconds of the latest prompt hook reply that missed Claude's limit.
        self.dropped_prompt_seconds: float | None = None
        self.independent = False
        self.archive: SessionArchive | None = None
        # Header ``extra_fields`` for a Session this execution archives first.
        self.extra_fields: dict | None = None
        self.agents_callback: Callable[[dict], AgentsResult] | None = None
        self.collector = None
        # Exact read-only resource settings applied before the first prompt.
        self.resource_settings: dict | None = None
        self.collection: queue.Queue = queue.Queue()
        self.collection_failure: Exception | None = None
        self.sdk_tools_listed = False
        self.sdk_calls: dict[str, tuple[dict, Future]] = {}
        self.displayed: set[tuple[str, str]] = set()
        # Review plugin state, unused without ``request['review']``: calls allowed
        # so far as (tool_use_id, call), one parent release per accepted call,
        # and the hook callbacks still under review.
        self.review_allowed: list[tuple[str | None, tuple[str, str]]] = []
        self.review_releases: Counter = Counter()
        self.reviewing: set[str] = set()
        self.turn_ended = False
        self.diagnostics = {'session_id': self.native_id, 'execution_id': self.execution_id,
                            'launch': 'unknown', 'popen_returned': False,
                            'initialize': {'reason': 'unknown'}, 'system_init': {'reason': 'unknown'},
                            'warnings': []}

    def record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Let the owning consumer retain process lifecycle observations."""

    def _collector(self, resources: ExitStack):
        """Collect into the bound archive; without one, plain control archives nothing.

        A consumer may still supply its own ``collector`` before ``run()``.
        """
        if self.collector is not None or self.archive is None:
            return self.collector
        from agent_swarm.sessions.claude import ClaudeJsonlCollector

        provider = self.request.get('provider', 'native')
        if provider == 'native' and not self.request.get('base_url'):
            provider = 'anthropic'
        return ClaudeJsonlCollector(self.archive, self.native_id,
                                    Path(self.request['worktree_path']), self.execution_id,
                                    provider=provider, resumed=self.expected is not None,
                                    extra_fields=self.extra_fields)

    def _connection(self, resources: ExitStack) -> str | None:
        """Expose CLI calls only through the native owner's PID-bound channel."""
        if self.host_connection is None:
            return None
        directory = Path(resources.enter_context(tempfile.TemporaryDirectory(prefix='agents-claude-')))
        return resources.enter_context(self.host_connection(directory))

    def _collect_child(self, event: dict) -> None:
        """Archive a finished native helper's own transcript beside its parent Session."""
        if self.archive is None:
            return
        from .collection import collect_hook_event

        collect_hook_event(self.archive, event, Path(self.request['worktree_path']),
                           extra_fields=self.extra_fields)

    def _parent_notice(self, message: str, details: dict) -> dict:
        """Require the owning host to bind native permission delivery."""
        raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'No parent notice receiver is bound.')

    def _settings(self, address: str | None) -> tuple[dict, dict]:
        """Keep native sandbox and read-only grants without project policy."""
        request = self.request
        cwd = Path(request['worktree_path']).resolve()
        home = Path(request['runtime_home']).resolve()
        resources = request.get('resources', [])
        private = self.directory.parent.parent.resolve()
        if any(Path(p).resolve().is_relative_to(private) or private.is_relative_to(Path(p).resolve())
               for p in resources):
            raise RuntimeAdapterError('RUNTIME_ACCESS_DENIED', 'A resource grant would expose private control state.')
        denied = [str(home), str(self.directory.parent.parent), *resources]
        readonly = request['worktree_access'] == 'read'
        settings = {
            'permissions': {
                'blockReadsOutsideWorkingDirectories': True,
                'allow': [rule for p in resources for rule in (f'Read(/{p})', f'Read(/{p}/**)')],
                'deny': [rule for p in denied for rule in (f'Edit(/{p})', f'Edit(/{p}/**)')]
                        + [rule for p in (str(home), str(self.directory.parent.parent))
                           for rule in (f'Read(/{p})', f'Read(/{p}/**)')]
                        + (['Edit', 'Write', 'NotebookEdit'] if readonly else []),
                'additionalDirectories': [],
            },
            'sandbox': {
                'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False,
                'autoAllowBashIfSandboxed': False, 'excludedCommands': [],
                'filesystem': {
                    'denyRead': [str(home), str(self.directory.parent.parent)],
                    'allowRead': [*resources, *([address] if address else []), str(Path(sys.prefix).resolve())],
                    'allowWrite': [address] if address else [],
                    'denyWrite': [*denied, *([str(cwd)] if readonly else [])],
                },
            },
        }
        return settings, {'mcpServers': {}}

    def configure_independent(
        self,
        *,
        archive: SessionArchive | None,
        agents_callback: Callable[[dict], AgentsResult],
        extra_fields: dict | None = None,
    ) -> None:
        """Bind the core's archive choice and verified caller before starting.

        ``extra_fields`` goes to the header of a Session first archived here.
        """
        if self.proc is not None:
            raise ValueError('Claude execution is already started.')
        self.independent = True
        self.archive = archive
        self.extra_fields = extra_fields
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
                              'capabilities': {'tools': {}}, 'serverInfo': {'name': 'agents', 'version': __version__}}
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
        self.turn_ended = False

    def _collect(self) -> None:
        """Archive native records in arrival order, off the protocol loop.

        Each message record makes the collector re-read the transcript and
        rewrite the archive, which grows with the Session. A native hook waits
        only 30 s, so the run loop keeps answering hooks while this thread
        collects. The first failure is kept for the run loop to raise.
        """
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
                    self.collector.accept_batch(records)
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
        home = Path(request['runtime_home']).resolve()
        settings, mcp = self._settings(address)
        if request.get('permission_mode') is not None:
            settings['permissions']['defaultMode'] = request['permission_mode']
        argv = [request['executable'], '--print', '--verbose', '--input-format', 'stream-json',
                '--output-format', 'stream-json', '--include-partial-messages',
                # Native echoes stay in the Trace. One observed run echoed mid-turn
                # input when it joined the running turn, before that turn's result.
                '--replay-user-messages',
                '--permission-prompt-tool', 'stdio',
                '--restricted', '--strict-mcp-config',
                # Restricted mode confines file tools to cwd; native --add-dir
                # admits the declared read-only directories, still Edit-denied.
                *[item for path in settings['permissions']['additionalDirectories'] for item in ('--add-dir', path)],
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
        environment.pop('AGENT_SWARM_CONNECTION', None)
        review_key_env = (request.get('review') or {}).get('api_key_env')
        if review_key_env and review_key_env != request.get('api_key_env'):
            # The reviewer's key stays with this host, away from the child it judges.
            environment.pop(review_key_env, None)
        if address:
            environment['AGENT_SWARM_CONNECTION' if self.independent else 'GRAPHTRAJ_CLI_CONNECTION'] = address
        if request.get('explicit_runtime_home'):
            environment['CLAUDE_CONFIG_DIR'] = str(home)
        if request['reasoning_effort'] is not None:
            environment['CLAUDE_CODE_EFFORT_LEVEL'] = request['reasoning_effort']
        if request.get('base_url'):
            environment['ANTHROPIC_BASE_URL'] = request['base_url']
        else:
            environment.pop('ANTHROPIC_BASE_URL', None)
        if request.get('api_key_env'):
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
            for line in self.proc.stdout:
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError('object')
                except ValueError as error:
                    # Only the failure class is kept, never the native line.
                    self.events.put({'type': 'transport_error', 'exception': type(error).__name__})
                    return
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
            if self.collector is not None:
                self.collection.put(('bind', self.transcript, set(self.input_ids)))
            # Keep the native file as the Trace reference, never a third
            # transport body. Nonempty older transport evidence stays untouched.
            self.trace.parent.mkdir(parents=True, exist_ok=True)
            if not self.trace.is_symlink() and (not self.trace.exists() or self.trace.stat().st_size == 0):
                self.trace.unlink(missing_ok=True)
                self.trace.symlink_to(self.transcript)
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
                from .display import display_response

                self._reply(event['request_id'], display_response(request['input'], self.displayed))
            elif request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'graphtraj_start':
                began = time.monotonic()
                received, received_at = self.prompt_received.pop(event['request_id'])
                self._bind(request)
                self._reply(event['request_id'], {})
                self.task_released = True
                # These are host observations, not native message timestamps.
                # Keep the latest prompt's queue and handler costs separate.
                replied_at = time.time()
                # Claude abandons the prompt when this reply misses its limit,
                # measured in wall time. The monotonic clock pauses in host
                # sleep, so only wall time shows a reply delayed by sleep.
                if replied_at - received_at > PROMPT_HOOK_LIMIT_SECONDS:
                    self.dropped_prompt_seconds = replied_at - received_at
                with self.lock:
                    self.diagnostics['prompt_hook'] = {
                        'received_at': received_at, 'replied_at': replied_at,
                        'queue_seconds': began - received,
                        'handler_seconds': time.monotonic() - began,
                    }
                    self._save_diagnostics()
            elif request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'graphtraj_collect_child':
                self._collect_child(request['input'])
                self._reply(event['request_id'], {})
            elif request.get('subtype') == 'hook_callback' and request.get('callback_id') == 'agents_review':
                self._review_hook(event)
            elif request.get('subtype') == 'can_use_tool':
                if not self._reviewed_prompt(event):
                    self._permission(event)
            else:
                raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Unknown Claude control request.')
        else:
            self.prompt_received.pop(event.get('request_id'), None)
            with self.lock:
                self.reviewing.discard(event.get('request_id'))
                self.pending = {key: value for key, value in self.pending.items()
                                if value['request_id'] != event.get('request_id')}

    def _permission(self, event: dict) -> None:
        """Send the native request to the direct parent without deciding consent."""
        if self.session is None:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', 'Claude requested permission before binding.')
        token = uuid.uuid4().hex
        details = {'session': self.session, 'execution_id': self.execution_id,
                   'request_id': event['request_id'], 'request_token': token,
                   'method': 'claude/can_use_tool', 'params': event['request']}
        with self.lock:
            self.pending[token] = details
        self._notify(token, details, 'Claude requires a native permission reply:\n' + json.dumps(details))

    def _notify(self, token: str, details: dict, message: str) -> None:
        """Tell the direct parent of one pending request, off the protocol loop."""

        def notify() -> None:
            """Deliver without blocking the pipe that must still accept interruption.

            A parent whose turn just settled refuses input until its terminal
            record lets the next execution resume it, so ``not-delivered`` is
            retried while this request is still pending, as Codex and DSH do.
            The request stays pending and is never answered here.
            """
            while True:
                with self.lock:
                    if token not in self.pending or self.stopping.is_set():
                        return
                try:
                    # A Task-free owner retains the request with its own control
                    # record instead of a Runner parent notice.
                    receipt = (self.parent_notice(message, details) if self.parent_notice is not None
                               else self._parent_notice(message, details))
                except Exception as error:
                    self.events.put({'type': 'notification_error', 'exception': type(error).__name__,
                                     'delivery': None})
                    return
                if receipt is None or receipt.get('delivery') in {'received', 'no-direct-parent', 'retained'}:
                    return
                time.sleep(1)

        threading.Thread(target=notify, daemon=True).start()

    def _review_hook(self, event: dict) -> None:
        """Answer one PreToolUse callback, always, and off the protocol loop.

        Claude treats a hook that errors or times out as non-blocking, so every
        path ends in an answer, an exception included, and only an allowed or
        released call gets ``{}``. That reply states no permission decision, so
        Claude's own rules, mode and sandbox still apply.
        """
        identity = event['request_id']
        native = event['request'].get('input')
        native = native if isinstance(native, dict) else {}
        if native.get('tool_name') == AGENTS_TOOL:
            self._reply(identity, {})
            return
        with self.lock:
            self.reviewing.add(identity)

        def respond() -> None:
            """Keep a reviewer that takes minutes off the pipe reader."""
            try:
                answer = self._review(identity, native)
            except Exception as error:
                failed = review_failed(f'{type(error).__name__} in the review path')
                answer = review_refusal(failed['reason'])
                try:
                    self._hold_review(identity, native, failed)
                except Exception:
                    pass  # The refusal stands; the call does not run.
            with self.lock:
                if identity not in self.reviewing:
                    return  # Claude cancelled the callback and reads no answer.
                self.reviewing.discard(identity)
            try:
                self._reply(identity, answer)
            except RuntimeAdapterError:
                pass  # The pipe closed: the process and its tool call are gone.

        threading.Thread(target=respond, daemon=True).start()

    def _review(self, identity: str, native: dict) -> dict:
        """Return the hook answer for one tool call, holding a refused one for the parent.

        Recording comes first: an unrecorded decision is a failed review.
        """
        tool, tool_input, tool_use_id = native.get('tool_name'), native.get('tool_input'), native.get('tool_use_id')
        call = review_key(tool, tool_input)
        with self.lock:
            released = self.review_releases[call] > 0
            if released:
                self.review_releases[call] -= 1
            waiting = any(details['method'] == REVIEW_METHOD
                          and review_key(details['params']['tool'], details['params']['input']) == call
                          for details in self.pending.values())
        if released:
            self._record_review(tool, tool_use_id, {'decision': 'released',
                                                    'reason': 'The direct parent released this exact retry.'})
            with self.lock:
                self.review_allowed.append((tool_use_id, call))
            return {}
        if waiting:
            # One question per call: a child that retries early does not ask again.
            return review_refusal('An identical refused call already waits for your direct parent.')
        decision = self._ask_reviewer(tool, tool_input)
        if decision['decision'] == 'allow':
            self._record_review(tool, tool_use_id, decision)
            with self.lock:
                self.review_allowed.append((tool_use_id, call))
            return {}
        self._record_review(tool, tool_use_id, decision)
        self._hold_review(identity, native, decision)
        return review_refusal(decision['reason'])

    def _ask_reviewer(self, tool: object, tool_input: object) -> dict:
        """Return one strict decision document; anything else is a failed review."""
        from agent_swarm.review import build_request, review_call

        try:
            request = build_request('claude', tool, tool_input, cwd=self.request['worktree_path'],
                                    instruction=self.prompt)
            return parse_decision(review_call(self.request['review'], request))
        except Exception as error:
            return review_failed(f'{type(error).__name__} while asking the reviewer')

    def _record_review(self, tool: object, request_id: str | None, decision: dict) -> None:
        """Keep the decision beside the Session, never the tool input."""
        from agent_swarm.review import record_decision

        record_decision(self.directory, 'claude', tool, request_id, decision)

    def _hold_review(self, identity: str, native: dict, decision: dict) -> None:
        """Retain a refused call for the direct parent before the child learns of it.

        Holding first means the turn cannot end before the execution knows it
        must stay open. A stopping execution or a cancelled callback holds nothing.
        """
        token = uuid.uuid4().hex
        details = {'session': self.session, 'execution_id': self.execution_id,
                   'request_id': 'agents-review:' + uuid.uuid4().hex, 'request_token': token,
                   'method': REVIEW_METHOD,
                   'params': {'tool': native.get('tool_name'), 'input': native.get('tool_input'),
                              'decision': decision['decision'], 'reason': decision['reason']}}
        with self.lock:
            if self.stopping.is_set() or identity not in self.reviewing:
                return
            self.pending[token] = details
        self._notify(token, details, 'Claude review requires a parent reply:\n' + json.dumps(details))

    def _reviewed_prompt(self, event: dict) -> bool:
        """Answer Claude's prompt for a call already allowed; say whether it was answered.

        A prompt naming ``blocked_path`` or asking to leave the sandbox goes to
        the parent: the reviewer was not asked to widen a native limit. A prompt
        for a call never allowed goes there too.
        """
        request = event['request']
        tool_input, tool_use_id = request.get('input'), request.get('tool_use_id')
        call = review_key(request.get('tool_name'), tool_input)
        with self.lock:
            allowed = next((item for item in self.review_allowed if item[1] == call
                            and (tool_use_id is None or item[0] is None or item[0] == tool_use_id)), None)
            if allowed is None:
                return False
            self.review_allowed.remove(allowed)
        if request.get('blocked_path') or (isinstance(tool_input, dict) and tool_input.get('dangerouslyDisableSandbox')):
            return False
        self._reply(event['request_id'], {'behavior': 'allow', 'updatedInput': tool_input})
        return True

    def _answer_review(self, token: str, details: dict, response: dict) -> dict:
        """Apply the parent's one answer to a refused review (under the lock).

        ``accept`` grants one release of exactly that call, whose retry skips the
        reviewer but not Claude's own limits. The answer is input to the running
        turn; after the turn ended only an accepted one starts another turn. A
        failed send leaves the request pending.
        """
        if response not in ({'decision': 'accept'}, {'decision': 'decline'}):
            raise RuntimeAdapterError('invalid-input', 'Return an explicit accept or decline decision.')
        accepted = response['decision'] == 'accept'
        params = details['params']
        message = (f"Your direct parent answered the refused review of your {params['tool']} call "
                   f"({details['request_id']}): "
                   + ('you may retry exactly that call once, with identical input; a changed call is reviewed again.'
                      if accepted else 'do not retry that call; continue with other work or report it as blocked.'))
        if accepted or not self.turn_ended:
            self._prompt(message)
        if accepted:
            self.review_releases[review_key(params['tool'], params['input'])] += 1
        del self.pending[token]
        return {'request_id': details['request_id'], 'reply_status': 'submitted'}

    def run(self) -> dict:
        """Own startup, work and cleanup; publish completion only after process exit."""
        last = None
        result_error = None
        reader = None
        stderr_reader = None
        collecting = None
        failure = None
        with ExitStack() as resources:
            collector = self._collector(resources)
            self.collector = collector
            source_position = 0
            address = self._connection(resources)
            stderr = resources.enter_context((self.directory / 'stderr.log').open('a', encoding='utf-8'))
            try:
                if collector is not None:
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
                self.record_process(self.proc.pid)

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
                    **({'PreToolUse': [{'matcher': None, 'hookCallbackIds': ['agents_review'],
                                        'timeout': review_hook_timeout(self.request['review'])}]}
                       if self.request.get('review') is not None else {}),
                })
                resource_update = None
                startup_deadline = time.monotonic() + 45
                stop_deadline = None
                last_echo = last_result = 0
                queued_turns = None
                model_reason = None
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
                        # A parent's answer can release a finished turn with no native event.
                        with self.lock:
                            if self.turn_ended and not self._review_held():
                                self.accepting = False
                                break
                        continue
                    source_position += 1
                    if event.get('type') != 'eof' and collector is not None:
                        self.collection.put(('event', event, source_position))
                    kind = event.get('type')
                    if kind == 'system' and event.get('subtype') not in ('init', 'session_state_changed'):
                        model_reason = native_model_reason(event) or model_reason
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
                                    if self.resource_settings is None:
                                        self._prompt(self.prompt)
                                    else:
                                        resource_update = self._control('apply_flag_settings', settings=self.resource_settings)
                                        self.diagnostics['read_resources'] = {
                                            'requested_paths': self.resource_settings['permissions']['additionalDirectories'],
                                            'control_status': 'pending',
                                        }
                                        self._save_diagnostics()
                        elif resource_update is not None and response.get('request_id') == resource_update:
                            self.diagnostics['read_resources']['control_status'] = response.get('subtype', 'unknown')
                            self._save_diagnostics()
                            if response.get('subtype') != 'success':
                                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Claude refused exact resource settings.')
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
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', model_change_message(
                                'Claude selected a different Session or model', self.request['model'],
                                event.get('model'), model_reason))
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
                            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', model_change_message(
                                'Claude changed the configured model', self.request['model'], model, model_reason))
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
                        # A refused review keeps the execution open for its parent's answer.
                        self.turn_ended = bool(self.results and settled and self.native_state == 'idle')
                        if self.turn_ended and not self._review_held():
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
                    self.record_process(self.proc.pid, {'terminal_confirmed': self.terminal_confirmed,
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
                    if self.collection_failure is not None and failure is None:
                        failure = RuntimeAdapterError('RUNTIME_ARCHIVE_FAILED', str(self.collection_failure))
                try:
                    if collector is not None and pipes_drained:
                        while not self.events.empty():
                            event = self.events.get_nowait()
                            source_position += 1
                            if event.get('type') != 'eof':
                                collector.accept(event, source_position, defer=not self.events.empty())
                        collector.close()
                    elif collector is not None:
                        collector.flush()
                except Exception as error:
                    failure = RuntimeAdapterError('RUNTIME_ARCHIVE_FAILED', str(error))
                self.diagnostics['collection'] = ('failed' if self.collection_failure is not None
                                                  or getattr(failure, 'code', None) == 'RUNTIME_ARCHIVE_FAILED'
                                                  else 'complete')
                self._save_diagnostics()
                if (failure is None and self.dropped_prompt_seconds is not None
                        and not self.stopping.is_set()):
                    failure = RuntimeAdapterError(
                        'RUNTIME_PROVIDER_FAILED',
                        'Claude did not receive the instruction: its UserPromptSubmit hook reply '
                        f'came {self.dropped_prompt_seconds:.0f} s after the request (host wall '
                        f'clock), past Claude\'s {PROMPT_HOOK_LIMIT_SECONDS} s limit; host sleep '
                        'or suspension causes this. The Session is unchanged; resume it to send '
                        'the instruction again.')
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

    def _review_held(self) -> bool:
        """Whether a refused review still waits for the parent's answer."""
        return any(details['method'] == REVIEW_METHOD for details in self.pending.values())

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
                    # A held review has no native request left to answer.
                    if details['method'] != REVIEW_METHOD:
                        self._reply(details['request_id'], {'behavior': 'deny', 'message': 'Execution interrupted.', 'interrupt': True})
                self.pending.clear()
                self.review_releases.clear()
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
                if details is not None and details['method'] == REVIEW_METHOD:
                    return self._answer_review(request['request_token'], details, response)
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


def review_key(tool: object, tool_input: object) -> tuple[str, str]:
    """Identify one exact tool call: its name and canonical JSON input, as a digest."""
    text = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return str(tool), hashlib.sha256(text.encode()).hexdigest()


def review_refusal(reason: str) -> dict:
    """Refuse the call through Claude's own PreToolUse decision."""
    return {'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': (f'{reason} Your direct parent has been asked; '
                                     'do not retry this call until you are told you may.'),
    }}


def review_hook_timeout(reviewer: dict) -> int:
    """Outlast the bounded reviewer, so that Claude never gives up on the hook first."""
    return max(REVIEW_HOOK_MIN_SECONDS, int(reviewer.get('timeout_seconds', 0)) + REVIEW_HOOK_MARGIN_SECONDS)


def native_model_reason(event: dict) -> str | None:
    """Return the explanation a native system event gives, such as a model fallback."""
    facts = ', '.join(f'{key}={event[key]}' for key in
                      ('trigger', 'apiRefusalCategory', 'originalModel', 'fallbackModel')
                      if event.get(key) is not None)
    text = ' '.join(event['content'].split())[:400] if isinstance(event.get('content'), str) else ''
    if not (text or facts):
        return None
    return redact(f"{event.get('subtype')}: {text}" + (f' ({facts})' if facts else ''))


def model_change_message(summary: str, requested: object, observed: object, reason: str | None) -> str:
    """State both models and the Runtime's reason so a stopped child is diagnosable."""
    return (f'{summary}: requested model {requested}, observed model {observed}; Runtime reason: '
            + (reason or 'not provided in the native stream') + '.')


def yaml_document(path: Path) -> dict:
    """Read this owner's retained native identity document."""
    import yaml

    return yaml.safe_load(path.read_text())
