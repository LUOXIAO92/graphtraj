"""Own native DSH input, cancellation, completion and retained Session records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import sys
import time
from typing import Any, Callable
import uuid
from contextlib import ExitStack

import yaml

from .service import DshService
from .errors import DshError
from .settings import credential_environment


# DSH's shipped profile patches carry `!!js` expressions (for example the
# platform guards on its tool rows). Preserve that tag while the adapter copies
# a shipped agent preset into this Session's own profile patch.
_JS_TAG = 'tag:yaml.org,2002:js'
_WEB_APP_BUNDLE = Path('node_modules') / '@deepseek-ai' / 'dsh-web-app'
_PERSONA_PLUGIN = '@deepseek-ai/dsh-persona'


class _JsExpression(str):
    """One `!!js` expression kept exactly as the installed profile wrote it."""


class _PatchLoader(yaml.SafeLoader):
    """Profile-patch loader that keeps `!!js` expressions instead of failing."""


class _PatchDumper(yaml.SafeDumper):
    """Profile-patch dumper that writes those expressions back."""


_PatchLoader.add_constructor(
    _JS_TAG, lambda loader, node: _JsExpression(loader.construct_scalar(node)),
)
_PatchDumper.add_representer(
    _JsExpression, lambda dumper, value: dumper.represent_scalar(_JS_TAG, str(value)),
)


def _dump_profile_patches(patches: list[dict]) -> str:
    """Serialize this Session's profile patch list, keeping `!!js` expressions."""
    return yaml.dump(patches, Dumper=_PatchDumper, sort_keys=False)


def _load_installed_patches(path: Path) -> list:
    """Read one installed profile patch list, or nothing when it is unavailable."""
    try:
        document = yaml.load(path.read_text(encoding='utf-8'), Loader=_PatchLoader)
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    return document if isinstance(document, list) else []


def _deployment_agent_preset(install_root: Path, instructions: str) -> dict | None:
    """Return the installed agent-preset override that carries ``instructions``.

    The Web profile's default ``standard`` agent preset mounts its own
    scope-only ``persona`` row, which shadows the deployment persona for every
    Session that preset creates. The role text therefore also replaces that
    row's prefix and suffix, and the preset's remaining plugins are copied
    exactly as installed so its tools, groups and isolation stay unchanged.

    Parameters
    ----------
    install_root:
        Directory holding the installed DSH package and its bundles.
    instructions:
        Resolved role text to install as the Session's system-layer input.

    Returns
    -------
    dict | None
        An id-targeted profile patch row, or None when the installed bundle
        cannot be read; the existing deployment-persona patch then stays the
        only prompt input.
    """
    bundle = install_root / _WEB_APP_BUNDLE
    try:
        manifest = json.loads((bundle / 'package.json').read_text(encoding='utf-8'))
        declared = manifest['dsh']['bundle']['patch']
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None
    names = [declared] if isinstance(declared, str) else declared
    if not isinstance(names, list):
        return None

    for name in names:
        if not isinstance(name, str):
            return None
        for row in _load_installed_patches(bundle / name):
            if not isinstance(row, dict):
                continue
            for entry in row.get('insert') or []:
                if not isinstance(entry, dict) or not isinstance(entry.get('id'), str):
                    continue
                config = entry.get('config')
                if not isinstance(config, dict) or config.get('id') != 'standard':
                    continue
                if not isinstance(config.get('plugins'), list):
                    continue
                for plugin in config['plugins']:
                    if (isinstance(plugin, dict) and plugin.get('id') == 'persona'
                            and plugin.get('name') == _PERSONA_PLUGIN):
                        plugin['config'] = {'prefix': '', 'suffix': instructions}
                        return {'id': entry['id'], 'config': config}
    return None


