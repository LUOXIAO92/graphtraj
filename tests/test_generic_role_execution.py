"""Configured roles execute through the same public task launch interface."""

import json
import shutil
import time
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_project_setup import CODING_METHOD_SKILL_NAMES
from test_ticket_graph import _change_status, _register, _ticket


def remove_coding_method_skills(root: Path, user_home: Path) -> None:
    """Leave a project whose work selected none of the coding methods."""
    for name in CODING_METHOD_SKILL_NAMES:
        harness_skill = root / '.agents' / 'skills' / name
        if harness_skill.exists():
            shutil.rmtree(harness_skill)
        shutil.rmtree(user_home / '.agents' / 'skills' / name)


def wait_for_idle(commands: InstalledCommands, root: Path, env: dict, alias: str) -> dict:
    """Observe this test's native execution through bounded public status calls."""
    for _ in range(100):
        result = run_process([str(commands.runner), 'status', alias], cwd=root, env=env)
        assert result.returncode == 0, result.stderr
        status = yaml.safe_load(result.stdout)['aliases'][0]
        if status['activity'] == 'idle':
            assert status['last_outcome'] == 'completed', status
            return status
        time.sleep(.05)
    raise AssertionError(status)


@pytest.mark.parametrize('role, coding_methods, reports, instruction_file', [
    ('researcher', True, [], None), ('engineer', False, [], None),
    ('researcher', False, [], None),
    ('research_team.team_leader', False, [], None), ('spec_reviewer', False, [], None),
    ('engineer', False, ['findings.md', 'evidence.md'], None),
    ('engineer-expert', False, [], None),
    ('coding-team.engineer-junior', False, [], None),
    ('engineer-senior', False, [], None),
    ('translator', False, [], 'relative'),
    ('translator', False, [], 'absolute'),
])
def test_single_role_launch_registers_and_executes_without_placeholder_members(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    role: str,
    coding_methods: bool,
    reports: list[str],
    instruction_file: str | None,
) -> None:
    """An authorized lone author runs, with its real membership and own Trace.

    The last case installs no coding method: an author that selects none of
    them still runs, leaving discovery of same-name Skills to its Runtime.
    """
    skill = temporary_git_repository / '.agents/skills/selected/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: selected\ndescription: Task-selected method.\n---\n')
    duplicate = temporary_git_repository / '.agents/skills/duplicate/SKILL.md'
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text('---\nname: selected\ndescription: Another native choice.\n---\n')
    run_process(['git', 'add', '.agents'], cwd=temporary_git_repository).check_returncode()
    run_process(['git', 'commit', '-m', 'Task Skill'], cwd=temporary_git_repository).check_returncode()
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    if not coding_methods:
        remove_coding_method_skills(root, tmp_path / 'operator-home')
    preset = {'runtime': 'codex', 'model': 'configured-author', 'reports': reports}
    external_text = 'Translate café.\nrequired_skills: [uninstalled-method]\n'
    if instruction_file:
        instruction_path = (
            root / 'role instructions.txt' if instruction_file == 'relative'
            else tmp_path / 'outside-role.txt'
        )
        instruction_path.write_text(external_text, encoding='utf-8')
        preset['instructions'] = instruction_path.name if instruction_file == 'relative' else str(instruction_path)
    group, _, name = role.rpartition('.')
    roles = {group: {name: preset}} if group else {role: preset}
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles,
        'role_tree': {role: {}},
    }))
    _register(installed_commands, root, _ticket('150', 'formal-author'))
    _change_status(installed_commands, root, '150', 'ready')
    original = Path(__file__).with_name('runner_codex_peer.py')
    peer = tmp_path / 'author-peer.py'
    peer.write_text(original.read_text().replace("    elif method == 'turn/start':\n", """    elif method == 'turn/start':
        import yaml
        root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
        alias = os.environ['GRAPHTRAJ_PARENT_ALIAS']
        mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())
        evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
        team = yaml.safe_load((evidence / 'teams/1/team.yml').read_text())
        assert len(team['members']) == 1
        assert next(iter(team['members'].values()))['session_ref'] == alias
        os.environ['AUTHOR_REPORTS'] = ','.join(Path(path).name for path in mapping['report_files'])
"""))
    scenario = Path(__file__).with_name('generic_role_scenario.py')
    code = fake_codex.executable.read_text().replace("'session_name': 'fake-thread'", "'session_name': os.environ['GRAPHTRAJ_PARENT_ALIAS']").replace(str(original), str(peer))
    code = code.replace("lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')",
                        'import runpy; runpy.run_path(' + repr(str(scenario)) + ')\nraise SystemExit(0)')
    fake_codex.executable.write_text(code)
    env['FAKE_CODEX_APPEND_LOG'] = '1'
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'role': role, 'ticket_id': '150'}]}))
    result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                         cwd=root, env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    task = yaml.safe_load(result.stdout)['tasks'][0]
    assert task['launch_status'] == 'launched'
    wait_for_idle(installed_commands, root, env, task['alias'])
    ticket = root / '.graphtraj/state/tickets/150-formal-author'
    state = yaml.safe_load((ticket / 'ticket.yml').read_text())
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert {member['role'] for member in team['members'].values()} == {role.rpartition('.')[2].replace('_', '-')}
    assert state['status'] != 'integrated' and state['current_candidate'] is None
    assert (ticket / 'teams/1/traces' / task['alias'] / 'events.jsonl').read_text()
    events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
              for line in shard.read_text().splitlines()]
    assert sum(event['kind'] == 'team-started' for event in events) == 1

    worktree = Path(task['worktree_path'])
    assert (worktree / 'result.md').is_file() and (worktree / 'result.tex').is_file()
    response = run_process([str(installed_commands.runner), 'reports', task['alias']], cwd=root, env=env)
    assert response.returncode == 0, response.stdout + response.stderr
    assert len(yaml.safe_load(response.stdout)['submissions']) == 1
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    settings = {}
    for index, arg in enumerate(records[0]['argv'][:-1]):
        if arg == '-c':
            settings.update(tomllib.loads(records[0]['argv'][index + 1]))
    if instruction_file:
        assert settings['developer_instructions'].startswith(external_text)
    assert 'skills' not in settings
    assert (worktree / '.agents/skills/selected/SKILL.md').is_file()
    assert (worktree / '.agents/skills/duplicate/SKILL.md').is_file()
    permission = settings['permissions'][settings['default_permissions']]['filesystem']
    assert permission[':workspace_roots']['.'] == 'write'
    mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / task['alias'] / 'mapping.yml').read_text())
    assert mapping['role_reference'] == role
    launch = yaml.safe_load((root / '.graphtraj/runner/sessions' / task['alias'] / 'launch.yml').read_text())
    assert launch['context_evidence']['model'] == 'configured-author'
    expected = reports or [role.rpartition('.')[2].replace('_', '-') + '.md']
    assert [Path(path).name for path in mapping['report_files']] == expected
    assert permission[str(root / '.graphtraj/state')] == 'none'
    before = (ticket / 'teams/1/traces' / task['alias'] / 'events.jsonl').read_bytes()
    sent = run_process([str(installed_commands.runner), 'send', task['alias'],
                        '--instruction', 'Continue the same research.', '--caused-by-event-id', events[-1]['event_id']],
                       cwd=root, env=env, timeout=20)
    assert sent.returncode == 0, sent.stdout + sent.stderr
    # This is a bounded development test wait for its own controlled Runtime.
    for _ in range(100):
        status = run_process([str(installed_commands.runner), 'status', task['alias']], cwd=root, env=env)
        observed = yaml.safe_load(status.stdout)['aliases'][0]
        if observed['activity'] == 'idle':
            break
        time.sleep(.05)
    assert observed['last_outcome'] == 'completed', observed
    assert observed['session'] == task['session']
    assert (worktree / 'visits.txt').read_text() == '2'
    assert (ticket / 'teams/1/traces' / task['alias'] / 'events.jsonl').read_bytes().startswith(before)
    reports = run_process([str(installed_commands.runner), 'reports', task['alias']], cwd=root, env=env)
    assert len(yaml.safe_load(reports.stdout)['submissions']) == 2


