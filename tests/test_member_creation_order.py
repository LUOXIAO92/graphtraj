"""Member registration at the native create/execute boundary."""

import json
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_ticket_graph import _register, _change_status, _ticket


def _observed_runtime(fake: FakeCodex, tmp_path: Path) -> None:
    """Observe actual native turn-start messages without replacing Runner code."""
    original = Path(__file__).with_name('runner_codex_peer.py')
    peer = tmp_path / 'member-peer.py'
    source = original.read_text().replace('import json\n', 'import json\nimport yaml\n', 1)
    source = source.replace("    elif method == 'turn/start':\n", """    elif method == 'turn/start':
        root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
        alias = os.environ['GRAPHTRAJ_PARENT_ALIAS']
        mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())
        if mapping['role'] in {'team-leader', 'engineer', 'standards-reviewer', 'spec-reviewer'}:
            evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
            team = yaml.safe_load((evidence / 'teams' / str(mapping['team_generation']) / 'team.yml').read_text())
            assert any(member['session_ref'] == alias for member in team['members'].values()), mapping
            with open(os.environ['MEMBER_OBSERVATIONS'], 'a') as log:
                log.write(json.dumps({'alias': alias, 'role': mapping['role'], 'parent': mapping['parent'],
                                      'members': team['members'], 'resumed': resumed}) + '\\n')
""")
    source = source.replace("        result = {'thread': {'id': session, 'path': str(native)}}", """        result = {'thread': {'id': session, 'path': str(native)}}
        if os.environ.get('FAIL_MEMBER_REGISTRATION') and not resumed:
            (Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']) / '.graphtraj/state/worldline/.lock').chmod(0o444)
""")
    peer.write_text(source)
    scenario = fake.executable.read_text().replace(str(original), str(peer))
    scenario = scenario.replace("lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')", """if os.environ.get('FAIL_MEMBER_ROLE') == os.environ.get('GRAPHTRAJ_ROLE'):
    raise SystemExit(1)
lifecycle_action = os.environ.get('FAKE_CODEX_LIFECYCLE_ACTION')""")
    fake.executable.write_text(scenario)


@pytest.mark.parametrize('failure', [None, 'team-leader', 'engineer', 'standards-reviewer', 'spec-reviewer', 'registration'])
def test_native_creation_registers_members_before_execution(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    failure: str | None,
) -> None:
    """Successful and failed turns keep actual members; failed registration prevents a turn."""
    root, _, _, env = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register(installed_commands, root, _ticket('148', 'creation-order'))
    _change_status(installed_commands, root, '148', 'ready')
    _observed_runtime(fake_codex, tmp_path)
    observation = tmp_path / 'member-observations.jsonl'
    env.update(
        FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
        FAKE_CODEX_REVIEW_AXES='standards-reviewer spec-reviewer',
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        MEMBER_OBSERVATIONS=str(observation),
    )
    if failure == 'registration':
        env['FAIL_MEMBER_REGISTRATION'] = '1'
    elif failure:
        env['FAIL_MEMBER_ROLE'] = failure
    batch = root / 'batch.yml'
    batch.write_text('tasks:\n  - ticket_id: "148"\n    ticket_name: creation-order\n    role: coding-team.team-leader\n')
    result = run_process(
        [str(installed_commands.runner), '--swarm-input', str(batch)],
        cwd=root, env=env, timeout=45,
    )
    assert result.returncode == (1 if failure in {'engineer', 'registration'} else 0), result.stderr
    ticket = root / '.graphtraj/state/tickets/148-creation-order'
    mappings = [yaml.safe_load(path.read_text()) for path in (root / '.graphtraj/runner/sessions').glob('*/mapping.yml')]
    if failure == 'registration':
        assert not observation.exists()
        assert not (ticket / 'teams/1/team.yml').exists()
        assert len(mappings) == 1 and mappings[0]['session']
        terminal = yaml.safe_load((root / '.graphtraj/runner/sessions' / mappings[0]['alias'] / 'execution.yml').read_text())
        assert terminal['error']['code'] == 'MEMBER_REGISTRATION_FAILED'
        # A resume cannot turn failed registration into permission to execute.
        (root / '.graphtraj/state/worldline/.lock').chmod(0o600)
        causes = [json.loads(line)['event_id'] for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl')
                  for line in shard.read_text().splitlines()]
        resumed = run_process(
            [str(installed_commands.runner), 'send', mappings[0]['alias'],
             '--instruction', 'Continue only if registered.', '--caused-by-event-id', causes[-1]],
            cwd=root, env=env, timeout=20,
        )
        assert resumed.returncode != 0
        assert not observation.exists()
        return
    rows = [json.loads(line) for line in observation.read_text().splitlines()]
    team = yaml.safe_load((ticket / 'teams/1/team.yml').read_text())
    events = [json.loads(line) for shard in (root / '.graphtraj/state/worldline').glob('*.jsonl') for line in shard.read_text().splitlines()]
    actual = {entry['session_ref'] for entry in team['members'].values()}
    assert None not in actual
    assert all(row['alias'] in actual for row in rows)
    assert sum(event['kind'] == 'team-started' for event in events) == 1
    assert sum(event['kind'] == 'team-member-started' for event in events) == len(actual) - 1
    if failure:
        failed = next(row for row in rows if row['role'] == failure)
        terminal = yaml.safe_load((root / '.graphtraj/runner/sessions' / failed['alias'] / 'execution.yml').read_text())
        assert terminal['outcome'] == 'runtime-error'
    else:
        assert {row['role'] for row in rows} == {'team-leader', 'engineer', 'standards-reviewer', 'spec-reviewer'}
        assert any(row['resumed'] for row in rows)
        leader = next(row['alias'] for row in rows if row['role'] == 'team-leader')
        assert all(row['parent'] == leader for row in rows if row['role'] != 'team-leader')

    if failure is None:
        # An ordinary process cannot impersonate the trusted creating Worker.
        before = (ticket / 'teams/1/team.yml').read_bytes()
        alias = rows[0]['alias']
        directory = root / '.graphtraj/runner/sessions' / alias
        attempted = run_process(
            [str(installed_commands.runner.with_name('python')), '-c',
             "import sys, yaml; from pathlib import Path; "
             "from graphtraj.execution.runner_worker import _register_created_member; "
             "p=Path(sys.argv[1]); "
             "_register_created_member(p/'launch.yml', yaml.safe_load((p/'mapping.yml').read_text()), created=True)",
             str(directory)],
            cwd=root, env=env, timeout=15,
        )
        assert attempted.returncode != 0
        assert 'owning Runner creation job' in attempted.stderr
        assert (ticket / 'teams/1/team.yml').read_bytes() == before
