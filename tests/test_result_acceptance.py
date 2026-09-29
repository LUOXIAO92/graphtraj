"""Task acceptance at the public Runner boundary."""

from pathlib import Path
from typing import Any

import pytest

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces import mcp, tools
from graphtraj.runtimes.codex.codex_adapter import native_runner_tools
from test_result_submission import result_project


def test_parent_accepts_document_submission_without_coding_reports(tmp_path: Path) -> None:
    """A parent records a versioned decision using the author's retained evidence."""
    runner, _, commit = result_project(tmp_path, multiple=False)
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({
            'commit': commit, 'result_refs': ['result.md'],
            'evidence_refs': ['result.md'], 'completion': 'Research complete',
        }, cwd=tmp_path).document
    with runtime_caller(runner, None):
        decision = tools.decide_result({
            'submission_id': submission['event_id'], 'commit': commit,
            'decision': 'accepted', 'reason': 'The sources meet the task criteria.',
            'evidence_refs': submission['evidence_refs'],
        }, cwd=tmp_path).document
    assert decision['kind'] == 'team-round-accepted'
    assert decision['candidate'] == commit
    assert decision['submission_id'] == submission['event_id']
    assert submission['event_id'] in decision['caused_by_event_ids']
    assert decision['reason'] == 'The sources meet the task criteria.'


@pytest.mark.parametrize('write_report', [False, True])
def test_rejection_then_corrected_submission_preserves_decision_and_cause(
    tmp_path: Path, write_report: bool,
) -> None:
    """A rejected result remains recorded when the same author submits a correction."""
    import subprocess
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    arguments = {'commit': commit, 'result_refs': ['result.md'],
                 'evidence_refs': ['result.md'], 'completion': 'First result'}
    with runtime_caller(runner, 'research@x1'):
        first = tools.submit_result(arguments, cwd=tmp_path).document
    with runtime_caller(runner, None):
        rejected = tools.decide_result({
            'submission_id': first['event_id'], 'commit': commit, 'decision': 'rejected',
            'reason': 'The result lacks the required conclusion.',
            'evidence_refs': first['evidence_refs'],
        }, cwd=tmp_path).document
    worktree = tmp_path / 'worktrees/research'
    (worktree / 'result.md').write_text('Result including the required conclusion.\n')
    subprocess.run(['git', 'commit', '-am', 'Add conclusion'], cwd=worktree,
                   check=True, capture_output=True)
    corrected = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    with runtime_caller(runner, 'research@x1'):
        if write_report:
            corrected_report = tools.submit_report({'name': 'researcher-x1.md', 'text': 'Correction checked.'},
                                                 cwd=tmp_path).document['report']
            assert '/rounds/2/' in corrected_report
        second = tools.submit_result({**arguments, 'commit': corrected}, cwd=tmp_path).document
    assert second['round'] == 2
    with runtime_caller(runner, None):
        accepted = tools.decide_result({
            'submission_id': second['event_id'], 'commit': corrected, 'decision': 'accepted',
            'reason': 'The conclusion now meets the requirement.',
            'evidence_refs': second['evidence_refs'],
        }, cwd=tmp_path).document
        history = tools.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document
    assert history['submissions'] == [first, second]
    events = read_worldline(tmp_path / 'state', tmp_path)
    assert rejected in events and accepted in events
    causes = {event['event_id']: event['caused_by_event_ids'] for event in events}
    pending = list(causes[second['event_id']])
    ancestors = set()
    while pending:
        ancestor = pending.pop()
        if ancestor not in ancestors:
            ancestors.add(ancestor)
            pending.extend(causes[ancestor])
    assert rejected['event_id'] in ancestors
    assert (tmp_path / first['evidence_refs'][0]).read_text() == 'A versioned research result\n'


