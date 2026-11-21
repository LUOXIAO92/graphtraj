"""546 round 2 scratch check (not a GraphTraj test): the closing window through GraphTraj's AdapterDriver.

  <G-style venv>/bin/python -I gtpath546.py <empty scratch dir>
Real: graftling AgentControl.send (the installed candidate wheel), and GraphTraj's AdapterDriver.deliver -> _operate
-> _native_error (graphtraj.execution.agent_driver), which re-raises the Adapter refusal as a plain AgentsError.
Replaced: the native turn. A fake turn registered in agent_driver._TURNS raises the Claude Adapter's refusal
(RuntimeAdapterError runtime-input-closed, finishing=True) once and reports the execution's end 0.3 s later, as the
closing window does. AdapterDriver.__init__/prepare/start are replaced, so no Runtime is launched.
Case 2: a pending request (unanswered) -> the refusal returns at once, rejected (the refused-reply contract).
"""
import json
import sys
import threading
import time
from pathlib import Path

import graftling
from graftling import AgentControl, Caller, ExecutionEvents
from graftling.runtime import RuntimeAdapterError
from graphtraj.execution import agent_driver


class Turn:
    def __init__(self, run, refuse):
        self.session, self.execution_id, self.run, self.refuse = 'native-s', run.execution, run, refuse

    def operate(self, request):
        if request['operation'] == 'send' and self.refuse:
            self.refuse = False
            threading.Timer(0.3, lambda: self.run.events.finished('completed', last_message='first')).start()
            raise RuntimeAdapterError('runtime-input-closed', 'Claude finished accepting input for this execution.',
                                      finishing=True)
        return {}


class Driver(agent_driver.AdapterDriver):
    def __init__(self, refuse_first):
        self.refuse_first, self.turns = refuse_first, []

    def prepare(self, runtime, caller, **_):
        return {'runtime': runtime}

    def start(self, run):
        turn = Turn(run, refuse=self.refuse_first and not self.turns)
        self.turns.append(turn)
        with agent_driver._TURNS_LOCK:
            agent_driver._TURNS[run.execution] = turn
        run.events.session('native-s')


def case(root, pending):
    control = AgentControl(root, {'claude': Driver(refuse_first=True)})
    call = graftling.bind(control, Caller('gtpath546', None))
    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'first'}).document
    if pending:
        ExecutionEvents(control, created['agent'], created['execution']).request(
            {'request_token': 't1', 'method': 'claude/can_use_tool'})
    started = time.monotonic()
    sent = call({'action': 'send', 'agent': created['agent'], 'message': 'second'})
    took = time.monotonic() - started
    record = json.loads(next(Path(root).rglob(f"{created['agent']}.json")).read_text())
    print(f"case {'request pending' if pending else 'closing window'}: failed={sent.failed} took={took:.2f}s")
    print('  send result:', json.dumps(sent.document.get('result', sent.document).get('delivery', sent.document.get('error'))))
    print('  first execution receipt:', json.dumps(record['executions'][0]['inputs']))
    return sent, took, created


def main():
    root = Path(sys.argv[1])
    print('graphtraj:', agent_driver.__file__)
    print('graftling:', graftling.__file__)
    sent, took, created = case(root / 'a', pending=False)
    ok1 = (not sent.failed and sent.document['result']['delivery']['delivery'] == 'next-execution'
           and sent.document['result']['delivery']['closed_execution'] == created['execution'])
    sent, took, _ = case(root / 'b', pending=True)
    ok2 = sent.failed and sent.document['error']['code'] == 'runtime-input-closed' and took < 1
    print('CHECK closing window via AdapterDriver -> next-execution:', 'PASS' if ok1 else 'FAIL')
    print('CHECK pending request via AdapterDriver -> prompt rejected:', 'PASS' if ok2 else 'FAIL')
    return 0 if ok1 and ok2 else 1


if __name__ == '__main__':
    sys.exit(main())
