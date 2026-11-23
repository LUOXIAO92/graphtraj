"""REHEARSAL ONLY (Engineer sandbox, no model, no login): stand in for the real probe Engineer of realhost.

    python -I rehearse_session.py <project> <home>     (the install venv's python; <project> = VERIFY588_ROOT
                                                        after `realhost` with VERIFY588_DRY=1; <home> = VERIFY588_HOME)

As the repository tests do (tests/test_result_submission.py result_project), it starts Task 1's Team through
GraphTraj's own delivery-state operation and writes the member's Runner mapping. Then, as that Session, it makes
the probe's three submit_report calls through runner_control.submit_session_report (the shared operation the tasks
tool uses), and records what a Claude host would leave: a transcript of those calls with their real results under
<home>/.claude/projects/ and a terminal execution.yml. It prints the alias for `steps.zsh check <alias>`.
Never used by Main.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.execution import runner_control
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_state import apply_delivery_state_request
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.workspace.runner_project import discover_runner_directory

ALIAS = '1-submit_report_name_probe-handover9-engineer@engineer'   # Runner's alias form (runner_status.ALIAS)
CALLS = [('engineer.md', 'probe bare'), ('.state/teams/1/rounds/1/validation.md', 'probe path'),
         ('engineer-budget', 'probe refused')]


def main(project: Path, home: Path) -> int:
    state = load_project_configuration(project).state
    runner = Path(discover_runner_directory(project))
    worktree = project / '.graphtraj/probe-588/worktree'
    if not (worktree / '.git').exists():
        worktree.mkdir(parents=True)
        for args in [('init', '-q'), ('-c', 'user.name=588', '-c', 'user.email=588@invalid', 'commit', '-q',
                                      '--allow-empty', '-m', 'probe')]:
            subprocess.run(['git', *args], cwd=worktree, check=True)
    request = {
        'phase': 'start', 'task_id': '1',
        'caused_by_event_ids': [read_worldline(state, project)[-1]['event_id']],
        'evidence_refs': ['.graphtraj/probe-588/evidence.md'],
        'worktree': str(worktree.relative_to(project)), 'branch': 'agent/1-submit-report-name-probe',
        'members': {'engineer': {'role': 'engineer', 'session_ref': ALIAS}},
    }
    apply_delivery_state_request(state, project, request, request)
    directory = runner / 'sessions' / ALIAS
    directory.mkdir(parents=True)
    session, execution = f'rehearsal-{uuid.uuid4()}', uuid.uuid4().hex
    (directory / 'mapping.yml').write_text(yaml.safe_dump({
        'alias': ALIAS, 'runtime': 'claude', 'session': session, 'task_id': '1', 'team_generation': 1,
        'role': 'engineer', 'role_reference': 'opus_coding_team.engineer', 'parent': None,
        'retained_batch_file': 'batch.yml', 'worktree_path': str(worktree), 'trace_file': 'events.jsonl',
        'worker_pid': 1, 'runtime_pid': 1, 'execution_id': execution,
        'report_files': ['.state/teams/1/rounds/1/engineer.md', '.state/teams/1/rounds/1/validation.md'],
    }))
    records, lines = [], []
    with runtime_caller(runner, ALIAS):
        for index, (name, text) in enumerate(CALLS, 1):
            try:
                result = runner_control.submit_session_report(name, text, project)
            except RunnerError as error:
                result = {'error': {'code': error.code, 'message': error.message}}
            identifier = f'toolu_rehearsal_{index}'
            arguments = {'action': 'execute', 'feature': 'submit_report',
                         'arguments': {'name': name, 'text': text, 'notify_parent': False}}
            records.append({'type': 'assistant', 'sessionId': session, 'message': {'content': [
                {'type': 'tool_use', 'id': identifier, 'name': 'mcp__graphtraj__tasks', 'input': arguments}]}})
            records.append({'type': 'user', 'sessionId': session, 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': identifier,
                 'content': [{'type': 'text', 'text': json.dumps(result)}]}]}})
            lines.append(f'RESULT{index}: {json.dumps(result)}')
    transcript = home / '.claude/projects/rehearsal-588' / f'{session}.jsonl'
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(''.join(json.dumps(record) + '\n' for record in records))
    (directory / 'execution.yml').write_text(yaml.safe_dump({
        'outcome': 'completed', 'execution_id': execution, 'session_id': session, 'terminal_confirmed': True,
        'last_agent_message': '\n'.join(lines)}))
    print('\n'.join(lines))
    print(f'stand-in transcript: {transcript}')
    print(f'alias: {ALIAS}')
    return 0


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
