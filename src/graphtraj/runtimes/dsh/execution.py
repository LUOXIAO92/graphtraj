"""Own native DSH input, cancellation, completion and retained Session records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid
from contextlib import ExitStack

import yaml

from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.runtimes.dsh.service import DshService
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


class DshExecution:
    """Keep one Session bound until work and the pending inbox are quiescent."""

    def __init__(
        self,
        request: dict,
        prompt: str,
        directory: Path,
        started: Callable[[str, int], None],
        created: Callable[[str, int], None],
        trace_file: Path,
        expected_session: str | None,
    ) -> None:
        """Capture this invocation; no process or model work starts here."""
        self.request = request
        self.prompt = prompt
        self.directory = directory
        self.started = started
        self.created = created
        self.trace_file = trace_file
        self.session = expected_session
        self.execution_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.finished = threading.Event()
        self.service: DshService | None = None
        self.active = False
        self.outcome: str | None = None
        self.last_message: str | None = None
        self.end: dict | None = None
        self.unsupported: str | None = None
        self.pending: dict[str, dict] = {}
        # Runner retires/moves its control directory. Keep native Session data
        # with the durable Trace so retirement cannot break the retained link.
        self.logs = trace_file.parent / 'dsh-native'

    def _prepare(self) -> dict[str, str]:
        """Compose an isolated native profile, retaining defaults outside this Agent."""
        home = self.directory / 'dsh-home'
        profile = home / 'profiles' / 'web'
        profile.mkdir(parents=True, exist_ok=True)
        # DSH public profile manifest: use installed official bundles, no installs.
        manifest = {'private': True, 'dsh': {'profile': {
            'bundles': ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'],
        }}}
        (profile / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
        mode = self.request['sandbox']
        patches = [
            {'id': 'hmr', 'disabled': True},
            {'id': 'session-persistence-jsonl', 'config': {'root': str(self.logs), 'compression': 'none'}},
            {'id': 'sandbox-policy', 'config': {'mode': mode, 'workspaceRoot': self.request['worktree_path']}},
            {'id': 'permission', 'config': {
                'presets': {mode: {'sandbox': mode, 'approval': 'ask'}}, 'defaultPreset': mode,
            }},
            {'id': 'llm-deepseek', 'config': {
                'baseURL': self.request['base_url'], 'apiKeyEnv': self.request['api_key_env'],
                **({'reasoningEffort': self.request['reasoning_effort']}
                   if self.request['reasoning_effort'] is not None else {}),
            }},
            {'id': 'system-prompt', 'config': {'personaSuffix': self.request['instructions']}},
            {'insert': [{'id': 'graphtraj', 'name': str(Path(__file__).with_name('tool.mjs'))}]},
        ]
        (profile / 'cordis.patch.yml').write_text(yaml.safe_dump(patches, sort_keys=False), encoding='utf-8')
        environment = dict(os.environ)
        environment.update({
            'DSH_HOME': str(home), 'DSH_PERMISSION_MODE': mode, 'NO_COLOR': '1',
            'GRAPHTRAJ_DSH_PACKAGE': self.request['package'],
            'GRAPHTRAJ_DSH_TOOL': self.request['tool'],
            'GRAPHTRAJ_HARNESS_ROOT': self.request['harness_root'],
        })
        return environment

    def _retain_trace(self) -> None:
        """Link the exact native uncompressed log; never substitute browser events."""
        if not self.session:
            return
        candidates = [path for path in self.logs.rglob('*.jsonl') if path.parent.name == self.session]
        if len(candidates) == 1:
            source = candidates[0].resolve()
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            if self.trace_file.is_symlink():
                if self.trace_file.resolve() != source:
                    raise RuntimeAdapterError('RUNTIME_TRACE_FAILED', 'DSH native Trace changed identity.')
            elif self.trace_file.exists() and self.trace_file.stat().st_size:
                raise RuntimeAdapterError('RUNTIME_TRACE_FAILED', 'Refusing to replace retained Trace content.')
            else:
                self.trace_file.unlink(missing_ok=True)
                self.trace_file.symlink_to(source)

    def _projections(self) -> dict:
        """Require native inbox evidence; missing state must not mean an empty queue."""
        result = self.service.rpc('session/projections', {'sessionId': self.session})
        values = result.get('values', {}) if isinstance(result, dict) else {}
        inbox = values.get('inbox')
        if not isinstance(inbox, dict) or any(not isinstance(inbox.get(key), list)
                                              for key in ('next-turn', 'next-step')):
            raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', 'DSH inbox projection unavailable.')
        if values.get('userQuestions', {}).get('active'):
            self.unsupported = 'DSH interactive user input is unsupported.'
            self.stopping.set()
        return values

    def _cancel(self) -> None:
        """Remove both pending queues BEFORE cancel; native cancel keeps the inbox."""
        with self.lock:
            if not self.active:
                return
            values = self._projections()
            with (self.directory / 'stderr.log').open('a', encoding='utf-8') as diagnostics:
                diagnostics.write('DSH cancellation inbox: ' + json.dumps({
                    key: len(value) for key, value in values['inbox'].items()
                }) + '\n')
            for messages in values['inbox'].values():
                for message in messages:
                    try:
                        self.service.rpc('session/updateQueue', {
                            'sessionId': self.session, 'itemId': message['id'], 'action': {'kind': 'remove'},
                        })
                    except RuntimeAdapterError as error:
                        # An item may have just entered the active turn. Cancel
                        # that turn below; never treat a missing item as stopped.
                        if 'session/queue-item-not-found' not in str(error):
                            raise
            self.service.rpc('session/cancel', {'sessionId': self.session})

    def _settled(self) -> bool:
        """Confirm native inactivity AND empty next-turn/next-step queues."""
        with self.lock:
            values = self._projections()
            if any(values['inbox'].values()):
                return False
            rows = self.service.rpc('session/list', {})['items']
            row = next((item for item in rows if item['sessionId'] == self.session), None)
            if row is None:
                raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', 'Owned DSH Session disappeared.')
            settled = row['running'] is False
            if settled and self.stopping.is_set():
                with (self.directory / 'stderr.log').open('a', encoding='utf-8') as diagnostics:
                    diagnostics.write('DSH stop confirmed: native running=false; both inbox queues empty.\n')
            return settled

    def _input(self, prompt: str, mode: str, request_id: str | None = None) -> None:
        """Submit only to this bound Session, keeping receipt distinct from execution."""
        self.service.rpc('session/prompt', {
            'sessionId': self.session, 'requestId': request_id or uuid.uuid4().hex,
            'mode': mode, 'content': [{'type': 'text', 'text': prompt}],
        })

    def _approval_frames(self) -> None:
        """Expose native approval requests to the parent; never decide them here."""
        for frame in self.service.take_events():
            kind = frame.get('type')
            if kind == 'waterfall' and frame.get('event') == 'approval/request':
                self._request_approval(frame)
            elif kind == 'cancel':
                # The first answer, native abort or process exit settles the
                # native request; a later reply must authorize nothing.
                with self.lock:
                    for token, details in list(self.pending.items()):
                        if details['request_id'] == frame.get('eventId'):
                            del self.pending[token]

    def _request_approval(self, frame: dict) -> None:
        """Publish one pending native approval with the identity its parent needs."""
        request  = frame.get('request') or {}
        event_id = frame.get('eventId')
        token    = uuid.uuid4().hex
        details  = {
            'session': self.session, 'execution_id': self.execution_id,
            'request_id': event_id, 'request_token': token,
            'method': 'dsh/approval-request', 'tool': request.get('toolName'),
            'call_id': request.get('callId'), 'reason': request.get('reason'),
        }
        with self.lock:
            if self.stopping.is_set() or self.finished.is_set():
                return
            self.pending[token] = details
        threading.Thread(target=self._notify_direct_parent, args=(token, details), daemon=True).start()

    def _notify_direct_parent(self, token: str, details: dict) -> None:
        """Announce a pending request through the real parent channel, without deciding."""
        from graphtraj.execution.runner_control import notify_direct_parent

        notice = (
            'Direct child notice: DSH Session {session} waits for your decision on native '
            'approval request {request_id} ({tool}) in execution {execution_id}. Reply through '
            'the existing reply entry for that request when you decide; receiving this notice '
            'neither approves nor rejects it.'
        ).format(**details)
        while True:
            with self.lock:
                if token not in self.pending:
                    return
            try:
                receipt = notify_direct_parent(self.directory, notice, details)
            except Exception:
                receipt = None
            if receipt is not None and receipt.get('delivery') in {'received', 'no-direct-parent'}:
                return
            # Retry only while the original native request is still pending.
            time.sleep(1)

    def run(self) -> dict:
        """Bind, subscribe, prompt and wait; retain ownership through stop confirmation."""
        from graphtraj.interfaces.hosted_cli import CONNECTION_ENV, cli_connection
        from graphtraj.runtimes.codex.managed_session import native_operation_features

        connections = ExitStack()
        environment = self._prepare()
        # The native plugin uses the prepared public CLI. Kernel-observed PID
        # ownership authenticates it; an environment address is not authority.
        environment[CONNECTION_ENV] = connections.enter_context(cli_connection(
            Path(self.request['harness_root']), self.directory.name, native_operation_features(),
        ))
        self.service = DshService(self.request['executable'], Path(self.request['worktree_path']), environment)
        try:
            self.service.start()
            request = {'cwd': self.request['worktree_path']}
            if self.session is not None:
                request['sessionId'] = self.session
            native = self.service.rpc('session/create', request)['sessionId']
            if self.session is not None and self.session != native:
                raise RuntimeAdapterError('RUNTIME_SESSION_NOT_RESUMABLE', 'DSH returned another Session.')
            self.session = native
            write_yaml_durably(self.directory / 'session.yml', {'session': native, 'runtime': 'dsh'})
            self.created(native, self.service.process.pid)
            self.service.follow(native)
            self.service.open_events()
            self.service.rpc('session/selectModel', {
                'sessionId': native, 'provider': self.request['provider'], 'model': self.request['model'],
                **({'reasoningEffort': self.request['reasoning_effort']}
                   if self.request['reasoning_effort'] is not None else {}),
            })
            with self.lock:
                self.active = True
                # A recovered Session must not silently execute an old inbox.
                if any(self._projections()['inbox'].values()):
                    self.stopping.set()
                    self.unsupported = 'DSH recovered with pending input; stopped it before continuation.'
                self.started(native, self.service.process.pid)
                if not self.stopping.is_set():
                    self._input(self.prompt, 'queue', self.execution_id)
            stopping_since = None
            while True:
                if self.stopping.is_set():
                    if stopping_since is None:
                        stopping_since = time.monotonic()
                        self._cancel()
                    if self._settled():
                        self.outcome = 'interrupted'
                        break
                    if time.monotonic() - stopping_since > 20:
                        raise RuntimeAdapterError('RUNTIME_STOP_FAILED', 'DSH did not reach cancellation quiescence.')
                frame = self.service.receive()
                self._retain_trace()
                self._approval_frames()
                if frame.get('type') == 'event':
                    event = frame['event']
                    kind = event['type']
                    data = event.get('data', {})
                    if kind == 'assistant/message':
                        self.last_message = ''.join(part.get('text', '') for part in data.get('message', {}).get('content', [])
                                                    if part.get('type') == 'text')
                    elif kind == 'turn/start':
                        self.end = None
                    elif kind == 'turn/end':
                        self.end = data
                    elif kind == 'tool/call' and data.get('name') == 'ask_user_question':
                        # approval/asked and approval/decided are log-only audit
                        # events; only non-approval user questions stay unsupported.
                        self.unsupported = 'DSH interactive user input is unsupported.'
                        self.stopping.set()
                with self.lock:
                    if self.end is not None and not self.stopping.is_set() and self._settled():
                        reason = self.end.get('reason', {}).get('kind')
                        if reason != 'completed':
                            raise RuntimeAdapterError('RUNTIME_EXECUTION_FAILED', f'DSH turn ended with {reason}.')
                        # Close input admission atomically with quiescence so a
                        # racing send cannot get a receipt after work finished.
                        self.active = False
                        self.outcome = 'completed'
                        break
            if self.unsupported:
                raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED', self.unsupported)
            return {'outcome': self.outcome, 'session_id': self.session,
                    'execution_id': self.execution_id, 'last_agent_message': self.last_message}
        except RuntimeAdapterError as error:
            with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                stream.write(error.code + ': ' + error.message + '\n')
            raise
        finally:
            try:
                self.service.close()
                with self.lock:
                    self.active = False
                    self.pending.clear()
                self._retain_trace()
                if self.outcome is not None and not self.trace_file.is_file():
                    raise RuntimeAdapterError('RUNTIME_TRACE_FAILED', 'DSH native Trace was not retained.')
            finally:
                connections.close()
                self.finished.set()

    def operate(self, request: dict) -> dict:
        """Use the exact native Session/invocation binding; never accept caller identity."""
        if request.get('operation') == 'interrupt':
            with self.lock:
                if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                    raise RuntimeAdapterError('operation-failed', 'DSH execution identity mismatch.')
                self.terminate()
            if not self.finished.wait(30) or self.outcome not in {'interrupted', 'completed'}:
                raise RuntimeAdapterError('operation-failed', 'DSH stop is not confirmed.', terminal_confirmed=False)
            return {}
        with self.lock:
            if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                raise RuntimeAdapterError('operation-failed', 'DSH execution identity mismatch.')
            operation = request.get('operation')
            if operation == 'status':
                return {'activity': 'running' if self.active else 'idle', 'last_outcome': self.outcome}
            if operation == 'requests':
                return {'requests': list(self.pending.values())}
            if operation == 'reply':
                details  = self.pending.get(request.get('request_token'))
                response = request.get('response')
                if details is None or self.stopping.is_set() or self.finished.is_set():
                    raise RuntimeAdapterError('invalid-input', 'Supply a reply to a pending DSH approval request.')
                decision = response.get('decision') if isinstance(response, dict) else None
                if not isinstance(response, dict) or set(response) != {'decision'} or decision not in {'allow', 'reject'}:
                    raise RuntimeAdapterError('invalid-input', 'Return exactly one explicit allow or reject decision.')
                outcome = 'allowed-once' if decision == 'allow' else 'rejected'
                self.service.answer_approval(details['request_id'], outcome)
                del self.pending[request['request_token']]
                return {'request_id': details['request_id'], 'reply_status': 'submitted'}
            if operation == 'send' and self.active and not self.stopping.is_set():
                self._input(request['instruction'], 'steer')
                self.end = None
                return {}
            raise RuntimeAdapterError('operation-unavailable', 'DSH operation unavailable for this execution.')

    def terminate(self) -> bool:
        """Schedule stopping; run() owns native quiescence and process cleanup."""
        self.stopping.set()
        return True
