"""An accepting parent can return an accepted result before integration."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import tools
from graphtraj.interfaces.cli.agent_runner import main as runner_main
from graphtraj.interfaces.cli.graphtraj import main
from test_result_submission import result_project


def accepted_result(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    """Retain a document and acceptance by its actual, non-top-level parent."""
    runner, team, commit = result_project(tmp_path)
    child = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(child.read_text())
    child.write_text(yaml.safe_dump({**mapping, 'parent': 'research@x3'}))
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Original evidence'}, cwd=tmp_path)
        submitted = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'],
            'evidence_refs': ['result.md'], 'completion': 'Complete',
        }, cwd=tmp_path).document
    decision = {
        'submission_id': submitted['event_id'], 'commit': commit, 'decision': 'accepted',
        'reason': 'The result meets the task criteria.', 'evidence_refs': submitted['evidence_refs'],
    }
    with runtime_caller(runner, 'research@x3'):
        accepted = tools.decide_result(decision, cwd=tmp_path).document
    return runner, team, decision, accepted


@pytest.mark.parametrize('entry', ['mcp', 'cli'])
def test_accepted_result_correction_and_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str,
) -> None:
    """A precommitted correction keeps old evidence and requires fresh acceptance."""
    runner, team, decision, accepted = accepted_result(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('CODEX_THREAD_ID', raising=False)
    worktree = tmp_path / 'worktrees/research'
    configuration = tmp_path / '.graphtraj/config.yml'
    config = yaml.safe_load(configuration.read_text())
    config['paths'].update(project_root='source', agent_worktrees='worktrees')
    configuration.write_text(yaml.safe_dump(config))
    subprocess.run(['git', 'worktree', 'add', '--detach', str(tmp_path / 'source')],
                   cwd=worktree, check=True, capture_output=True)
    subprocess.run(['git', 'worktree', 'add', '-b', 'dev', str(tmp_path / 'worktrees/dev')],
                   cwd=worktree, check=True, capture_output=True)
    (worktree / 'result.md').write_text('Corrected conclusion supported by the sources.\n')
    subprocess.run(['git', 'commit', '-am', 'Correct conclusion'], cwd=worktree,
                   check=True, capture_output=True)
    corrected = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    rejection = {**decision, 'decision': 'rejected',
                 'reason': 'New source comparison shows the retained conclusion is unsupported.'}
    before = read_worldline(tmp_path / 'state', tmp_path)
    old_report = team.parent / 'rounds/1/researcher-x1.md'
    with runtime_caller(runner, 'research@x3'):
        if entry == 'mcp':
            returned = tools.decide_result(rejection, cwd=tmp_path).document
        else:
            response = CliRunner().invoke(runner_main, [
                'decide-result', '--submission-id', decision['submission_id'],
                '--commit', decision['commit'], '--decision', 'rejected',
                '--reason', rejection['reason'], '--evidence-ref', decision['evidence_refs'][0],
            ])
            assert response.exit_code == 0, response.output
            returned = yaml.safe_load(response.output)
        with pytest.raises(ValueError):
            tools.decide_result(rejection, cwd=tmp_path)
    assert accepted['event_id'] in returned['caused_by_event_ids']
    assert read_worldline(tmp_path / 'state', tmp_path)[:len(before)] == before
    assert old_report.read_text() == 'Original evidence'
    assert not old_report.stat().st_mode & 0o200
    integrate = ['task', 'integrate', '--task-id', '148', '--', sys.executable, '-c', 'pass']
    with runtime_caller(runner, None):
        denied = CliRunner().invoke(main, integrate)
        assert denied.exit_code == 1, denied.output
        assert 'requires acceptance' in denied.output
    with runtime_caller(runner, 'research@x1'):
        if entry == 'cli':
            report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Correction checked'},
                                       cwd=tmp_path).document['report']
            assert '/rounds/2/' in report
        submitted = tools.submit_result({
            'commit': corrected, 'result_refs': ['result.md'], 'evidence_refs': ['result.md'],
            'completion': 'Corrected the unsupported conclusion.',
        }, cwd=tmp_path).document
    assert submitted['round'] == 2
    with runtime_caller(runner, None):
        denied = CliRunner().invoke(main, integrate)
        assert denied.exit_code == 1, denied.output
    with runtime_caller(runner, 'research@x3'):
        for obsolete in (decision, {**decision, 'submission_id': submitted['event_id']}):
            with pytest.raises(ValueError):
                tools.decide_result(obsolete, cwd=tmp_path)
        fresh = tools.decide_result({
            **decision, 'submission_id': submitted['event_id'], 'commit': corrected,
            'evidence_refs': submitted['evidence_refs'],
        }, cwd=tmp_path).document
        failed = CliRunner().invoke(main, [*integrate[:-1], 'raise SystemExit(1)'])
        assert yaml.safe_load(failed.output)['status'] == 'integrating'
        with pytest.raises(ValueError):
            tools.decide_result({**rejection, 'submission_id': submitted['event_id'],
                               'commit': corrected}, cwd=tmp_path)
        integrated = CliRunner().invoke(main, integrate)
    assert integrated.exit_code == 0, integrated.output
    assert yaml.safe_load(integrated.output)['candidate'] == corrected
    assert (tmp_path / 'worktrees/dev/result.md').read_text() == (worktree / 'result.md').read_text()
    events = read_worldline(tmp_path / 'state', tmp_path)
    started = next(event for event in events if event['event'] == 'task-integration-started')
    assert started['caused_by_event_ids'] == [fresh['event_id']]
    assert accepted in events and returned in events
    assert (tmp_path / decision['evidence_refs'][0]).read_text() == 'A versioned research result\n'
    with runtime_caller(runner, 'research@x3'), pytest.raises(ValueError):
        tools.decide_result({**rejection, 'submission_id': submitted['event_id'], 'commit': corrected},
                          cwd=tmp_path)


def test_return_requires_parent_exact_version_reason_and_evidence(tmp_path: Path) -> None:
    """Unowned, unsupported and mismatched returns leave acceptance unchanged."""
    runner, _, decision, _ = accepted_result(tmp_path)
    rejection = {**decision, 'decision': 'rejected', 'reason': 'New evidence contradicts the conclusion.'}
    before = read_worldline(tmp_path / 'state', tmp_path)
    for caller in (None, 'research@x1', 'research@x2'):
        with runtime_caller(runner, caller), pytest.raises(RunnerError):
            tools.decide_result(rejection, cwd=tmp_path)
    with runtime_caller(runner, 'research@x3'):
        for extra in ({'commit': 'a' * 40}, {'submission_id': 'missing'}, {'decision': 'accepted'},
                      {'reason': ''}, {'evidence_refs': []}, {'evidence_refs': ['missing.md']}):
            with pytest.raises((ValueError, RunnerError)):
                tools.decide_result({**rejection, **extra}, cwd=tmp_path)
    assert read_worldline(tmp_path / 'state', tmp_path) == before


def test_failed_return_preserves_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed event retention rolls back the return and keeps closed reports intact."""
    runner, team, decision, _ = accepted_result(tmp_path)
    before = read_worldline(tmp_path / 'state', tmp_path)
    graph = tools.read_current_graph({}, cwd=tmp_path).document
    original_open = Path.open

    def fail_append(path: Path, mode: str = 'r', *args: Any, **kwargs: Any):
        """Fail the Worldline append after the decision state has been written."""
        if mode == 'ab':
            raise OSError('injected append failure')
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch, runtime_caller(runner, 'research@x3'):
        patch.setattr(Path, 'open', fail_append)
        with pytest.raises(OSError, match='injected append failure'):
            tools.decide_result({**decision, 'decision': 'rejected', 'reason': 'Contradicting source found.'},
                              cwd=tmp_path)
    assert read_worldline(tmp_path / 'state', tmp_path) == before
    assert tools.read_current_graph({}, cwd=tmp_path).document == graph
    assert not (team.parent / 'rounds/1/researcher-x1.md').stat().st_mode & 0o200


