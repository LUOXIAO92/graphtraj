"""A resolver with a Session ended before submitting; its parent still completes the merge (405)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process, runner_operation
from test_generic_role_execution import wait_for_idle
from test_task_integration import (  # noqa: F401  (fixtures)
    _accept_resolution, accepted_document, accepted_task, stopped_committed_integration,
)

from graphtraj.configuration.project_configuration import load_project_configuration
from graphtraj.graph.delivery_worldline import read_worldline

RESOLVED = 'complete team round\nconflicting integration work\n'
VALIDATOR = [sys.executable, '-c', f"from pathlib import Path; assert Path('article.md').read_text() == {RESOLVED!r}"]
DIAGNOSIS = 'Preserve both document requirements'


@dataclass
class Interrupted:
    """Task 83 in 384's state: an escalated integration whose resolver has a Session."""

    commands: InstalledCommands
    root: Path
    dev: Path
    state: Path
    candidate: str
    environment: dict
    alias: str
    session: str
    escalation: str
    log: Path

    @property
    def integrate(self) -> list[str]:
        """Return the public integration command up to its options."""
        return [str(self.commands.product), 'task', 'integrate', '--task-id', '83']

    @property
    def sessions(self) -> Path:
        """Return the Runner's active Session records."""
        return self.root / '.graphtraj/runner/sessions'

    @property
    def status(self) -> str:
        """Read the Task's retained status."""
        return yaml.safe_load((self.state / 'tasks/83-integration/task.yml').read_text())['status']

    def events(self, name: str) -> list[dict]:
        """Return Task 83's retained Worldline events of one kind."""
        return [event for event in read_worldline(self.state, self.root)
                if event.get('task_id') == '83' and event['event'] == name]

    def repeat(self) -> dict:
        """Repeat the original validation command without selecting a resolver."""
        return yaml.safe_load(run_process(self.integrate + ['--', *VALIDATOR], cwd=self.root).stdout)

    def recover(self, *flags: str, alias: str | None = None) -> tuple[int, dict]:
        """Call the public recovery operation with concrete scope and its causal event."""
        result = run_process([
            str(self.commands.runner), 'recover', alias or self.alias, '--reason', 'Resolver was interrupted',
            '--instruction', 'Finish this merge', '--allowed-scope', 'The retained conflict',
            '--forbidden-scope', 'Anything else',
            '--caused-by-event-ids', json.dumps([self.escalation]), *flags,
        ], cwd=self.root, env=self.environment)
        return result.returncode, yaml.safe_load(result.stdout)

    def redispatch(self, role: str, diagnosis: str = DIAGNOSIS) -> tuple[int, dict]:
        """Select a resolver for the retained conflict again."""
        result = run_process(self.integrate + ['--resolve-conflict', diagnosis, '--role', role,
                                               '--', *VALIDATOR], cwd=self.root, env=self.environment)
        return result.returncode, yaml.safe_load(result.stdout)

    def complete(self, alias: str) -> dict:
        """Decide the resolver's submission and repeat the original validation."""
        wait_for_idle(self.commands, self.root, self.environment, alias)
        _accept_resolution(self.commands, self.root, alias)
        completed = run_process(self.integrate + ['--', *VALIDATOR], cwd=self.root)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return yaml.safe_load(completed.stdout)

    def adopt_committed(self) -> dict:
        """Commit the retained staged work and adopt it through confirmed_commit."""
        run_process(['git', 'commit', '--no-edit'], cwd=self.dev).check_returncode()
        head = run_process(['git', 'rev-parse', 'HEAD'], cwd=self.dev).stdout.strip()
        adopted = run_process(self.integrate + ['--confirm-resolution', head, '--', *VALIDATOR], cwd=self.root)
        assert adopted.returncode == 0, adopted.stdout + adopted.stderr
        return yaml.safe_load(adopted.stdout)


def _status(fixture: Interrupted, alias: str) -> dict:
    """Read one Agent's public status."""
    result = run_process(runner_operation(fixture.commands, 'status', alias), cwd=fixture.root, env=fixture.environment)
    assert result.returncode == 0, result.stdout + result.stderr
    return yaml.safe_load(result.stdout)['aliases'][0]


def _wait_ended(fixture: Interrupted, alias: str) -> None:
    """Wait until a stopped Agent's execution has confirmably ended."""
    for _ in range(200):
        if _status(fixture, alias)['activity'] == 'idle':
            return
        time.sleep(.05)
    raise AssertionError(_status(fixture, alias))