@pytest.mark.parametrize('surface', ['cli', 'mcp'])
@pytest.mark.parametrize('parent_role, child_role, historical', [
    ('researcher', 'analyst', False), ('team-leader', 'analyst', False),
    ('engineer', 'analyst', False), ('engineer-expert', 'engineer-junior', False),
    ('coding-team.engineer', 'analyst', True),
])
def test_configured_parent_dispatch_and_ordinary_resume_keep_actual_authority(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    parent_role: str,
    child_role: str,
    historical: bool,
) -> None:
    """Role-tree edges grant dispatch, while same-role peers cannot control instances."""
    import sys
    from graphtraj.interfaces import tools

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    actual_parent = parent_role.rpartition('.')[2]
    roles = {role: {'runtime': 'codex', 'model': 'selected-model', 'allow_runtime_swarm': True}
             for role in (parent_role, child_role, 'engineer')}
    if '.' in parent_role:
        group, _, name = parent_role.rpartition('.')
        roles[group] = {name: roles.pop(parent_role)}
        roles.pop(actual_parent, None)
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': roles,
        'role_tree': {parent_role: {child_role: {}}},
    }))
    scenario = tmp_path / 'dispatch_scenario.py'
    scenario.write_text(
        Path(__file__).with_name('generic_dispatch_scenario.py').read_text()
        .replace("'researcher'", repr(actual_parent))
        .replace("'analyst'", repr(child_role))
    )
    code = fake_codex.executable.read_text().replace("'session_name': 'fake-thread'", "'session_name': os.environ['GRAPHTRAJ_PARENT_ALIAS']").replace(
        "lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')",
        'import runpy; runpy.run_path(' + repr(str(scenario)) + ')\nraise SystemExit(0)',
    )
    fake_codex.executable.write_text(code)
    first_child = None
    for ticket_id in ('150', '151'):
        _register(installed_commands, root, _ticket(ticket_id, 'dispatch'))
        _change_status(installed_commands, root, ticket_id, 'ready')
        if first_child:
            env.update(FOREIGN_CHILD=first_child, CAUSE=events[-1]['event_id'])
        request = {'tasks': [{'role': parent_role, 'ticket_id': ticket_id}]}
        if surface == 'cli':
            batch = root / 'batch.yml'
            batch.write_text(yaml.safe_dump(request))
            result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                                 cwd=root, env=env, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            document = yaml.safe_load(result.stdout)
        else:
            with monkeypatch.context() as patch:
                for key, value in env.items():
                    patch.setenv(key, value)
                patch.setattr(sys, 'executable', str(installed_commands.runner.with_name('python')))
                result = tools.launch_swarm_tool(request, cwd=root)
            assert not result.failed, result.document
            document = result.document
        parent = document['tasks'][0]
        worktree = Path(parent['worktree_path'])
        for _ in range(200):
            if (worktree / 'parent-turns.txt').exists() and (worktree / 'parent-turns.txt').read_text() == '2':
                break
            time.sleep(.05)
        assert (worktree / 'parent-turns.txt').read_text() == '2'
        wait_for_idle(installed_commands, root, env, parent['alias'])
        child = json.loads((worktree / 'last-child.json').read_text())
        assert child['launch_status'] == 'registered'
        if first_child is None:
            first_child = child['alias']
        ticket = root / '.graphtraj/state/tickets' / (ticket_id + '-dispatch')
        team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
        assert {member['role'] for member in team['members'].values()} == {actual_parent, child_role}
        assert len(team['members']) == 2
        mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / child['alias'] / 'mapping.yml').read_text())
        assert mapping['parent'] == parent['alias']
        assert (worktree / 'child-work.txt').read_text() == 'Formal child executed'
        events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
                  for line in shard.read_text().splitlines()]
    if historical:
        # The saved input predates distinct configured tier roles; mapping is fact.
        parent_mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / parent['alias'] / 'mapping.yml').read_text())
        retained = Path(parent_mapping['retained_batch_file'])
        batch = yaml.safe_load(retained.read_text())
        batch['tasks'][0]['role'] = 'coding-team.engineer-expert'
        retained.chmod(0o644)
        retained.write_text(yaml.safe_dump(batch))
        retained.chmod(0o444)
        parent_mapping['role_reference'] = 'coding-team.engineer-expert'
        (root / '.graphtraj/runner/sessions' / parent['alias'] / 'mapping.yml').write_text(yaml.safe_dump(parent_mapping))
        roles_file = root / '.graphtraj/roles.yml'
        roles = yaml.safe_load(roles_file.read_text())
        roles['roles']['coding-team']['engineer-expert'] = dict(roles['roles']['coding-team']['engineer'])
        roles['role_tree']['coding-team.engineer-expert'] = {child_role: {}}
        roles_file.write_text(yaml.safe_dump(roles))

        original_batch = retained.read_bytes()
    sent = run_process([str(installed_commands.runner), 'send', parent['alias'],
                        '--instruction', 'Dispatch again', '--caused-by-event-id', events[-1]['event_id']],
                       cwd=root, env=env, timeout=20)
    assert sent.returncode == 0, sent.stdout + sent.stderr
    for _ in range(200):
        if (worktree / 'parent-turns.txt').read_text() == '4':
            break
        time.sleep(.05)
    assert (worktree / 'parent-turns.txt').read_text() == '4'
    wait_for_idle(installed_commands, root, env, parent['alias'])
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    assert len(team['members']) == 3
    assert sum(member['role'] == child_role for member in team['members'].values()) == 2
    assert all(member['session_ref'] for member in team['members'].values())
    if historical:
        assert retained.read_bytes() == original_batch
        assert parent_mapping['role'] == 'engineer'


