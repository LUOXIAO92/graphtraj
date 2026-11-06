"""Current rejections survive member changes without becoming replayable."""

import os
from pathlib import Path

import pytest
import yaml

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_results import assign_session_reports
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import tools
from test_result_submission import result_project


@pytest.mark.parametrize('parent', [None, 'research@x3'])
@pytest.mark.parametrize('report_first', [False, True])
def test_replacement_member_corrects_current_rejection(
    tmp_path: Path, parent: str | None, report_first: bool,
) -> None:
    """Root and child replacements use report/result entry with their own identity."""
    runner, team_file, commit = result_project(tmp_path)
    state = tmp_path / 'state'
    old_mapping = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(old_mapping.read_text())
    mapping['parent'] = parent
    old_mapping.write_text(yaml.safe_dump(mapping))
    arguments = {'commit': commit, 'result_refs': ['result.md'],
                 'evidence_refs': ['result.md'], 'completion': 'Result ready'}
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Original evidence'}, cwd=tmp_path)
        first = tools.submit_result(arguments, cwd=tmp_path).document
    decision = {'submission_id': first['event_id'], 'commit': commit,
                'decision': 'rejected', 'reason': 'Required conclusion is missing.',
                'evidence_refs': first['evidence_refs']}
    with runtime_caller(runner, parent):
        # Cover both direct rejection and returning a previously accepted result.
        if report_first:
            tools.decide_result({**decision, 'decision': 'accepted'}, cwd=tmp_path)
        rejected = tools.decide_result(decision, cwd=tmp_path).document
    old_report = team_file.parent / 'rounds/1/researcher-x1.md'
    before = read_worldline(state, tmp_path)

    # Register the fresh binding through the same shared operation used when
    # Runner has created a replacement Session. No Runtime launch is needed here.
    fresh = runner / 'sessions/research@x4'
    fresh.mkdir()
    reports = assign_session_reports('researcher', 'research@x4', 1, 1)
    (fresh / 'mapping.yml').write_text(yaml.safe_dump({
        **mapping, 'alias': 'research@x4', 'session': 'native-replacement',
        'report_files': [str(path) for path in reports],
    }))
    replacement = {
        'phase': 'replace-member', 'task_id': '148', 'member': 'first',
        'role': 'researcher', 'session_ref': 'research@x4',
        'caused_by_event_ids': [rejected['event_id']], 'evidence_refs': ['evidence.md'],
    }
    apply_delivery_state_request(state, tmp_path, replacement, replacement)
    replay = {'phase': 'rework', 'task_id': '148',
              'caused_by_event_ids': [rejected['event_id']],
              'evidence_refs': rejected['evidence_refs']}
    after_replacement = read_worldline(state, tmp_path)
    for caller in (None, 'research@x1'):
        with runtime_caller(runner, caller):
            with pytest.raises((RunnerError, ValueError)):
                apply_delivery_state_request(state, tmp_path, replay, replay)
            with pytest.raises(RunnerError):
                tools.submit_result(arguments, cwd=tmp_path)
            with pytest.raises(RunnerError):
                tools.submit_report({'name': 'researcher-x1.md', 'text': 'Unauthorized'}, cwd=tmp_path)
    assert read_worldline(state, tmp_path) == after_replacement

    with runtime_caller(runner, 'research@x4'):
        if report_first:
            report = tools.submit_report({'name': reports[0].name, 'text': 'Correction evidence'},
                                       cwd=tmp_path).document['report']
            assert '/rounds/2/' in report
        second = tools.submit_result(arguments, cwd=tmp_path).document
        assert second['round'] == 2
        assert second['alias'] == 'research@x4'
        assert second['session'] == 'native-replacement'
        with pytest.raises(ValueError, match='confirmed result rejection'):
            apply_delivery_state_request(state, tmp_path, replay, replay)
    assert read_team(team_file)['current_round'] == 2
    assert old_report.read_text() == 'Original evidence'
    assert not old_report.stat().st_mode & 0o200
    events = read_worldline(state, tmp_path)
    assert events[:len(before)] == before
    corrections = [event for event in events if event['event'] == 'team-round-rework-started']
    assert len(corrections) == 1
    assert corrections[0]['caused_by_event_ids'] == [rejected['event_id']]

    decision = {**decision, 'evidence_refs': second['evidence_refs']}
    with runtime_caller(runner, parent):
        accepted = tools.decide_result({**decision, 'submission_id': second['event_id'],
                                     'decision': 'accepted'}, cwd=tmp_path).document
    with runtime_caller(runner, 'research@x4'):
        with pytest.raises(ValueError, match='confirmed result rejection'):
            apply_delivery_state_request(state, tmp_path, replay, replay)
        with pytest.raises(ValueError, match='not accepting'):
            tools.submit_result(arguments, cwd=tmp_path)
    # Even while the Task is reworking again, the first rejection is spent.
    with runtime_caller(runner, parent):
        latest = tools.decide_result({**decision, 'submission_id': second['event_id']},
                                   cwd=tmp_path).document
    with runtime_caller(runner, 'research@x4'):
        with pytest.raises(ValueError, match='confirmed result rejection'):
            apply_delivery_state_request(state, tmp_path, replay, replay)
        third = tools.submit_result(arguments, cwd=tmp_path).document
    assert third['round'] == 3
    events = read_worldline(state, tmp_path)
    assert accepted in events and latest in events
    corrections = [event for event in events if event['event'] == 'team-round-rework-started']
    assert [event['caused_by_event_ids'] for event in corrections] == [
        [rejected['event_id']], [latest['event_id']],
    ]


