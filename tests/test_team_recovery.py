from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, app_server_peer, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket


RUNTIME = r'''
import json, os, subprocess, sys, yaml
from pathlib import Path

if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)

role = os.environ['GRAPHTRAJ_ROLE']
prompt = sys.stdin.read()
resumed = 'resume' in sys.argv
if resumed and 'Recovery required:' in prompt:
    (Path.cwd() / '.scratch' / ('recovery-prompt-' + role)).write_text(prompt)
evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
round_dir = evidence / 'teams/1/rounds' / os.environ['GRAPHTRAJ_TEAM_ROUND']
round_dir.mkdir(parents=True, exist_ok=True)
print(json.dumps({'type': 'thread.started', 'thread_id': 'recovery-' + role}), flush=True)

def native_command_failure(output):
    session = 'recovery-' + role
    rollout = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'sessions/fake' / ('rollout-' + session + '.jsonl')
    rollout.parent.mkdir(parents=True, exist_ok=True)
    with rollout.open('a') as stream:
        if rollout.stat().st_size == 0:
            stream.write(json.dumps({'timestamp': 'fake-native-start', 'type': 'session_meta', 'payload': {'id': session}}) + '\n')
        stream.write(json.dumps({'timestamp': 'fake-native-failure', 'type': 'event_msg', 'payload': {
            'type': 'item_completed',
            'item': {'type': 'CommandExecution', 'aggregated_output': output,
                     'exit_code': 1, 'status': 'failed'},
        }}) + '\n')

def git(*arguments):
    return subprocess.run(['git', *arguments], check=True, text=True, capture_output=True).stdout.strip()

def dispatch(roles):
    batch = Path.cwd() / '.scratch' / 'children.yml'
    bad_skill = (
        target == 'startup-preflight'
        and 'Register the corrected Engineer child Batch.' not in prompt
    )
    batch.write_text(yaml.safe_dump({'tasks': [
        {
            'ticket_id': '76',
            'ticket_name': 'session-alias-control',
            'role': 'coding-team.' + child,
            **({'skills': ['ponytail']} if bad_skill and child.startswith('engineer-') else {}),
        }
        for child in roles
    ]}, sort_keys=False))
    result = subprocess.run(
        [os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(batch)],
        check=False, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

target = os.environ.get('RECOVERY_TARGET', '')
message = prompt
if role == 'delivery-state':
    facts = json.loads(os.environ['GRAPHTRAJ_STATE_FACTS'])
    pending = Path.cwd() / '.scratch' / 'pending-member-failed'
    if (
        target == 'pending-member'
        and facts.get('phase') == 'member'
        and facts.get('member') == 'spec_reviewer'
        and not pending.exists()
    ):
        pending.write_text('failed\n')
        raise SystemExit(1)
    if target == 'delivery-state' and not resumed:
        Path(os.environ['GRAPHTRAJ_STATE_REQUEST']).write_text('{}')
    else:
        Path(os.environ['GRAPHTRAJ_STATE_REQUEST']).write_text(os.environ['GRAPHTRAJ_STATE_FACTS'])
elif (
    role == 'team-leader'
    and os.environ.get('RECOVERY_NATIVE') == '1'
    and (round_dir / 'spec.md').is_file()
    and not (Path.cwd() / '.scratch/retained-review-failed').exists()
):
    # Simulate loss of the current report copy after its real author completed.
    (round_dir / 'spec.md').unlink()
    (Path.cwd() / '.scratch/retained-review-failed').touch()
    raise SystemExit(1)
elif role == 'team-leader':
    if not (round_dir / 'engineer.md').exists():
        if target != 'dispatch' or 'Recovery required:' in prompt:
            dispatch(['engineer-junior'])
    elif target == 'retained-review' and (
        'Recover the missing Spec report.' in prompt
        or 'Register the remaining Spec Batch.' in prompt
        or (round_dir / 'spec.md').is_file()
        or (Path.cwd() / '.scratch/retained-review-failed').exists()
    ):
        if 'Register the remaining Spec Batch.' in prompt:
            dispatch(['spec-reviewer'])
        elif (Path.cwd() / '.scratch/retained-review-failed').exists() and (round_dir / 'spec.md').is_file():
            (round_dir / 'leader.md').write_text('Decision: ACCEPT\nCandidate commit: ' + git('rev-parse', 'HEAD') + '\n')
        else:
            (round_dir / 'leader.md').write_text(
                'Decision: CORRECT\nResponsible: coding-team.spec-reviewer\n'
                'Rule: Review report fields\nReason: Deliver the missing Spec report with its Comparison and Axis.\n'
                'Candidate commit: ' + git('rev-parse', 'HEAD') + '\n'
            )
    elif target == 'provider-before-review-correct':
        corrected = Path.cwd() / '.scratch' / 'provider-before-review-correct-written'
        if not corrected.exists():
            corrected.write_text('corrected\n')
            (round_dir / 'leader.md').write_text(
                'Decision: CORRECT\nResponsible: coding-team.engineer-junior\n'
                'Rule: accepted Ticket\nReason: correct the current Engineer work.\n'
                'Candidate commit: ' + git('rev-parse', 'HEAD') + '\n'
            )
        elif (round_dir / 'leader.md').exists():
            pass
        elif not (round_dir / 'standards.md').exists() or not (round_dir / 'spec.md').exists():
            dispatch(['standards-reviewer', 'spec-reviewer'])
        else:
            candidate = git('rev-parse', 'HEAD')
            (round_dir / 'leader.md').write_text('Decision: ACCEPT\nCandidate commit: ' + candidate + '\n')
    elif not (round_dir / 'standards.md').exists() or not (round_dir / 'spec.md').exists():
        dispatch(['standards-reviewer', 'spec-reviewer'])
    elif target == 'team-leader' and 'Recovery required:' not in prompt:
        pass
    else:
        candidate = git('rev-parse', 'HEAD')
        corrected = Path.cwd() / '.scratch' / 'provider-correct-written'
        if target == 'provider-correct' and not corrected.exists():
            corrected.write_text('corrected\n')
            (round_dir / 'leader.md').write_text(
                'Decision: CORRECT\nResponsible: coding-team.spec-reviewer\n'
                'Rule: accepted Ticket\nReason: repeat the current Spec review.\n'
                'Candidate commit: ' + candidate + '\n'
            )
        elif target in {'provider-rework', 'provider-rework-evidence', 'replacement-rework', 'state-invalid-report'} and round_dir.name == '1':
            (round_dir / 'leader.md').write_text(
                'Decision: REJECT\nDiagnosis: implementation\nReviews: compliant\n'
                'Action: rework\nRationale: bounded correction.\n'
                'Candidate commit: ' + candidate + '\n'
            )
        else:
            (round_dir / 'leader.md').write_text('Decision: ACCEPT\nCandidate commit: ' + candidate + '\n')
elif role.startswith('engineer-'):
    if target in {'provider', 'provider-engineer-evidence', 'provider-review-evidence', 'provider-before-review-correct', 'provider-correct', 'provider-quoted', 'provider-rework', 'provider-rework-evidence'} and not resumed:
        if target == 'provider-quoted':
            print(json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution',
                'aggregated_output': 'source says Permission denied',
                'exit_code': 0,
                'status': 'completed',
            }}), flush=True)
            print(json.dumps({'type': 'item.completed', 'item': {
                'type': 'agent_message',
                'text': 'the Agent quoted Permission denied',
            }}), flush=True)
        raise SystemExit(1)
    replacement_failure = Path.cwd() / '.scratch' / 'provider-replace-failed'
    if target == 'provider-replace' and not replacement_failure.exists():
        replacement_failure.write_text('failed\n')
        raise SystemExit(1)
    if target == 'access' and not resumed:
        sys.stderr.write('Permission denied by Runtime filesystem sandbox\n')
        raise SystemExit(1)
    missing_report = target == 'completed-wrong-target' and not resumed
    missing_validation = False
    if target == 'provider-rework-evidence' and round_dir.name == '2':
        missing = Path.cwd() / '.scratch' / 'provider-rework-validation-missing'
        if not missing.exists():
            missing.write_text('missing\n')
            missing_validation = True
    if missing_report:
        print(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution',
            'aggregated_output': (
                'Blocked path target: requested=.state/teams/1/rounds/1; '
                'resolved=' + str(round_dir) + '; '
                'condition=the report target is not authorized for this role'
            ),
            'exit_code': 1,
            'status': 'failed',
        }}), flush=True)
    delivered = Path.cwd() / 'RECOVERY_DELIVERED.txt'
    if not delivered.exists():
        delivered.write_text('delivered\n')
        subprocess.run(['git', 'add', delivered.name], check=True)
        subprocess.run(['git', 'commit', '-m', 'Deliver recovery candidate'], check=True)
    if target == 'uncommitted':
        if resumed:
            subprocess.run(['git', 'add', delivered.name], check=True)
            subprocess.run(['git', 'commit', '-m', 'Commit recovery change'], check=True)
        else:
            delivered.write_text('uncommitted\n')
    candidate = git('rev-parse', 'HEAD')
    if not missing_report:
        (round_dir / 'engineer.md').write_text('Candidate commit: ' + candidate + '\nSelf-review: complete.\n')
        validation = round_dir / 'validation.md'
        if missing_validation:
            pass
        elif target == 'provider-engineer-evidence' and 'Recovery required:' not in prompt:
            validation.write_text('Candidate commit: invalid\n')
        elif target == 'engineer-junior' and not resumed:
            validation.write_text('Candidate commit: invalid\n')
        else:
            validation.write_text('Candidate commit: ' + candidate + '\nTests: passed.\n')
else:
    failed_review = Path.cwd() / '.scratch/retained-review-failed'
    if target == 'retained-review' and role == 'spec-reviewer' and resumed and not failed_review.exists():
        failed_review.touch()
        raise SystemExit(0 if os.environ.get('RECOVERY_FAILURE') == 'report' else 1)
    if target == 'provider-review' and role == 'spec-reviewer' and not resumed:
        raise SystemExit(1)
    if (
        target in {'replacement-review', 'replacement-rework'}
        and role == 'spec-reviewer'
        and not Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).name.endswith('-replacement.md')
    ):
        raise SystemExit(1)
    if target == 'completed-access' and role == 'spec-reviewer':
        native_command_failure(
            'Blocked path target: requested=.state/reviews/spec.md; '
            'resolved=' + os.environ['GRAPHTRAJ_REVIEW_REPORT'] + '; '
            'condition=the report target is not authorized for this role'
        )
        print(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution',
            'aggregated_output': (
                'Blocked path target: requested=.state/reviews/spec.md; '
                'resolved=' + os.environ['GRAPHTRAJ_REVIEW_REPORT'] + '; '
                'condition=the report target is not authorized for this role'
            ),
            'exit_code': 1,
            'status': 'failed',
        }}), flush=True)
    elif target == 'completed-native-root' and role == 'spec-reviewer':
        sys.stderr.write(
            'Native startup failed: symlinked writable roots are not supported\n'
        )
    elif (
        target == 'completed-parse'
        and role == 'spec-reviewer'
        and not resumed
    ):
        native_command_failure('Cannot verify option: --glob')
        print(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution',
            'aggregated_output': 'Cannot verify option: --glob',
            'exit_code': 1,
            'status': 'failed',
        }}), flush=True)
    elif (target == role or target == 'provider-review-evidence' and role == 'spec-reviewer') and not resumed:
        pass
    else:
        candidate = git('rev-parse', 'HEAD')
        if target in {'replacement-review', 'replacement-rework'} and role == 'spec-reviewer':
            (Path.cwd() / '.scratch' / 'replacement-review-target').write_text(
                os.environ['GRAPHTRAJ_REVIEW_REPORT']
            )
        if target in {'provider-rework', 'provider-rework-evidence', 'replacement-rework', 'state-invalid-report'} and round_dir.name == '1':
            axis = 'Standards' if role == 'standards-reviewer' else 'Spec'
            if target == 'provider-rework' and role == 'standards-reviewer':
                Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
                    'Candidate commit: ' + candidate + '\n'
                    'Comparison: ' + os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] + '\n'
                    'Axis: Standards\nFinding: none\n'
                    'Explanation: an earlier Finding: implementation was not attributable.\n'
                )
                raise SystemExit(0)
            evidence_line = (
                ''
                if target == 'state-invalid-report' and role == 'standards-reviewer'
                else 'Evidence: retained report\\n'
            )
            Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
                'Candidate commit: ' + candidate + '\n'
                'Comparison: ' + os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] + '\n'
                'Axis: ' + axis + '\n'
                'Finding: implementation\nRule: accepted Ticket\nInput: recovered Team\n'
                'Trace: retained Session\nFailure: correction required\n'
                + evidence_line
            )
        else:
            Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
                'Candidate commit: ' + candidate + '\nFinding: none\n'
            )

print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}}), flush=True)
print(json.dumps({'type': 'turn.completed'}), flush=True)
'''
RUNTIME = app_server_peer(RUNTIME, "'recovery-' + os.environ['GRAPHTRAJ_ROLE']")



