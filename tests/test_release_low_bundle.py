"""Small release defects, each through the seam its caller reads (Task 438)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

from agent_swarm import bind
from agent_swarm.control import AgentControl
from agent_swarm.pi.execution import PiExecution
from agent_swarm.runtime import RuntimeAdapterError
from graphtraj.interfaces.agents import GraphTrajAgents
from graphtraj.interfaces.cli.graphtraj import main
from conftest import FakeCodex, InstalledCommands, run_process, wait_for_file
from runner_fixtures import configure_harness
from test_claude_host_concurrent_calls import run_mod
from test_team_round import _register_ready_inline_task
from test_agents_connections_presets import RecordingDriver, catalog, configured, create  # noqa: F401
from test_member_child_workspace import RecordingTurn, claimed_main, harness, request  # noqa: F401
from test_pi_generic_execution import generic
from test_pi_runtime import pi_environment  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_a_model_off_the_list_says_where_to_declare_it(tmp_path: Path, catalog: list) -> None:  # noqa: F811
    """A login can serve an id the catalog omits; the error names the field that admits it."""
    root = configured(tmp_path)
    document, failed = create(AgentControl(root, {'claude': RecordingDriver()}),
                              runtime='claude', model='claude-haiku-5-5')
    assert failed and document['error']['code'] == 'invalid-model'
    assert '`models`' in document['error']['message']
    assert str(root / 'config.yml') in document['error']['message']


def test_main_at_the_root_is_refused_a_pi_child_and_told_to_assign_a_workspace(
    harness: SimpleNamespace,  # noqa: F811
) -> None:
    """The refusal stays; its text names the field that resolves it."""
    started = len(RecordingTurn.started)
    created = bind(GraphTrajAgents(harness.root, harness.root), claimed_main(harness))(request('pi'))
    assert created.failed and created.document['error']['code'] == 'RUNTIME_ACCESS_DENIED'
    assert '`workspace`' in created.document['error']['message']
    assert len(RecordingTurn.started) == started


def test_a_suite_without_the_build_backend_stops_at_start(tmp_path: Path) -> None:
    """One clear message before collection, not one fixture error per test."""
    shadow = tmp_path / 'shadow' / 'setuptools'
    shadow.mkdir(parents=True)
    (shadow / '__init__.py').write_text("raise ImportError('setuptools is absent from this venv')\n")
    session = subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q',
         'tests/test_suite_environment.py::test_a_codex_without_the_sandbox_flag_is_refused_as_before'],
        cwd=PROJECT_ROOT, env={**os.environ, 'PYTHONPATH': str(shadow.parent)},
        capture_output=True, text=True, timeout=120,
    )
    output = session.stdout + session.stderr
    assert session.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert 'setuptools.build_meta' in output and 'pip install setuptools' in output
    assert 'passed' not in session.stdout


def test_a_missing_sandbox_tool_reads_as_the_missing_tool(
    tmp_path: Path, pi_environment: dict,  # noqa: F811
) -> None:
    """Pi ended by itself before any prompt: a start failure, whose stop stays uncertified."""
    directory = tmp_path / 'native'
    directory.mkdir()
    turn = PiExecution(generic(tmp_path, pi_environment, sandbox_path='/usr/bin:/bin', provider_domain='p.example'),
                       'unused', directory, lambda *_: None, lambda *_: None, tmp_path / 'trace.jsonl', None)
    with pytest.raises(RuntimeAdapterError) as caught:
        turn.run()
    assert caught.value.code == 'RUNTIME_START_FAILED'
    assert caught.value.message.startswith('Pi did not start: Pi requires installed srt')
    assert caught.value.terminal_confirmed is False


ROLES = """roles:
  sonnet:
    runtime: claude
    model: claude-sonnet-5-5
  mode:
    runtime: claude
    model: claude-opus-5-5
    claude:
      permission_mode: bypassPermissions
  opus:
    runtime: claude
    model: claude-opus-5-5
"""


def test_doctor_reports_the_claude_role_a_launch_would_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor reports the launch's own refusal; a Claude role that can start stays unmentioned."""
    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/roles.yml').write_text(ROLES, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ['doctor'])
    assert result.exit_code == 1, result.output
    assert 'sonnet: Use exact claude-opus-5-5' in result.output
    assert 'mode: claude.permission_mode must be default or auto' in result.output
    assert 'opus:' not in result.output and 'roles: OK' not in result.output


def test_an_end_esc_aborted_is_retried_by_a_later_hook_without_an_error(tmp_path: Path) -> None:
    """Esc rejects the interrupted hook's host calls; the next tick ends exactly that call, silently."""
    run_mod(tmp_path, r'''
const logged = [];
host.ui.log = line => { logged.push(line); };
await handlers.get('session.start')(host, {}, async () => 'started');
const request = {action: 'execute', feature: 'wait', arguments: {agent: 'a'}};
const aborted = {...host, process: {run: async () => { throw new Error('aborted'); }}};
await call('agents')(aborted, {tool: 'mcp__agents__agents', ...request}, async () => ({result: '{}'}));
assert.deepEqual(logged.filter(line => line.includes('cleanup failed')), []);
assert.equal(operations.length, 0);
await timers.shift()();
assert.deepEqual(operations.filter(item => item.operation === 'end'),
                 [{operation: 'end', tool: 'agents', request, session: 'main-session'}]);
// Ended once: a later tick does not send it again.
await timers.shift()();
assert.equal(operations.filter(item => item.operation === 'end').length, 1);
assert.deepEqual(logged.filter(line => line.includes('cleanup failed')), []);
''')


