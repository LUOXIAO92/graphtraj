from __future__ import annotations

import copy
import json
import shlex
import sys
import tomllib
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


def test_codex_turn_appends_stderr_for_later_diagnostic_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    from graphtraj.codex_adapter import create_codex_turn

    executable = tmp_path / "runtime"
    executable.write_text(
        "#!{0}\n".format(sys.executable)
        + "import json, sys\n"
        + "sys.stderr.write(sys.stdin.read() + '\\n')\n"
        + "print(json.dumps({'type': 'thread.started', 'thread_id': 'diagnostic'}))\n"
        + "print(json.dumps({'type': 'turn.completed'}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    session = tmp_path / "session"
    session.mkdir()
    request = {
        "arguments": [str(executable), "exec", "--json", "-"],
        "worktree_path": str(tmp_path),
    }

    create_codex_turn(request, "first diagnostic", session, lambda *_: None).run()
    create_codex_turn(request, "second diagnostic", session, lambda *_: None).run()

    assert (session / "stderr.log").read_text(encoding="utf-8") == (
        "first diagnostic\nsecond diagnostic\n"
    )


def test_current_runtime_diagnostic_uses_only_current_error_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from graphtraj.team_round import (
        _current_runtime_diagnostic,
        _runtime_access_failure,
        _runtime_command_parse_error,
    )

    session = tmp_path / "session"
    session.mkdir()
    stderr = session / "stderr.log"
    stderr.write_text("retained Permission denied diagnostic\n", encoding="utf-8")
    stderr_offset = stderr.stat().st_size
    events = session / "events.jsonl"
    events.write_text(
        json.dumps({"type": "report-observed", "content": "Permission denied"})
        + "\n",
        encoding="utf-8",
    )
    event_offset = events.stat().st_size
    with events.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": "source says Permission denied",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            )
            + "\n"
        )
        stream.write(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "the Agent quoted Permission denied",
                    },
                }
            )
            + "\n"
        )

    diagnostic = _current_runtime_diagnostic(
        session, stderr_offset, event_offset
    )
    assert not _runtime_access_failure(diagnostic)

    parse_offset = events.stat().st_size
    with events.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": "Cannot verify option: --glob",
                        "exit_code": 1,
                        "status": "failed",
                    },
                }
            )
            + "\n"
        )
    parse_diagnostic = _current_runtime_diagnostic(
        session, stderr_offset, parse_offset
    )
    assert not _runtime_access_failure(parse_diagnostic)
    assert _runtime_command_parse_error(parse_diagnostic) == "Cannot verify option: --glob"

    denial_offset = events.stat().st_size
    with events.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "aggregated_output": (
                            "permissionDecision deny: the report target is not "
                            "authorized for this role"
                        ),
                        "exit_code": 1,
                        "status": "failed",
                    },
                }
            )
            + "\n"
        )
    denial = _current_runtime_diagnostic(session, stderr_offset, denial_offset)
    assert _runtime_access_failure(denial)


def test_reviewer_send_refreshes_exact_replacement_report_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from graphtraj.codex_adapter import _toml_value
    from graphtraj.runner_control import _refresh_current_team_report_request

    worktree = tmp_path / "worktree"
    evidence = tmp_path / "evidence"
    worktree.mkdir()
    evidence.mkdir()
    hooks = {
        event: [{"hooks": [{"type": "command", "command": "python /tmp/worktree_guard.py"}]}]
        for event in ("PreToolUse", "SubagentStart")
    }
    request = {
        "arguments": [
            "/tmp/codex",
            "exec",
            "--model",
            "reviewer-model",
            "-c",
            'default_permissions="restricted"',
            "-c",
            'permissions={ restricted = { filesystem = { "." = "write" } } }',
            "-c",
            "hooks={0}".format(_toml_value(hooks)),
            "--json",
            "-",
        ],
        "worktree_path": str(worktree),
    }
    original = copy.deepcopy(request)
    report = Path(".state") / "reviews" / "r1-replacement.md"

    refreshed = _refresh_current_team_report_request(
        request,
        {"role": "spec-reviewer", "report_file": report.as_posix()},
        worktree,
        {
            "GRAPHTRAJ_EVIDENCE": str(evidence),
            "GRAPHTRAJ_TEAM_GENERATION": "1",
            "GRAPHTRAJ_TEAM_ROUND": "2",
        },
    )

    assert request == original
    arguments = refreshed["arguments"]
    assert arguments[:4] == ["/tmp/codex", "exec", "--model", "reviewer-model"]
    permissions = tomllib.loads(
        next(argument for argument in arguments if argument.startswith("permissions="))
    )["permissions"]
    filesystem = permissions["restricted"]["filesystem"]
    canonical = evidence / "reviews" / report.name
    view = worktree / report
    assert filesystem[str(canonical)] == "write"
    assert str(view) not in filesystem
    hooks = tomllib.loads(
        next(argument for argument in arguments if argument.startswith("hooks="))
    )["hooks"]
    for event in ("PreToolUse", "SubagentStart"):
        hook = shlex.split(hooks[event][0]["hooks"][0]["command"])
        write_paths = {
            hook[index + 1]
            for index, value in enumerate(hook[:-1])
            if value == "--write-path"
        }
        assert write_paths == {str(canonical), str(view)}
