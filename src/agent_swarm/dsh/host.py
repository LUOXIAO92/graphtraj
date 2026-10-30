"""Independent control owner started by the agents DSH plugin inside the user's DSH.

The plugin starts one host per native DSH main Session and supplies that
Session's header on the owned stdio launch boundary. Model requests supply
neither identity nor launch settings. The host configuration is Task-free:
``root`` plus optional per-Runtime settings (``dsh``, ``claude``, ``codex``,
``pi``); see PUBLIC_API.md 1.7.

Private pipe protocol with the plugin: stdin carries one ``{"header",
"model"}`` line, then one ``{"ready": true}`` line when the Session can take
held notices and ``{"ack": <notice id>, "shown": bool}`` lines, then EOF when
the native Session or DSH shuts down; stdout carries one ``{"connection"}``
line, then ``{"notice"}`` lines.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Mapping, TextIO

from agent_swarm import AgentControl, AgentsError, AgentsResult, Caller, bind
from agent_swarm.connection import agents_connection
from agent_swarm.notices import notice_id
from agent_swarm.process import process_ancestors, process_arguments, process_executable

# Top-level host configuration keys; each Runtime key holds that driver's settings.
CONFIG_KEYS = frozenset({'root', 'dsh', 'claude', 'codex', 'pi'})
# How long a written notice waits for the plugin's acknowledgement.
ACK_SECONDS = 10.0
# How many passes one host makes over the held notices, and the pause between
# them: DSH refuses a relay message while the Session is not active here.
FLUSH_ATTEMPTS = 6
FLUSH_RETRY_SECONDS = 5.0


def dsh_installation(entry: Path) -> Path | None:
    """Return the DSH package directory that owns ``entry``, if it is one."""
    for directory in entry.resolve().parents:
        manifest = directory / 'package.json'
        if manifest.is_file():
            try:
                name = json.loads(manifest.read_text(encoding='utf-8')).get('name')
            except (OSError, ValueError):
                return None
            return directory if name == '@deepseek-ai/dsh' else None
    return None


def verify_native_parent(environment: Mapping[str, str]) -> None:
    """Require the actual parent process to be the native DSH that loaded the plugin.

    The plugin names its Node executable and DSH entry; both are only
    constraints on the kernel-observed parent, never identity by themselves.
    """
    node, entry = environment.get('AGENT_SWARM_DSH_NODE'), environment.get('AGENT_SWARM_DSH_ENTRY')
    if not node or not entry:
        raise ValueError('Start the DSH host through the agents DSH plugin.')
    parent = os.getppid()
    actual = process_executable(parent)
    arguments = process_arguments(parent) if parent > 1 else []
    if (parent <= 1 or actual is None or actual.resolve() != Path(node).resolve()
            or len(arguments) < 2 or Path(arguments[1]).resolve() != Path(entry).resolve()
            or dsh_installation(Path(entry)) is None):
        raise ValueError('The host pipe is not owned by the native DSH process.')


def native_main(header: object, cwd: Path) -> dict:
    """Return the expected native facts of the DSH main Session the plugin supplied.

    The same criteria as ``plugin.mjs`` ``sessionEnvironment``: a version 4
    header with no origin, no delegation and a boolean ``isSeeded``. A native
    subagent or a Session of another directory is refused.
    """
    if (not isinstance(header, dict) or header.get('version') != 4
            or not isinstance(header.get('id'), str) or not header['id']
            or header.get('origin') is not None or header.get('delegationDepth', 0)
            or not isinstance(header.get('isSeeded'), bool)):
        raise ValueError('The DSH host binds only a native DSH main Session.')
    if not isinstance(header.get('cwd'), str) or Path(header['cwd']).resolve() != cwd.resolve():
        raise ValueError('The DSH native Session cwd does not match this host.')
    return {'runtime': 'dsh', 'session': header['id'], 'source': 'main', 'cwd': str(cwd)}


def read_configuration(document: object) -> tuple[Path, dict]:
    """Validate the Task-free host configuration; return the root and its settings."""
    if not isinstance(document, dict):
        raise ValueError('The DSH host configuration must be a JSON object.')
    unknown = set(document) - CONFIG_KEYS
    if unknown:
        raise ValueError(f'Unknown DSH host configuration keys: {sorted(unknown)}; allowed: {sorted(CONFIG_KEYS)}.')
    root = document.get('root')
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError('The DSH host configuration needs an absolute data root "root".')
    settings = {key: document.get(key) for key in ('dsh', 'claude', 'codex', 'pi')}
    for key, value in settings.items():
        if value is not None and not isinstance(value, dict):
            raise ValueError(f'"{key}" must be an object of {key} settings.')
    return Path(root), settings


def runtime_drivers(cwd: Path, settings: Mapping[str, Any], parent_model: str | None) -> dict:
    """One driver per Runtime through its public constructor.

    DSH children default to the read-only sandbox and the parent's current
    model; Claude children to read access. Codex needs its ``Run.settings``
    (as ``agent_swarm.codex.host --settings`` takes), else its create fails
    with ``invalid-config``. Pi has no native parent here, so a Pi driver
    exists only when ``pi`` holds its whole child request.
    """
    from agent_swarm.claude.driver import ClaudeDriver
    from agent_swarm.codex.driver import CodexDriver
    from agent_swarm.dsh.driver import DshDriver

    dsh = {'sandbox': 'read-only', **({'model': parent_model} if parent_model else {}), **(settings['dsh'] or {})}
    drivers = {
        'dsh': DshDriver(cwd, dsh),
        'claude': ClaudeDriver(cwd, {'worktree_access': 'read', **(settings['claude'] or {})}),
        'codex': CodexDriver(settings['codex']),
    }
    if settings['pi'] is not None:
        from agent_swarm.pi.driver import PiDriver

        drivers['pi'] = PiDriver({'worktree_path': str(cwd), **settings['pi']})
    return drivers


class Notices:
    """Push this Main's child messages, requests and system errors to the DSH plugin.

    Each notice is one stdout line; the plugin hands it to the existing
    ``agentMessages.receive`` relay (an ``agent-message`` in the Session's
    next-step inbox) and acknowledges it on stdin. Acknowledged as shown is
    ``delivered``; written but not acknowledged in time is ``unconfirmed``
    (it may have been admitted, so it is never repeated); unwritable, refused,
    or still waiting at shutdown is ``held``: it stays readable through
    ``status`` and ``wait`` and a later host for this Session delivers it.
    """

    def __init__(self, stream: TextIO, session: str, timeout: float = ACK_SECONDS) -> None:
        """Bind the plugin's pipe and the verified Main Session."""
        self.stream  = stream
        self.session = session
        self.timeout = timeout
        self.lock    = threading.Lock()
        self.waiting: dict[str, list] = {}
        self.closing = False
        self.closed  = threading.Event()
        self.started = time.time()

    def write(self, document: dict) -> None:
        """Write one protocol line; serialized with notice writes."""
        with self.lock:
            self.stream.write(json.dumps(document) + '\n')
            self.stream.flush()

    def receive(self, notice: dict) -> bool | str:
        """Event receiver for AgentControl: called once per notice for this Main."""
        if notice['parent'] is not None or (notice.get('creator') or {}).get('session') != self.session:
            return False
        identity = notice_id(notice['execution'], notice['outcome'], notice.get('request'))
        message = notice['body'] or (notice.get('error') or {}).get('message') or notice['outcome']
        acknowledged = threading.Event()
        slot = [acknowledged, False]
        with self.lock:
            if self.closing:
                return 'held'
            self.waiting[identity] = slot
            try:
                self.stream.write(json.dumps({'notice': {
                    'id': identity, 'agent': notice['agent'], 'session': notice.get('session'),
                    'event': notice['outcome'], 'message': message,
                    'execution': notice['execution']}}) + '\n')
                self.stream.flush()
            except (OSError, ValueError):
                self.waiting.pop(identity, None)
                return 'held'
        if not acknowledged.wait(self.timeout):
            with self.lock:
                self.waiting.pop(identity, None)
            return 'unconfirmed'
        return True if slot[1] else 'held'

    def flush(self, control: AgentControl, caller: Caller, attempts: int = FLUSH_ATTEMPTS,
              pause: float = FLUSH_RETRY_SECONDS) -> None:
        """Deliver the notices held for this Session, each once, from a new host process.

        Runs on its own thread: a delivery waits for an acknowledgement that
        the stdin loop reads. One a ``status`` or ``wait`` has shown meanwhile
        is no longer open and is not pushed. A pass that leaves a refused
        notice is repeated after ``pause``, ``attempts`` passes at most; what
        is still refused then stays held for a later host.
        """
        for attempt in range(attempts):
            if attempt and self.closed.wait(pause):
                return
            pending = control.held_notices(caller)
            if not pending:
                return
            for notice in pending:
                if not self.closing and control.notice_open(notice):
                    result = self.receive(notice)
                    control.settle_notice(notice, 'delivered' if result is True else
                                          'unconfirmed' if result == 'unconfirmed' else 'held')

    def acknowledge(self, identity: object, shown: bool) -> None:
        """Settle one written notice: admitted to the DSH Session, or refused there."""
        with self.lock:
            slot = self.waiting.pop(identity, None)
        if slot is not None:
            slot[1] = shown
            slot[0].set()

    def hide_pushed(self, document: Mapping[str, Any]) -> None:
        """Hide a body this host is about to push, so the Main receives it once.

        AgentControl marks such an end ``queueing`` before calling the
        receiver, so a concurrent ``wait`` or ``status`` would otherwise show
        the body and the notice would repeat it. A held end being flushed is
        shown as ``queueing`` the same way, so it is not settled as read. Ends
        of earlier host processes, and any end once shutdown began, keep their body.
        """
        pending = [document]
        while pending:
            agent = pending.pop()
            last = agent.get('last_result') or {}
            flushing = notice_id(last.get('id'), last.get('outcome')) in self.waiting
            if (not self.closing and agent.get('parent') is None and (flushing or (
                    last.get('notification') == 'queueing' and (last.get('ended_at') or 0) >= self.started))):
                last.update(notification='queueing', last_message=None)
            pending.extend(agent.get('children', []))

    def close(self) -> None:
        """Stop pushing at native shutdown; unacknowledged notices stay held."""
        with self.lock:
            self.closing = True
            self.closed.set()
            pending, self.waiting = list(self.waiting.values()), {}
        for slot in pending:
            slot[0].set()


