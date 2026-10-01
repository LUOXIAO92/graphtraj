"""Public recovery behavior across approval, state repair and native continuation."""

import copy
import json
import os
import shlex
import socket
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
from graphtraj.runtimes.codex.codex_adapter import CodexRuntimeAdapter
from test_ticket_integration import accepted_ticket


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


class NativeApproval:
    """A Runtime without Codex fields executes only its explicitly allowed payload."""

    def __init__(self, root: Path, mode: str) -> None:
        self.root = root
        self.mode = mode
        self.proposals = []
        self.before_apply = None

    def native_recovery_approval(self, command: list[str], proposal: dict) -> dict:
        """Observe unchanged state before simulating the actual native decision."""
        current, _ = recovery._snapshot(recovery.discover_project(self.root, require_clean_integration=False), proposal['request']['alias'])
        assert current == proposal['before']
        self.proposals.append(copy.deepcopy(proposal))
        if self.before_apply:
            self.before_apply()
        if self.mode in {'denied', 'failed'}:
            raise RunnerError('native-approval-' + self.mode, self.mode)
        with pytest.MonkeyPatch.context() as context:
            context.chdir(self.root)
            result = CliRunner().invoke(main, command[1:])
        assert result.exit_code == 0, result.output
        return yaml.safe_load(result.output)


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
    assert recovered['proposal']['before']['budget'] == recovered['proposal']['after']['budget']
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
    assert yaml.safe_load((ticket / 'execution-budget.yml').read_text()) == recovered['proposal']['after']['budget']

    assert all((root / ref).read_bytes() == content for ref, content in original_evidence.items())
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=dev, text=True).strip() == dev_commit
    stop = recovered['proposal']['before']['stop']
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
    assert state['current_candidate'] == result['proposal']['before']['ticket']['current_candidate']
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
    # Reexecuting the exact already-approved command also cannot add time.
    with monkeypatch.context() as context:
        context.chdir(root)
        repeated = CliRunner().invoke(main, ['recover-apply', '--proposal', json.dumps(result['proposal'])])
    assert repeated.exit_code == 0, repeated.output
    assert yaml.safe_load(repeated.output)['recovery_status'] == 'resumed'
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


