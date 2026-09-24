"""Report submission is bound to the issuing Session, not a supplied owner."""

from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution import runner_control
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import runtime_caller
from graphtraj.teams.coding import team_replacement


def test_report_submission_uses_only_the_issuers_assignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An assigned filename works; another report or a Main claim cannot write."""
    config = tmp_path / '.graphtraj/config.yml'
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    runner = config.parent / 'runner'
    report = config.parent / 'state/tickets/133-test/teams/1/rounds/1/engineer.md'
    monkeypatch.setattr(runner_control, 'discover_project', lambda *args, **kwargs: None)
    monkeypatch.setattr(team_replacement, 'require_active_session', lambda *args: None)
    monkeypatch.setattr(runner_control, '_session_report_paths',
                        lambda alias, cwd: (report,) if alias == 'owner@e1' else ())
    with runtime_caller(runner, 'owner@e1'):
        result = runner_control.submit_session_report('engineer.md', 'owned report', tmp_path)
        assert result['alias'] == 'owner@e1'
        assert report.read_text() == 'owned report'
        with pytest.raises(RunnerError) as denied:
            runner_control.submit_session_report('../leader.md', 'wrong owner', tmp_path)
        assert denied.value.code == 'authority-denied'
    with runtime_caller(runner, None):
        with pytest.raises(RunnerError) as denied:
            runner_control.submit_session_report('engineer.md', 'not its report', tmp_path)
        assert denied.value.code == 'authority-denied'
    assert report.read_text() == 'owned report'


def test_report_reader_rejects_a_redirected_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared report access cannot follow a link to another report."""
    config = tmp_path / '.graphtraj/config.yml'
    report = config.parent / 'state/tickets/133-test/engineer.md'
    report.parent.mkdir(parents=True)
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    private = report.with_name('other.md')
    private.write_text('synthetic other report')
    report.symlink_to(private)
    mapping = {'parent': 'parent@l1', 'worktree_path': str(tmp_path)}
    request = {'session_parameters': {'config': {'default_permissions': 'p',
                'permissions': {'p': {'filesystem': {str(report): 'read'}}}}}}
    monkeypatch.setattr(runner_control, 'read_alias_mapping', lambda *args: (mapping, report.parent))
    monkeypatch.setattr(runner_control, '_read_session_resume_request', lambda *args: (request, {}, {}))
    monkeypatch.setattr(runner_control, '_team_runtime_environment', lambda *args: {})
    monkeypatch.setattr(runner_control, '_refresh_current_team_report_request',
                        lambda request, *args, **kwargs: request)
    with runtime_caller(config.parent / 'runner', 'parent@l1'):
        with pytest.raises(RunnerError) as denied:
            runner_control.read_session_reports('child@e1', tmp_path)
    assert denied.value.code == 'authority-denied'


def test_direct_parent_reads_terminal_message_without_report_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temporary children expose their completed result only to their parent."""
    config = tmp_path / '.graphtraj/config.yml'
    directory = config.parent / 'runner/sessions/child@e1'
    directory.mkdir(parents=True)
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    (directory / 'execution.yml').write_text(
        'outcome: completed\nterminal_confirmed: true\nlast_agent_message: synthetic-result\n')
    monkeypatch.setattr(runner_control, 'read_alias_mapping',
                        lambda *args: ({'parent': 'parent@l1'}, directory))
    monkeypatch.setattr(runner_control, '_session_report_paths', lambda *args: ())
    with runtime_caller(config.parent / 'runner', 'parent@l1'):
        result = runner_control.read_session_reports('child@e1', tmp_path)
        assert result == {'alias': 'child@e1', 'reports': [], 'last_agent_message': 'synthetic-result'}
    with runtime_caller(config.parent / 'runner', 'sibling@e2'):
        with pytest.raises(RunnerError) as denied:
            runner_control.read_session_reports('child@e1', tmp_path)
        assert denied.value.code == 'authority-denied'
