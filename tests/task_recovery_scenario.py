"""Controlled model work using only assigned files and public report/result tools."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from graphtraj.interfaces import mcp

if sys.argv[1:3] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)

prompt = sys.stdin.read()
root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
role = os.environ['GRAPHTRAJ_ROLE']
alias = os.environ['GRAPHTRAJ_PARENT_ALIAS']
entity = alias.partition('@')[2]
stem = 'leader' if role == 'team-leader' else role
if entity != role.replace('-', '_'):
    assert 'Retained work by ' in prompt
    stem += '-' + entity
owned = mcp.submit_report({'name': stem + '.md', 'text': 'Retained work by ' + alias}, cwd=root).document
if os.environ.get('RECOVERY_CHILD') and role == 'researcher':
    child = Path('child.json')
    if not child.exists():
        response = mcp.launch_swarm_tool({'tasks': [{'role': 'analyst'}]}, cwd=root)
        child.write_text(json.dumps(response.document['tasks'][0]))
        print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Child registered'}}))
        raise SystemExit(0)
    if entity != role.replace('-', '_'):
        from graphtraj.execution.runner_models import RunnerError
        shard = next((root / '.graphtraj/state/worldline').glob('*.jsonl'))
        cause = json.loads(shard.read_text().splitlines()[0])['event_id']
        try:
            mcp.send_session_instruction({'alias': json.loads(child.read_text())['alias'],
                                         'instruction': 'Old child remains with its original parent',
                                         'caused_by_event_ids': [cause]}, cwd=root)
        except RunnerError as error:
            assert error.code == 'authority-denied'
        else:
            raise AssertionError('Replacement acquired another Session children')
Path(os.environ['RECOVERY_STARTED']).touch()
while not Path(os.environ['RECOVERY_RELEASE']).exists():
    time.sleep(.02)
Path('result.md').write_text('# Research\nRecovered by ' + alias + '\n')
subprocess.run(['git', 'add', 'result.md'], check=True, capture_output=True)
subprocess.run(['git', 'commit', '--allow-empty', '-m', 'Recovered result'], check=True, capture_output=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
submitted = mcp.submit_result({
    'commit': commit, 'result_refs': ['result.md'], 'evidence_refs': [owned['report']],
    'completion': 'Recovered result',
}, cwd=root).document
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(submitted)}}))
