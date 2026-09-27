"""Current rejections survive member changes without becoming replayable."""

from pathlib import Path

import pytest
import yaml

from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_results import assign_session_reports
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.graph.delivery_state import apply_delivery_state_request, read_team
from graphtraj.graph.delivery_worldline import read_worldline
from graphtraj.interfaces import mcp
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
        mcp.submit_report({'name': 'researcher-x1.md', 'text': 'Original evidence'}, cwd=tmp_path)
        first = mcp.submit_result(arguments, cwd=tmp_path).document
    decision = {'submission_id': first['event_id'], 'commit': commit,
                'decision': 'rejected', 'reason': 'Required conclusion is missing.',
                'evidence_refs': first['evidence_refs']}
    with runtime_caller(runner, parent):
        # Cover both direct rejection and returning a previously accepted result.
        if report_first:
            mcp.decide_result({**decision, 'decision': 'accepted'}, cwd=tmp_path)
        rejected = mcp.decide_result(decision, cwd=tmp_path).document
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
        'phase': 'replace-member', 'ticket_id': '148', 'member': 'first',
        'role': 'researcher', 'session_ref': 'research@x4',
        'caused_by_event_ids': [rejected['event_id']], 'evidence_refs': ['evidence.md'],
    }
    apply_delivery_state_request(state, tmp_path, replacement, replacement)
    replay = {'phase': 'rework', 'ticket_id': '148',
              'caused_by_event_ids': [rejected['event_id']],
              'evidence_refs': rejected['evidence_refs']}
    after_replacement = read_worldline(state, tmp_path)
    for caller in (None, 'research@x1'):
        with runtime_caller(runner, caller):
            with pytest.raises((RunnerError, ValueError)):
                apply_delivery_state_request(state, tmp_path, replay, replay)
            with pytest.raises(RunnerError):
                mcp.submit_result(arguments, cwd=tmp_path)
            with pytest.raises(RunnerError):
                mcp.submit_report({'name': 'researcher-x1.md', 'text': 'Unauthorized'}, cwd=tmp_path)
    assert read_worldline(state, tmp_path) == after_replacement

    with runtime_caller(runner, 'research@x4'):
        if report_first:
            report = mcp.submit_report({'name': reports[0].name, 'text': 'Correction evidence'},
                                       cwd=tmp_path).document['report']
            assert '/rounds/2/' in report
        second = mcp.submit_result(arguments, cwd=tmp_path).document
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
    corrections = [event for event in events if event['kind'] == 'team-round-rework-started']
    assert len(corrections) == 1
    assert corrections[0]['caused_by_event_ids'] == [rejected['event_id']]

    decision = {**decision, 'evidence_refs': second['evidence_refs']}
    with runtime_caller(runner, parent):
        accepted = mcp.decide_result({**decision, 'submission_id': second['event_id'],
                                     'decision': 'accepted'}, cwd=tmp_path).document
    with runtime_caller(runner, 'research@x4'):
        with pytest.raises(ValueError, match='confirmed result rejection'):
            apply_delivery_state_request(state, tmp_path, replay, replay)
        with pytest.raises(ValueError, match='not accepting'):
            mcp.submit_result(arguments, cwd=tmp_path)
    # Even while the Ticket is reworking again, the first rejection is spent.
    with runtime_caller(runner, parent):
        latest = mcp.decide_result({**decision, 'submission_id': second['event_id']},
                                   cwd=tmp_path).document
    with runtime_caller(runner, 'research@x4'):
        with pytest.raises(ValueError, match='confirmed result rejection'):
            apply_delivery_state_request(state, tmp_path, replay, replay)
        third = mcp.submit_result(arguments, cwd=tmp_path).document
    assert third['round'] == 3
    events = read_worldline(state, tmp_path)
    assert accepted in events and latest in events
    corrections = [event for event in events if event['kind'] == 'team-round-rework-started']
    assert [event['caused_by_event_ids'] for event in corrections] == [
        [rejected['event_id']], [latest['event_id']],
    ]
