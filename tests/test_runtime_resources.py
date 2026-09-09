from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import InstalledCommands, PROJECT_ROOT
from test_existing_repository_setup import run_setup


@pytest.mark.parametrize("same_root", (False, True))
@pytest.mark.parametrize("user_config", (None, '''# User-owned Main configuration
model = "operator-model"
personality = "friendly"
developer_instructions = "Follow my project instructions."
[agents]
enabled = false
[mcp_servers.user_service]
url = "https://example.invalid/mcp"
'''))
def test_installed_setup_leaves_main_configuration_to_the_user(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    same_root: bool,
    user_config: str | None,
) -> None:
    harness = temporary_git_repository if same_root else temporary_git_repository.parent
    config = harness / ".codex" / "config.toml"
    if user_config is not None:
        config.parent.mkdir()
        config.write_text(user_config, encoding="utf-8")

    first = run_setup(installed_commands, harness)
    assert first.returncode == 0, first.stdout + first.stderr
    second = run_setup(installed_commands, harness, answers="")
    assert second.returncode == 0, second.stdout + second.stderr

    if user_config is None:
        assert not config.exists()
    else:
        assert config.read_bytes() == user_config.encode()
    assert not (harness / "AGENTS.md").exists()
    assert not (temporary_git_repository / "AGENTS.md").exists()
    assert (harness / ".codex" / "hooks" / "worktree_guard.py").is_file()


@pytest.mark.parametrize("role_name", ("engineer-junior", "engineer-senior", "engineer-expert"))
def test_runtime_executes_the_resolved_responsibility_and_required_skill(
    monkeypatch: pytest.MonkeyPatch,
    temporary_git_repository: Path,
    tmp_path: Path,
    role_name: str,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from graphtraj.codex_adapter import create_codex_turn, preflight_runtime_context
    from graphtraj.project_initialization import plan_project_setup
    from graphtraj.project_roles import RolePreset
    from graphtraj.role_definitions import resolve_child_role

    harness = temporary_git_repository.parent
    monkeypatch.setenv("HOME", str(tmp_path / "operator-home"))
    plan_project_setup(harness, temporary_git_repository).apply(install_missing_skills=True)
    worktree = harness / ".graphtraj" / ".agent-worktrees" / "dev"
    session = tmp_path / "session"
    session.mkdir()
    # Replace model reasoning with a deterministic responsibility at the Runtime
    # boundary. Its output requires both the supplied instruction and Skill.
    role = replace(
        resolve_child_role(role_name, RolePreset("codex", "operator-model", None, None)),
        instructions=json.dumps({"skill": "research", "reference": "references/coding.md"}),
        required_skills=("research",),
    )
    executable = tmp_path / "controlled-runtime"
    executable.write_text("#!" + sys.executable + "\n" + r'''
import json, shlex, subprocess, sys, tomllib
from pathlib import Path
if sys.argv[1:] == ['exec', '--help']:
    print('--sandbox --dangerously-bypass-hook-trust')
    raise SystemExit(0)
settings = {}
for index, argument in enumerate(sys.argv[:-1]):
    if argument == '-c':
        settings.update(tomllib.loads(sys.argv[index + 1]))
duty = json.loads(settings['developer_instructions'])
selected = [Path(entry['path']) for entry in settings['skills']['config'] if entry['enabled']]
skill = next(path for path in selected if path.parent.name == duty['skill'])
reference = skill.parent / duty['reference']
hook = shlex.split(settings['hooks']['PreToolUse'][0]['hooks'][0]['command'])
checked = subprocess.run(hook, input=json.dumps({
    'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
    'tool_input': {'command': 'cat ' + shlex.quote(str(reference))},
}), text=True, capture_output=True, check=True)
assert not checked.stdout, checked.stdout
print(json.dumps({'type': 'thread.started', 'thread_id': 'resolved-role'}), flush=True)
print(json.dumps({'type': 'item.completed', 'item': {
    'type': 'agent_message', 'text': reference.read_text(),
    'model': sys.argv[sys.argv.index('--model') + 1],
    'filesystem': settings['permissions'][settings['default_permissions']]['filesystem'][':workspace_roots'],
}}), flush=True)
print(json.dumps({'type': 'turn.completed'}), flush=True)
''')
    executable.chmod(0o755)
    context = preflight_runtime_context(
        runtime_store=harness / ".codex", executable=executable,
        git_common_directory=temporary_git_repository / ".git",
        role=role, worktree=worktree, evidence=session,
        repository_skill_source=worktree, requested_skills=(),
    ).finalize()
    started = []
    create_codex_turn(
        context.launch_document()["adapter_request"], "Execute the resolved task.",
        session, lambda identity, pid: started.append(identity),
    ).run()
    assert started == ["resolved-role"]
    events = [json.loads(line) for line in (session / "events.jsonl").read_text().splitlines()]
    result = next(event["item"] for event in events if event["type"] == "item.completed")
    assert result["text"] == (harness / ".agents/skills/research/references/coding.md").read_text()
    assert result["model"] == "operator-model"
    assert result["filesystem"]["."] == "write"
    assert result["filesystem"]["CONTEXT.md"] == "read"
