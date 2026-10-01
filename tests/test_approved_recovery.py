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
        return recovery.apply_approved_recovery(proposal, self.root)


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
    assert recovery.apply_approved_recovery(result['proposal'], root)['recovery_status'] == 'resumed'
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


def test_native_approved_command_reaches_original_session_with_exact_scope(
    target: tuple,
    installed_commands: InstalledCommands,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