@pytest.mark.parametrize('selection, missing', [
    ({'instructions': 'engineer'}, 'engineer'),
    ({'instructions': 'missing-resource'}, 'missing-resource'),
    ({'instructions': 'unreadable.txt'}, 'Permission denied'),
    ({'instructions': 'invalid-utf8.txt'}, 'utf-8'),
])
def test_selected_resources_fail_clearly_when_absent(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    selection: dict,
    missing: str,
) -> None:
    """An explicit file or Skill selection fails clearly when absent."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    remove_coding_method_skills(root, tmp_path / 'operator-home')
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'coding_team': {
            'engineer': {'runtime': 'codex', 'model': 'selected-author', **selection},
        }},
        'role_tree': {'coding_team.engineer': {}},
    }))
    _register(installed_commands, root, _ticket('150', 'absent-method'))
    _change_status(installed_commands, root, '150', 'ready')
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{
        'role': 'coding_team.engineer', 'ticket_id': '150',
    }]}))

    unreadable = root / 'unreadable.txt'
    unreadable.write_text('Selected text must not bypass read permissions.')
    unreadable.chmod(0)
    (root / 'invalid-utf8.txt').write_bytes(b'\xff')
    try:
        result = run_process(
            [str(installed_commands.runner), '--swarm-input', str(batch)],
            cwd=root, env=env,
        )
    finally:
        unreadable.chmod(0o600)

    assert result.returncode == 1
    document = yaml.safe_load(result.stdout)
    task = document['tasks'][0]
    assert task['launch_status'] == 'failed'
    assert task['error']['code'] == 'invalid-config'
    assert missing in task['error']['message']
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))


@pytest.mark.parametrize('tree, task', [
    ({}, {'role': 'researcher'}),
    ({'researcher': {}}, {'role': 'unlisted'}),
    ({'researcher': {}}, {'role': {'unlisted': {'runtime': 'codex', 'model': 'inline'}}}),
])
def test_unpermitted_root_does_not_start_a_session(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    tree: dict,
    task: dict,
) -> None:
    """Neither a preset nor inline settings can create dispatch permission."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    (root / '.graphtraj/roles.yml').write_text(yaml.safe_dump({
        'roles': {'researcher': {'runtime': 'codex', 'model': 'selected'}},
        'role_tree': tree,
    }))
    _register(installed_commands, root, _ticket('150', 'no-dispatch'))
    _change_status(installed_commands, root, '150', 'ready')
    batch = root / 'batch.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'ticket_id': '150', **task}]}))
    result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)], cwd=root, env=env)
    assert result.returncode == 1
    assert yaml.safe_load(result.stdout)['error']['code'] == 'authority-denied'
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))