def _dispatch_held_resolver(
    commands: InstalledCommands, accepted: tuple, fake_codex, tmp_path: Path,
) -> tuple[Path, Path, Path, str, dict, str]:
    """Create a retained textual conflict and a resolver held after its first event."""
    root, worktrees, state, candidate, environment = accepted
    dev = worktrees / 'dev'
    (dev / 'article.md').write_text('conflicting integration work\n')
    run_process(['git', 'add', 'article.md'], cwd=dev).check_returncode()
    run_process(['git', 'commit', '-m', 'Existing document requirement'], cwd=dev).check_returncode()
    command = [str(commands.product), 'task', 'integrate', '--task-id', '83']
    failed = run_process(command + ['--', *VALIDATOR], cwd=root)
    assert failed.returncode == 1, failed.stdout
    environment.update(FAKE_CODEX_LIFECYCLE_ACTION='resolve-integration', FAKE_CODEX_RESOLUTION='resolved',
                       FAKE_CODEX_RELEASE_FILE=str(tmp_path / 'never-released'))
    # The held resolver inherits this call's descriptors, so a pipe would never reach end of file.
    written = tmp_path / 'dispatch.yml'
    with written.open('w') as stream:
        dispatched = subprocess.run(command + ['--resolve-conflict', DIAGNOSIS, '--role', 'editor', '--', *VALIDATOR],
                                    cwd=root, env=environment, stdout=stream, stderr=subprocess.DEVNULL, timeout=60)
    assert dispatched.returncode == 0, written.read_text()
    output = yaml.safe_load(written.read_text())
    assert output['status'] == 'resolving-integration'
    return root, dev, state, candidate, environment, output['resolution']['alias']


@pytest.fixture
def interrupted(
    installed_commands: InstalledCommands, accepted_document: tuple, fake_codex, tmp_path: Path,
) -> Interrupted:
    """Reproduce 384: interrupted resolver, staged resolution, MERGE_HEAD, then escalation."""
    root, dev, state, candidate, environment, alias = _dispatch_held_resolver(
        installed_commands, accepted_document, fake_codex, tmp_path)
    stopped = run_process(runner_operation(installed_commands, 'interrupt', alias), cwd=root, env=environment)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    environment.pop('FAKE_CODEX_RELEASE_FILE')
    (dev / 'article.md').write_text(RESOLVED)
    (dev / 'staged-by-first-resolver.txt').write_text('kept\n')
    run_process(['git', 'add', 'article.md', 'staged-by-first-resolver.txt'], cwd=dev).check_returncode()
    fixture = Interrupted(installed_commands, root, dev, state, candidate, environment, alias,
                          yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())['session'],
                          '', fake_codex.log_file)
    _wait_ended(fixture, alias)
    escalated = fixture.repeat()
    assert escalated['status'] == 'escalated', escalated
    fixture.escalation = escalated['event_id']
    assert run_process(['git', 'rev-parse', 'MERGE_HEAD'], cwd=dev).stdout.strip() == candidate
    return fixture


def test_resume_without_restore_active_is_refused_before_anything_is_recorded(interrupted: Interrupted) -> None:
    """384's half-applied recovery cannot recur: nothing is recorded and no input is sent."""
    stop = interrupted.sessions / interrupted.alias / 'stop.yml'
    retained, runtime = stop.read_bytes(), interrupted.log.read_bytes()
    code, output = interrupted.recover()
    assert code == 1 and output['error']['code'] == 'invalid-input' and 'restore_active' in output['error']['message']
    assert interrupted.events('recovery-applied') == []
    assert interrupted.status == 'escalated'
    assert stop.read_bytes() == retained and interrupted.log.read_bytes() == runtime


def test_resume_with_restore_active_continues_the_same_session_to_integrated(interrupted: Interrupted) -> None:
    """The original Session resumes under its stop record and completes through ordinary acceptance."""
    stop = interrupted.sessions / interrupted.alias / 'stop.yml'
    before = yaml.safe_load(stop.read_text())
    assert before.get('resumed') is not True
    launches = sorted(path.name for path in interrupted.sessions.iterdir())
    code, output = interrupted.recover('--restore-active')
    assert code == 0 and output['recovery_status'] == 'resumed', output
    # The stop stays retained; only its existing flag records the authorized resumption.
    assert yaml.safe_load(stop.read_text()) == {**before, 'resumed': True}
    assert sorted(path.name for path in interrupted.sessions.iterdir()) == launches
    assert interrupted.status == 'resolving-integration'
    native = json.loads(interrupted.log.read_text())
    assert 'resume' in native['argv'] and interrupted.session in native['argv']
    final = interrupted.complete(interrupted.alias)
    assert final['status'] == 'integrated'
    assert interrupted.events('task-integration-conflict-resolved')
    assert run_process(['git', 'merge-base', '--is-ancestor', interrupted.candidate, 'HEAD'],
                       cwd=interrupted.dev).returncode == 0
    assert run_process(['git', 'show', 'HEAD:staged-by-first-resolver.txt'], cwd=interrupted.dev).stdout == 'kept\n'


