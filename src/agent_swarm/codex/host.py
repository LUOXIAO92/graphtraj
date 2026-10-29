"""Run an independent Codex host with authenticated agents CLI and MCP.

Usage: python -m agent_swarm.codex.host --settings native-settings.json
       --directory /absolute/control-root 'Instruction for the parent Agent'
Repeat with --resume to continue the exact retained parent Session. The settings
file contains the existing Run.settings keys: adapter_request (arguments,
worktree_path, session_parameters), optional evidence, and optional connection
(base_url, api_key_env, runtime_home). Secrets remain in the native account or
named environment variable. Settings are launch configuration, never identity.

An optional ``runtimes`` object adds children on other Runtimes: Runtime name
to that driver's settings (``claude``: the Claude host's ``settings`` keys;
``dsh``: DshDriver settings such as executable, model, sandbox, api_key_env;
both run in adapter_request's worktree_path). Without an entry, a create for that
Runtime fails with ``unsupported-runtime``.

The actual native service owns the parent. Its CLI/MCP descendants authenticate
by kernel PID and the native Session returned by thread/start or thread/resume.
No Task, Git repository, GraphTraj package or normalized archive is required.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import yaml

from agent_swarm import AgentControl, AgentsError, Caller, bind
from agent_swarm.config import reject_archive_without_collector
from agent_swarm.runtime import RuntimeAdapterError
from .app_server import CodexServerRequest
from .driver import CodexDriver
from .managed_session import CodexManagedExecution


def _claude(settings: dict, cwd: Path) -> object:
    """Check Claude settings at start, then drive Claude children in ``cwd``."""
    from agent_swarm.claude.driver import ClaudeDriver
    from agent_swarm.claude.settings import prepare

    prepare(settings, cwd)
    return ClaudeDriver(cwd, settings)


def _dsh(settings: dict, cwd: Path) -> object:
    """Check DSH settings, executable and version at start, then drive DSH children in ``cwd``."""
    from agent_swarm.dsh.driver import DshDriver

    driver = DshDriver(cwd, settings)
    driver.prepare('dsh', Caller('codex', None))
    return driver


# Runtimes this host can run as children besides Codex; 382 adds pi.
RUNTIMES = {'claude': _claude, 'dsh': _dsh}


def runtime_drivers(settings: dict) -> dict:
    """Remove ``runtimes`` from the host settings and build one driver per entry."""
    entries = settings.pop('runtimes', {})
    if not isinstance(entries, dict) or any(not isinstance(value, dict) for value in entries.values()):
        raise AgentsError('invalid-config', 'runtimes maps a Runtime name to its settings object.')
    if 'codex' in entries:
        raise AgentsError('invalid-config', 'Codex children use the host settings, not a runtimes entry.')
    unsupported = sorted(set(entries) - set(RUNTIMES))
    if unsupported:
        raise AgentsError('unsupported-runtime', 'This Codex host does not support Runtime '
                                                 + ', '.join(unsupported) + ' yet.')
    cwd = Path(settings['adapter_request']['worktree_path'])
    return {runtime: RUNTIMES[runtime](entry, cwd) for runtime, entry in entries.items()}


class CodexHost(CodexManagedExecution):
    """Bind an actual owned native parent to the existing independent controller."""

    def __init__(self, settings: dict, directory: Path, instruction: str, resume: bool = False) -> None:
        """Restore parent identity only from this host's retained native result."""
        directory.mkdir(parents=True, exist_ok=True)
        reject_archive_without_collector(directory)
        native = directory / 'host'
        native.mkdir(exist_ok=True)
        settings = dict(settings)
        others = runtime_drivers(settings)
        driver = CodexDriver(settings)
        settings = driver.prepare('codex', Caller('codex', None))
        expected = None
        if resume:
            previous = yaml.safe_load((native / 'session.yml').read_text())
            expected = previous['session']
        elif (native / 'session.yml').exists():
            raise AgentsError('session-exists', 'Use --resume to continue this host Session.')
        self.control = AgentControl(directory, {'codex': driver, **others}, event_receiver=self._receive_child,
                                    request_notices=True)
        self.control.require_connections()
        self.authentications: list[dict] = []
        self.calls: list[dict] = []
        self.deliveries: list[dict] = []
        super().__init__(settings['adapter_request'], instruction, native,
                         self._started, settings.get('evidence', {}), native / 'trace.jsonl',
                         expected_session=expected, connection=settings.get('connection', {}),
                         agent_call=self._call_agents)

    async def _request(self, request: CodexServerRequest) -> dict:
        """Present the parent's own native requests to the human CLI operator."""
        if request.method == 'item/tool/call':
            return await super()._request(request)
        print(json.dumps({'native_request': {'method': request.method, 'params': request.params}},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            raise RuntimeAdapterError('RUNTIME_REQUEST_UNHANDLED',
                                      'The parent native request needs an explicit JSON response on stdin.')
        response = json.loads(line)
        if not isinstance(response, dict):
            raise RuntimeAdapterError('RUNTIME_REQUEST_INVALID', 'A native response must be a JSON object.')
        return response

    def _started(self, session: str, pid: int) -> None:
        """Publish actual parent provenance after native startup, without credentials."""
        print(json.dumps({'parent_session': session, 'service_pid': pid,
                          'source': 'thread/resume' if self.expected_session else 'thread/start'},
                         ensure_ascii=False), file=sys.stderr, flush=True)

    def _authenticate_mcp(self, pid: int) -> None:
        """Retain only authentication that the actual service owner accepted."""
        super()._authenticate_mcp(pid)
        self.authentications.append({'caller_pid': pid, 'service_pid': self.adapter.service_pid,
                                     'parent_session': self.native_session})

    @staticmethod
    def _display(sender: str, recipient: str, body: str) -> None:
        """Render a communication fact without injecting its screen frame into the model."""
        print(f'┌ {sender} → {recipient}', file=sys.stderr)
        for line in body.splitlines():
            print('│ ' + line, file=sys.stderr)
        print('└', file=sys.stderr, flush=True)

    def _call_agents(self, request: dict) -> object:
        """Bind only after process authentication and native context verification."""
        if self.native_session is None:
            raise AgentsError('authority-denied', 'The native parent Session is not ready.')
        call = bind(self.control, Caller('codex', None, self.native_session, 'codex'))
        result = call(request)
        if not result.failed and request['action'] in {'create', 'send', 'resume'}:
            body = request.get('instruction') or request.get('message')
            if body:
                self._display(self.native_session, result.document['agent'], body)
        self.calls.append({'action': request['action'], 'failed': result.failed,
                           'parent_session': self.native_session, 'result': result.document})
        return result

    def _receive_child(self, notice: dict) -> bool | str:
        """Forward one genuine end or native request notice to this still-owned external parent."""
        if notice['parent'] is not None or self.native_session is None or self.loop is None:
            return False
        if self.loop.is_closed() or self.outcome is not None:
            return False
        # The backend calls this only after retaining the child's native outcome.
        # No model-provided string or Session ID selects the recipient.
        event = {'source': 'agents', 'alias': notice['agent'], 'event': notice['outcome'],
                 'message': notice['body'] or (notice.get('error') or {}).get('message') or notice['outcome']}
        # Once submitted, a lost acknowledgement is unconfirmed, not unavailable.
        # Let the existing backend retain that distinction and suppress duplicates.
        try:
            asyncio.run_coroutine_threadsafe(
                self.adapter.send_host_event(self.native_session, event), self.loop,
            ).result()
        except Exception as error:
            # Only a written request can have shown the body; any earlier
            # failure leaves it readable through wait/status.
            return 'unconfirmed' if getattr(error, 'request_written', False) else False
        self._display(notice['agent'], self.native_session, notice['body'])
        self.deliveries.append({'agent': notice['agent'], 'parent_session': self.native_session,
                                'body': notice['body'], 'accepted': True})
        return True

    def run(self) -> dict:
        """Keep one actual parent owner, even across repeated host invocations."""
        import fcntl

        with (self.directory / 'owner.lock').open('a+b') as ownership:
            try:
                fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AgentsError('turn-running', 'This parent Session already has an owner.') from error
            try:
                result = super().run()
            finally:
                # A closing host stops only work its own controller started.
                # Native Session records remain available to the next invocation.
                self.control.interrupt_owned()
            return {**result, 'parent_session': self.native_session,
                    'operations': self.calls, 'deliveries': self.deliveries,
                    'authenticated_callers': self.authentications}


def main() -> None:
    """Start the packaged native host; request arguments never supply an identity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True, type=Path, help='Host-selected Run.settings JSON.')
    parser.add_argument('--directory', required=True, type=Path, help='Independent control and native state root.')
    parser.add_argument('--output', type=Path, help='Retain the native result and operation evidence as JSON.')
    parser.add_argument('--resume', action='store_true', help='Continue the retained parent native Session.')
    parser.add_argument('instruction', help='Instruction for the actual parent Agent.')
    arguments = parser.parse_args()
    try:
        settings = json.loads(arguments.settings.read_text())
        host = CodexHost(settings, arguments.directory.resolve(), arguments.instruction, arguments.resume)
        result = host.run()
    except (AgentsError, RuntimeAdapterError, OSError, ValueError, KeyError) as error:
        result = {'error': {'code': getattr(error, 'code', 'invalid-input'), 'message': str(error)}}
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(1) from error
    if arguments.output is not None:
        arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(result.get('last_agent_message') or result['outcome'])
    if result.get('error') is not None:
        print(json.dumps(result['error'], ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
