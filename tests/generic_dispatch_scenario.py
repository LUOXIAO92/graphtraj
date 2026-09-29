"""Controlled parent/child model decisions, using public tools with real ancestry."""

import json
import os
from pathlib import Path

from graphtraj.execution.runner_models import RunnerError
from graphtraj.interfaces import tools

root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
role = os.environ['GRAPHTRAJ_ROLE']
if role == 'researcher':
    visits = Path('parent-turns.txt')
    count = int(visits.read_text()) + 1 if visits.exists() else 1
    visits.write_text(str(count))
    if count in (1, 3):
        try:
            tools.launch_swarm_tool({'tasks': [{'role': 'engineer'}]}, cwd=root)
        except RunnerError as error:
            assert error.code == 'authority-denied'
        else:
            raise AssertionError('Undeclared role-tree edge was authorized')
        foreign = os.environ.get('FOREIGN_CHILD')
        if foreign:
            try:
                tools.send_session_instruction({'alias': foreign, 'instruction': 'Hijack',
                                             'caused_by_event_ids': [os.environ['CAUSE']]}, cwd=root)
            except RunnerError as error:
                assert error.code == 'authority-denied', error
            else:
                raise AssertionError('Same-role other-instance control was authorized')
        response = tools.launch_swarm_tool({'tasks': [{'role': 'analyst'}]}, cwd=root)
        assert not response.failed, response.document
        Path('last-child.json').write_text(json.dumps(response.document['tasks'][0]))
else:
    assert role == 'analyst'
    Path('child-work.txt').write_text('Formal child executed')
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Task turn done'}}))