@pytest.mark.parametrize('target', ('engineer-junior', 'spec-reviewer', 'team-leader', 'uncommitted', 'delivery-state', 'dispatch', 'completed-wrong-target'))
def test_installed_team_corrects_missing_member_evidence_in_its_existing_session(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, target,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )

    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env={
            **environment,
            'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
            'RECOVERY_TARGET': target,
        },
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    if target == 'delivery-state':
        trace = next((ticket / 'teams/1/traces').glob('*@d*/events.jsonl'))
    else:
        seat = {
            'engineer-junior': 'engineer',
            'uncommitted': 'engineer',
            'spec-reviewer': 'spec_reviewer',
            'team-leader': 'team_leader',
            'dispatch': 'team_leader',
            'completed-wrong-target': 'engineer',
        }[target]
        trace = ticket / 'teams/1/traces' / team['members'][seat]['session_ref'] / 'events.jsonl'
    recovered = trace.read_text()
    assert recovered.count('turn_context') >= 2
    recovery_role = {
        'uncommitted': 'engineer-junior',
        'dispatch': 'team-leader',
        'completed-wrong-target': 'engineer-junior',
    }.get(target, target)
    prompt = (harness / state['worktree'] / '.scratch' / ('recovery-prompt-' + recovery_role)).read_text()
    assert 'Recovery required:' in prompt
    assert 'Failure:' in prompt
    assert 'Evidence:' in prompt
    assert 'Expected result:' in prompt
    if target == 'completed-wrong-target':
        assert '.state/teams/1/rounds/1/engineer.md' in prompt
        assert '.state/teams/1/rounds/1/validation.md' in prompt
    if target == 'uncommitted':
        assert 'Tracked project changes must be committed' in prompt
        status = run_process(['git', 'status', '--short'], cwd=harness / state['worktree'])
        assert status.returncode == 0
        assert not status.stdout

    assert state['status'] == 'awaiting-integration'
    reports = ticket / 'teams/1/rounds/1'
    assert {path.name for path in reports.iterdir()} == {
        'engineer.md', 'validation.md', 'standards.md', 'spec.md', 'leader.md',
    }
    assert all(state['current_candidate'] in path.read_text() for path in reports.iterdir())


