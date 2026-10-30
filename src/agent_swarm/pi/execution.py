"""Own Pi's persistent stdio transport for one native execution.

This owner needs no GraphTraj installation. A consumer that adds project
connections, Task notices or Session archives overrides the hook methods.
"""

from __future__ import annotations

from contextlib import ExitStack, nullcontext
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
import time
import uuid

import tempfile

from agent_swarm.models import write_key_reference
from agent_swarm.runtime import RuntimeAdapterError, SessionStarted, credential_environment


INFORMATION = {'notify', 'setStatus', 'setWidget', 'setTitle', 'set_editor_text'}
DIALOGS = {'select', 'confirm', 'input', 'editor'}

# The launch request a host prepares. Other fields are kept for subclasses.
REQUIRED = ('executable', 'provider', 'model', 'worktree_path', 'agent_dir', 'instructions',
            'sandbox_python', 'sandbox_path', 'worktree_access')
# Absolute paths the host adds to this owner's own grants and denials.
PATH_LISTS = ('read_paths', 'write_paths', 'deny_read', 'deny_write')
OPTIONAL_TEXT = ('provider_domain', 'base_url', 'provider_api', 'api_key_env', 'reasoning_effort',
                 'native_directory', 'git_common_directory')
# How long Pi has to acknowledge one RPC command.
RPC_SECONDS = 30


def child_path(sandbox_path: str) -> str:
    """Return the PATH a Pi child gets: the host Python's directory, then ``sandbox_path``."""
    return str(Path(sys.executable).parent) + os.pathsep + sandbox_path


class AckLost(RuntimeAdapterError):
    """Pi got a command and did not acknowledge it, so it may have acted on it."""


