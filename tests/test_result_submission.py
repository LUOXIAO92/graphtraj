"""Versioned task results through the public Runner tool operations."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.execution.runner_results import assign_session_reports
from graphtraj.interfaces import tools
from test_generic_members import _register_research_team


def result_project(tmp_path: Path, *, multiple: bool = True) -> tuple[Path, Path, str]:
    """Register actual research members and a committed document result."""
    team = _register_research_team(tmp_path, multiple=multiple)
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    document = yaml.safe_load(default_configuration_content(tmp_path, tmp_path))
    document['paths']['state'] = 'state'
    config.write_text(yaml.safe_dump(document))
    worktree = tmp_path / 'worktrees/research'
    worktree.mkdir(parents=True)
    for args in [('init',), ('config', 'user.email', 'test@example.com'),
                 ('config', 'user.name', 'Test')]:
        subprocess.run(['git', *args], cwd=worktree, check=True, capture_output=True)
    (worktree / 'result.md').write_text('A versioned research result\n')
    subprocess.run(['git', 'add', '.'], cwd=worktree, check=True)
    subprocess.run(['git', 'commit', '-m', 'Result'], cwd=worktree, check=True, capture_output=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    runner = config.parent / 'runner'
    for alias in ('research@x1', 'research@x2', 'research@x3'):
        directory = runner / 'sessions' / alias
        directory.mkdir(parents=True)
        (directory / 'mapping.yml').write_text(yaml.safe_dump({
            'alias': alias, 'runtime': 'codex', 'session': 'native-' + alias,
            'task_id': '148', 'team_generation': 1, 'role': 'researcher',
            'parent': None, 'retained_batch_file': 'batch.yml',
            'worktree_path': str(worktree), 'trace_file': 'events.jsonl',
            'worker_pid': 1, 'runtime_pid': 1,
            'report_files': [str(path) for path in assign_session_reports('researcher', alias, 1, 1)],
        }))
    return runner, team, commit


def test_reports_expose_retained_terminal_diagnostics_only_to_owner(tmp_path: Path) -> None:
    """Expose stop evidence without inventing historical fields or widening access."""
    import pytest
    from graphtraj.execution.runner_models import RunnerError

    runner, _, _ = result_project(tmp_path)
    terminal = runner / 'sessions/research@x1/execution.yml'
    terminal.write_text(yaml.safe_dump({'outcome': 'interrupted', 'budget_stopped': True,
                                       'terminal_confirmed': True}))
    with runtime_caller(runner, None):
        result = tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document
    assert result['execution'] == {
        'outcome': 'interrupted', 'budget_stopped': True, 'terminal_confirmed': True,
    }
    with runtime_caller(runner, 'research@x2'), pytest.raises(RunnerError):
        tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path)
    terminal.write_text(yaml.safe_dump({'outcome': 'interrupted'}))
    with runtime_caller(runner, None):
        result = tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document
    assert result['execution'] == {'outcome': 'interrupted'}
    terminal.write_text(yaml.safe_dump({'outcome': 'runtime-error', 'error': {
        'code': 'RUNTIME_PROVIDER_FAILED', 'message': 'Bearer test-secret-value',
    }}))
    with runtime_caller(runner, None):
        result = tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document
    assert result['execution']['error'] == {
        'code': 'RUNTIME_PROVIDER_FAILED', 'message': 'Bearer [redacted]',
    }


def test_researchers_submit_distinct_retained_results_without_coding_reports(tmp_path: Path) -> None:
    """Each actual author exposes its commit and retained evidence to its parent."""
    runner, team, commit = result_project(tmp_path)
    submissions = []
    for alias, note in [('research@x1', 'First evidence'), ('research@x2', 'Second evidence')]:
        name = f'researcher-{alias.split("@")[1]}.md'
        with runtime_caller(runner, alias):
            report = tools.submit_report({'name': name, 'text': note}, cwd=tmp_path).document['report']
            submission = tools.submit_result({
                'commit': commit, 'result_refs': ['result.md'],
                'evidence_refs': [report], 'completion': 'Research complete',
                'unresolved': [],
            }, cwd=tmp_path).document
            submissions.append(submission)
            tools.submit_report({'name': name, 'text': 'Later work'}, cwd=tmp_path)
        with runtime_caller(runner, None):
            result = tools.read_reports({'alias': alias}, cwd=tmp_path).document
        assert result['submissions'] == [submission]
        assert submission['session'] == 'native-' + alias
        assert submission['candidate'] == commit
        assert submission['task_id'] == '148'
        assert submission['team_ordinal'] == submission['round'] == 1
        assert (tmp_path / submission['evidence_refs'][0]).read_text() == note
    assert submissions[0]['evidence_refs'] != submissions[1]['evidence_refs']
    assert not (team.parent / 'rounds/1/engineer.md').exists()


def test_repeated_unchanged_submission_is_recorded_once(tmp_path: Path) -> None:
    """A retry after an unconfirmed reply returns the recorded submission."""
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Evidence'}, cwd=tmp_path).document['report']
        arguments = {'commit': commit, 'result_refs': ['result.md'], 'evidence_refs': [report],
                     'completion': 'Research complete', 'unresolved': []}
        first = tools.submit_result(arguments, cwd=tmp_path).document
        repeated = tools.submit_result(arguments, cwd=tmp_path).document
        changed = tools.submit_result({**arguments, 'completion': 'Revised'}, cwd=tmp_path).document

    assert repeated == first
    assert changed['event_id'] != first['event_id']
    submitted = [event['event_id'] for event in read_worldline(tmp_path / 'state', tmp_path)
                 if event['event'] == 'result-submitted']
    assert submitted == [first['event_id'], changed['event_id']]


def test_report_can_notify_the_direct_parent(tmp_path: Path, monkeypatch) -> None:
    """A notified report is written first, then sent through the parent notice path."""
    from graphtraj.execution import runner_control

    runner, _, _ = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        plain = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Only written'}, cwd=tmp_path).document
        alone = tools.submit_report({'name': 'researcher-x1.md', 'text': 'No parent',
                                     'notify_parent': True}, cwd=tmp_path).document
    assert 'delivery' not in plain
    assert alone['delivery'] == 'no-direct-parent'
    assert Path(alone['report']).read_text() == 'No parent'

    notices = []

    def notify(directory: Path, message: str, identity: dict) -> dict:
        """Observe the existing child-to-parent notice and its receipt."""
        notices.append((directory.name, message, identity, Path(identity['report']).read_text()))
        return {'delivery': 'received', 'parent': 'research@x2'}

    monkeypatch.setattr(runner_control, 'notify_direct_parent', notify)
    with runtime_caller(runner, 'research@x1'):
        sent = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Needs a decision',
                                    'notify_parent': True}, cwd=tmp_path).document
    assert sent['delivery'] == 'received' and sent['parent'] == 'research@x2'
    # The notice names the report; its text stays in the saved report only.
    assert notices == [('research@x1',
                        'Submitted report researcher-x1.md for its direct parent to handle; '
                        'read it through session_reports: ' + sent['report'],
                        {'type': 'report-submitted', 'report': sent['report']}, 'Needs a decision')]


@pytest.mark.parametrize(('parent', 'runtime', 'outcome', 'parent_input', 'delivered'), [
    ('research@x2', None, 'completed', False, False),
    (None, 'codex', 'completed', False, False),
    ('research@x2', None, 'completed', True, True),
    (None, 'codex', 'completed', True, True),
    ('research@x2', None, 'runtime-error', False, True),
    ('research@x2', None, 'interrupted', False, True),
    (None, 'pi', 'completed', False, True),
    (None, 'claude', 'completed', False, True),
])
def test_only_ordinary_receipts_are_kept_without_a_parent_turn(
    tmp_path: Path, monkeypatch, parent, runtime, outcome, parent_input, delivered,
) -> None:
    """A completed end the parent did not start is retained; every other end is delivered."""
    from graphtraj.execution import runner_control

    runner, _, _ = result_project(tmp_path)
    child = runner / 'sessions/research@x1'
    mapping = yaml.safe_load((child / 'mapping.yml').read_text())
    mapping.update(parent=parent, execution_id='e1')
    if runtime is not None:
        mapping['parent_connection'] = {'runtime': runtime, 'session': 'main-session'}
    (child / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    sent = []
    monkeypatch.setattr(runner_control, 'notify_direct_parent',
                        lambda directory, message, identity: sent.append(identity) or {'delivery': 'received'})

    receipt = runner_control.deliver_execution_end(
        child, mapping, {'outcome': outcome, 'last_agent_message': 'Forwarded.'}, parent_input=parent_input)

    assert bool(sent) is delivered
    assert receipt['delivery'] == ('received' if delivered else 'retained')
    if not delivered:
        record = json.loads((child / 'parent-notices.jsonl').read_text().splitlines()[-1])
        assert record['delivery'] == 'retained' and 'Forwarded.' in json.loads(record['notice'])['message']


def test_submission_rejects_unowned_or_invalid_inputs(tmp_path: Path) -> None:
    """Role claims, foreign reports and absent/obsolete membership grant nothing."""
    import pytest
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.graph.delivery_state import apply_delivery_state_request

    runner, team, commit = result_project(tmp_path)
    arguments = {'commit': commit, 'result_refs': ['result.md'], 'completion': 'Done'}
    state = tmp_path / 'state'
    before = read_worldline(state, tmp_path)
    with runtime_caller(runner, 'research@x2'):
        tools.submit_report({'name': 'researcher-x2.md', 'text': 'Other member evidence'}, cwd=tmp_path)
    with runtime_caller(runner, None), pytest.raises(RunnerError):
        tools.submit_result(arguments, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        for extra in ({'alias': 'research@x2'}, {'task_id': 'other'}, {'role': 'engineer'}):
            with pytest.raises(ValueError):
                tools.submit_result({**arguments, **extra}, cwd=tmp_path)
        for extra in ({'result_refs': ['absent.md']}, {'commit': '0' * 40},
                      {'result_refs': ['../evidence.md']},
                      {'evidence_refs': [str(team.parent / 'rounds/1/researcher-x2.md')]}):
            with pytest.raises((ValueError, RunnerError)):
                tools.submit_result({**arguments, **extra}, cwd=tmp_path)
    assert read_worldline(state, tmp_path) == before
    request = {'phase': 'retiring', 'task_id': '148', 'actor': 'user',
               'caused_by_event_ids': [before[-1]['event_id']], 'evidence_refs': ['evidence.md']}
    apply_delivery_state_request(state, tmp_path, request, request)
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError):
        tools.submit_result(arguments, cwd=tmp_path)
    trace = team.parent / 'traces/research@x1/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.write_text('Retained Session trace\n')
    trace_ref = trace.relative_to(tmp_path).as_posix()
    retired = {'phase': 'retired', 'task_id': '148', 'session_ref': 'research@x1',
               'trace_ref': trace_ref, 'evidence_refs': [trace_ref],
               'caused_by_event_ids': [read_worldline(state, tmp_path)[-1]['event_id']]}
    apply_delivery_state_request(state, tmp_path, retired, retired)
    mapping = yaml.safe_load((runner / 'sessions/research@x1/mapping.yml').read_text())
    fresh = runner / 'sessions/research@x4'
    fresh.mkdir()
    (fresh / 'mapping.yml').write_text(yaml.safe_dump({
        **mapping, 'alias': 'research@x4', 'session': 'native-new', 'team_generation': 2,
        'report_files': [str(path) for path in assign_session_reports('researcher', 'research@x4', 2, 1)],
    }))
    start = {'phase': 'start', 'task_id': '148',
             'caused_by_event_ids': [read_worldline(state, tmp_path)[-1]['event_id']],
             'evidence_refs': ['evidence.md'], 'worktree': 'worktrees/research',
             'branch': 'agent/148-research',
             'members': {'new': {'role': 'researcher', 'session_ref': 'research@x4'}}}
    apply_delivery_state_request(state, tmp_path, start, start)
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError):
        tools.submit_result(arguments, cwd=tmp_path)
    with runtime_caller(runner, 'research@x4'):
        assert tools.submit_result(arguments, cwd=tmp_path).document['team_ordinal'] == 2


def test_failed_evidence_write_or_event_append_leaves_no_submission(tmp_path: Path, monkeypatch) -> None:
    """Filesystem failure rolls back the new evidence and Worldline fact together."""
    import pytest
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Retain me'}, cwd=tmp_path).document['report']
        arguments = {'commit': commit, 'result_refs': ['result.md'],
                     'evidence_refs': [report], 'completion': 'Done'}
        before = read_worldline(tmp_path / 'state', tmp_path)
        original_open = Path.open
        for failing_mode in ('xb', 'ab'):
            def fail_write(path: Path, mode: str = 'r', *args, **kwargs):
                """Inject one filesystem write failure, leaving reads real."""
                if mode == failing_mode:
                    raise OSError('injected write failure')
                return original_open(path, mode, *args, **kwargs)
            with monkeypatch.context() as patch:
                patch.setattr(Path, 'open', fail_write)
                with pytest.raises(OSError, match='injected write failure'):
                    tools.submit_result(arguments, cwd=tmp_path)
            assert read_worldline(tmp_path / 'state', tmp_path) == before
            assert not list((team.parent / 'traces/research@x1').iterdir())
        assert Path(report).read_text() == 'Retain me'


def test_cli_submits_versioned_code_using_real_process_ownership(tmp_path: Path) -> None:
    """The public CLI discovers the caller from its owned process, never flags."""
    import os
    import sys
    from graphtraj.execution.runner_heartbeat import hold_ownership

    runner, _, _ = result_project(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    (worktree / 'result.py').write_text('answer = 42\n')
    (worktree / 'result.tex').write_text('A versioned document.\n')
    subprocess.run(['git', 'add', '.'], cwd=worktree, check=True)
    subprocess.run(['git', 'commit', '-m', 'Code and LaTeX'], cwd=worktree, check=True, capture_output=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    directory = runner / 'sessions/research@x1'
    path = directory / 'mapping.yml'
    mapping = yaml.safe_load(path.read_text())
    mapping.update(worker_pid=os.getpid(), runtime_pid=os.getpid())
    path.write_text(yaml.safe_dump(mapping))
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    environment.pop('CODEX_THREAD_ID', None)
    command = [sys.executable, '-c', 'from graphtraj.interfaces.cli.agent_runner import main; main()',
               'submit-result', '--commit', commit, '--result-ref', 'result.py',
               '--result-ref', 'result.tex', '--evidence-ref', 'result.md', '--completion', 'Done']
    with hold_ownership(directory, os.getpid()):
        result = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    submission = yaml.safe_load(result.stdout)
    assert submission['candidate'] == commit
    assert submission['result_refs'] == ['result.py', 'result.tex']
    assert submission['alias'] == 'research@x1'
    with hold_ownership(directory, os.getpid()):
        read = subprocess.run(command[:3] + ['reports', 'research@x1'], cwd=worktree,
                              env=environment, capture_output=True, text=True)
    assert read.returncode == 0, read.stdout + read.stderr
    assert yaml.safe_load(read.stdout)['submissions'] == [submission]
    with runtime_caller(runner, None):
        assert tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document['submissions'] == [submission]


def test_new_role_aliases_get_distinct_named_reports(tmp_path: Path) -> None:
    """Native alias entities distinguish repeated role reports without a registry."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    base = yaml.safe_load((runner / 'sessions/research@x1/mapping.yml').read_text())
    reports = []
    for number, entity in enumerate(('researcher', 'researcher_2'), 1):
        alias = f'148-research-handover0-researcher@{entity}'
        request = {'phase': 'member', 'task_id': '148',
                   'caused_by_event_ids': [read_worldline(tmp_path / 'state', tmp_path)[-1]['event_id']],
                   'evidence_refs': ['evidence.md'], 'member': f'new{number}',
                   'role': 'researcher', 'session_ref': alias}
        assigned = assign_session_reports('researcher', alias, 1, 1)
        directory = runner / 'sessions' / alias
        directory.mkdir()
        (directory / 'mapping.yml').write_text(yaml.safe_dump({
            **base, 'alias': alias, 'session': f'new-native-{number}',
            'report_files': [str(path) for path in assigned],
        }))
        apply_delivery_state_request(tmp_path / 'state', tmp_path, request, request)
        with runtime_caller(runner, alias):
            report = tools.submit_report({'name': assigned[0].name, 'text': entity}, cwd=tmp_path).document
            reports.append(Path(report['report']))
            tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                               'completion': 'Done', 'evidence_refs': [report['report']]}, cwd=tmp_path)
    assert reports[0].name == 'researcher.md'
    assert reports[1].name == 'researcher-researcher_2.md'
    assert [path.read_text() for path in reports] == ['researcher', 'researcher_2']


