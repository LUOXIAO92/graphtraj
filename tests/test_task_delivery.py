from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from conftest import run_process
from test_project_setup import run_setup, setup_environment
from test_ticket_graph import _change_status, _register, _ticket


# Controlled Team decisions at the installed Runtime boundary. Main's decisions
# are supplied by the scenario below; the fake does not interpret Skill prose.
RUNTIME = r'''
import json
import os
import subprocess
import sys
from pathlib import Path
import yaml

if sys.argv[1:] == ['exec', '--help']:
    print('--config --json --sandbox --dangerously-bypass-hook-trust')
    raise SystemExit(0)

role = os.environ['GRAPHTRAJ_ROLE']
ticket = os.environ['GRAPHTRAJ_TICKET_ID']
generation = os.environ['GRAPHTRAJ_TEAM_GENERATION']
prompt = sys.stdin.read()
print(json.dumps({'type': 'thread.started', 'thread_id': 'fake-' + ticket + '-' + generation + '-' + role}), flush=True)
evidence = Path(os.environ['GRAPHTRAJ_EVIDENCE'])
round_dir = evidence / 'teams' / generation / 'rounds' / '1'

def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()

def validate():
    return subprocess.run([sys.executable, 'cli.py' if ticket == '3' else 'render.py'], text=True, capture_output=True)

if role == 'delivery-state':
    # Serialization of supplied facts, without selecting any semantic decision.
    Path(os.environ['GRAPHTRAJ_STATE_REQUEST']).write_text(os.environ['GRAPHTRAJ_STATE_FACTS'])
elif role == 'team-leader' and os.environ.get('GRAPHTRAJ_RETIRING'):
    assert 'handoff' in prompt
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text':
        'Handoff: render.py follows the original boundary; validation fails because settings.py was deferred. Continue from the corrected Ticket definition.'}}), flush=True)
elif role == 'team-leader':
    stage_file = Path('.scratch') / ('stage-' + generation)
    stage = int(stage_file.read_text()) if stage_file.exists() else 0
    stage_file.write_text(str(stage + 1))
    if generation == '2' and stage == 0:
        assert 'settings.py together' in prompt
        assert 'traces/' in prompt
    if stage < 3:
        child_role = ['engineer-junior', 'standards-reviewer', 'spec-reviewer'][stage]
        batch = Path('.scratch') / ('batch-' + generation + '-' + str(stage) + '.yml')
        batch.write_text(yaml.safe_dump({'tasks': [{
            'ticket_id': ticket, 'ticket_name': os.environ['GRAPHTRAJ_TICKET_NAME'], 'role': child_role,
        }]}))
        result = subprocess.run([os.environ['GRAPHTRAJ_AGENT_RUNNER'], '--batch-input', str(batch)], text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert yaml.safe_load(result.stdout)['tasks'][0]['launch_status'] == 'registered'
    else:
        candidate = git('rev-parse', 'HEAD')
        failure = ticket == '1' and generation == '1'
        (round_dir / 'leader.md').write_text('Candidate commit: ' + candidate + '\n' + (
            'Decision: REJECT\nDiagnosis: main\nRationale: The accepted split defers settings.py to a dependent Ticket, so render.py cannot validate independently. Main must merge the affected behavior.\n'
            if failure else 'Decision: ACCEPT\nRationale: Both Reviews and command validation support the accepted behavior.\n'))
elif role.startswith('engineer-'):
    if ticket == '1':
        Path('render.py').write_text('from settings import greeting\n\ndef render():\n    return greeting\n\nif __name__ == "__main__":\n    print(render())\n')
        if generation == '2':
            Path('settings.py').write_text('greeting = "hello"\n')
        git('add', 'render.py', *(['settings.py'] if generation == '2' else []))
    else:
        assert Path('settings.py').is_file(), 'Dependent must start from validated dev'
        Path('cli.py').write_text('from render import render\nprint(render() + " world")\n')
        git('add', 'cli.py')
    git('commit', '-m', 'Deliver accepted Ticket behavior')
    candidate = git('rev-parse', 'HEAD')
    result = validate()
    (round_dir / 'engineer.md').write_text('Candidate commit: ' + candidate + '\nSelf-review: implemented the supplied boundary; see validation.\n')
    (round_dir / 'validation.md').write_text('Candidate commit: ' + candidate + '\nExit: ' + str(result.returncode) + '\n' + result.stdout + result.stderr)
else:
    candidate = git('rev-parse', 'HEAD')
    assert candidate == os.environ['GRAPHTRAJ_REVIEW_CANDIDATE']
    assert candidate in prompt and os.environ['GRAPHTRAJ_REVIEW_COMPARISON'] in prompt
    result = validate()
    Path(os.environ['GRAPHTRAJ_REVIEW_REPORT']).write_text(
        'Candidate commit: ' + candidate + '\nAxis: ' + role + '\n' +
        ('Finding: accepted Ticket boundary omits required settings.py\n' + result.stderr if result.returncode else 'Finding: none\n'))
print(json.dumps({'type': 'turn.completed'}), flush=True)
'''


