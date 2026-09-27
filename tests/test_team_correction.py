"""Corrections use shared submission and decision operations for every role."""

import sys
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process


@pytest.mark.parametrize('role', ['engineer', 'researcher'])
def test_public_state_rejects_obsolete_candidate_and_correction(
    tmp_path: Path, installed_commands: InstalledCommands, role: str,
) -> None:
    """Old state requests cannot replace the common submission/decision protocol."""
    from graphtraj.graph.delivery_worldline import read_worldline
    from test_result_submission import result_project

    _, team, commit = result_project(tmp_path)
    before = read_worldline(tmp_path / 'state', tmp_path)
    original = (team.parents[2] / 'ticket.yml').read_bytes()
    request_file = tmp_path / 'request.yml'
    for fields in ({'phase': 'candidate', 'candidate': commit},
                   {'phase': 'correction', 'responsible_role': role,
                    'session_ref': 'research@x1'}):
        request_file.write_text(yaml.safe_dump({
            **fields, 'ticket_id': '148', 'evidence_refs': ['evidence.md'],
            'caused_by_event_ids': [before[-1]['event_id']],
        }))
        result = run_process([
            str(installed_commands.product), 'delivery-state', 'apply', '--request-file', str(request_file),
            '--facts-file', str(request_file),
        ], cwd=tmp_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert 'invalid schema' in result.stderr
    assert (team.parents[2] / 'ticket.yml').read_bytes() == original
    assert read_worldline(tmp_path / 'state', tmp_path) == before


@pytest.mark.parametrize('role', ['engineer', 'researcher'])
@pytest.mark.parametrize('entry', ['runner', 'state-cli'])
def test_common_correction_invalidates_candidate_for_every_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, entry: str,
) -> None:
    """Both retained correction entries preserve history and require new acceptance."""
    import subprocess
    from click.testing import CliRunner
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.graph.delivery_worldline import read_worldline
    from graphtraj.interfaces import mcp
    from graphtraj.interfaces.cli.graphtraj import main
    from test_result_submission import result_project

    runner, team, commit = result_project(tmp_path)
    monkeypatch.delenv('CODEX_THREAD_ID', raising=False)
    # Give the same real member each task role; aliases confer no role authority.
    members = yaml.safe_load(team.read_text())
    members['members']['first']['role'] = role
    team.write_text(yaml.safe_dump(members))
    mapping_file = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping_file.write_text(yaml.safe_dump({**mapping, 'role': role}))
    arguments = {'commit': commit, 'result_refs': ['result.md'],
                 'evidence_refs': ['result.md'], 'completion': 'First result'}
    with runtime_caller(runner, 'research@x1'):
        first = mcp.submit_result(arguments, cwd=tmp_path).document
    decision = {'submission_id': first['event_id'], 'commit': commit,
                'decision': 'rejected', 'reason': 'Missing conclusion.',
                'evidence_refs': first['evidence_refs']}
    with runtime_caller(runner, None):
        rejected = mcp.decide_result(decision, cwd=tmp_path).document
    history = read_worldline(tmp_path / 'state', tmp_path)
    monkeypatch.chdir(tmp_path)
    if entry == 'state-cli':
        request_file = tmp_path / 'rework.yml'
        request_file.write_text(yaml.safe_dump({
            'phase': 'rework', 'ticket_id': '148',
            'caused_by_event_ids': [rejected['event_id']],
            'evidence_refs': rejected['evidence_refs'],
        }))
        command = ['delivery-state', 'apply', '--request-file', str(request_file),
                   '--facts-file', str(request_file)]
        with runtime_caller(runner, None):
            denied = CliRunner().invoke(main, command)
        assert denied.exit_code == 1, denied.output
        assert read_worldline(tmp_path / 'state', tmp_path) == history
        with runtime_caller(runner, 'research@x1'):
            result = CliRunner().invoke(main, command)
        assert result.exit_code == 0, result.output
    else:
        with runtime_caller(runner, 'research@x1'):
            mcp.submit_report({'name': 'researcher-x1.md', 'text': 'Correcting conclusion.'},
                              cwd=tmp_path)
    state = yaml.safe_load((team.parents[2] / 'ticket.yml').read_text())
    assert state['current_candidate'] is None
    assert state['status'] == 'implementing'
    assert yaml.safe_load(team.read_text())['current_round'] == 2
    assert read_worldline(tmp_path / 'state', tmp_path)[:len(history)] == history
    with runtime_caller(runner, None):
        denied = CliRunner().invoke(main, ['ticket', 'integrate', '--ticket-id', '148',
                                          '--', sys.executable, '-c', 'pass'])
        assert denied.exit_code == 1, denied.output
        assert 'requires acceptance' in denied.output
        with pytest.raises(ValueError):
            mcp.decide_result({**decision, 'decision': 'accepted'}, cwd=tmp_path)
    worktree = tmp_path / 'worktrees/research'
    (worktree / 'result.md').write_text('Result with conclusion.\n')
    subprocess.run(['git', 'commit', '-am', 'Correct result'], cwd=worktree,
                   check=True, capture_output=True)
    corrected = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    with runtime_caller(runner, 'research@x1'):
        second = mcp.submit_result({**arguments, 'commit': corrected}, cwd=tmp_path).document
    with runtime_caller(runner, None):
        with pytest.raises(ValueError):
            mcp.decide_result({**decision, 'submission_id': second['event_id'],
                               'decision': 'accepted'}, cwd=tmp_path)
        accepted = mcp.decide_result({
            **decision, 'submission_id': second['event_id'], 'commit': corrected,
            'decision': 'accepted', 'evidence_refs': second['evidence_refs'],
        }, cwd=tmp_path).document
    state = yaml.safe_load((team.parents[2] / 'ticket.yml').read_text())
    assert state['current_candidate'] == accepted['candidate'] == corrected
    assert state['status'] == 'awaiting-integration'
    assert (tmp_path / first['evidence_refs'][0]).read_text() == 'A versioned research result\n'