def test_untracked_evidence_is_retained_before_worktree_cleanup(tmp_path: Path) -> None:
    """A named untracked attachment survives removal of its Worktree copy."""
    runner, _, commit = result_project(tmp_path)
    attachment = tmp_path / 'worktrees/research/evidence/截图-1.txt'
    attachment.parent.mkdir()
    attachment.write_bytes('桌面证据 \\u4e2d\n'.encode())
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'],
            'evidence_refs': ['evidence/截图-1.txt'], 'completion': 'Done', 'unresolved': [],
        }, cwd=tmp_path).document
        with pytest.raises(ValueError, match='existing Worktree files'):
            tools.submit_result({
                'commit': commit, 'result_refs': ['result.md'],
                'evidence_refs': ['evidence/absent.txt'], 'completion': 'Done', 'unresolved': [],
            }, cwd=tmp_path)
    attachment.unlink()
    retained = tmp_path / submission['evidence_refs'][0]
    assert retained.read_bytes() == '桌面证据 \\u4e2d\n'.encode()


def test_owner_retains_untracked_evidence_for_an_existing_submission(tmp_path: Path) -> None:
    """Retention copies bytes once, adds no submission or decision, and is listed."""
    from graphtraj.execution.runner_control import read_session_reports
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'], 'evidence_refs': [],
            'completion': 'Done', 'unresolved': [],
        }, cwd=tmp_path).document
    attachment = tmp_path / 'worktrees/research/evidence/截图-2.txt'
    attachment.parent.mkdir()
    attachment.write_bytes('桌面证据\n'.encode())
    from graphtraj.configuration.project_configuration import load_project_configuration

    state  = load_project_configuration(tmp_path).state
    before = [event['event'] for event in read_worldline(state, tmp_path)]

    arguments = {'submission_id': submission['event_id'], 'evidence_refs': ['evidence/截图-2.txt']}
    retained  = tools.retain_evidence(arguments, cwd=tmp_path).document
    assert retained['event'] == 'evidence-retained'
    assert retained['caused_by_event_ids'] == [submission['event_id']]
    assert tools.retain_evidence(arguments, cwd=tmp_path).document == retained
    after = [event['event'] for event in read_worldline(state, tmp_path)]
    assert after == [*before, 'evidence-retained']

    attachment.unlink()
    copy, = retained['evidence_refs']
    assert (tmp_path / copy).read_bytes() == '桌面证据\n'.encode()
    listed = read_session_reports('research@x1', tmp_path)['submissions']
    assert [event['event_id'] for event in listed] == [submission['event_id'], retained['event_id']]
    with pytest.raises(ValueError, match='Unknown result submission'):
        tools.retain_evidence({**arguments, 'submission_id': 'absent'}, cwd=tmp_path)


