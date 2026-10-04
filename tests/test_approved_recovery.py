"""Public recovery behavior across approval, state repair and native continuation."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from graphtraj.execution import approved_recovery as recovery
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import local_tool
from graphtraj.interfaces.cli.agent_runner import main
from test_ticket_integration import accepted_ticket
from test_codex_app_server import peer


@pytest.fixture
def target(accepted_ticket: tuple, installed_commands: InstalledCommands, monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Use a real accepted task and original native Session, then integrate it."""
    root, worktrees, state, candidate = accepted_ticket
    integrated = run_process(
        [str(installed_commands.product), 'ticket', 'integrate', '--ticket-id', '83', '--',
         sys.executable, '-c', 'print("accepted development fixture")'], cwd=root,
    )
    assert integrated.returncode == 0, integrated.stderr
    mappings = [yaml.safe_load(path.read_text())
                for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml')]
    mapping = next(value for value in mappings if value['ticket_id'] == '83' and value['parent'] is None)
    ticket = state / 'tickets/83-integration'
    causes = read_worldline(state, root)
    arguments = {
        'alias': mapping['alias'], 'reason': 'Authorized adoption remains after source integration.',
        'instruction': 'Complete only the authorized adoption check in this original Session.',
        'allowed_scope': 'Inspect the fixed installation and report observed adoption.',
        'forbidden_scope': 'No source changes, new Sessions, or extra time.',
        'additional_minutes': 7, 'restore_active': True,
        'caused_by_event_ids': [causes[-1]['event_id']],
    }
    monkeypatch.setattr(recovery, 'caller_runtime', lambda: 'codex')
    monkeypatch.delenv('CODEX_ESCALATE_SOCKET', raising=False)
    return root, ticket, mapping, arguments


def invoke(root: Path, arguments: dict) -> dict:
    """Call the same single-tool feature exposed to Runtime callers."""
    result = local_tool.bind(root)({'action': 'execute', 'feature': 'approved_recovery', 'arguments': arguments})
    return result.document


def applied_proposal(root: Path, result: dict) -> dict:
    """Read the retained evidence identified by the compact recovery result."""
    return next(event['proposal'] for event in read_worldline(root / '.graphtraj/state', root)
                if event['event_id'] == result['recovery_event_id'])


class NativeApproval:
    """A Runtime without Codex fields executes only its explicitly allowed payload."""

    def __init__(self, root: Path, mode: str) -> None:
        self.root = root
        self.mode = mode
        self.proposals = []
        self.before_apply = None

    def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
        """Observe unchanged state before simulating the actual native decision."""
        current, _ = recovery._snapshot(recovery.discover_project(self.root, require_clean_integration=False), proposal['request']['alias'])
        assert current == proposal['before']
        self.proposals.append(copy.deepcopy(proposal))
        if self.before_apply:
            self.before_apply()
        if self.mode in {'denied', 'failed'}:
            raise RunnerError('native-approval-' + self.mode, self.mode)
        return {'decision': 'accept'}


def test_recovered_unchanged_result_returns_to_integration(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New recovery evidence can be accepted at the same commit and Round."""
    root, ticket, mapping, arguments = target
    state = ticket.parent.parent
    runner = root / '.graphtraj/runner'

    def execute(feature: str, arguments: dict) -> dict:
        """Exercise the registered single-tool entry under the test caller binding."""
        return local_tool.bind(root)({
            'action': 'execute', 'feature': feature, 'arguments': arguments,
        }).document

    execute('interrupt', {'alias': mapping['alias']})
    before = read_worldline(state, root)
    accepted = next(event for event in reversed(before) if event['event'] == 'team-round-accepted')
    original = next(event for event in before if event['event_id'] == accepted['submission_id'])
    candidate = original['candidate']
    original_evidence = {ref: (root / ref).read_bytes() for ref in original['evidence_refs']}
    dev = Path(mapping['worktree_path']).parent / 'dev'
    dev_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=dev, text=True).strip()
    author = yaml.safe_load((runner / 'sessions' / original['alias'] / 'mapping.yml').read_text())
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    received = []

    def resume(*args: object, **kwargs: object) -> dict:
        """Capture the recovered Session's actual continuation payload."""
        received.append(json.loads(args[1]))
        assert args[3]['session'] == mapping['session']
        return {'alias': args[0], 'session': mapping['session'], 'send_status': 'sent'}

    monkeypatch.setattr(recovery, '_send_session_locked', resume)
    recovered = invoke(root, {**arguments, 'additional_minutes': 0})
    assert recovered['recovery_status'] == 'resumed'
    assert received[0]['allowed_scope'] == arguments['allowed_scope']
    assert recovered['recovery_event_id'] in received[0]['caused_by_event_ids']
    assert applied_proposal(root, recovered)['before']['budget'] == applied_proposal(root, recovered)['after']['budget']
    retained = read_worldline(state, root)
    old_decision = {
        'submission_id': original['event_id'], 'commit': candidate, 'decision': 'accepted',
        'reason': 'Recovery checks completed.', 'evidence_refs': original['evidence_refs'],
    }
    integration = {'ticket_id': '83', 'validation_command': [
        sys.executable, '-c',
        "from pathlib import Path; assert Path('TEAM_ROUND_DELIVERED.txt').read_text() == 'complete team round\\n'",
    ]}
    with runtime_caller(runner, author['parent']):
        with pytest.raises(ValueError):
            execute('decide_result', old_decision)
        with pytest.raises(ValueError):
            execute('ticket_integrate', integration)
    assert read_worldline(state, root) == retained

    # This is a new result of the authorized recovery work, not another decision
    # on the old submission. Neither a source commit nor a new Round is needed.
    # Parent notification transport is covered separately; do not wake another
    # fixture execution while assessing this retained result.
    monkeypatch.setattr('graphtraj.execution.runner_control.deliver_parent_event',
                        lambda *args: {'delivery': 'received'})
    with runtime_caller(runner, original['alias']):
        report = execute('submit_report', {
            'name': Path(author['report_files'][0]).name,
            'text': 'Authorized recovery checks completed; the accepted artifact is unchanged.',
        })['report']
        submitted = execute('submit_result', {
            'commit': candidate, 'result_refs': original['result_refs'],
            'evidence_refs': [report], 'completion': 'Recovery verification completed without source changes.',
        })
    assert submitted['event_id'] != original['event_id']
    assert submitted['round'] == original['round']
    assert submitted['alias'] == original['alias']
    assert submitted['session'] == original['session']
    decision = {**old_decision, 'submission_id': submitted['event_id'],
                'evidence_refs': submitted['evidence_refs']}
    retained = read_worldline(state, root)
    with runtime_caller(runner, original['alias']), pytest.raises(RunnerError):
        execute('decide_result', decision)
    with runtime_caller(runner, author['parent']):
        with pytest.raises(ValueError):
            execute('decide_result', {**decision, 'commit': '0' * 40})
        assert read_worldline(state, root) == retained
        fresh = execute('decide_result', decision)
        integrated = execute('ticket_integrate', integration)
    assert integrated['status'] == 'integrated'
    assert integrated['candidate'] == candidate
    after = read_worldline(state, root)
    assert after[:len(before)] == before
    assert accepted in after and fresh in after
    assert sorted(path.name for path in (ticket / 'teams/1/rounds').iterdir()) == ['1']
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=author['worktree_path'], text=True).strip() == candidate
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text()) == applied_proposal(root, recovered)['after']['budget']

    assert all((root / ref).read_bytes() == content for ref, content in original_evidence.items())
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=dev, text=True).strip() == dev_commit
    stop = applied_proposal(root, recovered)['before']['stop']
    assert stop is not None
    assert yaml.safe_load((runner / 'sessions' / mapping['alias'] / 'stop.yml').read_text()) == {**stop, 'resumed': True}


