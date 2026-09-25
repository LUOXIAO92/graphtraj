"""Versioned task results through the public Runner tool operations."""

import subprocess
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.execution.runner_results import assign_session_reports
from graphtraj.interfaces import mcp
from test_generic_members import _register_research_team


def result_project(tmp_path: Path) -> tuple[Path, Path, str]:
    """Register actual research members and a committed document result."""
    team = _register_research_team(tmp_path)
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
            'ticket_id': '148', 'team_generation': 1, 'role': 'researcher',
            'parent': None, 'retained_batch_file': 'batch.yml',
            'worktree_path': str(worktree), 'trace_file': 'events.jsonl',
            'worker_pid': 1, 'runtime_pid': 1,
            'report_files': [str(path) for path in assign_session_reports('researcher', alias, 1, 1)],
        }))
    return runner, team, commit


def test_researchers_submit_distinct_retained_results_without_coding_reports(tmp_path: Path) -> None:
    """Each actual author exposes its commit and retained evidence to its parent."""
    runner, team, commit = result_project(tmp_path)
    submissions = []
    for alias, note in [('research@x1', 'First evidence'), ('research@x2', 'Second evidence')]:
        name = f'researcher-{alias.split("@")[1]}.md'
        with runtime_caller(runner, alias):
            report = mcp.submit_report({'name': name, 'text': note}, cwd=tmp_path).document['report']
            submission = mcp.submit_result({
                'commit': commit, 'result_refs': ['result.md'],
                'evidence_refs': [report], 'completion': 'Research complete',
                'unresolved': [],
            }, cwd=tmp_path).document
            submissions.append(submission)
            mcp.submit_report({'name': name, 'text': 'Later work'}, cwd=tmp_path)
        with runtime_caller(runner, None):
            result = mcp.read_reports({'alias': alias}, cwd=tmp_path).document
        assert result['submissions'] == [submission]
        assert submission['session'] == 'native-' + alias
        assert submission['candidate'] == commit
        assert submission['ticket_id'] == '148'
        assert submission['team_ordinal'] == submission['round'] == 1
        assert (tmp_path / submission['evidence_refs'][0]).read_text() == note
    assert submissions[0]['evidence_refs'] != submissions[1]['evidence_refs']
    assert not (team.parent / 'rounds/1/engineer.md').exists()


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
        mcp.submit_report({'name': 'researcher-x2.md', 'text': 'Other member evidence'}, cwd=tmp_path)
    with runtime_caller(runner, None), pytest.raises(RunnerError):
        mcp.submit_result(arguments, cwd=tmp_path)
    with runtime_caller(runner, 'research@x1'):
        for extra in ({'alias': 'research@x2'}, {'ticket_id': 'other'}, {'role': 'engineer'}):
            with pytest.raises(ValueError):
                mcp.submit_result({**arguments, **extra}, cwd=tmp_path)
        for extra in ({'result_refs': ['absent.md']}, {'commit': '0' * 40},
                      {'result_refs': ['../evidence.md']},
                      {'evidence_refs': [str(team.parent / 'rounds/1/researcher-x2.md')]}):
            with pytest.raises((ValueError, RunnerError)):
                mcp.submit_result({**arguments, **extra}, cwd=tmp_path)
    assert read_worldline(state, tmp_path) == before
    request = {'phase': 'retiring', 'ticket_id': '148', 'actor': 'user',
               'caused_by_event_ids': [before[-1]['event_id']], 'evidence_refs': ['evidence.md']}
    apply_delivery_state_request(state, tmp_path, request, request)
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError):
        mcp.submit_result(arguments, cwd=tmp_path)
    trace = team.parent / 'traces/research@x1/events.jsonl'
    trace.parent.mkdir(parents=True)
    trace.write_text('Retained Session trace\n')
    trace_ref = trace.relative_to(tmp_path).as_posix()
    retired = {'phase': 'retired', 'ticket_id': '148', 'session_ref': 'research@x1',
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
    start = {'phase': 'start', 'ticket_id': '148',
             'caused_by_event_ids': [read_worldline(state, tmp_path)[-1]['event_id']],
             'evidence_refs': ['evidence.md'], 'worktree': 'worktrees/research',
             'branch': 'agent/148-research',
             'members': {'new': {'role': 'researcher', 'session_ref': 'research@x4'}}}
    apply_delivery_state_request(state, tmp_path, start, start)
    with runtime_caller(runner, 'research@x1'), pytest.raises(RunnerError):
        mcp.submit_result(arguments, cwd=tmp_path)
    with runtime_caller(runner, 'research@x4'):
        assert mcp.submit_result(arguments, cwd=tmp_path).document['team_ordinal'] == 2


def test_failed_evidence_write_or_event_append_leaves_no_submission(tmp_path: Path, monkeypatch) -> None:
    """Filesystem failure rolls back the new evidence and Worldline fact together."""
    import pytest
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    with runtime_caller(runner, 'research@x1'):
        report = mcp.submit_report({'name': 'researcher-x1.md', 'text': 'Retain me'}, cwd=tmp_path).document['report']
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
                    mcp.submit_result(arguments, cwd=tmp_path)
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
        assert mcp.read_reports({'alias': 'research@x1'}, cwd=tmp_path).document['submissions'] == [submission]


def test_role_assignments_survive_native_followup_permissions(tmp_path: Path) -> None:
    """Same-role members retain distinct exact report permissions on followup."""
    from graphtraj.configuration.project_roles import RolePreset
    from graphtraj.configuration.role_definitions import ResolvedChildRole
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context
    from graphtraj.execution.runner_control import _refresh_current_team_report_request

    runner, team, _ = result_project(tmp_path)
    worktree = tmp_path / 'worktrees/research'
    executable = tmp_path / 'codex-peer'
    executable.write_text('#!/bin/sh\necho --sandbox\n')
    executable.chmod(0o755)
    evidence = team.parents[2]
    requests = []
    for alias in ('research@x1', 'research@x2'):
        mapping = yaml.safe_load((runner / 'sessions' / alias / 'mapping.yml').read_text())
        reports = tuple(Path(path) for path in mapping['report_files'])
        resolved = preflight_runtime_context(
            runtime_store=tmp_path / '.codex', executable=executable,
            git_common_directory=worktree / '.git',
            role=ResolvedChildRole('temporary-role', 'Research.', (),
                                   RolePreset('codex', 'model', None, None)),
            worktree=worktree, evidence=evidence, repository_skill_source=worktree,
            requested_skills=(), report_files=reports,
        ).finalize()
        request = resolved.launch_document()['adapter_request']
        refreshed = _refresh_current_team_report_request(
            request, mapping, worktree, {'GRAPHTRAJ_EVIDENCE': str(evidence)},
        )
        config = refreshed['session_parameters']['config']
        filesystem = config['permissions'][config['default_permissions']]['filesystem']
        own = str(evidence / f'teams/1/rounds/1/researcher-{alias.split("@")[1]}.md')
        assert filesystem[own] == 'read'
        requests.append(filesystem)
    assert str(evidence / 'teams/1/rounds/1/researcher-x2.md') not in requests[0]
    assert str(evidence / 'teams/1/rounds/1/researcher-x1.md') not in requests[1]


def test_new_role_aliases_get_distinct_named_reports(tmp_path: Path) -> None:
    """Native alias entities distinguish repeated role reports without a registry."""
    from graphtraj.graph.delivery_state import apply_delivery_state_request
    from graphtraj.graph.delivery_worldline import read_worldline

    runner, team, commit = result_project(tmp_path)
    base = yaml.safe_load((runner / 'sessions/research@x1/mapping.yml').read_text())
    reports = []
    for number, entity in enumerate(('researcher', 'researcher_2'), 1):
        alias = f'148-research-handover0-researcher@{entity}'
        request = {'phase': 'member', 'ticket_id': '148',
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
            report = mcp.submit_report({'name': assigned[0].name, 'text': entity}, cwd=tmp_path).document
            reports.append(Path(report['report']))
            mcp.submit_result({'commit': commit, 'result_refs': ['result.md'],
                               'completion': 'Done', 'evidence_refs': [report['report']]}, cwd=tmp_path)
    assert reports[0].name == 'researcher.md'
    assert reports[1].name == 'researcher-researcher_2.md'
    assert [path.read_text() for path in reports] == ['researcher', 'researcher_2']
