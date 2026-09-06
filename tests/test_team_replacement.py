from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from conftest import run_process, wait_for_file
from runner_fixtures import configure_harness
from test_session_alias_control import _register_ready_ticket


@pytest.mark.parametrize(("during_implementation", "delivery"), [
    (False, "normal"), (True, "normal"), ("reviewing", "normal"),
    (False, "rework"), (False, "serial"),
])
def test_installed_team_and_member_replacement(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, during_implementation, delivery, request,
):
    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, root)
    # Exercise the same Runtime protocol with a final handoff and successive Teams.
    script = fake_codex.executable.read_text()
    script = script.replace("evidence / 'teams' / '1'", "evidence / 'teams' / os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1')")
    script = script.replace("('leader-stage-' + ordinal)", "('leader-stage-' + os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1') + '-' + ordinal)")
    script = script.replace("delivered.write_text('complete team round' + ('' if ordinal == '1' else ' ' + ordinal) + '\\n')", "delivered.write_text('team ' + os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1') + ' round ' + ordinal)")
    script = script.replace("elif role == 'team-leader':", """elif role == 'team-leader' and os.environ.get('GRAPHTRAJ_RETIRING'):
        prompt = sys.stdin.read()
        assert 'handoff' in prompt
        assert 'handoff/SKILL.md' in ' '.join(sys.argv)
        root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
        shard = sorted((root / '.graphtraj/state/worldline').glob('*.jsonl'))[-1]
        cause = json.loads(shard.read_text().splitlines()[-1])['event_id']
        alias = os.environ['GRAPHTRAJ_TICKET_ID'] + '-' + os.environ['GRAPHTRAJ_TICKET_NAME'] + '@l1'
        denied = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'send', alias,
                                 '--instruction', 'Start more work', '--caused-by-event-id', cause],
                                cwd=root, capture_output=True, text=True)
        assert denied.returncode == 1 and 'team-not-active' in denied.stdout
        print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Handoff: preserve TEAM_ROUND_DELIVERED.txt and continue the Ticket.'}}), flush=True)
    elif role == 'team-leader':
        if os.environ.get('GRAPHTRAJ_TEAM_GENERATION') == '2' and 'resume' not in sys.argv:
            prompt = sys.stdin.read()
            if 'Continue from the previous' in prompt:
                team = evidence / 'teams/1'
                trace = next((team / 'traces').glob('*@l1/events.jsonl'))
                assert str(trace.relative_to(Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']))) in prompt
                assert 'Handoff: preserve' in trace.read_text()
""")
    script = script.replace("elif role.startswith('engineer-'):", """elif role.startswith('engineer-') and 'Continue this Team seat' in sys.stdin.read():
        print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Engineer replacement ready to continue.'}}), flush=True)
    elif role.startswith('engineer-'):""")
    if during_implementation is True:
        script = script.replace("elif role.startswith('engineer-'):", """elif role.startswith('engineer-'):
        if os.environ.get('GRAPHTRAJ_TEAM_GENERATION') == '1':
            Path(os.environ['ENGINEER_STARTED']).touch()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                time.sleep(0.01)
""")
    if during_implementation == "reviewing":
        config_file = root / ".graphtraj/config.yml"
        config = yaml.safe_load(config_file.read_text())
        config["agent_runner"]["max_concurrency"] = 2
        config_file.write_text(yaml.safe_dump(config))
        environment["RETIREMENT_PROBE"] = str(tmp_path)
        script = script.replace("configured_events =", """
import atexit, fcntl
probe = Path(os.environ['RETIREMENT_PROBE'])
def observe(kind):
    with (probe / 'executions.jsonl').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps({'kind': kind, 'pid': os.getpid(),
                                'role': os.environ['GRAPHTRAJ_ROLE'],
                                'generation': os.environ['GRAPHTRAJ_TEAM_GENERATION'],
                                'retiring': bool(os.environ.get('GRAPHTRAJ_RETIRING'))}) + '\\n')
        stream.flush()
observe('start')
atexit.register(observe, 'exit')
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
configured_events =""", 1)
        script = script.replace("round_dir.mkdir(parents=True, exist_ok=True)", """round_dir.mkdir(parents=True, exist_ok=True)
    if role.endswith('reviewer') and os.environ['GRAPHTRAJ_TEAM_GENERATION'] == '1':
        (probe / (role + '-started')).touch()
        while not (probe / 'release-reviewers').exists():
            time.sleep(0.01)
""")
    if delivery == "rework":
        script = script.replace("            if serial:", """            if ordinal == '2':
                import yaml
                team = yaml.safe_load((round_dir.parent.parent / 'team.yml').read_text())
                members = {seat['role']: seat['session_ref'] for seat in team['members'].values()}
                assert all(child['alias'] == members[child['role']]
                           for child in yaml.safe_load(completed.stdout)['tasks'])
            if serial:""")
        environment.update(FAKE_CODEX_LEADER_DECISION="rework", FAKE_CODEX_REWORK_CASE="rework")
    if delivery == "serial":
        config_file = root / ".graphtraj/config.yml"
        config = yaml.safe_load(config_file.read_text())
        config["agent_runner"]["max_concurrency"] = 1
        config_file.write_text(yaml.safe_dump(config))
        environment["FAKE_CODEX_SERIAL_TEAM"] = "1"
    fake_codex.executable.write_text(script)
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    batch = root / "batch.yml"
    batch.write_text('tasks:\n- ticket_id: "76"\n  ticket_name: session-alias-control\n  role: team-leader\n')

    def command(*args, env=None):
        return run_process([str(installed_commands.runner), *args], cwd=root, env=env or environment, timeout=30)

    if during_implementation:
        environment["ENGINEER_STARTED"] = str(tmp_path / "engineer-started")
        launched = subprocess.Popen([str(installed_commands.runner), "--batch-input", str(batch)],
                                    cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def finish_original_batch():
            (tmp_path / "release-reviewers").touch()
            launched.communicate(timeout=60)
        request.addfinalizer(finish_original_batch)
        if during_implementation == "reviewing":
            for role in ("standards-reviewer", "spec-reviewer"):
                wait_for_file(tmp_path / (role + "-started"), timeout=15)
            observed = [json.loads(line) for line in (tmp_path / "executions.jsonl").read_text().splitlines()]
            active = set()
            for event in observed:
                if event["kind"] == "start":
                    active.add(event["pid"])
                else:
                    active.remove(event["pid"])
            assert len(active) == 2
        else:
            wait_for_file(tmp_path / "engineer-started", timeout=15)
    else:
        launched = command("--batch-input", str(batch))
        assert launched.returncode == 0, launched.stdout + launched.stderr
    ticket_dir = root / ".graphtraj/state/tickets/76-session-alias-control"
    original = yaml.safe_load((ticket_dir / "ticket.yml").read_text())
    team_file = ticket_dir / "teams/1/team.yml"
    team = yaml.safe_load(team_file.read_text())
    leader = team["members"]["team_leader"]["session_ref"]
    reviewer = team["members"]["spec_reviewer"]["session_ref"] or (
        "76-session-alias-control@r2" if during_implementation == "reviewing" else "76-session-alias-control@j1"
    )
    trace = ticket_dir / "teams/1/traces" / reviewer / "events.jsonl"
    prior = trace.read_bytes()

    def events():
        return [json.loads(line) for shard in sorted((root / ".graphtraj/state/worldline").glob("*.jsonl")) for line in shard.read_text().splitlines()]

    cause = events()[-1]["event_id"]
    denied = command("replace", leader, "--actor", "main", "--caused-by-event-id", cause,
                     env={**environment, "GRAPHTRAJ_ROLE": "team-leader"})
    assert denied.returncode == 1
    assert yaml.safe_load(denied.stdout)["error"]["code"] == "authority-denied"
    assert team_file.read_text() == yaml.safe_dump(team, sort_keys=False)

    if not during_implementation:
        engineer = team["members"]["engineer"]["session_ref"]
        engineer_trace = ticket_dir / "teams/1/traces" / engineer / "events.jsonl"
        engineer_before = engineer_trace.read_bytes()
        replacement = command("replace", engineer, "--actor", "main", "--caused-by-event-id", cause)
        assert replacement.returncode == 0, replacement.stdout + replacement.stderr
        assert engineer_trace.read_bytes() == engineer_before
        assert yaml.safe_load(team_file.read_text())["members"]["engineer"]["session_ref"] != engineer
        assert yaml.safe_load((ticket_dir / "ticket.yml").read_text()) == original
        replaced = command("replace", reviewer, "--actor", "main", "--caused-by-event-id", cause)
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        new_alias = yaml.safe_load(replaced.stdout)["replacement_alias"]
        assert new_alias != reviewer
        assert trace.read_bytes() == prior
        current = yaml.safe_load(team_file.read_text())
        assert current["team_ordinal"] == 1
        assert current["members"]["spec_reviewer"]["session_ref"] == new_alias
        assert current["members"]["team_leader"]["session_ref"] == leader

    replaced = command("replace", leader, "--actor", "user", "--caused-by-event-id", events()[-1]["event_id"])
    assert replaced.returncode == 0, replaced.stdout + replaced.stderr
    if during_implementation:
        launched.communicate(timeout=10)
        assert launched.returncode == 1
        status = command("status", reviewer)
        assert yaml.safe_load(status.stdout)["aliases"][0]["last_outcome"] == "interrupted"
    retired = yaml.safe_load(team_file.read_text())
    assert retired["status"] == "retired"
    assert retired["retired_by"] == "user"
    handoff = root / retired["final_trace_ref"]
    assert "Handoff: preserve" in handoff.read_text()
    assert retired["final_session_ref"] == leader
    successor = yaml.safe_load((ticket_dir / "teams/2/team.yml").read_text())
    assert successor["team_ordinal"] == 2
    assert successor["status"] == "active"
    if delivery == "rework":
        assert retired["current_round"] == successor["current_round"] == 2
        for generation in (1, 2):
            rounds = ticket_dir / "teams" / str(generation) / "rounds"
            assert {path.name for path in rounds.iterdir()} == {"1", "2"}
            assert all(not path.stat().st_mode & 0o200 for path in rounds.rglob("*.md"))
            reworks = [event for event in events()
                       if event["kind"] == "team-round-rework-started" and event["team_ordinal"] == generation]
            assert len(reworks) == 1 and reworks[0]["team_round"] == 2
    ticket = yaml.safe_load((ticket_dir / "ticket.yml").read_text())
    assert ticket["active_team_ordinal"] == 2
    assert ticket["status"] == "awaiting-integration"
    assert ticket["branch"] == original["branch"]
    assert ticket["worktree"] == original["worktree"]
    replacement_trace = ticket_dir / "teams/2/traces" / successor["members"]["team_leader"]["session_ref"] / "events.jsonl"
    assert replacement_trace.is_file()
    kinds = [event["kind"] for event in events()]
    assert kinds.index("team-retiring") < kinds.index("team-retired") < kinds.index("team-replaced")
    stale = command("send", leader, "--instruction", "Start more work", "--caused-by-event-id", events()[-1]["event_id"])
    assert stale.returncode == 1
    assert yaml.safe_load(stale.stdout)["error"]["code"] == "team-not-active"
    assert not list(ticket_dir.rglob("*handoff*"))
    if during_implementation == "reviewing":
        for old_alias in ("76-session-alias-control@r1", "76-session-alias-control@r2"):
            status = command("status", old_alias)
            assert yaml.safe_load(status.stdout)["aliases"][0]["last_outcome"] == "interrupted"
        active = set()
        maximum = 0
        for event in [json.loads(line) for line in (tmp_path / "executions.jsonl").read_text().splitlines()]:
            if event["kind"] == "start":
                active.add(event["pid"])
            else:
                active.remove(event["pid"])
            maximum = max(maximum, len(active))
        assert maximum == 2
        assert not active
        later = [json.loads(line) for line in (tmp_path / "executions.jsonl").read_text().splitlines()][len(observed):]
        assert all(event["role"] == "delivery-state" or event["retiring"]
                   for event in later if event["kind"] == "start" and event["generation"] == "1")
