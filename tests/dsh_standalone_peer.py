"""A controlled DshService for standalone DSH children; imports nothing from GraphTraj.

It answers the native service calls DshExecution makes, echoes each prompt as
the assistant's answer, writes the native Session log DshExecution links as
its Trace, and keeps every launch environment for inspection. No process,
network or model is used.

Session identity follows the installed version in DSH_AGENT_PACKAGE. On
0.2.0-rc.2, ``session/create`` with a stored ``sessionId`` returns it. Later
DSH (0.2.2-alpha.2: dsh-api-session-controller lib/index.js:345-365) mints a
new Session when the named one already has a turn, and resumes a stored
Session when a Session-addressed call (here ``follow``) names it (:160-213).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

import yaml


def install_dsh(root: Path, version: str = '0.2.2-alpha.2') -> Path:
    """Write a stand-in DSH install: ``bin/dsh`` beside a package.json with ``version``."""
    executable = root / 'bin' / 'dsh'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('#!/bin/sh\nexit 1\n')
    executable.chmod(0o755)
    (root / 'package.json').write_text(json.dumps({'name': '@deepseek-ai/dsh', 'version': version}))
    return executable


class FakeDshService:
    """One controlled native service per DSH execution."""

    instances: list['FakeDshService'] = []

    def __init__(self, executable: str, cwd: Path, environment: dict, **options: object) -> None:
        """Keep the launch facts; find the log root in the profile patch DshExecution wrote."""
        self.executable = executable
        self.cwd = cwd
        self.environment = dict(environment)
        self.options = options
        patch = Path(options.get('profile_patch') or Path(environment['DSH_HOME']) / 'profiles/web/cordis.patch.yml')
        self.patches = yaml.safe_load(patch.read_text())
        self.logs = Path(next(row['config']['root'] for row in self.patches
                              if row.get('id') == 'session-persistence-jsonl'))
        self.process = type('Process', (), {'pid': os.getpid(), 'poll': lambda self: None})()
        self.calls: list[tuple] = []
        self.frames: list[dict] = []
        self.lock = threading.Lock()
        self.running = False
        self.session: str | None = None
        self.seq = 0
        self.closed = False
        version = json.loads(Path(environment['DSH_AGENT_PACKAGE']).read_text())['version']
        self.mints = version != '0.2.0-rc.2'
        self.instances.append(self)

    def start(self) -> None:
        """Ready at once."""

    def _log(self) -> Path:
        return self.logs / 'workspace' / self.session / 'v4.jsonl'

    def rpc(self, method: str, body: dict | None = None) -> dict:
        """Answer with the native shapes DshExecution reads."""
        self.calls.append((method, body))
        if method == 'session/create':
            self.session = body.get('sessionId') or f'dsh-session-{len(self.instances)}'
            if self.mints and self._log().exists() and '"turn/start"' in self._log().read_text():
                self.session = f'dsh-minted-{len(self.instances)}'
            log = self._log()
            log.parent.mkdir(parents=True, exist_ok=True)
            if not log.exists():
                log.write_text(json.dumps({'type': 'session', 'version': 4, 'id': self.session,
                                           'cwd': str(self.cwd), 'createdAt': 1, 'isSeeded': False}) + '\n')
            return {'sessionId': self.session}
        if method == 'session/projections':
            return {'asOfSeq': self.seq, 'values': {'inbox': {'next-turn': [], 'next-step': []}}}
        if method == 'session/list':
            return {'items': [{'sessionId': self.session, 'running': self.running}]}
        if method == 'session/prompt':
            text = ''.join(part['text'] for part in body['content'])
            with self.lock:
                self.running = True
                self.frames += [self._event('turn/start', {}),
                                self._event('assistant/message', {'message': {
                                    'id': f'answer-{self.seq}', 'role': 'assistant',
                                    'content': [{'type': 'text', 'text': f'dsh answer: {text}'}]}}),
                                self._event('turn/end', {'reason': {'kind': 'completed'}})]
        if method == 'session/cancel':
            with self.lock:
                self.frames.clear()
                self.running = False
        return {'accepted': True}

    def _event(self, kind: str, data: dict) -> dict:
        self.seq += 1
        return {'type': 'event', 'event': {'type': kind, 'seq': self.seq, 'time': 1,
                                           'data': {'turn': 0, 'step': 0, **data}}}

    def follow(self, session: str, *, assistant_stream: bool = False) -> dict:
        """Return the opening cut of this exact Session, resuming a stored one by address."""
        if self.session is None:
            self.session = session
            if not self._log().exists():
                from agent_swarm.dsh.errors import DshError
                raise DshError('RUNTIME_REQUEST_FAILED', 'DSH session/follow failed (session/not-found).')
        header = json.loads(self._log().read_text().splitlines()[0])
        return {'type': 'snapshot', 'header': header, 'cursor': -1, 'hasMore': False, 'records': []}

    def history(self, snapshot: dict) -> list[dict]:
        return snapshot['records']

    def open_events(self) -> str:
        return 'controlled-client'

    def take_events(self) -> list:
        return []

    def receive(self, timeout: float = 1) -> dict:
        """Deliver the next scheduled event; turn/end ends the native turn."""
        with self.lock:
            if not self.frames:
                frame = {}
            else:
                frame = self.frames.pop(0)
                with self._log().open('a') as stream:
                    stream.write(json.dumps(frame['event']) + '\n')
                if frame['event']['type'] == 'turn/end':
                    self.running = False
        if not frame:
            threading.Event().wait(0.005)
        return frame

    def answer_approval(self, event_id: str, outcome: str) -> None:
        self.calls.append(('answer_approval', event_id, outcome))

    def close(self) -> None:
        self.closed = True
