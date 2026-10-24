"""Controlled parent/child model decisions, using public tools with real ancestry."""

import json
import os
import sys
from pathlib import Path

from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import tools
from graphtraj.interfaces.agents import run_agents_feature

root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
role = os.environ['GRAPHTRAJ_ROLE']
instruction = sys.stdin.read()
try:
    notice = json.loads(instruction)
except ValueError:
    notice = None
is_notice = (instruction.startswith('Direct child execution results:')
             or isinstance(notice, dict) and notice.get('source') == 'graphtraj')
if role == 'researcher':
    if instruction.startswith('Direct child execution results:'):
        summaries = Path('parent-batch-summaries.txt')
        summaries.write_text(str(int(summaries.read_text()) + 1 if summaries.exists() else 1))
    visits = Path('parent-turns.txt')
    count = int(visits.read_text()) + 1 if visits.exists() else 1
    visits.write_text(str(count))
    # A child completion and its Batch summary are separate delivery facts.
    # Model work dispatches on an instruction, never merely on its turn number.
    if not is_notice:
        dispatches = Path('parent-dispatches.txt')
        dispatches.write_text(str(int(dispatches.read_text()) + 1 if dispatches.exists() else 1))
        try:
            tools.launch_swarm_tool({'tasks': [{'role': 'engineer'}]}, cwd=root)
        except RunnerError as error:
            assert error.code == 'authority-denied'
        else:
            raise AssertionError('Undeclared role-tree edge was authorized')
        foreign = os.environ.get('FOREIGN_CHILD')
        if foreign:
            result = run_agents_feature({
                'action': 'send', 'agent': foreign, 'message': 'Hijack',
            }, cwd=root)
            assert result.failed and result.document['error']['code'] == 'authority-denied', result.document
        response = tools.launch_swarm_tool({'tasks': [{'role': 'analyst'}]}, cwd=root)
        assert not response.failed, response.document
        Path('last-child.json').write_text(json.dumps(response.document['tasks'][0]))
else:
    assert role == 'analyst'
    Path('child-work.txt').write_text('Formal child executed')
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Task turn done'}}))
