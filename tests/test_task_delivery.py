from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from conftest import app_server_peer, run_process
from test_project_setup import run_setup, setup_environment
from test_ticket_graph import _change_status, _register, _ticket


# Controlled Team decisions at the installed Runtime boundary. Main's decisions
# are supplied by the scenario below; the fake does not interpret Skill prose.
RUNTIME = app_server_peer(r'''
import json, os, subprocess, sys
from pathlib import Path
from graphtraj.interfaces import mcp
if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox')
    raise SystemExit(0)
prompt = sys.stdin.read()
root = Path(os.environ['GRAPHTRAJ_HARNESS_ROOT'])
ticket = os.environ['GRAPHTRAJ_TICKET_ID']
assert Path('CONTEXT.md').read_text() == 'Existing project context.\n'
assert Path('docs/decision.md').read_text() == 'Existing project decision.\n'
if ticket == '1':
    Path('render.py').write_text('from settings import greeting\ndef render():\n    return greeting\n\nif __name__ == "__main__":\n    print(render())\n')
    if 'settings.py together' in prompt:
        Path('settings.py').write_text('greeting = "hello"\n')
    names = ['render.py'] + (['settings.py'] if Path('settings.py').exists() else [])
else:
    Path('cli.py').write_text('from render import render\nprint(render() + " world")\n')
    names = ['cli.py']
subprocess.run(['git', 'add', *names], check=True, capture_output=True)
subprocess.run(['git', 'commit', '--allow-empty', '-m', 'Deliver task result'], check=True, capture_output=True)
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
validated = subprocess.run([sys.executable, 'cli.py' if ticket == '3' else 'render.py'], text=True, capture_output=True)
report = mcp.submit_report({'name': 'validation.md', 'text': validated.stdout + validated.stderr}, cwd=root).document
mcp.submit_report({'name': 'engineer.md', 'text': 'Candidate commit: ' + commit}, cwd=root)
mcp.submit_result({'commit': commit, 'result_refs': names, 'evidence_refs': [report['report']], 'completion': 'Validation evidence retained'}, cwd=root)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Submitted'}}))
''', "'fake-' + os.environ['GRAPHTRAJ_TICKET_ID']")