def test_runtime_write_markers_in_task_state_do_not_block_delivery(tmp_path: Path) -> None:
    """A Runtime's hidden ``.claude/.cc-writes`` marker anywhere in Task state is foreign."""
    from graphtraj.graph.task_graph import read_graph

    runner, team, commit = result_project(tmp_path)
    task = team.parent.parent.parent
    markers = [parent / '.claude/.cc-writes' for parent in (
        tmp_path / 'state', tmp_path / 'state/tasks', task, task / 'definitions', task / 'teams',
        team.parent, team.parent / 'rounds', team.parent / 'rounds/1',
    )]
    for marker in markers:
        marker.mkdir(parents=True, exist_ok=True)
    with runtime_caller(runner, 'research@x1'):
        report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Evidence'}, cwd=tmp_path)
        submitted = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'],
            'evidence_refs': [report.document['report']], 'completion': 'Done',
        }, cwd=tmp_path).document
    with runtime_caller(runner, None):
        decided = tools.decide_result({
            'submission_id': submitted['event_id'], 'commit': commit, 'decision': 'accepted',
            'reason': 'Meets the criteria.', 'evidence_refs': submitted['evidence_refs'],
        }, cwd=tmp_path).document
    assert decided['event'] == 'team-round-accepted'
    assert [task['task_id'] for task in read_graph(tmp_path / 'state')['tasks']] == ['148']
    assert all(marker.is_dir() for marker in markers)


