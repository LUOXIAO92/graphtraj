"""Members that one swarm call starts together all register (594, 595).

Each member's Worker reads the Task and Team before it takes the Project
Worldline lock. The test widens that window in the installed Workers through a
test sitecustomize (no product code is changed), so the sibling that takes the
lock first always rewrites the files the other one read.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_task_graph import _register, _change_status, _task


# Loaded by the installed Workers (-I) through conftest's graphtraj_test_clock
# hook. The Worker runs as ``-m`` (``__main__``), so the seam is the Delivery
# State module it imports when it registers: only a start or member request
# waits, after its entry read and before the Worldline lock. Every wait is
# logged so the test can show that the window was crossed.
WIDENING = """
import json, os, threading, time
try:
    import graphtraj.graph.delivery_state as delivery
except ModuleNotFoundError:
    pass
else:
    registering = threading.local()
    register, append = delivery.apply_delivery_state_request, delivery.append_project_worldline_event

    def _register(state_directory, harness_root, request, *args, **kwargs):
        registering.active = isinstance(request, dict) and request.get('phase') in ('start', 'member')
        try:
            return register(state_directory, harness_root, request, *args, **kwargs)
        finally:
            registering.active = False

    def _append(*args, **kwargs):
        if getattr(registering, 'active', False):
            started = time.time()
            time.sleep(float(os.environ['REGISTRATION_WINDOW_SECONDS']))
            with open(os.environ['REGISTRATION_LOG'], 'a') as log:
                log.write(json.dumps({'pid': os.getpid(), 'kind': args[2]['event'],
                                      'read': started, 'lock': time.time()}) + '\\n')
        return append(*args, **kwargs)

    delivery.apply_delivery_state_request = _register
    delivery.append_project_worldline_event = _append
"""


def _claude_members(root: Path, fake_codex: FakeCodex, roles: tuple[str, ...]) -> None:
    """Install the repository's fake claude and run the given coding roles on it."""
    binary = fake_codex.executable.with_name('claude')
    source = Path(__file__).with_name('claude_cli_fixture.py').read_text()
    binary.write_text(f'#!{sys.executable}\n' + source)
    binary.chmod(0o755)
    roles_file = root / '.graphtraj/roles.yml'
    configured = yaml.safe_load(roles_file.read_text())
    for name in roles:
        role = configured['roles']['coding_team'][name]
        # Claude has no Runtime-native swarm helper to allow.
        role.pop('allow_runtime_swarm', None)
        role.update(runtime='claude', model='claude-opus-5-5', reasoning_effort='high')
    roles_file.write_text(yaml.safe_dump(configured))


def _registrations(root: Path) -> tuple[set[str], list[tuple[str, str]], dict[str, dict]]:
    """Return the Sessions assigned a seat, the Team start events and each Session's error."""
    assigned, errors = set(), {}
    for session in (root / '.graphtraj/runner/sessions').iterdir():
        launch = session / 'launch.yml'
        if launch.is_file() and (yaml.safe_load(launch.read_text()) or {}).get('member_registration'):
            assigned.add(session.name)
        execution = session / 'execution.yml'
        if execution.is_file():
            error = (yaml.safe_load(execution.read_text()) or {}).get('error')
            if error:
                errors[session.name] = error
    events = []
    for shard in sorted((root / '.graphtraj/state/worldline').glob('*.jsonl')):
        for line in shard.read_text().splitlines():
            event = json.loads(line)
            if event['event'] in ('team-started', 'team-member-started'):
                events.append((event['event'], event['evidence_refs'][0].split('/')[-2]))
    return assigned, events, errors


@pytest.mark.parametrize('shape', ['joining', 'new-team'])
def test_concurrent_members_all_register(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    shape: str,
) -> None:
    """Every member started by one swarm call registers once; the Team starts once.

    ``joining``: the Team Leader's one swarm call starts two reviewers of the
    active Team (the 581/591 shape). ``new-team``: one top-level swarm call
    starts two members of a Task without a Team, so the member that loses the
    lock must turn its Team start into joining the Team its sibling started.
    """
    root, _, _, env = configure_harness(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    _register(installed_commands, root, _task('148', 'creation-order'))
    _change_status(installed_commands, root, '148', 'ready')
    controls = tmp_path / 'widening'
    controls.mkdir()
    (controls / 'sitecustomize.py').write_text(WIDENING)
    log = tmp_path / 'registrations.jsonl'
    env.update(
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
        CLAUDE_FIXTURE_HOME=str(tmp_path),
        PYTHONPATH=str(controls),
        WORKER_SITECUSTOMIZE='1',
        REGISTRATION_WINDOW_SECONDS='0.5',
        REGISTRATION_LOG=str(log),
    )
    batch = root / 'batch.yml'
    if shape == 'joining':
        _claude_members(root, fake_codex, ('engineer', 'standards_reviewer', 'spec_reviewer'))
        env.update(FAKE_CODEX_LIFECYCLE_ACTION='complete-team-round',
                   FAKE_CODEX_REVIEW_AXES='standards-reviewer spec-reviewer')
        batch.write_text('tasks:\n  - task_id: "148"\n    task_name: creation-order\n    role: coding-team.team-leader\n')
        expected = 4
    else:
        # The top level may dispatch only Team Leaders; two entries of the same
        # Task differ by instruction, so both start before either registers.
        _claude_members(root, fake_codex, ('team_leader',))
        batch.write_text('tasks:\n' + ''.join(
            '  - task_id: "148"\n    task_name: creation-order\n    role: coding-team.team-leader\n'
            f'    instruction: {name}\n' for name in ('first', 'second')
        ))
        expected = 2
    try:
        result = run_process([str(installed_commands.runner), '--swarm-input', str(batch)],
                             cwd=root, env=env, timeout=90)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = 'timeout'

    # Top-level members register in their own Workers after the call returns.
    deadline = time.monotonic() + 30
    while True:
        assigned, events, errors = _registrations(root)
        settled = {alias for _, alias in events} | set(errors)
        if len(assigned) >= expected and assigned <= settled or time.monotonic() > deadline:
            break
        time.sleep(0.2)

    waits = [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []
    detail = {'output': output[-2000:], 'events': events, 'errors': errors, 'waits': waits}
    assert len(assigned) == expected, detail
    assert not {alias: error for alias, error in errors.items()
                if error.get('code') == 'MEMBER_REGISTRATION_FAILED'}, detail
    # One registration event per member, and the Team started exactly once.
    assert sorted(alias for _, alias in events) == sorted(assigned), detail
    assert [kind for kind, _ in events].count('team-started') == 1, detail
    task_directory = root / '.graphtraj/state/tasks/148-creation-order'
    team = yaml.safe_load((task_directory / 'teams/1/team.yml').read_text())
    assert sorted(member['session_ref'] for member in team['members'].values()) == sorted(assigned), detail
    # The window was crossed: some member read before a sibling's lock and retried.
    pids = [wait['pid'] for wait in waits]
    assert any(pids.count(pid) > 1 for pid in pids), detail
