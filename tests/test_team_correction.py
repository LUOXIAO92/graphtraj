from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from conftest import app_server_peer, run_process
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket


RUNTIME = r'''
import json, os, subprocess, sys
from pathlib import Path

if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)

role = os.environ['GRAPHTRAJ_ROLE']
prompt = sys.stdin.read()
root = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
round_dir = root / 'teams/1/rounds/1'
scratch = Path.cwd() / '.scratch'
session = 'session-' + role
resumed = 'resume' in sys.argv
if resumed:
    assert session in sys.argv
with Path(os.environ['CORRECTION_LOG']).open('a') as log:
    log.write(json.dumps(dict(role=role, resumed=resumed, prompt=prompt)) + '\n')
print(json.dumps({'type': 'thread.started', 'thread_id': session}), flush=True)

def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout.strip()

def dispatch(roles):
    batch = scratch / 'children.yml'
    batch.write_text(json.dumps({'tasks': [dict(ticket_id='76', ticket_name='session-alias-control', role='coding-team.' + r if isinstance(r, str) else r) for r in roles]}))
    result = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(batch)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

if role == 'delivery-state':
    Path(os.environ['GRAPHTRAJ_STATE_REQUEST']).write_text(os.environ['GRAPHTRAJ_STATE_FACTS'])
elif role == 'team-leader':
    if not (round_dir / 'engineer.md').exists():
        dispatch(['engineer-junior'])
    else:
        reviewed = (round_dir / 'spec.md').exists()
        expanded = (Path.cwd() / 'UNREQUESTED.txt').exists()
        if expanded and reviewed and os.environ.get('CORRECTION_SERIAL') and not (scratch / 'specialist-done').exists():
            dispatch([{'investigation-specialist': {'runtime': 'codex', 'model': 'gpt-5.6-luna'}}])
            decision = None
        elif expanded and (reviewed or os.environ['CORRECTION_TIMING'] == 'before-review'):
            decision = 'Decision: CORRECT\nResponsible: coding-team.engineer-junior\nRule: Accepted Ticket limits work to Session transport.\nReason: UNREQUESTED.txt adds an unrelated feature.\n'
        elif not reviewed:
            if os.environ.get('CORRECTION_SERIAL'):
                dispatch(['spec-reviewer'] if (round_dir / 'standards.md').exists() else ['standards-reviewer'])
            else:
                dispatch(['standards-reviewer', 'spec-reviewer'])
            decision = None
        elif 'Unsupported finding' in (round_dir / 'spec.md').read_text():
            decision = 'Decision: CORRECT\nResponsible: coding-team.spec-reviewer\nRule: Findings must cite an accepted requirement and observable failure.\nReason: The report demands an unrequested cache without a requirement.\n'
        else:
            decision = 'Decision: ACCEPT\n'
        if decision:
            (round_dir / 'leader.md').write_text(decision + 'Candidate commit: ' + git('rev-parse', 'HEAD') + '\n')
elif role == 'investigation-specialist':
    (scratch / 'specialist-done').touch()
elif role.startswith('engineer-'):
    extra = Path.cwd() / 'UNREQUESTED.txt'
    if not resumed:
        extra.write_text('Unrequested feature\n')
        git('add', extra.name)
        git('commit', '-m', 'Expanded candidate')
    else:
        assert 'UNREQUESTED.txt' in prompt and 'Reflect' in prompt
        git('rm', extra.name)
        git('commit', '-m', 'Remove scope expansion')
    candidate = git('rev-parse', 'HEAD')
    (round_dir / 'engineer.md').write_text('Candidate commit: ' + candidate + '\nSelf-review: ' + ('corrected' if resumed else 'Unrequested feature') + '\n')
    (round_dir / 'validation.md').write_text('Candidate commit: ' + candidate + '\nTests: passed.\n')
else:
    report = Path(os.environ['GRAPHTRAJ_REVIEW_REPORT'])
    candidate = git('rev-parse', 'HEAD')
    assert candidate in prompt and os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] in prompt
    corrected = role == 'spec-reviewer' and 'unrequested cache' in prompt
    text = 'Unsupported finding: add an unrequested cache.' if role == 'spec-reviewer' and not corrected else 'Decision: pass.'
    report.write_text('Candidate commit: ' + candidate + '\n' + text + '\n')
print(json.dumps({'type': 'turn.completed'}), flush=True)
'''
RUNTIME = app_server_peer(RUNTIME, "'session-' + os.environ['GRAPHTRAJ_ROLE']")



