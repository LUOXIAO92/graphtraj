"""Run the standalone control contract with GraphTraj imports forbidden."""

import importlib.abc
import json
import os
from pathlib import Path
import sys
import time


class NoGraphTraj(importlib.abc.MetaPathFinder):
    """Make accidental runtime coupling fail even if GraphTraj is installed."""

    def find_spec(self, fullname: str, path: object = None, target: object = None):
        """Refuse GraphTraj before any module code can execute."""
        if fullname == 'graphtraj' or fullname.startswith('graphtraj.'):
            raise ImportError('GraphTraj is unavailable in this standalone host')
        return None


sys.meta_path.insert(0, NoGraphTraj())

from agent_swarm import AgentControl, Caller, bind
from agent_swarm.dsh import DshDriver
from agent_swarm.dsh.execution import DshExecution, _PatchLoader
import yaml


class Peer:
    """Controlled native service; no model inference or memory claim."""

    instances = []

    def __init__(self, executable: str, cwd: Path, environment: dict, **options: object) -> None:
        """Use only the native profile to locate this Session's retained log."""
        self.process = type('Process', (), {'pid': os.getpid()})()
        home = Path(environment['DSH_HOME'])
        patches = yaml.load((home / 'profiles/web/cordis.patch.yml').read_text(), Loader=_PatchLoader)
        logs = Path(next(row['config']['root'] for row in patches if row.get('id') == 'session-persistence-jsonl'))
        self.log = logs / 'workspace' / 'native-standalone' / 'v4.jsonl'
        self.log.parent.mkdir(parents=True, exist_ok=True)
        if not self.log.exists():
            self.log.write_text(json.dumps({'type': 'session', 'version': 4, 'id': 'native-standalone',
                                           'createdAt': 1, 'isSeeded': False}) + '\n')
        self.running = False
        self.inputs = []
        self.complete = False
        self.instances.append(self)

    def start(self) -> None:
        """The controlled native endpoint is immediately available."""

    def follow(self, session: str) -> dict:
        """Subscribe to the exact retained Session."""
        assert session == 'native-standalone'
        return {'type': 'snapshot'}

    def open_events(self) -> None:
        """No approvals are emitted by this controlled peer."""

    def take_events(self) -> list:
        """Return no native approval frames."""
        return []

    def rpc(self, method: str, request: dict) -> dict:
        """Implement the native lifecycle receipts used by the real owner."""
        if method == 'session/create':
            return {'sessionId': request.get('sessionId', 'native-standalone')}
        if method == 'session/projections':
            return {'values': {'inbox': {'next-step': [], 'next-turn': []}}}
        if method == 'session/list':
            return {'items': [{'sessionId': 'native-standalone', 'running': self.running}]}
        if method == 'session/prompt':
            self.inputs.append(request['content'][0]['text'])
            self.running = True
        if method == 'session/cancel':
            self.running = False
        return {'accepted': True}

    def receive(self) -> dict:
        """Finish only when the test releases this native turn."""
        time.sleep(0.005)
        if self.complete:
            self.running = False
            self.complete = False
            return {'type': 'event', 'event': {'type': 'turn/end', 'data': {'reason': {'kind': 'completed'}}}}
        return {}

    def close(self) -> None:
        """End only the controlled owned service."""
        self.running = False


DshExecution.service_type = Peer
root = Path(sys.argv[1])
driver = DshDriver(root, {'model': 'deepseek-flash', 'reasoning_effort': 'low', 'sandbox': 'workspace-write'})
control = AgentControl(root / 'own-data', {'dsh': driver})
agents = bind(control, Caller('standalone-test', None))
created = agents({'action': 'create', 'runtime': 'dsh', 'instruction': 'first'})
assert not created.failed, created.document
agent = created.document['agent']
try:
    assert not agents({'action': 'send', 'agent': agent, 'message': 'second'}).failed
    assert Peer.instances[0].inputs == ['first', 'second']
finally:
    agents({'action': 'interrupt', 'agent': agent})
stopped = agents({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})
assert stopped.document['result']['state'] == 'standby', stopped.document
resumed = agents({'action': 'resume', 'agent': agent, 'message': 'continue'})
assert not resumed.failed, resumed.document
assert resumed.document['session'] == created.document['session']
Peer.instances[-1].complete = True
finished = agents({'action': 'wait', 'agent': agent, 'timeout_seconds': 5})
assert finished.document['result']['last_result']['outcome'] == 'completed', finished.document
assert not (root / '.graphtraj').exists()
assert not (control.root / 'sessions').exists()
print('GraphTraj-free prepare/create/send/interrupt/resume passed')
