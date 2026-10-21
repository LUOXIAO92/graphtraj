"""Installed CLI list input on an isolated Task, without launching a Runtime."""

import json
import os
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands
from graphtraj.execution import execution_budget as budgets
from runner_fixtures import configure_harness
from test_task_budget_control import BODY, sample_stop
from test_task_graph import _change_status, _register, _task
from test_task_recovery import command, events, installed_commands


def test_installed_cli_json_event_list_on_unallocated_task(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decode two actual event IDs and preserve them in a real continuation.

    Only the clock/random draw used to create a sampled stop is controlled.
    No native Session, Team seat or real project budget is created or resumed.
    This is isolated administrative CLI evidence, not a Main identity test.
    """
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    definition = _task('160', 'cli-event-list')
    definition['title'] = r'中文数组与字面 \u4e2d、\n'
    definition['body'] = BODY + definition['body']
    _register(installed_commands, root, definition)
    _change_status(installed_commands, root, '160', 'ready')
    causes = [event['event_id'] for event in events(root)][-2:]
    assert len(causes) == 2 and len(set(causes)) == 2
    directory = root / '.graphtraj/state/tasks/160-cli-event-list'
    monitor = budgets.execution_budget_monitor(directory, '160', 'cli-event-list')
    assert not monitor.check('researcher', 'researcher')
    sample_stop(monitor, monkeypatch)
    before = yaml.safe_load((directory / 'execution-budget.yml').read_text())
    arguments = ['continue', '--task-id', '160', '--budget-only',
                 '--caused-by-event-ids', json.dumps(causes)]
    result = command(installed_commands, root, environment, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    response = yaml.safe_load(result.stdout)
    assert response['tasks'] == []
    retained = next(event for event in events(root)
                    if event['event_id'] == response['continuation_event_id'])
    assert retained['caused_by_event_ids'] == causes
    after = yaml.safe_load((directory / 'execution-budget.yml').read_text())
    assert after == dict(before, stopped=False)
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))
    output = os.environ.get('TASK344_CLI_EVIDENCE')
    if output:
        Path(output).write_text(json.dumps({
            'scope': 'Isolated installed CLI operation; not real Main/Runtime acceptance',
            'executable': str(installed_commands.runner), 'argv': arguments,
            'exit_code': result.returncode, 'stdout': result.stdout,
            'stderr': result.stderr, 'retained_event': retained,
            'same_budget_except_sampled_stop': after == dict(before, stopped=False),
            'native_sessions_created': 0,
        }, ensure_ascii=False, indent=2))