@pytest.mark.parametrize(('timing', 'serial'), [('before-review', False), ('after-review', False), ('after-review', True)])
def test_installed_team_corrects_engineer_and_reviewer_in_same_round(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, timing, serial
):
    harness, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    if serial:
        config_file = harness / '.graphtraj/config.yml'
        config = yaml.safe_load(config_file.read_text())
        config['agent_runner']['max_concurrency'] = 1
        config_file.write_text(yaml.safe_dump(config))
        environment['CORRECTION_SERIAL'] = '1'
    log = tmp_path / 'corrections.jsonl'
    batch = harness / 'batch.yml'
    batch.write_text('tasks:\n  - ticket_id: "76"\n    ticket_name: session-alias-control\n    role: coding-team.team-leader\n')
    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)], cwd=harness,
        env={**environment, 'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
             'CORRECTION_LOG': str(log), 'CORRECTION_TIMING': timing}, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    assert team['current_round'] == 1
    assert team['members']['engineer']['role'] == 'engineer-junior'
    assert [p.name for p in (ticket / 'teams/1/rounds').iterdir()] == ['1']
    reports = list((ticket / 'teams/1/rounds/1').iterdir())
    assert {p.name for p in reports} == {'engineer.md', 'validation.md', 'standards.md', 'spec.md', 'leader.md'}
    assert all(state['current_candidate'] in p.read_text() for p in reports)
    assert all('Unsupported finding' not in p.read_text() and 'Unrequested feature' not in p.read_text() for p in reports)
    assert all(p.stat().st_mode & 0o222 == 0 for p in reports)
    assert not (worktrees / '76-session-alias-control/UNREQUESTED.txt').exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    for role in ('team-leader', 'engineer-junior', 'standards-reviewer', 'spec-reviewer'):
        own = [call for call in calls if call['role'] == role]
        assert not own[0]['resumed']
        assert all(call['resumed'] for call in own[1:])
    if serial:
        specialists = [c for c in calls if c['role'] == 'investigation-specialist']
        assert len(specialists) == 1
        assert all(member['role'] != 'investigation-specialist' for member in team['members'].values())
    assert len([c for c in calls if c['role'] == 'engineer-junior']) == 2
    assert len([c for c in calls if c['role'] == 'standards-reviewer']) == (2 if timing == 'after-review' else 1)
    traces = ticket / 'teams/1/traces'
    engineer = traces / team['members']['engineer']['session_ref'] / 'events.jsonl'
    reviewer = traces / team['members']['spec_reviewer']['session_ref'] / 'events.jsonl'
    assert 'Unrequested feature' in engineer.read_text()
    assert 'Unsupported finding' in reviewer.read_text()
    events = [json.loads(line) for p in (harness / '.graphtraj/state/worldline').glob('*.jsonl') for line in p.read_text().splitlines()]
    corrections = [e for e in events if e['kind'] == 'team-process-correction']
    assert [e['responsible_role'] for e in corrections] == ['engineer-junior', 'spec-reviewer']
    assert all(e['action'] == 'resume-session-for-correction' and e['team_round'] == 1 for e in corrections)
    assert all(e['caused_by_event_ids'] and e['evidence_refs'] for e in corrections)
    assert all('traces/' in ref for e in corrections for ref in e['evidence_refs'])
    assert not any(e['kind'] == 'team-round-rejected' for e in events)
    candidates = [e for e in events if e['kind'] == 'candidate-ready-for-review']
    assert len({e['candidate'] for e in candidates}) == 2
    for event in candidates:
        assert all('traces/' in ref for ref in event['evidence_refs'])
        assert all(event['candidate'] in (harness / ref).read_text() for ref in event['evidence_refs'])
    for event in corrections:
        assert any(event['event_id'] in c['prompt'] for c in calls if c['role'] == event['responsible_role'])