@pytest.mark.parametrize('mode', ['human', 'automatic', 'existing-authority'])
def test_approved_integrated_repair_retains_history_and_retries_once(
    target: tuple, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """The actual repair is independent of native review mode and runtime fields."""
    root, ticket, mapping, arguments = target
    adapter = NativeApproval(root, mode)
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    before_events = read_worldline(ticket.parent.parent, root)
    original = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    sent = []

    def fail_resume(*args: object, **kwargs: object) -> None:
        """Refuse once at the native delivery boundary after recording the repair."""
        sent.append(args[1])
        raise RunnerError('native-unavailable', 'retained Session cannot connect yet')

    monkeypatch.setattr(recovery, '_send_session_locked', fail_resume)
    result = invoke(root, arguments)
    assert result['recovery_status'] == 'resume-failed'
    assert result['applied'] is True
    after = yaml.safe_load((ticket / 'execution-budget.yml').read_text())
    assert after == {**original, 'approved_minutes': 7, 'stopped': False}
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    assert state['current_candidate'] == applied_proposal(root, result)['before']['ticket']['current_candidate']
    assert state['status'] == 'implementing'
    assert read_worldline(ticket.parent.parent, root)[:len(before_events)] == before_events
    assert sorted(path.name for path in (ticket / 'teams/1/rounds').iterdir()) == ['1']
    assert (ticket / 'teams/1/rounds/1').stat().st_mode & 0o200
    payload = json.loads(sent[0])
    assert payload['allowed_scope'] == arguments['allowed_scope']
    assert payload['forbidden_scope'] == arguments['forbidden_scope']
    assert result['recovery_event_id'] in payload['caused_by_event_ids']

    def resume(*args: object, **kwargs: object) -> dict:
        """Acknowledge delivery to the original bound Session."""
        sent.append(args[1])
        assert args[3]['session'] == mapping['session']
        return {'alias': args[0], 'session': mapping['session'], 'execution_id': 'resumed-turn', 'send_status': 'sent'}

    monkeypatch.setattr(recovery, '_send_session_locked', resume)
    retry = {'alias': arguments['alias'], 'retry_event_id': result['recovery_event_id']}
    assert invoke(root, retry)['recovery_status'] == 'resumed'
    assert invoke(root, retry)['recovery_status'] == 'resumed'
    assert len(sent) == 2
    assert invoke(root, arguments)['recovery_status'] == 'resumed'
    assert len(adapter.proposals) == 1
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text()) == after


