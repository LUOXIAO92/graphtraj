from __future__ import annotations

import yaml

from conftest import run_process
from test_project_setup import run_setup, setup_environment


def test_installed_commands_reject_delivery_run_inputs(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    root = temporary_git_repository.parent
    home = tmp_path / "operator-home"
    setup = run_setup(
        installed_commands, harness_root=root, user_home=home,
        fake_codex=fake_codex, answers="y\ny\n",
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    ticket = root / "old-ticket.md"
    ticket.write_text("Historical Ticket\n")
    batch = root / "old-batch.yml"
    batch.write_text(yaml.safe_dump({"run_id": "20260906-obsolete", "tasks": [{
        "ticket_id": "87", "ticket_name": "contraction", "role": "engineer-junior",
        "ticket_file": str(ticket),
    }]}))
    launch = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=root, env=setup_environment(home, fake_codex),
    )
    assert launch.returncode != 0, launch.stdout
    assert yaml.safe_load(launch.stdout)["error"]["code"] == "invalid-input"
    assert not fake_codex.log_file.exists()
    for command in (
        [str(installed_commands.product), "worldline", "project", "--run-root", str(root)],
        [str(installed_commands.product), "worldline", "append", "--run-id", "20260906-obsolete"],
        [str(installed_commands.runner), "send", "old@e1", "--instruction", "resume", "--caused-by-worldline-seq", "1"],
    ):
        rejected = run_process(command, cwd=root)
        assert rejected.returncode == 2, rejected.stdout + rejected.stderr


def test_team_engineer_keeps_explicit_repository_skill_selection(
    installed_commands, temporary_git_repository, fake_codex, tmp_path,
):
    import json
    import tomllib
    from runner_fixtures import configure_harness
    from test_team_round import _register_ready_inline_ticket

    for name in ("selected", "disabled"):
        skill = temporary_git_repository / ".agents" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: " + name + "\ndescription: Probe skill.\n---\n")
    run_process(["git", "add", ".agents"], cwd=temporary_git_repository).check_returncode()
    run_process(["git", "commit", "-m", "Add Repository Skills"], cwd=temporary_git_repository).check_returncode()
    root, worktrees, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_inline_ticket(root, installed_commands.product)
    batch = root / "team.yml"
    batch.write_text(yaml.safe_dump({"tasks": [{
        "ticket_id": "75", "ticket_name": "inline-specialist", "role": "team-leader",
    }]}))
    environment.update(
        FAKE_CODEX_LIFECYCLE_ACTION="complete-team-round",
        FAKE_CODEX_ENGINEER_SKILLS='["selected"]',
        FAKE_CODEX_CAPTURE_ROLE="1", FAKE_CODEX_APPEND_LOG="1",
        GRAPHTRAJ_AGENT_RUNNER=str(installed_commands.runner),
    )
    launched = run_process(
        [str(installed_commands.runner), "--batch-input", str(batch)],
        cwd=root, env=environment, timeout=45,
    )
    assert launched.returncode == 0, launched.stdout + launched.stderr
    records = [json.loads(line) for line in fake_codex.log_file.read_text().splitlines()]
    for record in records:
        skills = tomllib.loads(next(arg for arg in record["argv"] if arg.startswith("skills=")))["skills"]["config"]
        if record["role"] == "engineer-junior":
            assert {"path": str(worktrees / "75-inline-specialist/.agents/skills/selected/SKILL.md"), "enabled": True} in skills
        assert {"path": str(worktrees / "75-inline-specialist/.agents/skills/disabled/SKILL.md"), "enabled": False} in skills
    batches = [yaml.safe_load(path.read_text()) for path in (root / ".graphtraj/state/batches").glob("*.yml")]
    assert any(task.get("skills") == ["selected"] for batch in batches for task in batch["tasks"])