class PiExecution:
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
        self.bound = False
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
        # Set when Pi accepted the first prompt; the driver also sets it at the end.
        self.accepted = threading.Event()
        # Child notices given to Pi that no user message has shown yet.
        self.unseen: list[dict] = []
        self.unseen_lock = threading.Lock()
        self.stderr_reader: threading.Thread | None = None
        self.startup_terminal_confirmed = False
        self.independent = True
        self.archive = None
        # Header ``extra_fields`` for a Session this execution archives first.
        self.extra_fields: dict | None = None
        # Header ``source`` of a Session this execution archives first.
        self.archive_source: str | None = 'child'
        # Installed control code the sandboxed child reads but never rewrites.
        self.packages = [str(Path(__file__).resolve().parents[1])]
        self.agent = None
        self.parent_notice = None
        self.agent_call = None

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
            response = reply.get(timeout=RPC_SECONDS)
            if not response.get('success'):
                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED',
                                          'Pi ' + kind + ' failed: ' + str(response.get('error', 'transport closed')))
            return response.get('data', {})
        except queue.Empty as error:
            raise AckLost('RUNTIME_REQUEST_FAILED', 'Pi did not acknowledge ' + kind + '.') from error
        finally:
            self.responses.pop(identity, None)

    def _read(self) -> None:
        """Drain replies and native events continuously, including idle dialogs."""
        assert self.proc is not None
        try:
            for line in self.proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    self.events.put({'type': 'transport_error'})
                    break
                if not isinstance(event, dict):
                    self.events.put({'type': 'transport_error'})
                    break
                if event.get('type') == 'message_start':
                    self._saw_message(event.get('message'))
                if event.get('type') == 'extension_ui_request' and event.get('method') not in INFORMATION:
                    self.events.put({'type': 'pi/dialog', 'event': event})
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

    def _saw_message(self, message: object) -> None:
        """Clear the notice this user message shows: Pi took it from its queue here.

        On the reader, not the run loop, which can return with events unread.
        Equal texts clear oldest first, as Pi's own queue does.
        """
        if not isinstance(message, dict) or message.get('role') != 'user':
            return
        content = message.get('content')
        text = content if isinstance(content, str) else ''.join(
            p.get('text', '') for p in content or [] if isinstance(p, dict) and p.get('type') == 'text')
        with self.unseen_lock:
            for entry in self.unseen:
                if entry['text'] == text:
                    entry['taken'] = True
                    self.unseen.remove(entry)
                    return

    def send_notice(self, instruction: str, notice: dict) -> bool | str:
        """Queue one child's notice into the turn, unseen until Pi takes it.

        Returns ``True`` once Pi acknowledged or took it, ``'unconfirmed'`` when
        it never acknowledged the write, and ``False`` when nothing reached it:
        refused, stopping, ended or not yet accepting input.
        """
        entry = {'text': instruction, 'notice': notice}
        with self.unseen_lock:
            self.unseen.append(entry)
        try:
            self.operate({'operation': 'send', 'session': self.session if self.bound else None,
                          'execution_id': self.execution_id, 'instruction': instruction})
            return True
        except RuntimeAdapterError as error:
            with self.unseen_lock:
                if entry in self.unseen:
                    self.unseen.remove(entry)
            return entry.get('taken', False) or ('unconfirmed' if isinstance(error, AckLost) else False)

    def take_unseen(self) -> list[dict]:
        """Return and forget the notices Pi never showed as a user message."""
        with self.unseen_lock:
            unseen, self.unseen = self.unseen, []
        return [entry['notice'] for entry in unseen]

    def prepare_launch(self, address: str | None) -> tuple[list[str], dict]:
        """Project native asb fields and preserve user resources through references.

        The request takes ``REQUIRED``, ``PATH_LISTS``, ``OPTIONAL_TEXT``,
        ``allowed_domains`` and the ``allow_*`` service fields; the caller's
        paths and hostnames add to this owner's own grants and denials.
        """
        request = self.request
        _validate(request)
        credential_environment(request.get('api_key_env'))
        worktree = Path(request['worktree_path']).resolve()
        # Migrated hosts retain native files separately from Task Trace views.
        native = Path(request['native_directory']) if request.get('native_directory') else self.trace.with_suffix('.pi')
        native.mkdir(parents=True, exist_ok=True)
        source = Path(request['agent_dir'])
        agent = native / 'agent'
        agent.mkdir(exist_ok=True)
        read = [str(worktree), str(native),
                str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve()), *self.packages]
        write = [str(native)]
        if address is not None:
            read.append(address)
            write.append(address)
        override = bool(request.get('base_url') or request.get('api_key_env'))
        if override:
            # Retained executions may contain links created by older versions.
            # Unlink the private entry, never write through it into the native Home.
            (agent / 'auth.json').unlink(missing_ok=True)
            (agent / 'models.json').unlink(missing_ok=True)
        for name in ('settings.json', 'models.json', 'auth.json', 'trust.json', 'keybindings.json', 'npm', 'extensions',
                     'skills', 'prompts', 'themes', 'mcp.json', 'AGENTS.md',
                     'AGENTS.override.md', 'AGENTS.MD', 'CLAUDE.md', 'CLAUDE.MD', 'SYSTEM.md', 'APPEND_SYSTEM.md'):
            if (override and name == 'auth.json') or (request.get('base_url') and name == 'models.json'):
                continue
            original = source / name
            link = agent / name
            if original.exists():
                if not link.exists() and not link.is_symlink():
                    link.symlink_to(original)
                read.append(str(original.resolve()))
        provider = request['provider']
        if request.get('api_key_env'):
            write_key_reference(agent, provider, request['api_key_env'])
        if request.get('base_url'):
            # Only an explicit route needs a model overlay. Key-only overrides
            # retain the native definitions; the private auth.json outranks their keys.
            custom = {'baseUrl': request['base_url'], 'api': request['provider_api'],
                      'apiKey': '$' + request['api_key_env'] if request.get('api_key_env') else 'local',
                      'models': [{'id': request['model'],
                                  'reasoning': request.get('reasoning_effort') not in {None, 'off'}}]}
            (agent / 'models.json').write_text(json.dumps({'providers': {provider: custom}}), encoding='utf-8')
        git = request.get('git_common_directory')
        if request['worktree_access'] == 'write':
            write.extend((str(worktree), git))
        write.extend(request.get('write_paths', ()))
        read.extend(request.get('read_paths', ()))
        protected = [str(source), str(Path(sys.prefix).resolve()), *self.packages]
        if git:
            # A writable worktree must not rewrite Git's own config or hooks.
            protected += [str(Path(git) / 'config'), str(Path(git) / 'hooks')]
        policy = {
            'network': {'allowedDomains': list(request.get('allowed_domains', ())), 'deniedDomains': []},
            'filesystem': {
                'denyRead': [*request.get('deny_read', ()), str(source)],
                'allowRead': read,
                'allowWrite': write,
                'denyWrite': [*protected, *request.get('deny_write', ())],
            },
        }
        if self.independent:
            # AgentControl places this owner at <root>/native/<agent>. The
            # caller's cwd may contain that root under any name, not .graphtraj.
            private = self.directory.parent.parent.resolve()
            policy['filesystem']['denyRead'].append(str(private))
            # srt applies write denials after grants: denying the whole root
            # also denies this child's trace and MCP channel. Default-deny
            # writes already protect the root when no broader grant covers it.
            # The selected srt also grants these native log/scratch directories
            # by default. Never place protected control records inside them.
            default_write = ('/tmp/claude', '/private/tmp/claude',
                             str(Path.home() / '.npm/_logs'), str(Path.home() / '.claude/debug'))
            if any(private.is_relative_to(Path(path).resolve()) for path in (*write, *default_write)):
                raise RuntimeAdapterError(
                    'ROLE_CONFIG_UNSUPPORTED',
                    'Pi independent data root overlaps a writable grant; '
                    'retain a separate data root or a read-only worktree.')
        if request.get('base_url'):
            from urllib.parse import urlsplit

            policy['network']['allowedDomains'].append(urlsplit(request['base_url']).hostname)
        else:
            domain = request.get('provider_domain') or self.provider_domain(source, provider)
            if domain not in policy['network']['allowedDomains']:
                policy['network']['allowedDomains'].append(domain)
        # Service access is opt-in for this Runtime and its descendants; keep
        # the existing filesystem grants and denials independent of it.
        for field, native_field in (
            ('allow_mach_lookup', 'allowMachLookup'),
            ('allow_mach_register', 'allowMachRegister'),
            ('allow_local_binding', 'allowLocalBinding'),
            ('allow_unix_sockets', 'allowUnixSockets'),
        ):
            if request.get(field):
                policy['network'][native_field] = request[field]
        _require_read_denials(policy['filesystem'])
        # Grants are native filesystem rules, never a command/path-filter hook.
        policy_file = self.directory / 'pi-policy.json'
        policy_file.write_text(json.dumps(policy), encoding='utf-8')
        instructions = native / 'role-instructions.txt'
        instructions.write_text(request['instructions'], encoding='utf-8')
        native_trace = native / 'session.jsonl'
        if self.expected and not native_trace.is_file():
            raise RuntimeAdapterError('RUNTIME_SESSION_NOT_RESUMABLE', 'Pi native Session file is missing.')
        argv = [request['executable'], '--mode', 'rpc', '--provider', provider,
                '--model', request['model'], '--session', str(native_trace),
                '--append-system-prompt', str(instructions)]
        if self.independent and address is not None:
            argv += ['--extension', str(Path(__file__).with_name('extension.mjs'))]
        if request.get('reasoning_effort'):
            argv += ['--thinking', request['reasoning_effort']]
        spec = self.directory / 'pi-process.json'
        spec.write_text(json.dumps({'policy': str(policy_file), 'argv': argv}), encoding='utf-8')
        env = dict(os.environ)
        # Do not forward Runner bookkeeping as model-declared authority. The only
        # child operation address is authenticated by the existing hosted CLI.
        for key in tuple(env):
            if (key.startswith(('GRAPHTRAJ_', 'AGENT_SWARM_', 'AGENTS_'))
                    or key in {'DSH_SESSION_ID', 'DSH_AGENT_SOURCE'}):
                del env[key]
        env.update(credential_environment(request.get('api_key_env')))
        env.update({'PATH': child_path(request['sandbox_path']),
                    'PI_CODING_AGENT_DIR': str(agent),
                    'PI_ASB_NO_ALIAS_PROMPT': '1'})
        if address is not None:
            env.update(self.connection_environment(address))
        # Pi's native find accepts an existing fd on PATH; do not download it or
        # alter the user's installation to populate the isolated cache.
        fd = source / 'bin/fd'
        if fd.is_file():
            env['PATH'] += os.pathsep + str(fd.parent)
            policy['filesystem']['allowRead'].append(str(fd.resolve()))
            policy_file.write_text(json.dumps(policy), encoding='utf-8')
        self.native_trace = native_trace
        return [request['sandbox_python'], str(Path(__file__).with_name('launch.py')), str(spec)], env

    def provider_domain(self, source: Path, provider: str) -> str:
        """Read the selected model's destination from Pi's own catalog in ``source``."""
        from agent_swarm.models import pi_destination

        return pi_destination(self.request['executable'], str(source), provider, self.request['model'],
                              self.request.get('api_key_env'))

    def bind_connection(self):
        """Serve the existing agents connection to this owned native process."""
        if self.agent_call is None:
            return nullcontext(None)
        from agent_swarm.connection import agents_connection
        from agent_swarm.process import authenticate_process

        return agents_connection(
            self.directory / 'mcp', self.agent_call,
            lambda pid: authenticate_process(self.proc, pid),
        )

    def connection_environment(self, address: str) -> dict:
        """Name the existing connection for the extension's MCP client."""
        return {'AGENT_SWARM_CONNECTION': address, 'AGENT_SWARM_PYTHON': sys.executable}

    def archive_collector(self, header: dict, native: dict):
        """Collect the native Session into the bound archive; without one, archive nothing."""
        if self.archive is None:
            return None
        from agent_swarm.sessions.pi import PiArchive

        # The project root bounds relative attachment paths and private state;
        # a request without one uses its working tree.
        return PiArchive(
            self.archive, header, project=self.request.get('harness_root') or self.request['worktree_path'],
            entries=native['entries'], leaf_id=native['leafId'], source=self.archive_source,
            attachment_root=Path(self.request['worktree_path']), extra_fields=self.extra_fields,
        )

    def record_process(self, pid: int, outcome: dict | None = None) -> None:
        """Publish owned process facts; the host binds the observer."""

    def _notify_parent(self, message: str, details: dict) -> dict | None:
        """Deliver a pending native dialog through the host's direct parent."""
        if self.parent_notice is None:
            raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'No direct parent receives Pi dialogs.')
        return self.parent_notice(message, details)

    def _retain_trace(self) -> None:
        """Link the native file without normalizing timestamps or encrypted fields."""
        if self.native_trace.is_file() and not self.trace.is_symlink():
            self.trace.unlink(missing_ok=True)
            self.trace.symlink_to(self.native_trace)

    def run(self) -> dict:
        """Bind real Pi identity before task input, then observe native settlement."""
        reader = None
        collector = None
        with ExitStack() as resources:
            address = resources.enter_context(self.bind_connection())
            argv, env = self.prepare_launch(address)
            stderr = resources.enter_context((self.directory / 'stderr.log').open('a', encoding='utf-8'))
            stderr_offset = stderr.tell()
            try:
                self.proc = subprocess.Popen(argv, cwd=self.request['worktree_path'], env=env,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             text=True, bufsize=1, start_new_session=True)
                self.record_process(self.proc.pid)

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
                if self.stopping.is_set():
                    raise RuntimeAdapterError('RUNTIME_EXECUTION_INTERRUPTED', 'Pi startup was interrupted.')
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
                _write_yaml(self.directory / 'session.yml', {
                    'session': self.session, 'rollout_path': str(self.native_trace), 'model': model,
                    'runtime_version': self.request.get('version'),
                })
                self.created(self.session, self.proc.pid)
                self.bound = True
                header = {'id': self.session, 'type': 'session'}
                if self.native_trace.is_file():
                    with self.native_trace.open() as stream:
                        header = json.loads(stream.readline())
                collector = self.archive_collector(header, self._rpc('get_entries'))
                with self.lock:
                    if self.stopping.is_set():
                        return self._result('interrupted', None)
                    self.started(self.session, self.proc.pid)
                disposition = self._rpc('prompt', identity=self.execution_id, message=self.prompt)
                if disposition.get('disposition') != 'started':
                    raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', 'Pi task prompt did not start a run.')
                self.prompt_started = True
                self.accepted.set()
                if self.stopping.is_set():
                    self._interrupt()
                last = None
                failure = None
                native_aborted = False
                while True:
                    event = self.events.get()
                    self._retain_trace()
                    kind = event.get('type')
                    if collector is not None and kind not in {'transport_error', 'interaction_error'}:
                        collector.receive(event)
                        if kind in {'turn_end', 'agent_settled'}:
                            native = self._rpc('get_entries')
                            header = None
                            if self.native_trace.is_file():
                                with self.native_trace.open() as stream:
                                    header = json.loads(stream.readline())
                            collector.sync(native['entries'], native['leafId'], header=header,
                                           settled=kind == 'agent_settled')
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
                    self.startup_terminal_confirmed = (
                        native_idle and self.proc is not None and self.proc.poll() is not None
                    )
                    if self.proc is not None:
                        self.record_process(self.proc.pid, self.process_exit_evidence(native_idle))
                    if self.stderr_reader is not None:
                        self.stderr_reader.join(timeout=5)
                    if reader is not None:
                        reader.join(timeout=5)
                    try:
                        if collector is not None:
                            collector.close()
                        if hasattr(self, 'native_trace'):
                            self._retain_trace()
                    finally:
                        self.done.set()

    def process_exit_evidence(self, native_idle: bool) -> dict:
        """Report only facts observed while this owner still holds its Popen.

        A reaped launcher and an absent owned process group do not prove that
        detached native tools stopped. Keep native confirmation separate; an
        unavailable group observation is unknown, never a successful stop.
        """
        if self.proc is None:
            return {'terminal_confirmed': False, 'wrapper_exited': False,
                    'native_idle_confirmed': bool(native_idle), 'owned_process_group_exited': None}
        code = self.proc.poll()
        group_exited = None
        if code is not None:
            try:
                os.killpg(self.proc.pid, 0)
            except ProcessLookupError:
                group_exited = True
            except OSError:
                pass
            else:
                group_exited = False
        return {
            'terminal_confirmed': bool(native_idle and code is not None),
            'runtime_exit_code': code,
            'wrapper_exited': code is not None,
            'owned_process_group_exited': group_exited,
            'native_idle_confirmed': bool(native_idle),
            'native_session_bound': self.bound,
            'prompt_started': self.prompt_started,
            'runtime_execution_id': self.execution_id,
        }

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
            """Notify through the existing parent execution without granting consent.

            A parent still closing its settled turn refuses input, so a
            ``not-delivered`` receipt is retried while the dialog is pending,
            as Codex, Claude and DSH do. The dialog is never answered here.
            """
            message = 'Pi child requires a native reply:\n' + json.dumps(details)
            while True:
                with self.lock:
                    if token not in self.pending or self.stopping.is_set():
                        return
                try:
                    receipt = self._notify_parent(message, details)
                except Exception:
                    self.events.put({'type': 'interaction_error', 'error': RuntimeAdapterError(
                        'RUNTIME_REQUEST_FAILED', 'Pi native dialog could not reach its direct parent.')})
                    return
                if receipt is None or receipt.get('delivery') in {'received', 'retained', 'no-direct-parent'}:
                    return
                time.sleep(1)

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
        """Control only this bound Session/execution using the existing server."""
        with self.lock:
            if (request.get('session'), request.get('execution_id')) != (
                self.session if self.bound else None, self.execution_id,
            ):
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
        if not self.done.wait(timeout=30) or not (
            self.startup_terminal_confirmed and not self.bound
            or self.outcome and self.outcome['outcome'] == 'interrupted'
        ):
            raise RuntimeAdapterError('operation-failed', 'Pi interruption is not yet confirmed.', terminal_confirmed=False)
        return {}