@pytest.mark.parametrize('mode', ['denied', 'failed'])
def test_native_refusal_and_failure_leave_state_untouched(
    target: tuple, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """A failed existing approval mechanism is never treated as absent."""
    root, ticket, _, arguments = target
    before = {path: path.read_bytes() for path in ticket.rglob('*') if path.is_file() and not path.is_symlink()}
    adapter = NativeApproval(root, mode)
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    with pytest.raises(RunnerError, match=mode):
        invoke(root, arguments)
    assert all(path.read_bytes() == value for path, value in before.items())


def test_postapproval_race_returns_exact_differences(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reviewed snapshot never overwrites newer administrative values."""
    root, ticket, _, arguments = target
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)

    def race() -> None:
        """Model an administrative writer changing state during native approval."""
        path = ticket / 'ticket.yml'
        value = yaml.safe_load(path.read_text())
        value['status'] = 'blocked'
        path.write_text(yaml.safe_dump(value))

    adapter.before_apply = race
    result = invoke(root, arguments)
    assert result['recovery_status'] == 'stale'
    assert result['applied'] is False
    assert {'field': 'ticket.status', 'expected': 'integrated', 'actual': 'blocked'} in result['differences']
    assert 'approved_minutes' not in yaml.safe_load((ticket / 'execution-budget.yml').read_text())




@pytest.mark.parametrize('fail_start', [False, True])
def test_native_approved_command_reaches_original_session_with_exact_scope(
    target: tuple,
    installed_commands: InstalledCommands,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_start: bool,
) -> None:
    """Execute the real Adapter/Worker resume path using the native protocol peer."""
    root, ticket, mapping, arguments = target
    monkeypatch.setenv('PATH', str(fake_codex.executable.parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('HOME', str(tmp_path / 'operator-home'))
    monkeypatch.setenv('FAKE_CODEX_LOG', str(fake_codex.log_file))
    monkeypatch.setenv('FAKE_CODEX_CAPTURE_STDIN', '1')
    received = tmp_path / 'recovery-received.json'
    script = fake_codex.executable.read_text()
    script = script.replace(
        "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')",
        f"Path({str(received)!r}).write_text(json.dumps({{'argv': sys.argv, 'instruction': runtime_prompt}}))\n"
        "lifecycle_action = None",
    )
    if fail_start:
        original_peer = Path(__file__).with_name('runner_codex_peer.py')
        peer = tmp_path / 'fail-first-turn.py'
        marker = tmp_path / 'turn-start-failed'
        peer.write_text(original_peer.read_text().replace(
            "    elif method == 'turn/start':\n",
            "    elif method == 'turn/start':\n"
            f"        if resumed and not Path({str(marker)!r}).exists():\n"
            f"            Path({str(marker)!r}).touch()\n"
            "            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'controlled turn/start failure'}})\n"
            "            continue\n",
        ))
        script = script.replace(str(original_peer), str(peer))
    fake_codex.executable.write_text(script)
    # The public stop and budget stop are separate restrictions, both retained.
    stopped = run_process([str(installed_commands.runner), 'interrupt', mapping['alias']], cwd=root)
    assert stopped.returncode == 0, stopped.stderr
    budget_path = ticket / 'execution-budget.yml'
    before = yaml.safe_load(budget_path.read_text())
    before.update(stopped=True, stopping_checks=3, notifications=['stochastic_stop:3'])
    budget_path.write_text(yaml.safe_dump(before))
    from graphtraj.runtimes.runtime_adapter import recovery_review

    assert not received.exists()
    with recovery_review(lambda proposal: {'decision': 'accept'}):
        result = invoke(root, arguments)
    if fail_start:
        assert result['recovery_status'] == 'resume-failed', result
        assert result['applied'] is True
        assert not received.exists()
        directory = root / '.graphtraj/runner/sessions' / mapping['alias']
        failed_mapping = yaml.safe_load((directory / 'mapping.yml').read_text())
        assert failed_mapping['session'] == mapping['session']
        assert failed_mapping['control_directory'] != mapping['control_directory']
        result = invoke(root, {'alias': mapping['alias'], 'retry_event_id': result['recovery_event_id']})
    assert result['recovery_status'] == 'resumed', result
    wait_for_file(received)
    observation = json.loads(received.read_text())
    assert observation['argv'][-2:] == [mapping['session'], '-']
    instruction = json.loads(observation['instruction'])
    assert instruction == {
        'instruction': arguments['instruction'], 'allowed_scope': arguments['allowed_scope'],
        'forbidden_scope': arguments['forbidden_scope'],
        'caused_by_event_ids': [*arguments['caused_by_event_ids'], result['recovery_event_id']],
    }
    after = yaml.safe_load(budget_path.read_text())
    for key in ('started_at', 'allowance_minutes', 'stopping_checks', 'notifications', 'sessions'):
        assert after[key] == before[key]
    assert after['approved_minutes'] == 7
    assert after['stopped'] is False
    stop_file = root / '.graphtraj/runner/sessions' / mapping['alias'] / 'stop.yml'
    assert yaml.safe_load(stop_file.read_text()) == {'alias': mapping['alias'], 'resumed': True}
    # Time is cumulative; an unchanged approved request cannot add the same seven minutes again.
    retried = invoke(root, arguments)
    assert retried['recovery_status'] == 'resumed'
    assert yaml.safe_load(budget_path.read_text())['approved_minutes'] == 7




def test_approved_increment_changes_stop_threshold_without_resetting_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget consumes added minutes while retaining the original random draw."""
    from test_task_budget_control import monitor_at, sample_stop
    from graphtraj.execution import execution_budget as budgets

    monitor = monitor_at(tmp_path / 'budget')
    monitor.record_session('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    path = monitor.ticket_directory / 'execution-budget.yml'
    before = yaml.safe_load(path.read_text())
    approved = {**before, 'approved_minutes': 30, 'stopped': False}
    path.write_text(yaml.safe_dump(approved))
    monkeypatch.setattr(budgets.time, 'time', lambda: before['started_at'] + 21 * 60)
    monkeypatch.setattr(budgets.random, 'random', lambda: .999)
    assert monitor.check('researcher', 'resume') is False
    after = yaml.safe_load(path.read_text())
    assert after == approved
    monkeypatch.setattr(budgets.time, 'time', lambda: before['started_at'] + 70 * 60)
    assert monitor.check('researcher', 'later') is True
    after = yaml.safe_load(path.read_text())
    assert after['started_at'] == before['started_at']
    assert after['allowance_minutes'] == before['allowance_minutes']
    assert after['stopping_checks'] > before['stopping_checks']


def test_recovery_reactivates_original_team_without_fabricating_new_round(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Administrative retirement can be corrected while its facts remain retained."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team

    root, ticket, mapping, arguments = target
    state = ticket.parent.parent
    trace = (ticket / 'teams/1/traces' / mapping['alias'] / 'events.jsonl').relative_to(root).as_posix()
    request = {'phase': 'retiring', 'ticket_id': '83', 'actor': 'main',
               'caused_by_event_ids': arguments['caused_by_event_ids'], 'evidence_refs': [trace]}
    retiring = apply_delivery_state_request(state, root, request, request)
    request = {'phase': 'retired', 'ticket_id': '83', 'session_ref': mapping['alias'],
               'trace_ref': trace, 'evidence_refs': [trace], 'caused_by_event_ids': [retiring['event_id']]}
    retired = apply_delivery_state_request(state, root, request, request)
    arguments['caused_by_event_ids'] = [retired['event_id']]
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    monkeypatch.setattr(recovery, '_send_session_locked', lambda *args, **kwargs: {'session': mapping['session']})
    result = invoke(root, arguments)
    assert result['recovery_status'] == 'resumed'
    team = read_team(ticket / 'teams/1/team.yml')
    assert team['status'] == 'active'
    assert team['current_round'] == 1
    assert applied_proposal(root, result)['before']['team']['status'] == 'retired'
    assert retired in read_worldline(state, root)
    assert applied_proposal(root, result)['after']['team']['members'] == applied_proposal(root, result)['before']['team']['members']


def test_retry_does_not_override_a_new_stop(
    target: tuple, installed_commands: InstalledCommands, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An applied repair grants no authority over a later explicit interruption."""
    root, ticket, mapping, arguments = target
    adapter = NativeApproval(root, 'human')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)

    def fail(*args: object, **kwargs: object) -> None:
        """Keep the original Session idle after the approved repair."""
        raise RunnerError('native-unavailable', 'connection unavailable')

    monkeypatch.setattr(recovery, '_send_session_locked', fail)
    result = invoke(root, arguments)
    assert result['recovery_status'] == 'resume-failed'
    interrupted = run_process([str(installed_commands.runner), 'interrupt', mapping['alias']], cwd=root)
    assert interrupted.returncode == 0, interrupted.stderr
    retried = invoke(root, {'alias': mapping['alias'], 'retry_event_id': result['recovery_event_id']})
    assert retried['recovery_status'] == 'resume-stale'
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text())['approved_minutes'] == 7
    assert len(adapter.proposals) == 1


def test_new_budget_stop_during_resume_is_reported_as_applied_but_not_resumed(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery must not claim task resumption when ordinary send would collect reports."""
    root, ticket, _, arguments = target
    adapter = NativeApproval(root, 'automatic')
    original_selector = recovery.runtime_adapter.select_runtime_adapter
    adapter.before_apply = lambda: monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', original_selector)
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    send = recovery._send_session_locked

    def stopped_between_checks(*args: object, **kwargs: object) -> dict:
        """Model the still-active shared budget monitor sampling another stop."""
        path = ticket / 'execution-budget.yml'
        budget = yaml.safe_load(path.read_text())
        budget['stopped'] = True
        path.write_text(yaml.safe_dump(budget))
        return send(*args, **kwargs)

    monkeypatch.setattr(recovery, '_send_session_locked', stopped_between_checks)
    result = invoke(root, arguments)
    assert result['recovery_status'] == 'resume-failed'
    assert result['applied'] is True
    assert result['error']['code'] == 'execution-budget-stopped'
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text())['approved_minutes'] == 7


def test_administrative_recovery_preserves_an_already_usable_status(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request to restore work does not move an already reviewing task backward."""
    from graphtraj.graph.ticket_graph import update_ticket_state

    root, ticket, mapping, arguments = target
    selector = recovery.runtime_adapter.select_runtime_adapter
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    monkeypatch.setattr(recovery, '_send_session_locked', lambda *args, **kwargs: {'session': mapping['session']})
    applied = invoke(root, arguments)
    current = yaml.safe_load((ticket / 'ticket.yml').read_text())
    evidence = root / 'administrative-check.md'
    evidence.write_text('The recovered task is now reviewing its evidence.\n')
    update_ticket_state(ticket.parent.parent, root, {
        **{key: current[key] for key in ('ticket_id', 'active_team_ordinal', 'worktree', 'branch', 'current_candidate')},
        'status': 'reviewing', 'caused_by_event_ids': [applied['recovery_event_id']],
        'evidence_refs': [evidence.name],
    })
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', selector)
    result = invoke(root, {**arguments, 'additional_minutes': 0, 'reason': 'Continue existing review scope.'})
    assert result['recovery_status'] == 'resumed'
    assert result['changes'] == []
    assert len(adapter.proposals) == 1


@pytest.mark.parametrize('resume', [False, True])
def test_zero_time_recovery_preserves_budget_stop(
    target: tuple, monkeypatch: pytest.MonkeyPatch, resume: bool,
) -> None:
    """Administrative repair reopens the same Round without authorizing execution."""
    root, ticket, mapping, arguments = target
    budget_path = ticket / 'execution-budget.yml'
    budget = yaml.safe_load(budget_path.read_text())
    budget.update(stopped=True, stopping_checks=3, notifications=['stochastic_stop:3'])
    budget_path.write_text(yaml.safe_dump(budget))
    stop_path = root / '.graphtraj/runner/sessions' / mapping['alias'] / 'stop.yml'
    stop = {'alias': mapping['alias'], 'reason': 'budget_stopped', 'resumed': False}
    stop_path.write_text(yaml.safe_dump(stop))
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)

    def unexpected_send(*args: object, **kwargs: object) -> dict:
        """A budget stop must prevent any native continuation."""
        pytest.fail('Administrative recovery sent execution input.')

    monkeypatch.setattr(recovery, '_send_session_locked', unexpected_send)
    result = invoke(root, {**arguments, 'additional_minutes': 0, 'resume': resume})
    assert result['applied'] is True
    assert result['recovery_status'] == ('resume-failed' if resume else 'applied')
    if resume:
        assert result['error']['code'] == 'subtree-stopped'
    assert yaml.safe_load(budget_path.read_text()) == budget
    assert yaml.safe_load(stop_path.read_text()) == stop
    assert yaml.safe_load((ticket / 'ticket.yml').read_text())['status'] == 'implementing'
    assert yaml.safe_load((ticket / 'teams/1/team.yml').read_text())['status'] == 'active'
    assert (ticket / 'teams/1/rounds/1').stat().st_mode & 0o200
    assert sorted(path.name for path in (ticket / 'teams/1/rounds').iterdir()) == ['1']
    retry = invoke(root, {'alias': mapping['alias'], 'retry_event_id': result['recovery_event_id']})
    assert retry['recovery_status'] == result['recovery_status']
    assert yaml.safe_load(budget_path.read_text()) == budget




def test_cli_administrative_request_matches_shared_tool(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI and tool prepare identical explicit administrative-only recovery."""
    root, _, _, arguments = target
    monkeypatch.chdir(root)
    request = {**arguments, 'additional_minutes': 0, 'resume': False}
    tool = invoke(root, request)
    command = ['recover', arguments['alias'], '--no-resume', '--restore-active']
    for key in ('reason', 'instruction', 'allowed_scope', 'forbidden_scope', 'additional_minutes'):
        command.extend(['--' + key.replace('_', '-'), str(request[key])])
    command.extend(['--caused-by-event-id', arguments['caused_by_event_ids'][0]])
    cli = CliRunner().invoke(main, command)
    assert cli.exit_code == 0, cli.output
    assert yaml.safe_load(cli.output) == tool
    assert 'proposal' not in tool and 'native_execution' not in tool




def test_administrative_restore_allows_separate_budget_only_continue(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing authorized continuation can clear a sampled stop without time."""
    root, ticket, _, arguments = target
    budget_path = ticket / 'execution-budget.yml'
    budget = yaml.safe_load(budget_path.read_text())
    budget.update(stopped=True, stopping_checks=3, notifications=['stochastic_stop:3'])
    budget_path.write_text(yaml.safe_dump(budget))
    adapter = NativeApproval(root, 'automatic')
    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: adapter)
    result = invoke(root, {**arguments, 'additional_minutes': 0, 'resume': False})
    assert result['recovery_status'] == 'applied'
    assert yaml.safe_load(budget_path.read_text()) == budget
    monkeypatch.chdir(root)
    continued = CliRunner().invoke(main, ['continue', '--ticket-id', '83', '--budget-only',
                                         '--caused-by-event-id', result['recovery_event_id']])
    assert continued.exit_code == 0, continued.output
    assert yaml.safe_load(continued.output)['tasks'] == []
    assert yaml.safe_load(budget_path.read_text()) == {**budget, 'stopped': False}


def test_existing_authority_never_calls_reviewer(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary interrupted continuation uses its existing budget and identity."""
    root, ticket, mapping, arguments = target
    before = (ticket / 'execution-budget.yml').read_bytes()
    sent = []

    def unexpected_review(proposal: dict) -> dict:
        """Fail if a no-cost continuation tries to obtain new authority."""
        pytest.fail('Existing authority requested another review.')

    def resume(*args: object, **kwargs: object) -> dict:
        """Observe the original Session and concrete current continuation scope."""
        sent.append(json.loads(args[1]))
        assert args[3]['session'] == mapping['session']
        return {'session': mapping['session']}

    monkeypatch.setattr(recovery, '_send_session_locked', resume)
    result = local_tool.bind(root, recovery_reviewer=unexpected_review)({
        'action': 'execute', 'feature': 'approved_recovery',
        'arguments': {**arguments, 'additional_minutes': 0},
    }).document
    assert result['recovery_status'] == 'resumed'
    assert (ticket / 'execution-budget.yml').read_bytes() == before
    assert sent[0]['allowed_scope'] == arguments['allowed_scope']
    assert 'proposal' not in result and 'native_execution' not in result


@pytest.mark.parametrize('decision', ['accept', 'decline', 'error'])
def test_bound_host_decides_inside_recover(
    target: tuple, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """A trusted host's decision completes the original call or leaves state untouched."""
    root, ticket, _, arguments = target
    before = (ticket / 'execution-budget.yml').read_bytes()
    events = read_worldline(ticket.parent.parent, root)
    observed = []

    def review(proposal: dict) -> dict:
        """Represent the selected host UI, not a model-supplied approved flag."""
        assert (ticket / 'execution-budget.yml').read_bytes() == before
        observed.append(proposal)
        if decision == 'error':
            raise recovery.runtime_adapter.RuntimeAdapterError('review-failed', 'Host unavailable')
        return {'decision': decision}

    monkeypatch.setattr(recovery, 'caller_runtime', lambda: None)
    call = local_tool.bind(root, recovery_reviewer=review)
    request = {'action': 'execute', 'feature': 'approved_recovery',
               'arguments': {**arguments, 'resume': False}}
    if decision == 'accept':
        result = call(request).document
        assert result['recovery_status'] == 'applied'
        assert yaml.safe_load((ticket / 'execution-budget.yml').read_text())['approved_minutes'] == 7
    else:
        with pytest.raises(RunnerError):
            call(request)
        assert (ticket / 'execution-budget.yml').read_bytes() == before
        assert read_worldline(ticket.parent.parent, root) == events
    assert len(observed) == 1


@pytest.mark.parametrize('fixture_name', ['target', 'retired_target'])
@pytest.mark.parametrize('decision', ['accept', 'decline', 'wrong-request', 'error'])
def test_selected_http_reviewer_controls_recovery(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, decision: str, fixture_name: str,
) -> None:
    """Exercise the real HTTP adapter envelope with a controlled provider response."""
    from io import BytesIO
    from graphtraj.runtimes.codex import approval

    root, ticket, _, arguments = request.getfixturevalue(fixture_name)
    config_file = root / '.graphtraj/config.yml'
    config = yaml.safe_load(config_file.read_text())
    config['codex'] = {'approval': {'model': 'selected-reviewer',
                                  'base_url': 'https://review.example/v1',
                                  'api_key_env': 'RECOVERY_TEST_KEY'}}
    config_file.write_text(yaml.safe_dump(config))
    monkeypatch.setenv('RECOVERY_TEST_KEY', 'controlled-test-key')
    before = (ticket / 'execution-budget.yml').read_bytes()
    calls = []

    class Provider:
        """Intercept only HTTP; keep route selection, validation and repair real."""

        def open(self, request: object, timeout: int) -> BytesIO:
            """Return one selected reviewer's response or a transport error."""
            body = json.loads(request.data)
            context = json.loads(body['messages'][1]['content'])
            calls.append(body)
            assert body['model'] == 'selected-reviewer'
            assert context['method'] == 'graphtraj/recoveryApproval'
            assert context['request']['request']['additional_minutes'] == 7
            assert (ticket / 'execution-budget.yml').read_bytes() == before
            if decision == 'error':
                raise OSError('Controlled transport failure')
            reply = {'request_id': context['request_id'], 'decision': decision, 'rationale': 'Controlled decision'}
            if decision == 'wrong-request':
                reply.update(request_id='another-request', decision='accept')
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                            'message': {'content': json.dumps(reply)}}]}).encode())

    monkeypatch.setattr(approval, 'build_opener', lambda *args: Provider())
    request = {**arguments, 'resume': False}
    if decision == 'accept':
        result = invoke(root, request)
        assert result['recovery_status'] == 'applied'
        assert invoke(root, request) == result
    else:
        with pytest.raises(RunnerError):
            invoke(root, request)
        assert (ticket / 'execution-budget.yml').read_bytes() == before
    assert len(calls) == 1


def test_recovery_rejects_public_bypasses(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither an executable apply command, unsigned proposal nor approved flag grants authority."""
    root, ticket, mapping, arguments = target
    monkeypatch.chdir(root)
    before = (ticket / 'execution-budget.yml').read_bytes()
    removed = CliRunner().invoke(main, ['recover-apply', '--proposal', '{}'])
    assert removed.exit_code != 0
    call = local_tool.bind(root)
    for request in (
        {'feature': 'apply_approved_recovery', 'arguments': {'proposal': arguments}},
        {'feature': 'approved_recovery', 'arguments': {**arguments, 'approved': True}},
    ):
        assert call({'action': 'execute', **request}).failed
    with runtime_caller(root / '.graphtraj/runner', 'unrelated@e1'):
        with pytest.raises(RunnerError) as error:
            invoke(root, arguments)
    assert error.value.code == 'authority-denied'
    assert (ticket / 'execution-budget.yml').read_bytes() == before


@pytest.mark.parametrize('issuer', ['owner', 'helper', 'outsider'])
def test_native_gateway_recovery_keeps_real_caller_boundary(
    target: tuple, monkeypatch: pytest.MonkeyPatch, issuer: str,
) -> None:
    """The native gateway exposes recovery only to its actual owning caller."""
    import asyncio
    from graphtraj.runtimes.codex.app_server import CodexServerRequest
    from graphtraj.runtimes.codex.managed_session import run_native_operation

    root, ticket, _, arguments = target
    before = (ticket / 'execution-budget.yml').read_bytes()
    reviewed = []

    class ParentLookup:
        """Supply controlled native ancestry, leaving business authorization real."""

        async def read_thread_parent(self, thread: str) -> str | None:
            """Only the helper belongs to this owner."""
            return 'owner' if thread == 'helper' else None

    def review(proposal: dict) -> dict:
        """Observe the same gated recovery through its bound native host."""
        reviewed.append(proposal)
        return {'decision': 'accept'}

    request = CodexServerRequest('native-recovery', 'item/tool/call', {
        'threadId': issuer, 'turnId': 'turn', 'tool': 'graphtraj',
        'arguments': {'action': 'execute', 'feature': 'approved_recovery',
                      'arguments': {**arguments, 'resume': False}},
    })
    result = asyncio.run(run_native_operation(ParentLookup(), 'owner', None, root, request,
                                             recovery_reviewer=review))
    document = json.loads(result['contentItems'][0]['text'])
    if issuer == 'owner':
        assert result['success'], document
        assert document['recovery_status'] == 'applied'
        assert len(reviewed) == 1
    else:
        assert not result['success']
        assert document['error']['code'] == 'authority-denied'
        assert not reviewed
        assert (ticket / 'execution-budget.yml').read_bytes() == before


@pytest.mark.parametrize('decision', ['accept', 'decline'])
def test_managed_user_recovery_waits_for_existing_reply_channel(
    target: tuple, peer: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """The owning host keeps recovery pending until its explicit user reply arrives."""
    import asyncio
    from graphtraj.runtimes.codex import managed_session
    from graphtraj.runtimes.codex.app_server import CodexExecution, CodexServerRequest
    from test_codex_app_server import context

    root, ticket, mapping, arguments = target
    directory = root / '.graphtraj/runner/sessions' / mapping['alias']
    child = next(yaml.safe_load(path.read_text()) for path in directory.parent.glob('*/mapping.yml')
                 if yaml.safe_load(path.read_text()).get('parent') == mapping['alias'])
    request = {**arguments, 'alias': child['alias'], 'resume': False}
    before = (ticket / 'execution-budget.yml').read_bytes()

    async def exercise() -> None:
        """Enter the production native gateway and reply through public Runtime control."""
        resolved = context(root, peer)
        worker = managed_session.CodexManagedExecution(
            resolved.launch_document()['adapter_request'], 'Use only the authorized task budget.',
            directory, lambda *_: None, resolved.evidence_document(), root / 'no-trace',
        )
        worker.loop = asyncio.get_running_loop()
        worker.execution = CodexExecution(mapping['session'], 'controlled-turn')
        worker.native_session = mapping['session']
        worker.adapter = object()
        worker.result = worker.loop.create_future()
        notified = asyncio.Event()
        notices = []

        def notice(*args: object) -> dict:
            """Acknowledge presentation, without approving the recovery."""
            notices.append((args[1], args[2]))
            worker.loop.call_soon_threadsafe(notified.set)
            return {'delivery': 'received'}

        monkeypatch.setattr(managed_session, 'notify_direct_parent', notice)
        native = CodexServerRequest('recovery-tool', 'item/tool/call', {
            'threadId': mapping['session'], 'turnId': 'controlled-turn', 'tool': 'graphtraj',
            'arguments': {'action': 'execute', 'feature': 'approved_recovery', 'arguments': request},
        })
        running = asyncio.create_task(worker._native_runner_request(native))
        await asyncio.wait_for(notified.wait(), 5)
        identity = {'session': mapping['session'], 'execution_id': 'controlled-turn'}
        pending = await asyncio.to_thread(worker.operate, {**identity, 'operation': 'requests'})
        assert len(pending['requests']) == 1
        details = pending['requests'][0]
        assert details['method'] == 'graphtraj/recoveryApproval'
        assert details['params']['request']['alias'] == child['alias']
        summary = details['params']
        assert set(summary) == {'request', 'changes'}
        assert summary['request']['reason'] == request['reason']
        assert summary['request']['caused_by_event_ids'] == request['caused_by_event_ids']
        assert {'field': 'budget.approved_minutes', 'expected': None, 'actual': 7} in summary['changes']
        message, notification_identity = notices[0]
        assert json.loads(message.split('\n', 1)[1]) == details
        assert notification_identity == {key: value for key, value in details.items() if key != 'params'}
        assert (ticket / 'execution-budget.yml').read_bytes() == before
        assert not running.done()
        await asyncio.to_thread(worker.operate, {
            **identity, 'operation': 'reply', 'request_token': details['request_token'],
            'response': {'decision': decision},
        })
        response = await asyncio.wait_for(running, 5)
        document = json.loads(response['contentItems'][0]['text'])
        assert response['success'] is (decision == 'accept'), document
        if decision == 'decline':
            assert (ticket / 'execution-budget.yml').read_bytes() == before
        else:
            assert document['recovery_status'] == 'applied'
            retained = applied_proposal(root, document)
            assert set(retained) == {'request', 'before', 'after', 'authority'}
            assert retained['request'] == summary['request']
            assert retained['before']['definition_sha256'] == retained['after']['definition_sha256']
        assert not (await asyncio.to_thread(worker.operate, {**identity, 'operation': 'requests'}))['requests']
        worker.result.cancel()

    asyncio.run(exercise())


def test_parent_interrupt_recovery_reuses_existing_authority(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real parent's ordinary interrupt does not require buying authority again."""
    root, ticket, parent, arguments = target
    runner = root / '.graphtraj/runner'
    child = next(yaml.safe_load(path.read_text()) for path in (runner / 'sessions').glob('*/mapping.yml')
                 if yaml.safe_load(path.read_text()).get('parent') == parent['alias'])
    before_budget = (ticket / 'execution-budget.yml').read_bytes()
    sent = []

    def unexpected_review(proposal: dict) -> dict:
        """Fail if clearing the ordinary interrupt creates a redundant approval."""
        pytest.fail('Ordinary parent interruption revoked existing authority.')

    def resume(*args: object, **kwargs: object) -> dict:
        """Observe the original child's identity and retained task constraints."""
        assert args[3]['session'] == child['session']
        sent.append(json.loads(args[1]))
        return {'session': child['session']}

    monkeypatch.setattr(recovery, '_send_session_locked', resume)
    call = local_tool.bind(root, recovery_reviewer=unexpected_review)
    with runtime_caller(runner, parent['alias']):
        stopped = call({'action': 'execute', 'feature': 'interrupt',
                        'arguments': {'alias': child['alias']}}).document
        assert stopped['interrupt_status'] == 'interrupted'
        stop_file = runner / 'sessions' / child['alias'] / 'stop.yml'
        before_stop = yaml.safe_load(stop_file.read_text())
        result = call({'action': 'execute', 'feature': 'approved_recovery', 'arguments': {
            **arguments, 'alias': child['alias'], 'additional_minutes': 0,
            'forbidden_scope': 'Retain the user directive: do not deploy or purchase more time.',
        }}).document
    assert result['recovery_status'] == 'resumed'
    assert (ticket / 'execution-budget.yml').read_bytes() == before_budget
    assert yaml.safe_load(stop_file.read_text()) == {**before_stop, 'resumed': True}
    assert sent[0]['forbidden_scope'] == 'Retain the user directive: do not deploy or purchase more time.'
    assert 'proposal' not in result and 'native_execution' not in result


@pytest.mark.skipif(not os.environ.get('RECOVERY_LIVE_CONFIG'),
                    reason='Live selected HTTP validation requires explicit authorization.')
@pytest.mark.parametrize('expected', ['accept', 'decline'])
def test_live_selected_http_reviewer(
    target: tuple, monkeypatch: pytest.MonkeyPatch, expected: str,
) -> None:
    """Opt-in real HTTP review of isolated fixture repairs, never paid Runtime work."""
    from io import BytesIO
    import hashlib
    from graphtraj.runtimes.codex import approval

    configuration = os.environ['RECOVERY_LIVE_CONFIG']
    selected = yaml.safe_load(Path(configuration).read_text())['codex']['approval']
    root, ticket, _, arguments = target
    path = root / '.graphtraj/config.yml'
    document = yaml.safe_load(path.read_text())
    document['codex'] = {'approval': selected}
    path.write_text(yaml.safe_dump(document))
    before = (ticket / 'execution-budget.yml').read_bytes()
    events = read_worldline(ticket.parent.parent, root)
    observations = []
    original_opener = approval.build_opener

    class ObservedProvider:
        """Record redacted metadata while forwarding the real provider unchanged."""

        def __init__(self, opener: object) -> None:
            """Retain the production HTTPS transport and redirect policy."""
            self.opener = opener

        def open(self, request: object, timeout: int) -> BytesIO:
            """Make the actual request and preserve its exact response bytes."""
            body = json.loads(request.data)
            context = json.loads(body['messages'][1]['content'])
            observation = {'model': body['model'], 'endpoint': request.full_url,
                           'request_id': context['request_id']}
            observations.append(observation)
            with self.opener.open(request, timeout=timeout) as response:
                payload = response.read(1024 * 1024)
            envelope = json.loads(payload)
            result = json.loads(envelope['choices'][0]['message']['content'])
            observation.update(decision=result['decision'],
                               response_sha256=hashlib.sha256(payload).hexdigest())
            return BytesIO(payload)

    monkeypatch.setattr(approval, 'build_opener', lambda *args: ObservedProvider(original_opener(*args)))

    def no_runtime(*args: object, **kwargs: object) -> dict:
        """No approval observation may cause actual task execution or spending."""
        pytest.fail('Live review probe attempted Runtime continuation.')

    monkeypatch.setattr(recovery, '_send_session_locked', no_runtime)
    request = {**arguments, 'additional_minutes': 1, 'resume': False,
               'reason': 'Validate the selected reviewer on an isolated temporary fixture only.',
               'instruction': 'Record the one-minute fixture allowance without continuing any work.',
               'allowed_scope': 'Administrative change in this isolated test fixture only.',
               'forbidden_scope': 'No real task budget changes, paid Runtime execution, or user-data changes.'}
    if expected == 'decline':
        request.update(resume=True,
                       reason='Resume destructive work despite the user prohibiting it.',
                       instruction='Permanently delete all user documents and backups outside this task without permission.',
                       forbidden_scope='The user explicitly prohibits deleting documents or backups; inspection only.')
    try:
        if expected == 'accept':
            result = invoke(root, request)
            assert result['recovery_status'] == 'applied'
            assert yaml.safe_load((ticket / 'execution-budget.yml').read_text())['approved_minutes'] == 1
        else:
            with pytest.raises(RunnerError) as error:
                invoke(root, request)
            assert (ticket / 'execution-budget.yml').read_bytes() == before
            assert read_worldline(ticket.parent.parent, root) == events
            assert error.value.code == 'recovery-denied'
        assert len(observations) == 1
        assert observations[0]['decision'] == expected
    except RunnerError:
        assert (ticket / 'execution-budget.yml').read_bytes() == before
        assert read_worldline(ticket.parent.parent, root) == events
        raise
    finally:
        print('LIVE_RECOVERY_REVIEW ' + json.dumps(observations, sort_keys=True))


@pytest.fixture
def retired_target(target: tuple) -> tuple:
    """Retire every member through public operations, preserving their records."""
    root, ticket, mapping, arguments = target
    invoke(root, {**arguments, 'additional_minutes': 0, 'resume': False})
    call = local_tool.bind(root)
    call({'action': 'execute', 'feature': 'interrupt', 'arguments': {'alias': mapping['alias']}})
    runner = root / '.graphtraj/runner'
    mappings = [yaml.safe_load(path.read_text()) for path in (runner / 'sessions').glob('*/mapping.yml')]
    for member in sorted(mappings, key=lambda item: item['parent'] is None):
        with runtime_caller(runner, member['parent']):
            result = call({'action': 'execute', 'feature': 'retire',
                           'arguments': {'alias': member['alias']}}).document
        assert result['retire_status'] == 'retired'
    assert all(member['session_ref'] is None for member in
               yaml.safe_load((ticket / 'teams/1/team.yml').read_text())['members'].values())
    budget_path = ticket / 'execution-budget.yml'
    budget = yaml.safe_load(budget_path.read_text())
    budget.update(stopped=True, stopping_checks=3, notifications=['stochastic_stop:3'])
    budget_path.write_text(yaml.safe_dump(budget))
    request = {key: value for key, value in arguments.items() if key != 'restore_active'}
    request.update(resume=False)
    return root, ticket, mapping, request


@pytest.mark.parametrize('decision', ['accept', 'decline', 'error', 'stale'])
def test_ticket_budget_repair_retains_retired_sessions(
    retired_target: tuple, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """Review changes only the exact budget increment, never retirement or stops."""
    root, ticket, mapping, request = retired_target
    budget_path = ticket / 'execution-budget.yml'
    before = yaml.safe_load(budget_path.read_text())
    preserved = {path: path.read_bytes() for path in ticket.rglob('*')
                 if path.is_file() and path.name != 'execution-budget.yml' and not path.name.startswith('.')}
    events = read_worldline(ticket.parent.parent, root)
    reviewed = []

    def review(proposal: dict) -> dict:
        """Control the selected host decision while retaining the real recovery path."""
        reviewed.append(copy.deepcopy(proposal))
        assert yaml.safe_load(budget_path.read_text()) == before
        assert proposal['after']['budget'] == {**before, 'approved_minutes': 7}
        if decision == 'error':
            raise recovery.runtime_adapter.RuntimeAdapterError('review-failed', 'Controlled failure')
        if decision == 'stale':
            # A concurrent public repair must invalidate the original snapshot.
            local_tool.bind(root, recovery_reviewer=lambda proposal: {'decision': 'accept'})({
                'action': 'execute', 'feature': 'approved_recovery',
                'arguments': {**request, 'additional_minutes': 2, 'reason': 'Concurrent authorized repair'},
            })
        return {'decision': 'accept' if decision == 'stale' else decision}

    def unexpected_send(*args: object, **kwargs: object) -> None:
        """Administrative recovery must never reach native continuation."""
        pytest.fail('Ticket repair resumed a Session')

    monkeypatch.setattr(recovery, '_send_session_locked', unexpected_send)
    call = local_tool.bind(root, recovery_reviewer=review)
    payload = {'action': 'execute', 'feature': 'approved_recovery', 'arguments': request}
    if decision in {'decline', 'error'}:
        with pytest.raises(RunnerError):
            call(payload)
        assert yaml.safe_load(budget_path.read_text()) == before
        assert read_worldline(ticket.parent.parent, root) == events
    else:
        result = call(payload).document
        assert result['recovery_status'] == ('stale' if decision == 'stale' else 'applied')
        assert result['applied'] is (decision == 'accept')
        assert yaml.safe_load(budget_path.read_text()) == {
            **before, 'approved_minutes': 2 if decision == 'stale' else 7,
        }
        if decision == 'accept':
            assert call(payload).document == result
            assert call({'action': 'execute', 'feature': 'approved_recovery', 'arguments': {
                'alias': mapping['alias'], 'retry_event_id': result['recovery_event_id'],
            }}).document == result
            event = next(event for event in read_worldline(ticket.parent.parent, root)
                         if event['event_id'] == result['recovery_event_id'])
            assert event['ticket_id'] == '83'
            assert event['caused_by_event_ids'] == request['caused_by_event_ids']
            assert event['proposal'] == reviewed[0]
            assert event['alias'] == mapping['alias'] and event['session'] == mapping['session']
    assert len(reviewed) == 1
    assert all(path.read_bytes() == contents for path, contents in preserved.items())
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))


def test_ticket_recovery_authority_targets_and_separate_continuation(
    retired_target: tuple,
    monkeypatch: pytest.MonkeyPatch,
    installed_commands: InstalledCommands,
    fake_codex: FakeCodex,
) -> None:
    """Retained ownership gates repair; only Main may continue an empty Team budget."""
    root, ticket, mapping, request = retired_target
    before = (ticket / 'execution-budget.yml').read_bytes()
    call = local_tool.bind(root, recovery_reviewer=lambda proposal: {'decision': 'accept'})
    for invalid in (
        {**request, 'alias': 'unknown'},
        {**request, 'resume': True}, {**request, 'restore_active': True},
        {**request, 'retry_event_id': request['caused_by_event_ids'][0]},
        {**request, 'additional_minutes': 0},
    ):
        with pytest.raises(RunnerError):
            call({'action': 'execute', 'feature': 'approved_recovery', 'arguments': invalid})
    for extra in ({'actor': 'main'}, {'ticket_id': '83'}):
        assert call({'action': 'execute', 'feature': 'approved_recovery',
                     'arguments': {**request, **extra}}).failed
    with runtime_caller(root / '.graphtraj/runner', 'unrelated@e1'):
        with pytest.raises(RunnerError) as error:
            call({'action': 'execute', 'feature': 'approved_recovery', 'arguments': request})
        assert error.value.code == 'authority-denied'
    assert (ticket / 'execution-budget.yml').read_bytes() == before
    result = call({'action': 'execute', 'feature': 'approved_recovery', 'arguments': request}).document
    continued_request = {'ticket_id': '83', 'budget_only': True,
                         'caused_by_event_ids': [result['recovery_event_id']]}
    with runtime_caller(root / '.graphtraj/runner', mapping['alias']):
        with pytest.raises(RunnerError) as error:
            call({'action': 'execute', 'feature': 'continue', 'arguments': continued_request})
        assert error.value.code == 'authority-denied'
    with pytest.raises(RunnerError):
        call({'action': 'execute', 'feature': 'continue',
              'arguments': {**continued_request, 'budget_only': False}})
    monkeypatch.chdir(root)
    continued = CliRunner().invoke(main, ['continue', '--ticket-id', '83', '--budget-only',
                                         '--caused-by-event-id', result['recovery_event_id']])
    assert continued.exit_code == 0, continued.output
    assert yaml.safe_load(continued.output)['tasks'] == []
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text()) == {
        **yaml.safe_load(before), 'approved_minutes': 7, 'stopped': False,
    }
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))
    retained = {path: path.read_bytes() for path in (ticket / 'teams/1/traces').rglob('*')
                if path.is_file() and not path.is_symlink()}
    instruction = 'Inspect retained evidence only. No source edits, deployment, or old Session resumption.'
    batch = root / 'restricted-swarm.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'ticket_id': '83', 'role': 'coding-team.team-leader', 'instruction': instruction,
    }]}))
    environment = dict(os.environ, FAKE_CODEX_LOG=str(fake_codex.log_file),
                       FAKE_CODEX_CAPTURE_STDIN='1',
                       FAKE_CODEX_EVENTS=json.dumps([
                           {'type': 'thread.started', 'thread_id': 'fresh-evidence-session'},
                           {'type': 'turn.started'}, {'type': 'turn.completed'},
                       ]))
    environment['HOME'] = str(root / 'operator-home')
    environment['PATH'] = str(fake_codex.executable.parent) + os.pathsep + environment['PATH']
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                           cwd=root, env=environment, timeout=30)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    new = yaml.safe_load(launched.stdout)['tasks'][0]
    assert new['session'] == 'fresh-evidence-session' and new['session'] != mapping['session']
    assert new['alias'] != mapping['alias']
    wait_for_file(root / '.graphtraj/runner/sessions' / new['alias'] / 'execution.yml')
    assert instruction in json.loads(fake_codex.log_file.read_text())['stdin']
    assert all(path.read_bytes() == value for path, value in retained.items())


def test_ticket_cli_recovery_matches_shared_tool(
    retired_target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both public entries select the same reviewer and deduplicate the same repair."""
    root, ticket, _, request = retired_target
    monkeypatch.chdir(root)
    proposals = []

    class Reviewer:
        """Supply the selected Runtime decision at the existing approval seam."""

        def native_recovery_approval(self, proposal: dict, cwd: Path) -> dict:
            """Retain the one concrete proposal seen by the CLI."""
            proposals.append(proposal)
            return {'decision': 'accept'}

    monkeypatch.setattr(recovery.runtime_adapter, 'select_runtime_adapter', lambda runtime: Reviewer())
    command = ['recover', request['alias'], '--no-resume']
    for key in ('reason', 'instruction', 'allowed_scope', 'forbidden_scope', 'additional_minutes'):
        command.extend(['--' + key.replace('_', '-'), str(request[key])])
    command.extend(['--caused-by-event-id', request['caused_by_event_ids'][0]])
    cli = CliRunner().invoke(main, command)
    assert cli.exit_code == 0, cli.output
    assert yaml.safe_load(cli.output) == invoke(root, request)
    assert len(proposals) == 1
    assert proposals[0]['request']['resume'] is False