def test_decision_rejects_unowned_mismatched_and_superseded_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A role claim, wrong commit, or obsolete submission cannot advance the task."""
    import pytest
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                                        'evidence_refs': ['result.md'], 'completion': 'Done'},
                                       cwd=tmp_path).document
    arguments = {'submission_id': submission['event_id'], 'commit': commit,
                 'decision': 'accepted', 'reason': 'Meets requirements.',
                 'evidence_refs': submission['evidence_refs']}
    before = read_worldline(tmp_path / 'state', tmp_path)
    monkeypatch.setenv('GRAPHTRAJ_ROLE', 'team-leader')
    for caller in ('research@x1', 'research@x2'):
        with runtime_caller(runner, caller), pytest.raises(RunnerError):
            tools.decide_result(arguments, cwd=tmp_path)
    with runtime_caller(runner, None):
        for extra in ({'commit': 'a' * 40}, {'reason': ''}, {'evidence_refs': []},
                      {'evidence_refs': ['absent.md']}, {'decision': 'maybe'},
                      {'alias': 'research@x1'}):
            with pytest.raises((ValueError, RunnerError)):
                tools.decide_result({**arguments, **extra}, cwd=tmp_path)
    assert read_worldline(tmp_path / 'state', tmp_path) == before
    with runtime_caller(runner, 'research@x1'):
        tools.submit_result({'commit': commit, 'result_refs': ['result.md'], 'completion': 'Revised claim'},
                          cwd=tmp_path)
    with runtime_caller(runner, None), pytest.raises(ValueError, match='latest submission'):
        tools.decide_result(arguments, cwd=tmp_path)


def test_actual_parent_decides_with_its_own_retained_evidence(tmp_path: Path) -> None:
    """The actual parent can judge a child and retain evidence independent of report edits."""
    import yaml

    runner, team, commit = result_project(tmp_path)
    mapping_file = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(mapping_file.read_text())
    mapping['parent'] = 'research@x3'
    mapping_file.write_text(yaml.safe_dump(mapping))
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                                        'completion': 'Done'}, cwd=tmp_path).document
    with runtime_caller(runner, 'research@x3'):
        report = tools.submit_report({'name': 'researcher-x3.md', 'text': 'Checked required sources.'},
                                   cwd=tmp_path).document['report']
        decided = tools.decide_result({
            'submission_id': submission['event_id'], 'commit': commit, 'decision': 'accepted',
            'reason': 'The required sources are covered.',
            'evidence_refs': [Path(report).relative_to(tmp_path).as_posix()],
        }, cwd=tmp_path).document
    assert decided['alias'] == 'research@x3'
    assert decided['session'] == 'native-research@x3'
    retained = tmp_path / decided['evidence_refs'][0]
    assert retained != Path(report)
    assert retained.read_text() == 'Checked required sources.'


def test_cli_accepts_code_as_actual_parent_and_mcp_exposes_same_operation(tmp_path: Path) -> None:
    """The CLI attests its process owner and accepts code through the common operation."""
    import io
    import json
    import os
    import subprocess
    import sys
    import yaml
    from graphtraj.execution.runner_heartbeat import hold_ownership

    runner, _, _ = result_project(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    (worktree / 'result.py').write_text('answer = 42\n')
    subprocess.run(['git', 'add', '.'], cwd=worktree, check=True)
    subprocess.run(['git', 'commit', '-m', 'Code result'], cwd=worktree, check=True, capture_output=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree, text=True).strip()
    child = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(child.read_text())
    child.write_text(yaml.safe_dump({**mapping, 'parent': 'research@x3'}))
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result({'commit': commit, 'result_refs': ['result.py'],
                                        'evidence_refs': ['result.py'], 'completion': 'Code complete'},
                                       cwd=tmp_path).document
    directory = runner / 'sessions/research@x3'
    path = directory / 'mapping.yml'
    mapping = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**mapping, 'worker_pid': os.getpid(), 'runtime_pid': os.getpid()}))
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    environment.pop('CODEX_THREAD_ID', None)
    command = [sys.executable, '-c', 'from graphtraj.interfaces.cli.agent_runner import main; main()',
               'decide-result', '--submission-id', submission['event_id'], '--commit', commit,
               '--decision', 'accepted', '--reason', 'The answer satisfies the task.',
               '--evidence-ref', submission['evidence_refs'][0]]
    with hold_ownership(directory, os.getpid()):
        result = subprocess.run(command, cwd=worktree, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    accepted = yaml.safe_load(result.stdout)
    assert accepted['kind'] == 'team-round-accepted'
    assert accepted['alias'] == 'research@x3'
    assert accepted['candidate'] == commit
    graph = tools.read_current_graph({}, cwd=tmp_path).document
    assert graph['tickets'][0]['status'] == 'awaiting-integration'

    output = io.StringIO()
    mcp.serve(io.StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'), output)
    descriptors = json.loads(output.getvalue())['result']['tools']
    descriptor = next(tool for tool in descriptors if tool['name'] == 'decide_result')
    native = next(tool for tool in native_runner_tools() if tool['name'] == 'graphtraj_decide_result')
    assert descriptor['inputSchema'] == native['inputSchema']


def test_changed_worktree_and_closed_submission_cannot_be_accepted_again(tmp_path: Path) -> None:
    """Only the clean submitted version advances, and acceptance closes submission."""
    import pytest
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    arguments = {'commit': commit, 'result_refs': ['result.md'],
                 'evidence_refs': ['result.md'], 'completion': 'Done'}
    with runtime_caller(runner, 'research@x1'):
        submission = tools.submit_result(arguments, cwd=tmp_path).document
    decision = {'submission_id': submission['event_id'], 'commit': commit,
                'decision': 'accepted', 'reason': 'Meets requirements.',
                'evidence_refs': submission['evidence_refs']}
    before = read_worldline(tmp_path / 'state', tmp_path)
    result = worktree / 'result.md'
    original = result.read_bytes()
    result.write_text('Uncommitted change\n')
    with runtime_caller(runner, None), pytest.raises(ValueError, match='Worktree'):
        tools.decide_result(decision, cwd=tmp_path)
    assert read_worldline(tmp_path / 'state', tmp_path) == before
    result.write_bytes(original)
    with runtime_caller(runner, None):
        tools.decide_result(decision, cwd=tmp_path)
        with pytest.raises(ValueError):
            tools.decide_result(decision, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        with pytest.raises(ValueError):
            tools.submit_result(arguments, cwd=tmp_path)
        with pytest.raises(ValueError):
            tools.submit_report({'name': 'researcher-x1.md', 'text': 'After closure'}, cwd=tmp_path)


def test_failed_decision_append_restores_state_reports_and_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write failure cannot leave accepted state without its Worldline decision."""
    import pytest
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Author evidence'}, cwd=tmp_path)
        submission = tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                                        'evidence_refs': ['result.md'], 'completion': 'Done'},
                                       cwd=tmp_path).document
    before = tools.read_current_graph({}, cwd=tmp_path).document
    events = read_worldline(tmp_path / 'state', tmp_path)
    original_open = Path.open

    def fail_append(path: Path, mode: str = 'r', *args: Any, **kwargs: Any):
        """Fail at the durable Worldline boundary after state writes."""
        if mode == 'ab':
            raise OSError('injected append failure')
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patch, runtime_caller(runner, None):
        patch.setattr(Path, 'open', fail_append)
        with pytest.raises(OSError, match='injected append failure'):
            tools.decide_result({'submission_id': submission['event_id'], 'commit': commit,
                               'decision': 'accepted', 'reason': 'Satisfied.',
                               'evidence_refs': submission['evidence_refs']}, cwd=tmp_path)
    assert tools.read_current_graph({}, cwd=tmp_path).document == before
    assert read_worldline(tmp_path / 'state', tmp_path) == events
    assert len(list((team.parent / 'traces/research@x1').iterdir())) == 1
    with runtime_caller(runner, 'research@x1'):
        tools.submit_report({'name': 'researcher-x1.md', 'text': 'Still open'}, cwd=tmp_path)