@pytest.mark.parametrize(
    ('target', 'round_ordinal'),
    (
        ('provider', 1),
        ('provider-engineer-evidence', 1),
        ('provider-review-evidence', 1),
        ('provider-before-review-correct', 1),
        ('provider-correct', 1),
        ('provider-quoted', 1),
        ('provider-rework', 2),
        ('provider-rework-evidence', 2),
    ),
)
def test_provider_failure_returns_to_the_caller_for_an_explicit_same_session_retry(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
    target, round_ordinal,
):
    harness, _, integration, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    launch_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': target,
    }

    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )

    assert failed.returncode == 1
    error = yaml.safe_load(failed.stdout)['tasks'][0]['error']
    assert error['code'] == 'launch-failed'
    assert 'caller or superior' in error['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'implementing'
    mapping_file = next(
        path
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'engineer-junior'
    )
    mapping = yaml.safe_load(mapping_file.read_text())
    trace = ticket / 'teams/1/traces' / mapping['alias'] / 'events.jsonl'
    assert trace.is_file()
    assert 'Recovery required:' not in trace.read_text()
    identities = [
        json.loads(line)['payload']['id']
        for line in trace.read_text().splitlines()
        if json.loads(line).get('type') == 'session_meta'
    ]
    assert identities == [mapping['session']]
    events = [
        json.loads(line)
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ]
    (integration / 'other-ticket-in-progress.txt').write_text(
        'temporary work from another Ticket\n'
    )
    retried = run_process(
        [
            str(installed_commands.runner), 'send', mapping['alias'],
            '--instruction', 'Retry the interrupted current Team step.',
            '--caused-by-event-id', events[-1]['event_id'],
        ],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )

    diagnostics = retried.stdout + retried.stderr + (mapping_file.parent / 'worker-stderr.log').read_text()
    error_file = mapping_file.parent / 'resume-error.yml'
    if error_file.exists():
        diagnostics += error_file.read_text()
    assert retried.returncode == 0, diagnostics
    wait_for_file(mapping_file.parent / 'execution.yml')
    assert trace.read_text().count('turn_context') == 2
    reports = ticket / 'teams/1/rounds/1'
    assert (reports / 'engineer.md').is_file()
    assert (reports / 'validation.md').is_file()
    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )
    assert continued.returncode == 0, continued.stdout + continued.stderr
    current = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert current['status'] == 'awaiting-integration'
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert team['current_round'] == round_ordinal
    if target in {'provider-before-review-correct', 'provider-correct'}:
        events = [
            json.loads(line)
            for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
            for line in path.read_text().splitlines()
        ]
        assert any(event['kind'] == 'team-process-correction' for event in events)
    if target == 'provider-before-review-correct':
        assert trace.read_text().count('turn_context') == 3
    if target == 'provider-rework-evidence':
        assert trace.read_text().count('turn_context') == 4
        prompt = (
            harness / current['worktree']
            / '.scratch/recovery-prompt-engineer-junior'
        ).read_text()
        assert 'Recovery required:' in prompt
        assert 'Engineer evidence is missing or unreadable' in prompt
    if target == 'provider-engineer-evidence':
        assert trace.read_text().count('turn_context') == 3
        prompt = (
            harness / current['worktree'] / '.scratch/recovery-prompt-engineer-junior'
        ).read_text()
        assert 'Failure:' in prompt and 'Evidence:' in prompt and 'Expected result:' in prompt
    if target == 'provider-review-evidence':
        reviewer = team['members']['spec_reviewer']['session_ref']
        review_trace = ticket / 'teams/1/traces' / reviewer / 'events.jsonl'
        assert review_trace.read_text().count('turn_context') == 2
        prompt = (harness / current['worktree'] / '.scratch/recovery-prompt-spec-reviewer').read_text()
        assert 'Failure:' in prompt and 'Evidence:' in prompt and 'Expected result:' in prompt
    if target == 'provider-rework':
        state_trace = next((ticket / 'teams/1/traces').glob('*@d*/events.jsonl'))
        assert state_trace.read_text().count('turn_context') == 9