def test_codex_prepares_native_review_without_writes_and_cli_matches(target: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both public surfaces prepare the same exact review without granting authority."""
    root, ticket, _, arguments = target
    monkeypatch.chdir(root)
    before = (ticket / 'ticket.yml').read_bytes()
    tool = invoke(root, arguments)
    command = ['recover', arguments['alias']]
    for key in ('reason', 'instruction', 'allowed_scope', 'forbidden_scope', 'additional_minutes'):
        command.extend(['--' + key.replace('_', '-'), str(arguments[key])])
    command.extend(['--restore-active', '--caused-by-event-id', arguments['caused_by_event_ids'][0]])
    cli = CliRunner().invoke(main, command)
    assert cli.exit_code == 0, cli.output
    result = yaml.safe_load(cli.output)
    assert result['proposal'] == tool['proposal']
    assert tool['recovery_status'] == 'requires-native-approval'
    assert tool['native_execution']['arguments']['sandbox_permissions'] == 'require_escalated'
    assert (ticket / 'ticket.yml').read_bytes() == before
    monkeypatch.setenv('CODEX_ESCALATE_SOCKET', 'broken')
    with pytest.raises(RunnerError) as error:
        invoke(root, arguments)
    assert error.value.code == 'native-approval-unavailable'
    assert (ticket / 'ticket.yml').read_bytes() == before


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
    monkeypatch.setattr(recovery.sys, 'executable', str(installed_commands.runner.with_name('python')))
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
    request = invoke(root, arguments)
    assert not received.exists()
    native = request['native_execution']['arguments']
    executed = subprocess.run(shlex.split(native['cmd']), cwd=root, capture_output=True, text=True,
                              env=dict(os.environ), timeout=30)
    assert executed.returncode == 0, executed.stderr
    result = yaml.safe_load(executed.stdout)
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


@pytest.mark.parametrize('decision', ['allow', 'deny', 'cancel', 'error'])
def test_codex_native_wrapper_executes_only_reviewed_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    """Review and execution remain native, including refusal without fallback."""
    wrapper = tmp_path / 'native-review'
    wrapper.write_text(
        f'#!{sys.executable}\nimport os, sys\n' +
        ('os.execv(sys.argv[1], sys.argv[2:])\n' if decision == 'allow' else
         f'print({decision!r}, file=sys.stderr); sys.exit(1)\n')
    )
    wrapper.chmod(0o755)
    marker = tmp_path / 'applied'
    command = [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch(); print("recovery_status: resumed")']
    channel, peer = socket.socketpair()
    with channel, peer:
        monkeypatch.setenv('CODEX_ESCALATE_SOCKET', str(channel.fileno()))
        monkeypatch.setenv('EXEC_WRAPPER', str(wrapper))
        if decision == 'allow':
            assert CodexRuntimeAdapter().native_recovery_approval(command, {'authority': ['existing']}) == {'recovery_status': 'resumed'}
        else:
            with pytest.raises(RunnerError, match=decision):
                CodexRuntimeAdapter().native_recovery_approval(command, {'authority': ['existing']})
    assert marker.exists() is (decision == 'allow')


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
    assert result['proposal']['before']['team']['status'] == 'retired'
    assert retired in read_worldline(state, root)
    assert result['proposal']['after']['team']['members'] == result['proposal']['before']['team']['members']


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
    assert result['recovery_status'] == 'requires-native-approval'
    assert result['proposal']['before'] == result['proposal']['after']


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


def test_public_execution_rejects_changed_proposal_and_wrong_caller(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command cannot turn its recovery payload into arbitrary state edits."""
    root, ticket, mapping, arguments = target
    prepared = invoke(root, arguments)
    proposal = prepared['proposal']
    before = (ticket / 'ticket.yml').read_bytes()
    monkeypatch.chdir(root)
    changed = copy.deepcopy(proposal)
    changed['after']['budget']['started_at'] = 0
    result = CliRunner().invoke(main, ['recover-apply', '--proposal', json.dumps(changed)])
    assert result.exit_code != 0
    assert 'invalid-input' in result.output
    assert (ticket / 'ticket.yml').read_bytes() == before
    child = next(member['session_ref'] for member in proposal['before']['team']['members'].values()
                 if member['session_ref'] != mapping['alias'])
    with runtime_caller(root / '.graphtraj/runner', child):
        result = CliRunner().invoke(main, ['recover-apply', '--proposal', json.dumps(proposal)])
    assert result.exit_code != 0
    assert 'authority-denied' in result.output
    assert (ticket / 'ticket.yml').read_bytes() == before
    raw = local_tool.bind(root)({'action': 'execute', 'feature': 'apply_approved_recovery',
                                 'arguments': {'proposal': proposal}})
    assert raw.failed


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
    assert yaml.safe_load(cli.output)['proposal'] == tool['proposal']
    native_command = shlex.split(tool['native_execution']['arguments']['cmd'])
    assert Path(native_command[0]).name == 'agent-runner'
    assert native_command[1] == 'recover-apply'
    assert json.loads(native_command[3]) == tool['proposal']


@pytest.mark.parametrize('decision', ['allow', 'deny', 'cancel', 'error'])
def test_native_review_runs_public_administrative_execution(
    target: tuple,
    installed_commands: InstalledCommands,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    """The native execution peer approves or refuses the actual public command."""
    root, ticket, _, arguments = target
    monkeypatch.chdir(root)
    monkeypatch.setattr(recovery.sys, 'executable', str(installed_commands.runner.with_name('python')))
    wrapper = tmp_path / 'native-review'
    wrapper.write_text(
        f'#!{sys.executable}\nimport os, sys\n' +
        ('os.execv(sys.argv[1], sys.argv[2:])\n' if decision == 'allow' else
         f'print({decision!r}, file=sys.stderr); sys.exit(1)\n')
    )
    wrapper.chmod(0o755)
    before = (ticket / 'ticket.yml').read_bytes()
    budget = (ticket / 'execution-budget.yml').read_bytes()
    events = read_worldline(ticket.parent.parent, root)
    channel, peer = socket.socketpair()
    with channel, peer:
        monkeypatch.setenv('CODEX_ESCALATE_SOCKET', str(channel.fileno()))
        monkeypatch.setenv('EXEC_WRAPPER', str(wrapper))
        request = {**arguments, 'additional_minutes': 0, 'resume': False}
        if decision == 'allow':
            result = invoke(root, request)
            assert result['recovery_status'] == 'applied'
            assert result['applied'] is True
            assert yaml.safe_load((ticket / 'ticket.yml').read_text())['status'] == 'implementing'
        else:
            with pytest.raises(RunnerError, match=decision):
                invoke(root, request)
            assert (ticket / 'ticket.yml').read_bytes() == before
            assert read_worldline(ticket.parent.parent, root) == events
    assert (ticket / 'execution-budget.yml').read_bytes() == budget


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


def test_retry_of_retained_request_without_resume_field_does_not_add_time(
    target: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older applied requests remain idempotent after adding the resume option."""
    root, ticket, mapping, arguments = target
    proposal = invoke(root, arguments)['proposal']
    proposal['request'].pop('resume')
    monkeypatch.chdir(root)
    monkeypatch.setattr(recovery, '_send_session_locked', lambda *args, **kwargs: {'session': mapping['session']})
    applied = CliRunner().invoke(main, ['recover-apply', '--proposal', json.dumps(proposal)])
    assert applied.exit_code == 0, applied.output
    event_id = yaml.safe_load(applied.output)['recovery_event_id']
    before = (ticket / 'execution-budget.yml').read_bytes()
    retried = invoke(root, arguments)
    assert retried['recovery_status'] == 'resumed'
    assert retried['recovery_event_id'] == event_id
    assert (ticket / 'execution-budget.yml').read_bytes() == before