class DshExecution:
    """Keep one Session bound until work and the pending inbox are quiescent."""

    error_type = DshError
    service_type = DshService
    host_connection = None
    connection_env = 'AGENT_SWARM_CONNECTION'
    parent_notice = None
    archive = None
    confirm_native = None

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
        self.native_header: dict | None = None
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
        # Streamed tool/call contexts, keyed by callId, held only while the
        # call is open so an approval can name exactly what it will run.
        self.tool_calls: dict[str, dict] = {}
        # Runner retires/moves its control directory. Keep native Session data
        # with the durable Trace so retirement cannot break the retained link.
        self.native_directory = Path(request['native_directory']) if request.get('native_directory') else directory
        self.logs = (self.native_directory / 'dsh-native' if request.get('native_directory')
                     else trace_file.parent / 'dsh-native')

    def _prepare(self) -> dict[str, str]:
        """Compose an isolated native profile, retaining defaults outside this Agent."""
        key = self.request.get('api_key_env')
        try:
            credentials = ({key: 'local'} if self.request.get('unauthenticated')
                           else credential_environment(key))
        except DshError as error:
            raise self.error_type(error.code, error.message) from None
        home = self.native_directory / 'dsh-home'
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
                **({'baseURL': self.request['base_url']} if self.request.get('base_url') else {}),
                **({'apiKeyEnv': self.request['api_key_env']} if self.request.get('api_key_env') else {}),
                **({'models': [{'id': self.request['model']}]}
                   if self.request.get('connection') and (
                       self.request.get('model_source') == 'manual' or self.request.get('base_url')
                   ) else {}),
                **({'reasoningEffort': self.request['reasoning_effort']}
                   if self.request['reasoning_effort'] is not None else {}),
            }},
            {'id': 'system-prompt', 'config': {'personaSuffix': self.request['instructions']}},
        ]
        if self.request.get('plugin'):
            patches.append({'insert': [{'id': 'agents', 'name': self.request['plugin']}]})
        if self.request.get('mcp'):
            mcp = self.request['mcp']
            patches.append({'insert': [{'id': 'agents-mcp', 'name': str(Path(__file__).with_name('plugin.mjs')),
                                        'config': {'mcpCommand': mcp['command'], 'mcpArgs': mcp.get('args', [])}}]})
        if self.request.get('connection'):
            # Native selectModel otherwise saves the selection to the shared
            # profile. This service must keep it scoped to its own Session.
            patches.append({'id': 'config-editor', 'disabled': True})
        preset = _deployment_agent_preset(
            Path(self.request['package']).parent, self.request['instructions'],
        )
        if preset is not None:
            patches.append(preset)
        (profile / 'cordis.patch.yml').write_text(_dump_profile_patches(patches), encoding='utf-8')
        environment = {**os.environ, **credentials}
        environment.update({
            'DSH_AGENT_PACKAGE': self.request['package'],
            'DSH_HOME': self.request.get('runtime_home') or str(home), 'DSH_PERMISSION_MODE': mode, 'NO_COLOR': '1',
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
                    raise self.error_type('RUNTIME_TRACE_FAILED', 'DSH native Trace changed identity.')
            elif self.trace_file.exists() and self.trace_file.stat().st_size:
                raise self.error_type('RUNTIME_TRACE_FAILED', 'Refusing to replace retained Trace content.')
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
            raise self.error_type('RUNTIME_PROTOCOL_ERROR', 'DSH inbox projection unavailable.')
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
                    except self.error_type as error:
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
                raise self.error_type('RUNTIME_PROTOCOL_ERROR', 'Owned DSH Session disappeared.')
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

    def _drain_archive(self) -> None:
        """Drain the native stopped cut and its terminal stream before disconnect.

        Quiescence and follow use different connections. A successful cancel
        response does not prove buffered cursorless terminal frames were read.
        The native projection cursor bounds formal history; an open assistant
        attempt additionally needs its own terminal marker.
        """
        if self.archive is None:
            return
        cut = self.service.rpc('session/projections', {'sessionId': self.session}).get('asOfSeq')
        if type(cut) is not int:
            raise self.error_type('RUNTIME_PROTOCOL_ERROR', 'DSH stopped projection cursor is unavailable.')
        deadline = time.monotonic() + 20
        while (self.archive.observed_cursor < cut
               or self.archive.live is not None and self.archive.live.attempt is not None):
            if time.monotonic() >= deadline:
                raise self.error_type('RUNTIME_TRACE_FAILED', 'DSH stopped follow did not reach its native terminal cut.')
            frame = self.service.receive()
            if frame.get('type') == 'event':
                self.archive.event(frame['event'])
            elif frame.get('type') == 'assistant-stream':
                self.archive.frame(frame['frame'])

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
                            self.tool_calls.pop(details.get('call_id'), None)
                            del self.pending[token]

    def _remember_tool_call(self, data: dict) -> None:
        """Retain one streamed tool call's exact arguments for its approval frame."""
        call_id = data.get('callId')
        if not isinstance(call_id, str) or not call_id:
            return
        arguments = data.get('arguments')
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except (TypeError, ValueError):
            parsed = arguments
        with self.lock:
            if self.stopping.is_set() or self.finished.is_set():
                return
            self.tool_calls[call_id] = {'tool': data.get('name'), 'arguments': parsed}

    def _forget_tool_call(self, call_id: Any) -> None:
        """Drop one completed tool call so no stale action context is served."""
        with self.lock:
            self.tool_calls.pop(call_id, None)

    def _request_approval(self, frame: dict) -> None:
        """Publish one pending native approval with the identity its parent needs."""
        request  = frame.get('request') or {}
        event_id = frame.get('eventId')
        token    = uuid.uuid4().hex
        call_id  = request.get('callId')
        with self.lock:
            # The approval frame names only the tool call; the same native stream
            # already delivered that call's exact arguments, so the parent can
            # review what the operation will actually run.
            action = self.tool_calls.get(call_id) if isinstance(call_id, str) else None
        details  = {
            'session': self.session, 'execution_id': self.execution_id,
            'request_id': event_id, 'request_token': token,
            'method': 'dsh/approval-request', 'tool': request.get('toolName'),
            'call_id': call_id, 'reason': request.get('reason'),
            'display_reason': request.get('displayReason'), 'action': action,
        }
        with self.lock:
            if self.stopping.is_set() or self.finished.is_set():
                return
            self.pending[token] = details
        threading.Thread(target=self._notify_direct_parent, args=(token, details), daemon=True).start()

    def _notify_direct_parent(self, token: str, details: dict) -> None:
        """Announce a pending request through the real parent channel, without deciding."""
        if self.parent_notice is None:
            return  # The native request remains available through requests().

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
                receipt = self.parent_notice(notice, details)
            except Exception:
                receipt = None
            if receipt is not None and receipt.get('delivery') in {'received', 'no-direct-parent', 'retained'}:
                return
            # Retry only while the original native request is still pending.
            time.sleep(1)

    def run(self) -> dict:
        """Bind, subscribe, prompt and wait; retain ownership through stop confirmation."""
        connections = ExitStack()
        if self.host_connection is not None:
            # The selected host interpreter and MCP use the same installed
            # combination. Explicit caller-supplied launch settings still win.
            self.request.setdefault('mcp', {
                'command': str(Path(sys.executable).absolute()),
                'args': ['-I', '-m', 'agent_swarm.mcp'],
            })
        environment = self._prepare()
        for inherited in ('AGENTS_CONNECTION', 'AGENT_SWARM_CONNECTION', 'GRAPHTRAJ_CLI_CONNECTION'):
            environment.pop(inherited, None)
        if self.host_connection is not None:
            channel = Path(self.request['worktree_path']) / '.scratch'
            environment[self.connection_env] = connections.enter_context(self.host_connection(channel))
        options = ({'profile_patch': self.native_directory / 'dsh-home/profiles/web/cordis.patch.yml'}
                   if self.request.get('runtime_home') else {})
        self.service = self.service_type(
            self.request['executable'], Path(self.request['worktree_path']), environment, **options,
        )
        try:
            self.service.start()
            request = {'cwd': self.request['worktree_path']}
            if self.session is not None:
                request['sessionId'] = self.session
            native = self.service.rpc('session/create', request)['sessionId']
            if self.session is not None and self.session != native:
                raise self.error_type('RUNTIME_SESSION_NOT_RESUMABLE', 'DSH returned another Session.')
            self.session = native
            self.created(native, self.service.process.pid)
            snapshot = (self.service.follow(native, assistant_stream=True)
                        if self.archive is not None else self.service.follow(native))
            self.native_header = snapshot.get('header')
            if self.archive is not None:
                records = (self.service.history(snapshot)
                           if not self.archive.resumed or self.archive.archive.backfill_history else [])
                self.archive.start(snapshot, records, execution_id=self.execution_id)
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
                if not self.stopping.is_set():
                    notice = self.request.get('completion_message')
                    if notice is not None:
                        self.service.rpc('agentMessages/receive', {
                            'id': notice['execution'], 'sessionId': native,
                            'senderSessionId': notice['session'], 'sender': notice['agent'],
                            'recipient': notice['parent'], 'body': notice['body'],
                        })
                    else:
                        self._input(self.prompt, 'queue', self.execution_id)
                self.started(native, self.service.process.pid)
            stopping_since = None
            while True:
                if self.stopping.is_set():
                    if stopping_since is None:
                        stopping_since = time.monotonic()
                        self._cancel()
                    if self._settled():
                        self._drain_archive()
                        self.outcome = 'interrupted'
                        break
                    if time.monotonic() - stopping_since > 20:
                        raise self.error_type('RUNTIME_STOP_FAILED', 'DSH did not reach cancellation quiescence.')
                frame = self.service.receive()
                self._retain_trace()
                self._approval_frames()
                if frame.get('type') == 'assistant-stream' and self.archive is not None:
                    self.archive.frame(frame['frame'])
                if frame.get('type') == 'event':
                    event = frame['event']
                    if self.archive is not None:
                        self.archive.event(event)
                    kind = event['type']
                    data = event.get('data', {})
                    if kind == 'assistant/message':
                        self.last_message = ''.join(part.get('text', '') for part in data.get('message', {}).get('content', [])
                                                    if part.get('type') == 'text')
                    elif kind == 'turn/start':
                        self.end = None
                    elif kind == 'turn/end':
                        self.end = data
                    elif kind == 'tool/call':
                        # Keep the streamed call context until its approval frame
                        # arrives, so the parent can review the exact arguments.
                        self._remember_tool_call(data)
                        if data.get('name') == 'ask_user_question':
                            # approval/asked and approval/decided are log-only audit
                            # events; only non-approval user questions stay unsupported.
                            self.unsupported = 'DSH interactive user input is unsupported.'
                            self.stopping.set()
                    elif kind == 'tool/result':
                        self._forget_tool_call(data.get('callId'))
                with self.lock:
                    if self.end is not None and not self.stopping.is_set() and self._settled():
                        reason = self.end.get('reason', {}).get('kind')
                        if reason != 'completed':
                            raise self.error_type('RUNTIME_EXECUTION_FAILED', f'DSH turn ended with {reason}.')
                        # Close input admission atomically with quiescence so a
                        # racing send cannot get a receipt after work finished.
                        self.active = False
                        self.outcome = 'completed'
                        break
            if self.unsupported:
                raise self.error_type('RUNTIME_REQUEST_UNHANDLED', self.unsupported)
            return {'outcome': self.outcome, 'session_id': self.session,
                    'execution_id': self.execution_id, 'last_agent_message': self.last_message}
        except self.error_type as error:
            with (self.directory / 'stderr.log').open('a', encoding='utf-8') as stream:
                stream.write(error.code + ': ' + error.message + '\n')
            raise
        finally:
            try:
                self.service.close()
                with self.lock:
                    self.active = False
                    self.pending.clear()
                    self.tool_calls.clear()
                self._retain_trace()
                if self.outcome is not None and not self.trace_file.is_file():
                    raise self.error_type('RUNTIME_TRACE_FAILED', 'DSH native Trace was not retained.')
                if self.archive is not None and self.trace_file.is_file():
                    try:
                        self.archive.finish(self.trace_file)
                    except (OSError, ValueError, StopIteration) as error:
                        raise self.error_type('RUNTIME_TRACE_FAILED', str(error)) from error
                if self.outcome is not None and self.confirm_native is not None:
                    self.confirm_native(self)
            finally:
                connections.close()
                self.finished.set()

    def operate(self, request: dict) -> dict:
        """Use the exact native Session/invocation binding; never accept caller identity."""
        if request.get('operation') == 'interrupt':
            with self.lock:
                if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                    raise self.error_type('operation-failed', 'DSH execution identity mismatch.')
                self.terminate()
            if not self.finished.wait(30) or self.outcome not in {'interrupted', 'completed'}:
                raise self.error_type('operation-failed', 'DSH stop is not confirmed.', terminal_confirmed=False)
            return {}
        with self.lock:
            if (request.get('session'), request.get('execution_id')) != (self.session, self.execution_id):
                raise self.error_type('operation-failed', 'DSH execution identity mismatch.')
            operation = request.get('operation')
            if operation == 'status':
                return {'activity': 'running' if self.active else 'idle', 'last_outcome': self.outcome}
            if operation == 'requests':
                return {'requests': list(self.pending.values())}
            if operation == 'reply':
                details  = self.pending.get(request.get('request_token'))
                response = request.get('response')
                if details is None or self.stopping.is_set() or self.finished.is_set():
                    raise self.error_type('invalid-input', 'Supply a reply to a pending DSH approval request.')
                decision = response.get('decision') if isinstance(response, dict) else None
                if not isinstance(response, dict) or set(response) != {'decision'} or decision not in {'allow', 'reject'}:
                    raise self.error_type('invalid-input', 'Return exactly one explicit allow or reject decision.')
                outcome = 'allowed-once' if decision == 'allow' else 'rejected'
                self.service.answer_approval(details['request_id'], outcome)
                self.tool_calls.pop(details.get('call_id'), None)
                del self.pending[request['request_token']]
                return {'request_id': details['request_id'], 'reply_status': 'submitted'}
            if operation == 'send' and self.active and not self.stopping.is_set():
                self._input(request['instruction'], 'steer')
                self.end = None
                return {}
            if operation == 'receive' and self.active and not self.stopping.is_set():
                # Only the host completion receiver supplies this communication
                # fact. The native relay renders it and admits its body once.
                message = request.get('message')
                if not isinstance(message, dict) or message.get('sessionId') != self.session:
                    raise self.error_type('invalid-input', 'The Agent reply targets another native Session.')
                result = self.service.rpc('agentMessages/receive', message)
                self.end = None
                return result
            raise self.error_type('operation-unavailable', 'DSH operation unavailable for this execution.')

    def terminate(self) -> bool:
        """Schedule stopping; run() owns native quiescence and process cleanup."""
        self.stopping.set()
        return True
