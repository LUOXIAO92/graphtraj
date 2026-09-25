"""Deterministic model work behind the real Runner/native stdio boundary."""

import json
import os
import subprocess
from pathlib import Path

import yaml

from graphtraj.interfaces import mcp
from graphtraj.execution.runner_models import RunnerError


root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
alias = os.environ['GRAPHTRAJ_PARENT_ALIAS']
worktree = Path.cwd()
# The test Runtime observes the binding at turn/start; model work uses only
# assigned artifacts and public Runner tools, without fabricating a caller.
report = next(part for part in os.environ['AUTHOR_REPORTS'].split(',') if part)
visits = worktree / 'visits.txt'
count = int(visits.read_text()) + 1 if visits.exists() else 1
visits.write_text(str(count))
(worktree / 'result.md').write_text('# Research\nEvidence from the assigned task.\n')
(worktree / 'result.tex').write_text(r'\documentclass{article}\begin{document}Result\end{document}' + '\n')
for args in (['git', 'add', 'result.md', 'result.tex', 'visits.txt'],
             ['git', 'commit', '-m', 'Deliver task documents']):
    subprocess.run(args, check=True, capture_output=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
owned = mcp.submit_report({'name': report, 'text': 'Candidate: ' + commit}, cwd=root).document
try:
    mcp.submit_report({'name': 'foreign.md', 'text': 'forbidden'}, cwd=root)
except RunnerError as error:
    assert error.code == 'authority-denied'
else:
    raise AssertionError('Foreign report write was authorized')
submitted = mcp.submit_result({'commit': commit, 'result_refs': ['result.md', 'result.tex'],
                              'evidence_refs': [owned['report']], 'completion': 'Research delivered'},
                             cwd=root).document
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message',
                                                  'text': json.dumps(submitted)}}))
