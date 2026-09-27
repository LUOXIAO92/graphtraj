"""Explicit recovery preserves actual Sessions and versioned task evidence."""

import json
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process
from runner_fixtures import configure_harness
from test_generic_role_execution import wait_for_idle
from test_ticket_graph import _change_status, _register, _ticket


RUNTIME = r'''
import json, os, subprocess, sys
from pathlib import Path
from graphtraj.interfaces import mcp

if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
prompt = sys.stdin.read()
root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
role = os.environ['GRAPHTRAJ_ROLE']
visits = Path('visits.txt')
count = int(visits.read_text()) + 1 if visits.exists() else 1
visits.write_text(str(count))
if count == 1:
    if os.environ['RECOVERY_CASE'] == 'provider':
        raise SystemExit(1)
    if os.environ['RECOVERY_CASE'] == 'prose':
        mcp.submit_report({'name': role + '.md', 'text': 'Decision: ACCEPT\n'}, cwd=root)
else:
    assert 'Repair the assigned result' in prompt
    report = mcp.submit_report({'name': role + '.md', 'text': 'Restored evidence'}, cwd=root).document
    Path('result.md').write_text('Corrected task result\n')
    subprocess.run(['git', 'add', 'result.md'], check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'Corrected result'], check=True, capture_output=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    mcp.submit_result({'commit': commit, 'result_refs': ['result.md'],
                       'evidence_refs': [report['report']], 'completion': 'Recovered'}, cwd=root)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Turn finished'}}))
'''


@pytest.mark.parametrize('role', ['engineer', 'researcher'])
@pytest.mark.parametrize('failure', ['provider', 'missing-report', 'prose'])
def test_explicit_retry_preserves_session_without_automatic_report_gates(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: str,
    failure: str,
) -> None:
    """Failure or report prose never accepts work or automatically resumes a role."""
    root, _, _, env = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {role: {'runtime': 'codex', 'model': 'selected'}}, 'role_tree': {role: {}},
    }))
    _register(installed_commands, root, _ticket('169', 'explicit-recovery'))
    _change_status(installed_commands, root, '169', 'ready')
    env['RECOVERY_CASE'] = failure
    fake_codex.executable.write_text(app_server_peer('#!' + sys.executable + '\n' + RUNTIME,
                                                    "os.environ['GRAPHTRAJ_PARENT_ALIAS']"))
    launch = root / 'launch.yml'
    launch.write_text(yaml.safe_dump({'tasks': [{'role': role, 'ticket_id': '169'}]}))
    result = run_process([str(installed_commands.runner), '--swarm-input', str(launch)],
                         cwd=root, env=env, timeout=30)
    assert result.returncode == (1 if failure == 'provider' else 0), result.stdout + result.stderr
    mapping_path = next((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))
    task = yaml.safe_load(mapping_path.read_text())
    alias = task['alias']
    directory = root / '.graphtraj/runner/sessions' / alias
    for _ in range(100):
        result = run_process([str(installed_commands.runner), 'status', alias], cwd=root, env=env)
        observed = yaml.safe_load(result.stdout)['aliases'][0]
        if observed['activity'] == 'idle':
            break
        time.sleep(.05)
    assert observed['activity'] == 'idle'
    assert observed['last_outcome'] == ('runtime-error' if failure == 'provider' else 'completed')
    original = yaml.safe_load((directory / 'mapping.yml').read_text())
    trace = Path(original['trace_file']).read_bytes()
    worktree = Path(task['worktree_path'])
    assert (worktree / 'visits.txt').read_text() == '1'
    ticket = root / '.graphtraj/state/tickets/169-explicit-recovery'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'implementing' and state['current_candidate'] is None
    history = [json.loads(line) for shard in sorted((root / '.graphtraj/state/worldline').glob('*.jsonl'))
               for line in shard.read_text().splitlines()]
    resumed = run_process([str(installed_commands.runner), 'send', alias,
                           '--instruction', 'Repair the assigned result',
                           '--caused-by-event-id', history[-1]['event_id']],
                          cwd=root, env=env, timeout=30)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    current = wait_for_idle(installed_commands, root, env, alias)
    assert current['session'] == original['session']
    assert current['execution_id'] != original['execution_id']
    assert Path(original['trace_file']).read_bytes().startswith(trace)
    assert (worktree / 'visits.txt').read_text() == '2'
    reports = run_process([str(installed_commands.runner), 'reports', alias], cwd=root, env=env)
    delivered = yaml.safe_load(reports.stdout)
    assert len(delivered['submissions']) == 1
    submission = delivered['submissions'][0]
    assert submission['candidate'] == run_process(['git', 'rev-parse', 'HEAD'], cwd=worktree).stdout.strip()
    assert (root / submission['evidence_refs'][0]).read_text() == 'Restored evidence'
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert [member['session_ref'] for member in team['members'].values()] == [alias]
    after = [json.loads(line) for shard in sorted((root / '.graphtraj/state/worldline').glob('*.jsonl'))
             for line in shard.read_text().splitlines()]
    assert after[:len(history)] == history