@pytest.mark.parametrize("layout", ["same", "separated"])
def test_installed_delivery_corrects_a_split_and_delivers_the_current_graph(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, layout,
):
    root = temporary_git_repository if layout == "same" else temporary_git_repository.parent
    user_home = tmp_path / "operator-home"
    setup = run_setup(
        installed_commands, harness_root=root, user_home=user_home,
        fake_codex=fake_codex, answers="y\ny\n",
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    assert (root / ".agents/skills/task-delivery/SKILL.md").is_file()
    config_file = root / ".graphtraj/config.yml"
    config = yaml.safe_load(config_file.read_text())
    config["agent_runner"]["max_concurrency"] = 1
    config_file.write_text(yaml.safe_dump(config))
    state = root / config["paths"]["state"]
    worktrees = root / config["paths"]["agent_worktrees"]
    environment = setup_environment(user_home, fake_codex)
    environment["GRAPHTRAJ_AGENT_RUNNER"] = str(installed_commands.runner)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    fake_codex.executable.write_text("#!" + sys.executable + "\n" + RUNTIME)

    def product(*arguments):
        result = run_process([str(installed_commands.product), *arguments], cwd=root, env=environment, timeout=30)
        if result.returncode:
            document = yaml.safe_load(result.stdout) or {}
            evidence = (root / document["evidence"]).read_text() if "evidence" in document else ""
            pytest.fail(result.stdout + result.stderr + evidence)
        return yaml.safe_load(result.stdout)

    def runner(*arguments):
        result = run_process([str(installed_commands.runner), *arguments], cwd=root, env=environment, timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        return yaml.safe_load(result.stdout)

    def record(identifier, name):
        return yaml.safe_load((state / "tickets" / (identifier + "-" + name) / "ticket.yml").read_text())

    def events():
        result = run_process([str(installed_commands.product), "worldline", "read"], cwd=root)
        assert result.returncode == 0, result.stderr
        return [json.loads(line) for line in result.stdout.splitlines()]

    first = {**_ticket("1", "renderer"), "body": "Deliver render.py importing greeting from settings. Defer settings.py to Ticket 2."}
    second = {**_ticket("2", "settings", dependencies=["1"]), "body": "Deliver settings.py with greeting hello."}
    dependent = {**_ticket("3", "cli", dependencies=["1", "2"]), "body": "Deliver cli.py printing hello world using render()."}
    for ticket in (first, second, dependent):
        _register(installed_commands, root, ticket)
    original_definitions = {path: path.read_bytes() for path in state.glob("tickets/*/ticket.md")}
    assert [item["ticket_id"] for item in product("ticket", "graph")["tickets"] if item["ready"]] == ["1"]
    _change_status(installed_commands, root, "1", "ready")
    batch = root / "frontier.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "1", "ticket_name": "renderer", "role": "team-leader"}]}))
    first_delivery = runner("--batch-input", str(batch))
    assert first_delivery["tasks"][0]["launch_status"] == "not-accepted"
    original_ticket = record("1", "renderer")
    first_round = state / "tickets/1-renderer/teams/1/rounds/1"
    assert "ModuleNotFoundError" in (first_round / "validation.md").read_text()
    assert not (first_round.parent / "2").exists()
    historical = {path: path.read_bytes() for path in first_round.iterdir()}
    traces = {path: path.read_bytes() for path in state.glob("tickets/*/teams/*/traces/*/events.jsonl")}
    batches = {path: path.read_bytes() for path in (state / "batches").glob("*.yml")}
    before = events()

    # Main corrects the boundary and every affected edge in one decision.
    revision = root / "revision.yml"
    revision.write_text(yaml.safe_dump({
        "product_preserving": True,
        "caused_by_event_ids": [before[-1]["event_id"]],
        "evidence_refs": [str((first_round / "validation.md").relative_to(root)), str((first_round / "leader.md").relative_to(root))],
        "tickets": [
            {**first, "body": "Deliver render.py and settings.py together; render() returns hello.", "active": True, "replaced_by": []},
            {**second, "active": False, "replaced_by": ["1"]},
            {**dependent, "dependencies": ["1"], "active": True, "replaced_by": []},
        ],
    }))
    revised = product("ticket", "revise", "--revision-file", str(revision))
    assert revised["caused_by_event_ids"] == [before[-1]["event_id"]]
    assert not any(item["ready"] for item in product("ticket", "graph")["tickets"])
    # A new Leader reads the corrected definition and the retired Leader Trace,
    # continuing the same Ticket branch rather than treating a graph error as rework.
    runner("replace", first_delivery["tasks"][0]["alias"], "--actor", "main", "--caused-by-event-id", revised["event_id"])
    combined = record("1", "renderer")
    assert combined["status"] == "awaiting-integration"
    assert combined["active_team_ordinal"] == 2
    assert combined["worktree"] == original_ticket["worktree"]
    assert combined["branch"] == original_ticket["branch"]
    assert not any(item["ready"] for item in product("ticket", "graph")["tickets"])

    integrated = product("ticket", "integrate", "--ticket-id", "1", "--", sys.executable, "-c", "from render import render; assert render() == 'hello'")
    assert integrated["status"] == "integrated"
    assert [item["ticket_id"] for item in product("ticket", "graph")["tickets"] if item["ready"]] == ["3"]
    runner("cleanup", "--ticket-id", "1")
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "3", "ticket_name": "cli", "role": "team-leader"}]}))
    runner("--batch-input", str(batch))
    product("ticket", "integrate", "--ticket-id", "3", "--", sys.executable, "-c", "import subprocess, sys; assert subprocess.check_output([sys.executable, 'cli.py'], text=True) == 'hello world\\n'")
    runner("cleanup", "--ticket-id", "3")
    graph = product("ticket", "graph")["tickets"]
    assert {item["ticket_id"] for item in graph if item["active"]} == {"1", "3"}
    assert all(item["status"] == "integrated" for item in graph if item["active"])
    assert not any(item["ready"] for item in graph)
    assert not (worktrees / "1-renderer").exists()
    assert not (worktrees / "3-cli").exists()
    assert (worktrees / "dev/docs").resolve() == (root / "docs").resolve()
    assert {path: path.read_bytes() for path in original_definitions} == original_definitions
    assert {path: path.read_bytes() for path in historical} == historical
    assert {path: path.read_bytes() for path in batches} == batches
    assert all(path.read_bytes().startswith(content) for path, content in traces.items())
    assert events()[:len(before)] == before
    assert {path.name for path in state.iterdir()} == {"tickets", "batches", "worldline"}
    assert not any(path.name in {"run.yml", "metadata.yml", "ledger.yml", "dag.md", "handoff.md"} for path in state.rglob("*"))
