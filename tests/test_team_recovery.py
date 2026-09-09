from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from conftest import run_process, wait_for_file
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket


RUNTIME = r'''
import json, os, subprocess, sys, yaml
from pathlib import Path

if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox --dangerously-bypass-hook-trust')
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

def git(*arguments):
    return subprocess.run(['git', *arguments], check=True, text=True, capture_output=True).stdout.strip()

def dispatch(roles):
    batch = Path.cwd() / '.scratch' / 'children.yml'
    batch.write_text(yaml.safe_dump({'tasks': [
        {'ticket_id': '76', 'ticket_name': 'session-alias-control',
         'role': 'coding-team.' + child}
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
elif role == 'team-leader':
    if not (round_dir / 'engineer.md').exists():
        if target != 'dispatch' or 'Recovery required:' in prompt:
            dispatch(['engineer-junior'])
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
        elif target == 'provider-rework' and round_dir.name == '1':
            (round_dir / 'leader.md').write_text(
                'Decision: REJECT\nDiagnosis: implementation\nReviews: compliant\n'
                'Action: rework\nRationale: bounded correction.\n'
                'Candidate commit: ' + candidate + '\n'
            )
        else:
            (round_dir / 'leader.md').write_text('Decision: ACCEPT\nCandidate commit: ' + candidate + '\n')
elif role.startswith('engineer-'):
    if target in {'provider', 'provider-correct', 'provider-rework'} and not resumed:
        raise SystemExit(1)
    replacement_failure = Path.cwd() / '.scratch' / 'provider-replace-failed'
    if target == 'provider-replace' and not replacement_failure.exists():
        replacement_failure.write_text('failed\n')
        raise SystemExit(1)
    if target == 'access' and not resumed:
        sys.stderr.write('Permission denied by Runtime filesystem sandbox\n')
        raise SystemExit(1)
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
    (round_dir / 'engineer.md').write_text('Candidate commit: ' + candidate + '\nSelf-review: complete.\n')
    validation = round_dir / 'validation.md'
    if target == 'engineer-junior' and not resumed:
        validation.write_text('Candidate commit: invalid\n')
    else:
        validation.write_text('Candidate commit: ' + candidate + '\nTests: passed.\n')
else:
    if target == 'provider-review' and role == 'spec-reviewer' and not resumed:
        raise SystemExit(1)
    if (
        target == 'replacement-review'
        and role == 'spec-reviewer'
        and not Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).name.endswith('-replacement.md')
    ):
        raise SystemExit(1)
    if target == 'completed-access' and role == 'spec-reviewer':
        message = 'Permission denied by Runtime filesystem sandbox'
    elif (
        target == 'completed-parse'
        and role == 'spec-reviewer'
        and not resumed
    ):
        message = 'Cannot verify option: --glob'
    elif target == role and not resumed:
        pass
    else:
        candidate = git('rev-parse', 'HEAD')
        if target == 'replacement-review' and role == 'spec-reviewer':
            (Path.cwd() / '.scratch' / 'replacement-review-target').write_text(
                os.environ['GRAPHTRAJ_REVIEW_REPORT']
            )
        if target == 'provider-rework' and round_dir.name == '1':
            axis = 'Standards' if role == 'standards-reviewer' else 'Spec'
            Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
                'Candidate commit: ' + candidate + '\n'
                'Comparison: ' + os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] + '\n'
                'Axis: ' + axis + '\n'
                'Finding: implementation\nRule: accepted Ticket\nInput: recovered Team\n'
                'Trace: retained Session\nFailure: correction required\n'
                'Evidence: retained report\n'
            )
        else:
            Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
                'Candidate commit: ' + candidate + '\nFinding: none\n'
            )

print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}}), flush=True)
print(json.dumps({'type': 'turn.completed'}), flush=True)
'''


@pytest.mark.parametrize('target', ('engineer-junior', 'spec-reviewer', 'team-leader', 'uncommitted', 'delivery-state', 'dispatch'))
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
        }[target]
        trace = ticket / 'teams/1/traces' / team['members'][seat]['session_ref'] / 'events.jsonl'
    recovered = trace.read_text()
    assert recovered.count('thread.started') >= 2
    recovery_role = {
        'uncommitted': 'engineer-junior',
        'dispatch': 'team-leader',
    }.get(target, target)
    prompt = (harness / state['worktree'] / '.scratch' / ('recovery-prompt-' + recovery_role)).read_text()
    assert 'Recovery required:' in prompt
    assert 'Failure:' in prompt
    assert 'Evidence:' in prompt
    assert 'Expected result:' in prompt
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
    (('provider', 1), ('provider-correct', 1), ('provider-rework', 2)),
)
def test_provider_failure_returns_to_the_caller_for_an_explicit_same_session_retry(
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
        json.loads(line)['thread_id']
        for line in trace.read_text().splitlines()
        if json.loads(line).get('type') == 'thread.started'
    ]
    assert identities == [mapping['session']]
    events = [
        json.loads(line)
        for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
        for line in path.read_text().splitlines()
    ]
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
    assert trace.read_text().count('thread.started') == 2
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
    if target == 'provider-correct':
        events = [
            json.loads(line)
            for path in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
            for line in path.read_text().splitlines()
        ]
        assert any(event['kind'] == 'team-process-correction' for event in events)


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


def test_replacement_reviewer_report_continues_the_current_team_once(
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
        'RECOVERY_TARGET': 'replacement-review',
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
    target = target_file.read_text()
    assert target.endswith(alias + '-replacement.md')

    continued = run_process(
        [str(installed_commands.runner), '--batch-input', str(batch)],
        cwd=harness, env=runtime_environment, timeout=45,
    )

    assert continued.returncode == 0, continued.stdout + continued.stderr
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['status'] == 'awaiting-integration'
    assert (ticket / 'teams/1/rounds/1/spec.md').is_file()
    sessions = [
        yaml.safe_load(path.read_text())
        for path in (harness / '.graphtraj/runner/sessions').glob('*/mapping.yml')
        if yaml.safe_load(path.read_text())['role'] == 'spec-reviewer'
    ]
    assert len(sessions) == 2


def test_completed_current_access_denial_returns_to_the_operator(
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
            'RECOVERY_TARGET': 'completed-access',
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