def start(config: Path, launch: Mapping[str, Any]) -> tuple[Path, dict, Notices, Callable, Callable, AgentControl, Caller]:
    """Verify the native parent, Session and configuration; bind the DSH Main to its control.

    ``launch`` is the plugin's first pipe line: the native Session ``header``
    and the parent's current ``model``. Returns the model-facing entry and the
    plain bound ``call``: only what the model reads settles a held notice, not
    this host's own shutdown.
    """
    if any(name in os.environ for name in ('AGENT_SWARM_CONNECTION', 'DSH_SESSION_ID', 'DSH_AGENT_SOURCE')):
        raise ValueError('An already-bound child must use its existing connection, not adopt Main.')
    root, settings = read_configuration(json.loads(config.read_text(encoding='utf-8')))
    verify_native_parent(os.environ)
    cwd = Path.cwd()
    expected = native_main(launch.get('header'), cwd)
    model = launch.get('model') if isinstance(launch.get('model'), str) and launch.get('model') else None
    notices = Notices(sys.stdout, expected['session'])
    control = AgentControl(root, runtime_drivers(cwd, settings, model),
                           event_receiver=notices.receive, request_notices=True, hold_notices=True)
    caller = Caller('dsh-native', None, session=expected['session'], runtime='dsh')
    call = bind(control, caller)
    # Fail at start, not mid-turn, when config.yml declares a connection
    # this machine cannot run; create re-checks the selected one.
    control.require_connections()

    def operate(request: dict) -> AgentsResult:
        """Serve one action; a body this host is pushing is hidden, a held one shown is settled."""
        result = call(request)
        found = result.document.get('result')
        if isinstance(found, dict):
            for agent in found.get('agents', [found]):
                notices.hide_pushed(agent)
            if not result.failed:
                control.settle_shown(request, result.document)
        return result

    return root, expected, notices, operate, call, control, caller