def test_parent_cannot_retain_an_unassigned_sibling_report(tmp_path: Path) -> None:
    """Acceptance authority does not broaden the deciding Session's file access."""
    import yaml
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    child = runner / 'sessions/research@x1/mapping.yml'
    mapping = yaml.safe_load(child.read_text())
    child.write_text(yaml.safe_dump({**mapping, 'parent': 'research@x3'}))
    with runtime_caller(runner, 'research@x1'):
        submitted = tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                                      'completion': 'Done'}, cwd=tmp_path).document
    with runtime_caller(runner, 'research@x2'):
        report = tools.submit_report({'name': 'researcher-x2.md', 'text': 'Private sibling evidence'},
                                   cwd=tmp_path).document['report']
    before = read_worldline(tmp_path / 'state', tmp_path)
    with runtime_caller(runner, 'research@x3'), pytest.raises(ValueError):
        tools.decide_result({'submission_id': submitted['event_id'], 'commit': commit,
                           'decision': 'accepted', 'reason': 'Done',
                           'evidence_refs': [Path(report).relative_to(tmp_path).as_posix()]}, cwd=tmp_path)
    assert read_worldline(tmp_path / 'state', tmp_path) == before


def test_delivery_state_cli_cannot_bypass_actual_caller_authority(tmp_path: Path) -> None:
    """Identical request/facts files confer no authority on another member."""
    import os
    import subprocess
    import sys
    import yaml
    from graphtraj.execution.runner_heartbeat import hold_ownership
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, _, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        submitted = tools.submit_result({'commit': commit, 'result_refs': ['result.md'],
                                      'evidence_refs': ['result.md'], 'completion': 'Done'},
                                     cwd=tmp_path).document
    request = tmp_path / 'decision.yml'
    request.write_text(yaml.safe_dump({
        'phase': 'final', 'ticket_id': '148', 'candidate': commit,
        'submission_id': submitted['event_id'], 'decision': 'accepted', 'reason': 'Claimed.',
        'caused_by_event_ids': [submitted['event_id']], 'evidence_refs': submitted['evidence_refs'],
    }))
    owner = runner / 'sessions/research@x2'
    mapping = yaml.safe_load((owner / 'mapping.yml').read_text())
    (owner / 'mapping.yml').write_text(yaml.safe_dump({
        **mapping, 'worker_pid': os.getpid(), 'runtime_pid': os.getpid(),
    }))
    before = read_worldline(tmp_path / 'state', tmp_path)
    environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    environment.pop('CODEX_THREAD_ID', None)
    with hold_ownership(owner, os.getpid()):
        result = subprocess.run([
            sys.executable, '-c', 'from graphtraj.interfaces.cli.graphtraj import main; main()',
            'delivery-state', 'apply', '--request-file', str(request), '--facts-file', str(request),
        ], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert read_worldline(tmp_path / 'state', tmp_path) == before