def test_preflight_failed_engineer_starts_once_from_the_leader_correction(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    runtime_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': 'startup-preflight',
    }

    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )
    assert failed.returncode == 1
    error = yaml.safe_load(failed.stdout)['tasks'][0]['error']
    assert error['code'] == 'invalid-input'
    assert 'Repository Skill ponytail was not found' in error['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    leader_alias = team['members']['team_leader']['session_ref']
    assert state['status'] == 'implementing'
    assert team['members']['engineer']['session_ref'] is None
    assert not [
        path for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'engineer-junior'
    ]
    repeated = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )
    assert repeated.returncode == 1
    repeated_error = yaml.safe_load(repeated.stdout)['tasks'][0]['error']
    assert repeated_error['code'] == 'invalid-input'
    assert 'Repository Skill ponytail was not found' in repeated_error['message']
    repeated_state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    repeated_team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert repeated_state['status'] == 'implementing'
    assert repeated_team['team_ordinal'] == 1
    assert repeated_team['members']['team_leader']['session_ref'] == leader_alias
    assert repeated_team['members']['engineer']['session_ref'] is None
    assert not [
        path for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'engineer-junior'
    ]
    events = [
        json.loads(line)
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ]

    corrected = run_process(
        [
            str(installed_commands.runner), 'send', leader_alias,
            '--instruction', 'Register the corrected Engineer child Batch.',
            '--caused-by-event-id', events[-1]['event_id'],
        ],
        cwd=harness, env=runtime_environment, timeout=45,
    )
    assert corrected.returncode == 0, corrected.stdout + corrected.stderr

    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )
    assert continued.returncode == 0, continued.stdout + continued.stderr
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    assert team['team_ordinal'] == 1
    assert team['current_round'] == 1
    assert team['members']['team_leader']['session_ref'] == leader_alias
    engineer_mapping = next(
        path for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'engineer-junior'
    )
    engineer = yaml.safe_load(engineer_mapping.read_text())
    trace = ticket / 'teams/1/traces' / engineer['alias'] / 'events.jsonl'
    assert trace.read_text().count('turn_context') == 1
    retained = [
        yaml.safe_load(path.read_text())
        for path in (harness / '.graphtraj/state/batches').glob('*.yml')
    ]
    assert any(
        task['role'] == 'coding-team.engineer-junior'
        and task.get('skills') == ['ponytail']
        for retained_batch in retained for task in retained_batch['tasks']
    )
    assert any(
        task['role'] == 'coding-team.engineer-junior'
        and 'skills' not in task
        for retained_batch in retained for task in retained_batch['tasks']
    )