def test_closed_round_keeps_nested_directories_enterable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    """Closing a Round freezes every file in its tree and leaves every directory enterable."""
    def writable_again() -> None:
        """Let pytest remove the frozen tree afterwards, whether or not the test passed."""
        for directory, _, _ in os.walk(tmp_path):
            os.chmod(directory, os.stat(directory).st_mode | 0o700)

    request.addfinalizer(writable_again)
    runner, team, commit = result_project(tmp_path)
    child = runner / 'sessions/research@x1/mapping.yml'
    child.write_text(yaml.safe_dump({**yaml.safe_load(child.read_text()), 'parent': 'research@x3'}))
    round_directory = team.parent / 'rounds/1'
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Report'}, cwd=tmp_path)
        submitted = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'],
            'evidence_refs': ['result.md'], 'completion': 'Complete',
        }, cwd=tmp_path).document
    nested = round_directory / 'realhost/rerun'
    nested.mkdir(parents=True)
    (round_directory / 'realhost/host.log').write_text('host log')
    (nested / 'output.txt').write_text('nested output')
    hidden = round_directory / '.claude'
    hidden.mkdir()
    hidden_mode = hidden.stat().st_mode & 0o777
    outside = tmp_path / 'outside.txt'
    outside.write_text('not part of the Round')
    (round_directory / 'realhost/link').symlink_to(outside)
    tree = [round_directory, *sorted(round_directory.rglob('*'))]
    before = {path: path.lstat().st_mode & 0o777 for path in tree}
    decision = {
        'submission_id': submitted['event_id'], 'commit': commit, 'decision': 'accepted',
        'reason': 'The result meets the task criteria.', 'evidence_refs': submitted['evidence_refs'],
    }
    original_open = Path.open

    def fail_append(path: Path, mode: str = 'r', *args: object, **kwargs: object):
        """Fail the Worldline append after the Round has been frozen."""
        if mode == 'ab':
            raise OSError('injected append failure')
        return original_open(path, mode, *args, **kwargs)

    with runtime_caller(runner, 'research@x3'):
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'open', fail_append)
            with pytest.raises(OSError, match='injected append failure'):
                tools.decide_result(decision, cwd=tmp_path)
        # The failed closure restores every mode it changed, nested ones included.
        assert {path: path.lstat().st_mode & 0o777 for path in tree} == before
        tools.decide_result(decision, cwd=tmp_path)
    for directory in (round_directory, round_directory / 'realhost', nested):
        assert directory.stat().st_mode & 0o777 == 0o555, directory
    for path in (round_directory / 'researcher-x1.md', round_directory / 'realhost/host.log',
                 nested / 'output.txt'):
        assert path.stat().st_mode & 0o777 == 0o444, path
    assert sorted(os.listdir(nested)) == ['output.txt']
    assert (nested / 'output.txt').read_text() == 'nested output'
    assert hidden.stat().st_mode & 0o777 == hidden_mode
    assert outside.stat().st_mode & 0o222
