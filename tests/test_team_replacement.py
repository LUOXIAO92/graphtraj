from __future__ import annotations

import json
import os
import subprocess
from importlib import resources

import pytest
import yaml

from conftest import run_process, wait_for_file
from runner_fixtures import configure_harness, retained_state
from test_session_alias_control import _register_ready_ticket


@pytest.mark.parametrize(("during_implementation", "delivery"), [
    (False, "normal"), (True, "normal"), ("reviewing", "normal"),
    (False, "rework"), (False, "serial"),
])
def test_installed_team_and_member_replacement(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, during_implementation, delivery, request,
):
    root, _, integration, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, root)
    retirement_instructions = resources.files("graphtraj.resources").joinpath(
        "roles", "retirement-instructions.md"
    ).read_text(encoding="utf-8")
    environment["GRAPHTRAJ_RETIREMENT_INSTRUCTIONS"] = retirement_instructions
    # Exercise the same Runtime protocol with a final handoff and successive Teams.
    script = fake_codex.executable.read_text()
    script = script.replace("evidence / 'teams' / '1'", "evidence / 'teams' / os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1')")
    script = script.replace("('leader-stage-' + ordinal)", "('leader-stage-' + os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1') + '-' + ordinal)")
    script = script.replace("delivered.write_text('complete team round' + ('' if ordinal == '1' else ' ' + ordinal) + '\\n')", "delivered.write_text('team ' + os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1') + ' round ' + ordinal)")
    script = script.replace("elif role == 'team-leader':", """elif role == 'team-leader' and os.environ.get('GRAPHTRAJ_RETIRING'):
        prompt = sys.stdin.read()
        assert os.environ['GRAPHTRAJ_RETIREMENT_INSTRUCTIONS'] in prompt
        assert 'handoff/SKILL.md' not in ' '.join(sys.argv)
        root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
        shard = sorted((root / '.graphtraj/state/worldline').glob('*.jsonl'))[-1]
        cause = json.loads(shard.read_text().splitlines()[-1])['event_id']
        alias = (os.environ['GRAPHTRAJ_TICKET_ID'] + '-'
                 + os.environ['GRAPHTRAJ_TICKET_NAME'].replace('-', '_') + '-handover'
                 + str(int(os.environ.get('GRAPHTRAJ_TEAM_GENERATION', '1')) - 1)
                 + '-team_leader@team_leader')
        denied = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], 'send', alias,
                                 '--instruction', 'Start more work', '--caused-by-event-id', cause],
                                cwd=root, capture_output=True, text=True)
        assert denied.returncode == 1 and 'team-not-active' in denied.stdout
        emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Handoff: preserve TEAM_ROUND_DELIVERED.txt and continue the Ticket.'}})
    elif role == 'team-leader':
        if os.environ.get('GRAPHTRAJ_TEAM_GENERATION') == '2' and 'resume' not in sys.argv:
            import io
            prompt = sys.stdin.read()
            sys.stdin = io.StringIO(prompt)
            if 'Continue from the previous' in prompt:
                team = evidence / 'teams/1'
                trace = next((team / 'traces').glob('*@team_leader/events.jsonl'))
                assert str(trace.relative_to(Path(os.environ['GRAPHTRAJ_HARNESS_ROOT']))) in prompt
                assert 'Handoff: preserve' in trace.read_text()
""")
    script = script.replace("elif role == 'engineer':", """elif role == 'engineer' and 'Continue this Team seat' in sys.stdin.read():
        emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Engineer replacement ready to continue.'}})
    elif role == 'engineer':""")
    if during_implementation is True:
        script = script.replace("elif role == 'engineer':", """elif role == 'engineer':
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
    if not during_implementation:
        # The retired Team already completed its Review axes. Its successor
        # verifies those retained reports instead of dispatching them again.
        script = script.replace(
            "        engineer_stage = 1 if inline_specialist else 0",
            "        if os.environ.get('GRAPHTRAJ_TEAM_GENERATION') == '2':\n"
            "            review_axes = []\n"
            "        engineer_stage = 1 if inline_specialist else 0",
        )
        script = script.replace(
            "and ordinal == '1':",
            "and ordinal == '1' and os.environ.get('GRAPHTRAJ_TEAM_GENERATION') == '1':",
        )
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
        launched = subprocess.Popen([str(installed_commands.runner), "--swarm-input", str(batch)],
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
        launched = command("--swarm-input", str(batch))
        assert launched.returncode == 0, launched.stdout + launched.stderr
    ticket_dir = root / ".graphtraj/state/tickets/76-session-alias-control"
    original = yaml.safe_load((ticket_dir / "ticket.yml").read_text())
    team_file = ticket_dir / "teams/1/team.yml"
    team = yaml.safe_load(team_file.read_text())
    leader = team["members"]["team_leader"]["session_ref"]
    reviewer = team["members"]["spec_reviewer"]["session_ref"] or (
        "76-session_alias_control-handover0-spec_reviewer@spec_reviewer"
        if during_implementation == "reviewing"
        else "76-session_alias_control-handover0-engineer@engineer"
    )
    trace = ticket_dir / "teams/1/traces" / reviewer / "events.jsonl"
    prior = retained_state(trace)

    def events():
        return [json.loads(line) for shard in sorted((root / ".graphtraj/state/worldline").glob("*.jsonl")) for line in shard.read_text().splitlines()]

    cause = events()[-1]["event_id"]
    (integration / "other-ticket-in-progress.txt").write_text(
        "temporary work from another Ticket\n"
    )
    if not during_implementation:
        engineer = team["members"]["engineer"]["session_ref"]
        engineer_trace = ticket_dir / "teams/1/traces" / engineer / "events.jsonl"
        engineer_before = retained_state(engineer_trace)
        # Only a member's direct parent may replace it: Main reaches the Team
        # Leader it dispatched itself, not the Leader's members.
        for member in (engineer, reviewer):
            denied_member = command("replace", member, "--actor", "main", "--caused-by-event-id", cause)
            response = yaml.safe_load(denied_member.stdout)
            if denied_member.returncode == 0:
                assert response["replacement_status"] == "requires-native-approval"
                assert response["native_execution"]["arguments"]["sandbox_permissions"] == "require_escalated"
            else:
                assert denied_member.returncode == 1, denied_member.stdout
                assert response["error"]["code"] in {"authority-denied", "native-approval-unavailable"}
        assert retained_state(engineer_trace) == engineer_before
        assert retained_state(trace) == prior
        assert team_file.read_text() == yaml.safe_dump(team, sort_keys=False)
        assert yaml.safe_load((ticket_dir / "ticket.yml").read_text()) == original

    if during_implementation:
        refused = command("replace", leader, "--actor", "user", "--caused-by-event-id", events()[-1]["event_id"])
        assert refused.returncode == 1
        assert yaml.safe_load(refused.stdout)["error"]["code"] == "replacement-not-stopped"
        # Stop the existing execution before replacement; replacement itself
        # must not silently turn permission into an interruption operation.
        status = yaml.safe_load(command("status", leader).stdout)["aliases"][0]
        if status["activity"] != "idle":
            interrupted = command("interrupt", leader)
            assert interrupted.returncode == 0, interrupted.stdout + interrupted.stderr
        for path in (root / ".graphtraj/runner/sessions").glob("*/mapping.yml"):
            mapping = yaml.safe_load(path.read_text())
            if mapping.get("parent") == leader:
                status = yaml.safe_load(command("status", mapping["alias"]).stdout)["aliases"][0]
                if status["activity"] != "idle":
                    result = command("interrupt", mapping["alias"])
                    assert result.returncode == 0, result.stdout + result.stderr
        # Native interruption is acknowledged before the outer Team worker
        # finishes its failure handoff and releases its capacity position.
        launched.communicate(timeout=60)

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
    # Only the whole-Team handover counts up, from handover0 to handover1.
    assert successor["members"]["team_leader"]["session_ref"] == (
        "76-session_alias_control-handover1-team_leader@team_leader"
    )
    if delivery == "rework":
        assert retired["current_round"] == 2
        assert successor["current_round"] == 1
        for generation in (1, 2):
            rounds = ticket_dir / "teams" / str(generation) / "rounds"
            assert {path.name for path in rounds.iterdir()} == ({"1", "2"} if generation == 1 else {"1"})
            assert all(not path.stat().st_mode & 0o200 for path in rounds.rglob("*.md"))
            reworks = [event for event in events()
                       if event["kind"] == "team-round-rework-started" and event["team_ordinal"] == generation]
            if generation == 1:
                assert len(reworks) == 1 and reworks[0]["team_round"] == 2
            else:
                assert reworks == []
        for report in ("standards.md", "spec.md"):
            assert len(list((ticket_dir / "teams").glob("*/rounds/*/" + report))) == 1
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
        for old_alias in ("76-session_alias_control-handover0-standards_reviewer@standards_reviewer",
                          "76-session_alias_control-handover0-spec_reviewer@spec_reviewer"):
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