def test_invalid_review_report_stops_the_matching_state_request_without_retry(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )

    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env={
            **environment,
            'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
            'RECOVERY_TARGET': 'state-invalid-report',
        },
        timeout=45,
    )

    assert result.returncode == 1
    error = yaml.safe_load(result.stdout)['tasks'][0]['error']
    assert 'Delivery State could not apply its requested state change' in error['message']
    assert 'Review report ' in error['message']
    assert '(Axis: Standards)' in error['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'reviewing'
    state_trace = next((ticket / 'teams/1/traces').glob('*@d*/events.jsonl'))
    assert state_trace.read_text().count('turn_context') == 6


def test_access_failure_returns_to_the_responsible_operator_without_agent_reflection(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env={
            **environment,
            'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
            'RECOVERY_TARGET': 'access',
        },
        timeout=45,
    )

    assert result.returncode == 1
    error = yaml.safe_load(result.stdout)['tasks'][0]['error']
    assert error['code'] == 'invalid-config'
    assert 'responsible operator' in error['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    engineer = next((ticket / 'teams/1/traces').glob('*@j*/events.jsonl'))
    assert 'Recovery required:' not in engineer.read_text()


def test_recovery_registers_a_completed_reviewer_before_finalizing(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    runtime_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': 'pending-member',
    }

    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert failed.returncode == 1
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    team_file = ticket / 'teams/1/team.yml'
    team = yaml.safe_load(team_file.read_text())
    assert (ticket / 'teams/1/rounds/1/spec.md').is_file()
    assert team['members']['spec_reviewer']['session_ref'] is None

    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert continued.returncode == 0, continued.stdout + continued.stderr
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load(team_file.read_text())
    assert state['status'] == 'awaiting-integration'
    assert team['members']['spec_reviewer']['session_ref']
    sessions = [
        yaml.safe_load(path.read_text())
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'spec-reviewer'
    ]
    assert len(sessions) == 1


def test_main_replaces_an_unregistered_failed_engineer_from_its_durable_alias(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    runtime_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': 'provider-replace',
    }

    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert failed.returncode == 1
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    team_file = ticket / 'teams/1/team.yml'
    team = yaml.safe_load(team_file.read_text())
    mapping_file = next(
        path
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'engineer-junior'
    )
    mapping = yaml.safe_load(mapping_file.read_text())
    alias = mapping['alias']
    trace = ticket / 'teams/1/traces' / alias / 'events.jsonl'
    trace_before = trace.read_bytes()
    assert team['members']['engineer']['session_ref'] is None
    cause = [
        json.loads(line)['event_id']
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ][-1]

    replaced = run_process(
        [
            str(installed_commands.runner), 'replace', alias, '--actor', 'main',
            '--caused-by-event-id', cause,
        ],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    replacement = yaml.safe_load(replaced.stdout)['replacement_alias']
    team = yaml.safe_load(team_file.read_text())
    assert replacement != alias
    assert team['members']['engineer']['session_ref'] == replacement
    assert trace.read_bytes() == trace_before


@pytest.mark.parametrize(
    ('target', 'round_ordinal'),
    (('replacement-review', 1), ('replacement-rework', 2)),
)
def test_replacement_reviewer_report_continues_the_current_team_once(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
    target, round_ordinal,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    runtime_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': target,
    }

    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert failed.returncode == 1
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    team_file = ticket / 'teams/1/team.yml'
    mapping_file = next(
        path
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'spec-reviewer'
    )
    mapping = yaml.safe_load(mapping_file.read_text())
    alias = mapping['alias']
    cause = [
        json.loads(line)['event_id']
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ][-1]

    replaced = run_process(
        [
            str(installed_commands.runner), 'replace', alias, '--actor', 'main',
            '--caused-by-event-id', cause,
        ],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    replacement = yaml.safe_load(replaced.stdout)['replacement_alias']
    assert yaml.safe_load(team_file.read_text())['members']['spec_reviewer']['session_ref'] == replacement
    target_file = (
        harness / '.graphtraj/.agent-worktrees/76-session-alias-control'
        / '.scratch/replacement-review-target'
    )
    target_file.unlink()
    replacement_cause = [
        json.loads(line)['event_id']
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ][-1]
    resumed = run_process(
        [
            str(installed_commands.runner), 'send', replacement,
            '--instruction', 'Continue the exact current Spec report.',
            '--caused-by-event-id', replacement_cause,
        ],
        cwd=harness, env=runtime_environment, timeout=45,
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    wait_for_file(target_file)
    report_target = target_file.read_text()
    assert report_target.endswith(alias + '-replacement.md')

    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert continued.returncode == 0, continued.stdout + continued.stderr
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    assert (ticket / 'teams/1/rounds' / str(round_ordinal) / 'spec.md').is_file()
    assert yaml.safe_load(team_file.read_text())['current_round'] == round_ordinal
    sessions = [
        yaml.safe_load(path.read_text())
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'spec-reviewer'
    ]
    assert len(sessions) == 2


@pytest.mark.parametrize('target', ('completed-access', 'completed-native-root'))
def test_completed_current_configuration_failure_returns_to_the_operator(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
    target,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )

    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env={
            **environment,
            'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
            'RECOVERY_TARGET': target,
        },
        timeout=45,
    )

    assert result.returncode == 1
    error = yaml.safe_load(result.stdout)['tasks'][0]['error']
    assert error['code'] == 'invalid-config'
    assert 'responsible operator' in error['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    reviewer = next((ticket / 'teams/1/traces').glob('*@r2/events.jsonl'))
    assert 'Recovery required:' not in reviewer.read_text()


def test_completed_current_command_parse_error_returns_to_the_reviewer(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env={
            **environment,
            'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
            'RECOVERY_TARGET': 'completed-parse',
        },
        timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    prompt = (
        harness / state['worktree'] / '.scratch/recovery-prompt-spec-reviewer'
    ).read_text()
    assert 'Recovery required:' in prompt
    assert 'Cannot verify option: --glob' in prompt


def test_retried_reviewer_report_continues_the_same_team_without_repeating_reviews(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n'
        '  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )
    launch_environment = {
        **environment,
        'GRAPHTRAJ_AGENT_RUNNER': str(installed_commands.runner),
        'RECOVERY_TARGET': 'provider-review',
    }
    failed = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )
    assert failed.returncode == 1
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    mapping_file = next(
        path
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'spec-reviewer'
    )
    mapping = yaml.safe_load(mapping_file.read_text())
    events = [
        json.loads(line)
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ]
    retried = run_process(
        [
            str(installed_commands.runner), 'send', mapping['alias'],
            '--instruction', 'Retry the interrupted Spec report only.',
            '--caused-by-event-id', events[-1]['event_id'],
        ],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )
    assert retried.returncode == 0, retried.stdout + retried.stderr
    wait_for_file(mapping_file.parent / 'execution.yml')
    assert (ticket / 'reviews/spec.md').is_file()

    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness,
        env=launch_environment,
        timeout=45,
    )
    assert continued.returncode == 0, continued.stdout + continued.stderr
    assert yaml.safe_load((ticket / 'ticket.yml').read_text())['status'] == 'awaiting-integration'
    sessions = [
        yaml.safe_load(path.read_text())
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] in {'standards-reviewer', 'spec-reviewer'}
    ]
    assert len(sessions) == 2


@pytest.mark.parametrize(('registered', 'native'), [
    pytest.param(None, False, id='leader-corrects'),
    pytest.param(False, False, id='retained-correction'),
    pytest.param(True, False, id='registered-batch'),
    pytest.param(False, True, id='native', marks=pytest.mark.skipif(
        os.environ.get('CODEX_RECOVERY_REAL') != '1',
        reason='explicit real Codex report recovery probe',
    )),
])
def test_missing_current_review_can_be_corrected_in_the_retained_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    registered: bool | None,
    native: bool,
) -> None:
    """A failed correction keeps its member, candidate and unaffected Review."""
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(
        installed_commands, harness,
        body='Preserve README.md containing "# Target project". The fixed candidate needs only a Review report.',
    )
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    environment.update(
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        RECOVERY_TARGET='retained-review',
    )
    if native:
        real = shutil.which('codex')
        assert real
        driver = fake_codex.executable.with_name('controlled-codex')
        shutil.copy2(fake_codex.executable, driver)
        fake_codex.executable.write_text(
            '#!' + sys.executable + '\nimport os, sys\n'
            + 'target = ' + repr(real) + " if os.environ.get('GRAPHTRAJ_ROLE') == 'spec-reviewer' else " + repr(str(driver)) + '\n'
            + 'os.execv(target, [target, *sys.argv[1:]])\n'
        )
        native_home = harness / 'native-home'
        native_home.mkdir()
        operator = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        for name in ('config.toml', 'auth.json'):
            if (operator / name).is_file():
                shutil.copy2(operator / name, native_home / name)
        config_file = native_home / 'config.toml'
        config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
        roles_file = harness / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_file.read_text())
        roles['roles']['coding-team']['spec-reviewer'].update(
            model=os.environ.get('CODEX_RECOVERY_MODEL', config.get('model', 'gpt-5.6')),
            reasoning_effort='low',
        )
        roles_file.write_text(yaml.safe_dump(roles))
        environment.update(CODEX_HOME=str(native_home), RECOVERY_NATIVE='1')
        environment.pop('PYTHONPATH', None)
        print('Recovery probe control: ' + json.dumps({
            'root': str(harness), 'runner': str(installed_commands.runner),
            'reviewer': '76-session-alias-control@r2',
        }), flush=True)

        def stop_native_probe() -> None:
            """Release only this probe's execution if outer validation stops."""
            for mapping in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml'):
                status = command('status', mapping.parent.name)
                if yaml.safe_load(status.stdout)['aliases'][0].get('activity') == 'running':
                    command('interrupt', mapping.parent.name)

        request.addfinalizer(stop_native_probe)

    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )

    def command(*arguments: str):
        """Call the independently installed public Runner."""
        return run_process(
            [str(installed_commands.runner), *arguments],
            cwd=harness, env=environment,
            timeout=float(os.environ.get('CODEX_RECOVERY_WAIT', '900')) if native else 45,
        )

    failed = command('--batch-input', str(batch))
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert 'caller or superior' in yaml.safe_load(failed.stdout)['tasks'][0]['error']['message']
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    reports = ticket / 'teams/1/rounds/1'
    assert not (reports / 'spec.md').exists()
    leader = team['members']['team_leader']['session_ref']
    reviewer = team['members']['spec_reviewer']['session_ref']
    status_before = yaml.safe_load(command('status', reviewer).stdout)['aliases'][0]
    assert status_before['last_outcome'] == ('completed' if native else 'runtime-error')
    preserved = {
        path: path.read_bytes()
        for path in (
            reports / 'engineer.md', reports / 'validation.md', reports / 'standards.md',
            ticket / 'teams/1/traces' / team['members']['engineer']['session_ref'] / 'events.jsonl',
            ticket / 'teams/1/traces' / team['members']['standards_reviewer']['session_ref'] / 'events.jsonl',
        )
    }
    reviewer_trace = ticket / 'teams/1/traces' / reviewer / 'events.jsonl'
    prior_trace = reviewer_trace.read_bytes()
    cause = [
        json.loads(line)['event_id']
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ][-1]
    if registered is not None:
        correction = command(
            'send', leader, '--instruction', 'Recover the missing Spec report.',
            '--caused-by-event-id', cause,
        )
        assert correction.returncode == 0, correction.stdout + correction.stderr
        wait_for_file(harness / '.graphtraj/runner/sessions' / leader / 'execution.yml')
    if registered:
        registration = command(
            'send', leader, '--instruction', 'Register the remaining Spec Batch.',
            '--caused-by-event-id', cause,
        )
        assert registration.returncode == 0, registration.stdout + registration.stderr
        wait_for_file(harness / '.graphtraj/runner/sessions' / leader / 'execution.yml')
    batches_before = set((harness / '.graphtraj/state/batches').glob('*.yml'))

    continued = command('--batch-input', str(batch))

    assert continued.returncode == 0, continued.stdout + continued.stderr
    current = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert current['status'] == 'awaiting-integration'
    assert current['current_candidate'] == state['current_candidate']
    assert current['worktree'] == state['worktree']
    current_team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert current_team['members'] == team['members']
    assert current_team['current_round'] == 1
    status = yaml.safe_load(command('status', reviewer).stdout)['aliases'][0]
    assert status['last_outcome'] == 'completed'
    assert status['session'] == status_before['session']
    assert reviewer_trace.read_bytes().startswith(prior_trace)
    assert reviewer_trace.read_text().count('turn_context') == (2 if native else 3)
    assert all(path.read_bytes() == content for path, content in preserved.items())
    recovery_prompt = reviewer_trace.read_text() if native else (
        harness / current['worktree'] / '.scratch/recovery-prompt-spec-reviewer'
    ).read_text()
    assert 'Recovery required:' in recovery_prompt
    assert 'Failure:' in recovery_prompt
    assert 'Evidence:' in recovery_prompt and reviewer in recovery_prompt
    assert 'Expected result:' in recovery_prompt
    assert current['current_candidate'] in recovery_prompt
    new_batches = set((harness / '.graphtraj/state/batches').glob('*.yml')) - batches_before
    assert len(new_batches) == 1  # Only Main's explicit continuation Batch.
    assert yaml.safe_load(new_batches.pop().read_text())['tasks'][0]['role'] == 'coding-team.team-leader'


def test_missing_correction_report_returns_to_its_reviewer_without_replaying_work(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Successful Runtime execution without a report needs local report repair."""
    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness)
    fake_codex.executable.write_text('#!' + sys.executable + '\n' + RUNTIME)
    environment.update(
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        RECOVERY_TARGET='retained-review', RECOVERY_FAILURE='report',
    )
    batch = harness / 'batch.yml'
    batch.write_text(
        'tasks:\n  - ticket_id: "76"\n'
        '    ticket_name: session-alias-control\n'
        '    role: coding-team.team-leader\n'
    )

    result = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=environment, timeout=45,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    ticket = harness / '.graphtraj/state/tickets/76-session-alias-control'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    for seat, executions in (('engineer', 1), ('standards_reviewer', 1), ('spec_reviewer', 3)):
        alias = team['members'][seat]['session_ref']
        trace = ticket / 'teams/1/traces' / alias / 'events.jsonl'
        assert trace.read_text().count('turn_context') == executions
    prompt = (harness / state['worktree'] / '.scratch/recovery-prompt-spec-reviewer').read_text()
    assert 'Failure:' in prompt and 'AGENT_EVIDENCE_INVALID' in prompt
    assert 'Evidence:' in prompt and 'Expected result:' in prompt