def _write_yaml(path: Path, document: dict) -> None:
    """Atomically replace one YAML record so a reader never sees a partial file."""
    import yaml

    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _validate(request: dict) -> None:
    """Refuse a launch request whose fields have the wrong type, naming the field."""
    def invalid(field: str, expected: str) -> RuntimeAdapterError:
        return RuntimeAdapterError('ROLE_CONFIG_INVALID', f'Pi request field {field} must be {expected}.')

    for field in REQUIRED:
        # Instructions and the sandbox PATH may be empty; names and paths may not.
        if not isinstance(request.get(field), str) or not (request[field] or field in {'instructions', 'sandbox_path'}):
            raise invalid(field, 'a nonempty string')
    if request['worktree_access'] not in {'read', 'write'}:
        raise invalid('worktree_access', "'read' or 'write'")
    for field in OPTIONAL_TEXT:
        if request.get(field) is not None and not isinstance(request[field], str):
            raise invalid(field, 'a string when given')
    for field in PATH_LISTS:
        paths = request.get(field, [])
        if not isinstance(paths, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
            raise invalid(field, 'a list of absolute paths')
    for field in ('allowed_domains', 'allow_mach_lookup', 'allow_mach_register', 'allow_unix_sockets'):
        values = request.get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise invalid(field, 'a list of nonempty strings')
    if not isinstance(request.get('allow_local_binding', False), bool):
        raise invalid('allow_local_binding', 'a boolean')
    if request['worktree_access'] == 'write' and not request.get('git_common_directory'):
        raise invalid('git_common_directory', 'given for write access')
    if request.get('base_url') and not request.get('provider_api'):
        raise invalid('provider_api', 'given with base_url')


def _require_read_denials(filesystem: dict) -> None:
    """Refuse a launch whose read grants would void an existing protected path.

    srt lets allowRead override denyRead, so a denied path inside a readable
    directory (for example ``<root>/.graphtraj`` in a worktree that is the
    project root) cannot be expressed. A protected path that does not exist
    has no contents to expose. A path the launching host itself may not
    inspect is treated as existing, so a covering grant is still refused.
    """
    for denied in filesystem['denyRead']:
        protected = Path(denied).resolve()
        try:
            if not protected.exists():
                continue
        except PermissionError:
            pass
        for allowed in filesystem['allowRead']:
            if protected.is_relative_to(Path(allowed).resolve()):
                raise RuntimeAdapterError(
                    'ROLE_CONFIG_UNSUPPORTED',
                    f'Pi cannot deny reading {protected} inside the readable {allowed}; '
                    'use a worktree or data root that does not contain it.')