def stop_children(call: Callable) -> None:
    """Interrupt every active child, descendants first, through the public stop path."""
    status = call({'action': 'status'})
    if status.failed:
        return
    pending = list(status.document['result']['agents'])
    owned = []
    while pending:
        agent = pending.pop()
        owned.append(agent)
        pending.extend(agent['children'])
    for agent in reversed(owned):
        if agent['state'] == 'active':
            call({'action': 'interrupt', 'agent': agent['agent']})
            result = call({'action': 'wait', 'agent': agent['agent'], 'timeout_seconds': 10})
            if result.failed or result.document['result']['state'] == 'active':
                raise RuntimeError('Native child stop was not confirmed before host shutdown.')


def main() -> None:
    """Keep one control owner alive until the plugin closes its pipe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    options = parser.parse_args()
    try:
        launch = json.loads(sys.stdin.readline() or 'null')
        if not isinstance(launch, dict):
            raise ValueError('The DSH plugin did not supply its native Session.')
        root, expected, notices, operate, call, control, caller = start(options.config, launch)
    except (AgentsError, OSError, ValueError, KeyError) as error:
        # The plugin logs this line; the Session then has no agents tool.
        print(json.dumps({'error': {'code': getattr(error, 'code', 'invalid-config'), 'message': str(error)}}),
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    parent = os.getppid()
    flusher = threading.Thread(target=notices.flush, args=(control, caller), daemon=True)

    def authenticate(caller_pid: int) -> None:
        """Accept only direct clients of the verified native DSH, not child Runtimes."""
        chain = process_ancestors(caller_pid)
        if os.getppid() != parent or len(chain) < 2 or chain[1] != parent:
            raise AgentsError('authority-denied', 'The client is not owned by this native DSH host.')

    try:
        with agents_connection(root / 'live' / 'dsh-host', operate, authenticate,
                               native_context=lambda: expected) as address:
            notices.write({'connection': address})
            # Only readiness, acknowledgements and lifecycle EOF travel over this
            # private plugin pipe. Model requests use the shared authenticated bridge.
            for line in sys.stdin:
                message = json.loads(line)
                if message == {'ready': True}:
                    if flusher.ident is None:
                        flusher.start()
                    continue
                if (not isinstance(message, dict) or set(message) != {'ack', 'shown'}
                        or not isinstance(message['shown'], bool)):
                    raise ValueError('The native host pipe only accepts readiness, notice acknowledgements and close.')
                notices.acknowledge(message['ack'], message['shown'])
    finally:
        # Closing the plugin pipe ends this owner's lifetime. Stop pushing
        # first: ends caused by this shutdown are held, not shown.
        control.close_notices()
        notices.close()
        if flusher.ident is not None:
            flusher.join(10)
        stop_children(call)


if __name__ == '__main__':
    main()