def test_task_update_cannot_return_an_accepted_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic state command cannot bypass the accepting parent's decision."""
    runner, team, _, accepted = accepted_result(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('CODEX_THREAD_ID', raising=False)
    task = yaml.safe_load((team.parents[2] / 'task.yml').read_text())
    request = {key: task[key] for key in (
        'task_id', 'active_team_ordinal', 'worktree', 'branch', 'current_candidate',
    )}
    request.update(status='reworking', caused_by_event_ids=[accepted['event_id']],
                   evidence_refs=accepted['evidence_refs'])
    path = tmp_path / 'return.yml'
    path.write_text(yaml.safe_dump(request))
    before = read_worldline(tmp_path / 'state', tmp_path)
    with runtime_caller(runner, 'research@x2'):
        denied = CliRunner().invoke(main, ['task', 'update', '--state-file', str(path)])
    assert denied.exit_code == 1, denied.output
    assert "requires its parent's result decision" in denied.output
    assert read_worldline(tmp_path / 'state', tmp_path) == before


def test_explicit_reopening_of_integrated_file_task_requires_new_result_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph reopening preserves the integrated version and starts an actual correction Round."""
    from test_task_node_protocol import task

    runner, team, decision, accepted = accepted_result(tmp_path)
    monkeypatch.chdir(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    configuration = tmp_path / '.graphtraj/config.yml'
    config = yaml.safe_load(configuration.read_text())
    config['paths'].update(project_root='source', agent_worktrees='worktrees')
    configuration.write_text(yaml.safe_dump(config))
    for args in [('worktree', 'add', '--detach', str(tmp_path / 'source')),
                 ('worktree', 'add', '-b', 'dev', str(tmp_path / 'worktrees/dev'))]:
        subprocess.run(['git', *args], cwd=worktree, check=True, capture_output=True)
    old = tools.read_current_graph({}, cwd=tmp_path).document['tasks'][0]
    definition = {key: old[key] for key in ('task_id', 'task_name', 'source', 'title', 'body', 'dependencies')}
    definition.update(schema_version=2, parent_id=None, disposition='active', replaced_by=[], retirement_reason=None,
                      current_definition=old['current_definition'])
    revision = {'product_preserving': True, 'caused_by_event_ids': [], 'evidence_refs': ['evidence.md'],
                'tasks': [definition]}
    with runtime_caller(runner, None):
        tools.revise_current_tasks(revision)
    integrate = ['task', 'integrate', '--task-id', '148', '--', sys.executable, '-c', 'pass']
    with runtime_caller(runner, 'research@x3'):
        integrated = CliRunner().invoke(main, integrate)
    assert integrated.exit_code == 0, integrated.output
    old_report = team.parent / 'rounds/1/researcher-x1.md'
    original = old_report.read_bytes()
    current = tools.read_current_graph({}, cwd=tmp_path).document['tasks'][0]
    definition['current_definition'] = current['current_definition']
    revision.update(tasks=[definition, {**task('149', '148'), 'current_definition': None}],
                    reopen_task_ids=['148'])
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError):
        tools.revise_current_tasks(revision)
    with runtime_caller(runner, 'research@x3'):
        tools.revise_current_tasks(revision)
        denied = CliRunner().invoke(main, integrate)
    assert denied.exit_code == 1
    nodes = {node['task_id']: node for node in tools.read_current_graph({}, cwd=tmp_path).document['tasks']}
    assert nodes['148']['status'] == 'reworking'
    assert nodes['148']['current_candidate'] == decision['commit']
    with runtime_caller(runner, 'research@x1'), pytest.raises(ValueError):
        tools.complete_current_task({
            'task_id': '149', 'current_definition': 'task.md',
            'reason': 'A member cannot self-accept a pure summary', 'cancelled_scope': {},
            'evidence_refs': ['evidence.md'], 'caused_by_event_ids': [],
        })
    with runtime_caller(runner, None):
        tools.complete_current_task({
            'task_id': '149', 'current_definition': 'task.md',
            'reason': 'The added child scope has been independently accepted', 'cancelled_scope': {},
            'evidence_refs': ['evidence.md'], 'caused_by_event_ids': [],
        })
    (worktree / 'result.md').write_text('The integrated scope now includes the newly accepted child.\n')
    subprocess.run(['git', 'commit', '-am', 'Complete reopened task'], cwd=worktree, check=True, capture_output=True)
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    with runtime_caller(runner, 'research@x1'):
        report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'New scope checked'}, cwd=tmp_path).document
        assert '/rounds/2/' in report['report']
        submission = tools.submit_result({'commit': candidate, 'result_refs': ['result.md'],
                                          'evidence_refs': ['result.md'], 'completion': 'New scope delivered'},
                                         cwd=tmp_path).document
    assert submission['round'] == 2 and old_report.read_bytes() == original
    with runtime_caller(runner, 'research@x3'):
        tools.decide_result({**decision, 'submission_id': submission['event_id'], 'commit': candidate,
                             'evidence_refs': submission['evidence_refs']}, cwd=tmp_path)
        integrated = CliRunner().invoke(main, integrate)
    assert integrated.exit_code == 0, integrated.output
    assert yaml.safe_load(integrated.output)['candidate'] == candidate
    assert accepted in read_worldline(tmp_path / 'state', tmp_path)