@pytest.mark.parametrize('surface', ['cli', 'mcp'])
@pytest.mark.parametrize('skills', [[], ['uninstalled-method']])
def test_public_launch_rejects_retired_skill_selection(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    surface: str,
    skills: list[str],
) -> None:
    """CLI and MCP reject new name selections through their shared service."""
    from test_mcp_host_tools import McpServerProcess

    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register(installed_commands, root, _ticket('176', 'native-selection'))
    _change_status(installed_commands, root, '176', 'ready')
    request = {'tasks': [{'role': 'coding_team.engineer', 'ticket_id': '176', 'skills': skills}]}
    if surface == 'cli':
        batch = root / 'input.yml'
        batch.write_text(yaml.safe_dump(request))
        result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                             cwd=root, env=env)
        assert result.returncode == 1
        document = yaml.safe_load(result.stdout)
        assert document['error']['code'] == 'invalid-input'
        message = document['error']['message']
    else:
        with McpServerProcess(installed_commands.runner.with_name('graphtraj-mcp'), root, env) as server:
            result = server.call('swarm', request)['result']
        assert result['isError']
        message = result['content'][0]['text']
    assert 'Runtime native Skill selection' in message
    assert not list((root / '.graphtraj/runner/sessions').glob('*/mapping.yml'))