def test_decision_cites_task_state_records_but_not_runner_or_unrelated_files(tmp_path: Path) -> None:
    """A mapped decider may cite member reports and integration evidence by Harness-relative path."""
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    child = runner / 'sessions/research@x1/mapping.yml'
    child.write_text(yaml.safe_dump({**yaml.safe_load(child.read_text()), 'parent': 'research@x3'}))
    with runtime_caller(runner, 'research@x2'):
        other = tools.submit_report({'name': 'researcher-x2.md', 'text': 'Other member'}, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        submitted = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'], 'completion': 'Done',
        }, cwd=tmp_path).document
    task = team.parent.parent.parent
    (task / 'integration-evidence').mkdir()
    (task / 'integration-evidence/main-adoption.txt').write_text('Main adoption record\n')
    runner_record = team.parent / 'traces/research@x1/runner/claude-settings.yml'
    runner_record.parent.mkdir(parents=True)
    runner_record.write_text('env: {}\n')
    (tmp_path / 'notes.txt').write_text('Unrelated\n')
    (tmp_path / 'worktrees/research/draft.md').write_text('Uncommitted\n')
    (tmp_path / 'docs/specs').mkdir(parents=True)
    (tmp_path / 'docs/specs/spec.md').write_text('Harness Project Document\n')
    worldline = next((tmp_path / 'state/worldline').glob('*.jsonl'))
    decision = {'submission_id': submitted['event_id'], 'commit': commit,
                'decision': 'rejected', 'reason': 'Needs a source comparison.'}
    before = read_worldline(tmp_path / 'state', tmp_path)
    with runtime_caller(runner, 'research@x3'):
        for refused in (runner_record, runner / 'sessions/research@x1/mapping.yml',
                        tmp_path / 'notes.txt', tmp_path / 'worktrees/research/draft.md'):
            with pytest.raises(ValueError, match='Decision evidence') as error:
                tools.decide_result({**decision, 'evidence_refs': [
                    refused.relative_to(tmp_path).as_posix()]}, cwd=tmp_path)
            assert 'subpath' not in str(error.value)
        with pytest.raises(ValueError, match='does not exist'):
            tools.decide_result({**decision, 'evidence_refs': [
                (task / 'integration-evidence').relative_to(tmp_path).as_posix()]}, cwd=tmp_path)
        assert read_worldline(tmp_path / 'state', tmp_path) == before
        cited = [Path(other.document['report']).relative_to(tmp_path).as_posix(),
                 (task / 'integration-evidence/main-adoption.txt').relative_to(tmp_path).as_posix(),
                 'docs/specs/spec.md', worldline.relative_to(tmp_path).as_posix()]
        decided = tools.decide_result({**decision, 'evidence_refs': cited}, cwd=tmp_path).document
    assert decided['event'] == 'team-round-implementation-rejected'