def test_an_end_that_keeps_failing_is_shown_once(tmp_path: Path) -> None:
    """A failure outside the interrupted hook is real, so it stays visible, without repeating."""
    run_mod(tmp_path, r'''
const logged = [];
host.ui.log = line => { logged.push(line); };
await handlers.get('session.start')(host, {}, async () => 'started');
host.process.run = async () => { throw new Error('host gone'); };
await call('agents')(host, {tool: 'mcp__agents__agents', action: 'execute'}, async () => ({result: '{}'}));
await timers.shift()();
await timers.shift()();
assert.equal(logged.filter(line => line.includes('cleanup failed')).length, 1);
''')


def test_a_claude_members_archive_names_the_project_not_its_worktree(tmp_path: Path) -> None:
    """``projectId`` means the Harness Project Root; the working directory is the header's ``cwd``."""
    from graphtraj.runtimes.claude.execution import ClaudeExecution

    project, worktree, directory = tmp_path / 'project', tmp_path / 'project/worktrees/one', tmp_path / 'session'
    worktree.mkdir(parents=True)
    directory.mkdir()
    turn = ClaudeExecution({'harness_root': str(project), 'worktree_path': str(worktree)}, 'x', directory,
                           lambda *_: None, lambda *_: None, tmp_path / 't', None)
    assert turn.extra_fields['graphtraj']['projectId'] == str(project)


def test_a_claude_native_hooks_archive_names_the_project_from_a_subdirectory(tmp_path: Path) -> None:
    """A native Session working below the project root still belongs to that project."""
    from agent_swarm.sessions import JsonlSessionStore, archive_path
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.runtimes.claude.collection import collect_jsonl_hook

    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/config.yml').write_text(default_configuration_content(tmp_path, tmp_path))
    below = tmp_path / 'below'
    below.mkdir()
    transcript = tmp_path / 'native.jsonl'
    transcript.write_text('')
    assert collect_jsonl_hook({'hook_event_name': 'SessionStart', 'session_id': 's', 'source': 'startup',
                               'cwd': str(below), 'transcript_path': str(transcript)}, below)['saved']
    store = JsonlSessionStore(archive_path(tmp_path / '.graphtraj/swarm', 'claude:s'))
    assert store.header['extra_fields']['graphtraj']['projectId'] == str(tmp_path)


def test_a_running_team_is_told_where_a_later_revision_of_its_definition_is(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A revision after dispatch leaves ``.state/task.md`` alone; the prompt's path reaches the new text."""
    root, _, _, environment = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    _register_ready_inline_task(root, installed_commands.product)
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['role_tree']['researcher'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'task_id': '75', 'task_name': 'inline-specialist', 'instruction': 'Inspect.',
        'role': {'researcher': {'runtime': 'codex', 'model': 'gpt-5.6-luna'}}}]}))
    environment['FAKE_CODEX_CAPTURE_STDIN'] = '1'
    launched = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                           cwd=root, env=environment, timeout=10)
    assert launched.returncode == 0, launched.stderr
    wait_for_file(fake_codex.log_file)
    prompt = json.loads(fake_codex.log_file.read_text())['stdin']
    assert '`.state/task.yml`' in prompt and '`current_definition`' in prompt

    definition = yaml.safe_load((root / 'task.yml').read_text())
    revision = root / 'revision.yml'
    revision.write_text(yaml.safe_dump({
        'product_preserving': True, 'caused_by_event_ids': [], 'evidence_refs': ['readiness.md'],
        'tasks': [{**definition, 'body': 'Revised after dispatch.', 'current_definition': 'task.md'}]}))
    revised = run_process([str(installed_commands.product), 'task', 'revise', '--revision-file', str(revision)],
                          cwd=root)
    assert revised.returncode == 0, revised.stderr
    [state] = (root / '.graphtraj').rglob('tasks/75-inline-specialist')
    record = yaml.safe_load((state / 'task.yml').read_text())
    assert (root / record['worktree'] / '.state').resolve() == state.resolve()
    assert 'Revised after dispatch.' not in (state / 'task.md').read_text()
    assert 'Revised after dispatch.' in (state / record['current_definition']).read_text()


CONNECTIONS = {'version': 1, 'runtimes': {'claude': {'runtime': 'claude', 'providers': {'anthropic': {'models': {
    'opus-5_5': {'id': 'claude-opus-5-5', 'source': 'manual'}}}}}}}


def doctor_with_connection_roles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, roles: str):
    """Run doctor with a real user catalog holding this project's real Claude connection."""
    home = tmp_path / 'home'
    (home / '.graphtraj').mkdir(parents=True)
    (home / '.graphtraj/connections.yml').write_text(yaml.safe_dump(CONNECTIONS))
    monkeypatch.setenv('HOME', str(home))
    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/roles.yml').write_text(roles, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(main, ['doctor'])


def test_doctor_passes_a_claude_role_whose_connection_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shape this project's real Claude roles use is not a false failure."""
    result = doctor_with_connection_roles(tmp_path, monkeypatch, """roles:
  opus:
    connection: claude/anthropic/opus-5_5
    reasoning_effort: high
""")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ['roles: OK']


def test_doctor_reports_a_connection_it_cannot_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A launch cannot start this role either, and nothing else names its Runtime."""
    result = doctor_with_connection_roles(tmp_path, monkeypatch, """roles:
  missing:
    connection: claude/anthropic/absent
""")
    assert result.exit_code == 1, result.output
    assert 'missing: Unknown Runtime/provider/model connection reference.' in result.output


def test_doctor_checks_a_claude_role_reached_through_its_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection role has no ``runtime`` until it resolves, so it must not skip the check."""
    result = doctor_with_connection_roles(tmp_path, monkeypatch, """roles:
  mode:
    connection: claude/anthropic/opus-5_5
    claude:
      permission_mode: bypassPermissions
""")
    assert result.exit_code == 1, result.output
    assert 'mode: claude.permission_mode must be default or auto' in result.output