def test_redispatch_replaces_an_ended_resolver_with_a_new_role_and_integrates(interrupted: Interrupted) -> None:
    """A new entity works on the staged merge; the old entity's records are unchanged and it has no assignment."""
    from graphtraj.execution.runner_control import send_instruction
    from graphtraj.execution.runner_models import RunnerError

    roles_file = interrupted.root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['roles']['reconciler'] = {'runtime': 'codex', 'model': 'document-model', 'reports': ['sources.md']}
    roles['role_tree']['reconciler'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
    old = interrupted.sessions / interrupted.alias
    retained = {name: (old / name).read_bytes() for name in ('mapping.yml', 'session.yml', 'stop.yml', 'launch.yml')}
    team_file = interrupted.state / 'tasks/83-integration/teams/1/team.yml'
    seat = next(name for name, member in yaml.safe_load(team_file.read_text())['members'].items()
                if member['session_ref'] == interrupted.alias)

    code, output = interrupted.redispatch('reconciler', 'A different diagnosis of the same conflict')
    assert code == 0 and output['status'] == 'resolving-integration', output
    alias = output['resolution']['alias']
    assert alias != interrupted.alias
    started = interrupted.events('task-integration-conflict-started')[-1]
    assert started['superseded_resolvers'] == [interrupted.alias]
    assert started['role_reference'] == 'reconciler'
    assert started['diagnosis'] == 'A different diagnosis of the same conflict'
    assert started['caused_by_event_ids'] == [interrupted.escalation]
    assert {name: (old / name).read_bytes() for name in retained} == retained
    assert yaml.safe_load(team_file.read_text())['members'][seat]['session_ref'] == interrupted.alias
    new_session = yaml.safe_load((interrupted.sessions / alias / 'mapping.yml').read_text())['session']
    assert new_session != interrupted.session
    wait_for_idle(interrupted.commands, interrupted.root, interrupted.environment, alias)

    # The replaced resolver holds no assignment, though its parent can still collect its reports.
    event = started['event_id']
    with pytest.raises(RunnerError, match='active conflict assignment'):
        send_instruction(interrupted.alias, 'More work', interrupted.root, (event,))
    code, refused = interrupted.recover('--restore-active')
    assert code == 1 and 'active conflict assignment' in refused['error']['message']
    code, refused = interrupted.recover('--no-resume')
    assert code == 1 and 'active conflict assignment' in refused['error']['message']
    assert interrupted.events('recovery-applied') == []
    assert {name: (old / name).read_bytes() for name in retained} == retained
    reports_only = {key: value for key, value in interrupted.environment.items()
                    if key != 'FAKE_CODEX_LIFECYCLE_ACTION'}
    collected = run_process(runner_operation(interrupted.commands, 'send', interrupted.alias,
                                             '--instruction', 'Send your report', '--caused-by-event-id', event,
                                             '--reports-only'),
                            cwd=interrupted.root, env=reports_only)
    assert collected.returncode == 0, collected.stdout + collected.stderr
    _wait_ended(interrupted, interrupted.alias)

    final = interrupted.complete(alias)
    assert final['status'] == 'integrated'
    assert run_process(['git', 'merge-base', '--is-ancestor', interrupted.candidate, 'HEAD'],
                       cwd=interrupted.dev).returncode == 0
    assert run_process(['git', 'show', 'HEAD:staged-by-first-resolver.txt'], cwd=interrupted.dev).stdout == 'kept\n'


def test_redispatch_after_the_resolver_retired_keeps_its_retirement(interrupted: Interrupted) -> None:
    """A stop or retirement stays bound to the old entity and does not block a new one."""
    retired = run_process(runner_operation(interrupted.commands, 'retire', interrupted.alias),
                          cwd=interrupted.root, env=interrupted.environment)
    assert retired.returncode == 0, retired.stdout + retired.stderr
    code, output = interrupted.redispatch('editor')
    assert code == 0 and output['status'] == 'resolving-integration', output
    assert interrupted.events('task-integration-conflict-started')[-1]['superseded_resolvers'] == [interrupted.alias]
    assert not (interrupted.sessions / interrupted.alias).exists()
    assert interrupted.complete(output['resolution']['alias'])['status'] == 'integrated'


@pytest.mark.parametrize('path', ['resume', 'redispatch'])
def test_a_continued_resolver_that_ends_again_escalates_and_commit_can_be_adopted(
    interrupted: Interrupted, path: str,
) -> None:
    """Repeating the original validation escalates again, keeps the facts and leaves confirmed_commit usable."""
    interrupted.environment['FAKE_CODEX_RESOLUTION'] = 'prose-only'
    first = interrupted.events('task-integration-escalated')[-1]
    if path == 'resume':
        code, output = interrupted.recover('--restore-active')
        assert code == 0 and output['recovery_status'] == 'resumed', output
        alias = interrupted.alias
    else:
        code, output = interrupted.redispatch('editor')
        assert code == 0, output
        alias = output['resolution']['alias']
    wait_for_idle(interrupted.commands, interrupted.root, interrupted.environment, alias)
    assert interrupted.status == 'resolving-integration'
    again = interrupted.repeat()
    assert again['status'] == 'escalated', again
    escalated = interrupted.events('task-integration-escalated')[-1]
    assert escalated['event_id'] != first['event_id']
    assert escalated['session_ref'] == alias
    for fact in ('candidate', 'dev_before', 'dev_commit', 'validation_command', 'conflict_kind'):
        assert escalated[fact] == first[fact]
    assert run_process(['git', 'rev-parse', 'MERGE_HEAD'], cwd=interrupted.dev).stdout.strip() == interrupted.candidate
    assert interrupted.adopt_committed()['status'] == 'integrated'


def test_confirmed_commit_adopts_without_either_continuation(interrupted: Interrupted) -> None:
    """The original adoption path stays available for 384's retained state."""
    assert interrupted.adopt_committed()['status'] == 'integrated'


def test_escalation_without_a_session_reference_uses_the_reopening_alias() -> None:
    """384's retained escalation names no Session; the recovery that reopened it does."""
    from graphtraj.teams.task_integration import _current_resolver

    retained = {'event': 'task-integration-escalated', 'event_id': '2'}
    reopening = {'event': 'recovery-applied', 'event_id': '3', 'task_id': '83', 'alias': 'resolver',
                 'proposal': {'after': {'task': {'status': 'resolving-integration'}}}}
    budget_only = {**reopening, 'event_id': '4', 'alias': 'other',
                   'proposal': {'after': {'task': {'status': 'escalated'}}}}
    assert _current_resolver([retained, reopening, budget_only], {'task_id': '83'}, retained) == ('resolver', '3')
    assert _current_resolver([retained, budget_only], {'task_id': '83'}, retained) == (None, None)


def test_running_resolver_refuses_redispatch_and_resume(
    installed_commands: InstalledCommands, accepted_document: tuple, fake_codex, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver that may still be working keeps the assignment; no second one starts."""
    from graphtraj.execution import runner_status
    from graphtraj.teams.task_integration import integrate_task

    root, dev, state, candidate, environment, alias = _dispatch_held_resolver(
        installed_commands, accepted_document, fake_codex, tmp_path)
    fixture = Interrupted(installed_commands, root, dev, state, candidate, environment, alias, '', '', fake_codex.log_file)
    # Only a lost status answer leaves a running resolver under an escalated Task.
    monkeypatch.chdir(root)
    with monkeypatch.context() as lost:
        lost.setattr(runner_status, 'owning_execution', lambda *arguments: None)
        escalated = integrate_task(load_project_configuration(root), '83', tuple(VALIDATOR))
    assert escalated['status'] == 'escalated'
    fixture.escalation = escalated['event_id']
    assert _status(fixture, alias)['activity'] != 'idle'
    runtime, launches = fake_codex.log_file.read_bytes(), sorted(path.name for path in fixture.sessions.iterdir())
    try:
        code, output = fixture.redispatch('editor')
        assert code == 1 and 'not idle' in str(output), output
        code, output = fixture.recover('--restore-active')
        assert code == 1 and output['error']['code'] == 'replacement-not-stopped', output
    finally:
        stopped = run_process(runner_operation(installed_commands, 'interrupt', alias), cwd=root, env=environment)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert fixture.events('recovery-applied') == []
    assert len(fixture.events('task-integration-conflict-started')) == 1
    assert fake_codex.log_file.read_bytes() == runtime
    assert sorted(path.name for path in fixture.sessions.iterdir()) == launches
    assert fixture.status == 'escalated'


def test_non_parent_caller_is_refused(interrupted: Interrupted, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither continuation accepts a caller outside the resolver's direct relation."""
    from graphtraj.execution.approved_recovery import approved_recovery
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.teams.task_integration import integrate_task

    runner = interrupted.root / '.graphtraj/runner'
    other = next(path.parent.name for path in interrupted.sessions.glob('*/mapping.yml')
                 if path.parent.name != interrupted.alias)
    before = read_worldline(interrupted.state, interrupted.root)
    monkeypatch.chdir(interrupted.root)
    with runtime_caller(runner, other):
        with pytest.raises(RunnerError, match='direct parent'):
            approved_recovery({'alias': interrupted.alias, 'reason': 'x', 'instruction': 'x', 'allowed_scope': 'x',
                               'forbidden_scope': 'x', 'restore_active': True,
                               'caused_by_event_ids': [interrupted.escalation]}, interrupted.root)
        with pytest.raises((ValueError, RunnerError)):
            integrate_task(load_project_configuration(interrupted.root), '83', tuple(VALIDATOR), DIAGNOSIS, 'editor')
    assert read_worldline(interrupted.state, interrupted.root) == before
    assert interrupted.status == 'escalated'


def test_stopped_caller_cannot_dispatch_another_resolver(interrupted: Interrupted) -> None:
    """The old resolver's stop does not block a new entity, but the caller's own stopped subtree does."""
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.execution.runner_batch import parse_batch
    from graphtraj.teams.merge_resolution import require_resolver_redispatch

    parent = next(path.parent.name for path in interrupted.sessions.glob('*/mapping.yml')
                  if path.parent.name != interrupted.alias)
    stopped = run_process(runner_operation(interrupted.commands, 'interrupt', parent),
                          cwd=interrupted.root, env=interrupted.environment)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    configuration = load_project_configuration(interrupted.root)
    record = yaml.safe_load((interrupted.state / 'tasks/83-integration/task.yml').read_text())
    task = parse_batch({'tasks': [{'task_id': '83', 'task_name': 'integration', 'role': 'editor',
                                   'instruction': DIAGNOSIS}]}).tasks[0]
    conflict = {'task_id': '83', 'event': 'task-integration-conflict-started', 'parent': parent,
                'role_reference': 'editor', 'instruction': DIAGNOSIS}
    with pytest.raises(RunnerError, match='stopped subtree'):
        require_resolver_redispatch(configuration, record, [conflict], task, parent)


def test_restore_active_refuses_a_resolver_outside_a_reopenable_integration(interrupted: Interrupted) -> None:
    """Reopening a conflict assignment applies only to an escalated or resolving integration."""
    from graphtraj.graph.task_graph import update_task_state

    record = yaml.safe_load((interrupted.state / 'tasks/83-integration/task.yml').read_text())
    update_task_state(interrupted.state, interrupted.root, {
        key: record[key] for key in ('task_id', 'active_team_ordinal', 'worktree', 'branch', 'current_candidate')
    } | {'status': 'blocked', 'caused_by_event_ids': [interrupted.escalation],
         'evidence_refs': interrupted.events('task-integration-escalated')[-1]['evidence_refs']})
    code, output = interrupted.recover('--restore-active')
    assert code == 1 and output['error']['code'] == 'invalid-input' and 'reopens only' in output['error']['message']
    assert interrupted.events('recovery-applied') == []
    assert interrupted.status == 'blocked'


def test_additional_minutes_on_a_reopened_resolver_still_needs_the_reviewer(
    installed_commands: InstalledCommands, stopped_committed_integration: tuple,
) -> None:
    """A plain caller with no selected reviewer applies nothing, and the budget stop stays."""
    root, _, state, _, _ = stopped_committed_integration
    task = state / 'tasks/83-integration'
    resolver = next(path.parent.name for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml')
                    if yaml.safe_load(path.read_text())['role'] == 'merge-resolver')
    budget = (task / 'execution-budget.yml').read_bytes()
    before = read_worldline(state, root)
    result = run_process([str(installed_commands.runner), 'recover', resolver, '--reason', 'Needs more time',
                          '--instruction', 'Finish this merge', '--allowed-scope', 'The retained conflict',
                          '--forbidden-scope', 'Anything else', '--additional-minutes', '5', '--restore-active',
                          '--caused-by-event-ids', json.dumps([before[-1]['event_id']])], cwd=root)
    assert result.returncode == 1, result.stdout + result.stderr
    assert read_worldline(state, root) == before
    assert (task / 'execution-budget.yml').read_bytes() == budget
    assert yaml.safe_load((task / 'task.yml').read_text())['status'] == 'escalated'