@pytest.mark.parametrize("layout", ["same", "separated"])
def test_installed_delivery_corrects_a_split_and_delivers_the_current_graph(
    installed_commands, temporary_git_repository, fake_codex, tmp_path, layout,
):
    root = temporary_git_repository if layout == "same" else temporary_git_repository.parent
    documents = {"CONTEXT.md": "Existing project context.\n",
                 "docs/decision.md": "Existing project decision.\n"}
    for name, content in documents.items():
        path = temporary_git_repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    run_process(["git", "add", "CONTEXT.md", "docs"], cwd=temporary_git_repository).check_returncode()
    run_process(["git", "commit", "-m", "Existing project documents"], cwd=temporary_git_repository).check_returncode()
    old_state = root / "state" / "20260814-historical"
    old_state.mkdir(parents=True)
    for name in ("run.yml", "ledger.yml", "task-map.yml", "history.jsonl", "handoff.md"):
        (old_state / name).write_bytes(b"Historical user evidence: \x00\xff\n")
    old_evidence = {path.relative_to(old_state): path.read_bytes() for path in old_state.iterdir()}
    user_home = tmp_path / "operator-home"
    setup = run_setup(
        installed_commands, harness_root=root, user_home=user_home,
        fake_codex=fake_codex, answers="y\ny\n",
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    from runner_fixtures import configure_coding_roles
    configure_coding_roles(root)
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['role_tree']['engineer'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
    assert not (root / ".codex" / "agent-runner").exists()
    assert not (root / ".codex" / "agents").exists()
    assert not (root / ".pi" / "agents").exists()
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
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "1", "ticket_name": "renderer", "role": "engineer"}]}))
    first_delivery = runner("--swarm-input", str(batch))
    assert first_delivery["tasks"][0]["launch_status"] == "launched"
    author = first_delivery['tasks'][0]['alias']

    def decide(alias: str, decision: str) -> None:
        """The actual parent decides the exact submitted version from retained evidence."""
        submission = runner('reports', alias)['submissions'][-1]
        runner('decide-result', '--submission-id', submission['event_id'],
               '--commit', submission['candidate'], '--decision', decision,
               '--reason', 'Validation establishes the required behavior.',
               '--evidence-ref', submission['evidence_refs'][0])

    decide(author, 'rejected')
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
        "evidence_refs": [str((first_round / "validation.md").relative_to(root)), str((first_round / "engineer.md").relative_to(root))],
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
    runner("send", author, "--instruction", "Deliver render.py and settings.py together", "--caused-by-event-id", revised["event_id"])
    from test_generic_role_execution import wait_for_idle
    wait_for_idle(installed_commands, root, environment, author)
    decide(author, "accepted")
    combined = record("1", "renderer")
    assert combined["status"] == "awaiting-integration"
    assert combined["active_team_ordinal"] == 1
    assert combined["worktree"] == original_ticket["worktree"]
    assert combined["branch"] == original_ticket["branch"]
    assert not any(item["ready"] for item in product("ticket", "graph")["tickets"])

    integrated = product("ticket", "integrate", "--ticket-id", "1", "--", sys.executable, "-c", "from render import render; assert render() == 'hello'")
    assert integrated["status"] == "integrated"
    assert [item["ticket_id"] for item in product("ticket", "graph")["tickets"] if item["ready"]] == ["3"]
    runner("cleanup", "--ticket-id", "1")
    batch.write_text(yaml.safe_dump({"tasks": [{"ticket_id": "3", "ticket_name": "cli", "role": "engineer"}]}))
    delivered = runner("--swarm-input", str(batch))
    decide(delivered["tasks"][0]["alias"], "accepted")
    product("ticket", "integrate", "--ticket-id", "3", "--", sys.executable, "-c", "import subprocess, sys; assert subprocess.check_output([sys.executable, 'cli.py'], text=True) == 'hello world\\n'")
    runner("cleanup", "--ticket-id", "3")
    graph = product("ticket", "graph")["tickets"]
    assert {item["ticket_id"] for item in graph if item["active"]} == {"1", "3"}
    assert all(item["status"] == "integrated" for item in graph if item["active"])
    assert not any(item["ready"] for item in graph)
    assert not (worktrees / "1-renderer").exists()
    assert not (worktrees / "3-cli").exists()
    for name, content in documents.items():
        assert (worktrees / "dev" / name).read_text() == content
        assert (temporary_git_repository / name).read_text() == content
    assert not (worktrees / "dev/docs").is_symlink()
    assert not (worktrees / "dev/CONTEXT.md").is_symlink()
    tracked = run_process(["git", "ls-files", "CONTEXT.md", "docs"], cwd=worktrees / "dev")
    assert tracked.stdout.splitlines() == ["CONTEXT.md", "docs/decision.md"]
    assert {path: path.read_bytes() for path in original_definitions} == original_definitions
    assert {path: path.read_bytes() for path in historical} == historical
    assert {path: path.read_bytes() for path in batches} == batches
    assert all(path.read_bytes().startswith(content) for path, content in traces.items())
    assert events()[:len(before)] == before
    assert {path.name for path in state.iterdir()} == {"tickets", "batches", "worldline"}
    assert not any(path.name in {"run.yml", "metadata.yml", "ledger.yml", "dag.md", "handoff.md"} for path in state.rglob("*"))

    assert {path.relative_to(old_state): path.read_bytes() for path in old_state.rglob("*") if path.is_file()} == old_evidence
    assert not any(path.name in {"task-map.yml", "history.jsonl", "turn.yml"} or path.name.startswith("turn-") for path in state.rglob("*"))
