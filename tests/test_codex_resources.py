from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import run_process


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = PROJECT_ROOT / "src" / "graphtraj" / "resources" / "codex"
WORKTREE_GUARD = RESOURCE_ROOT / "hooks" / "worktree_guard.py"


def run_hook(
    hook: Path,
    event: dict,
    *,
    cwd: Path,
    arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(hook), *arguments],
        cwd=cwd,
        input=json.dumps(event),
        check=False,
        text=True,
        capture_output=True,
    )


def run_worktree_guard(
    event: dict,
    *,
    cwd: Path,
    arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return run_hook(WORKTREE_GUARD, event, cwd=cwd, arguments=arguments)


def assert_hook_denies(
    hook: Path,
    event: dict,
    *,
    cwd: Path,
    arguments: tuple[str, ...] = (),
) -> None:
    result = run_hook(hook, event, cwd=cwd, arguments=arguments)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def assert_worktree_guard_denies(
    event: dict,
    *,
    cwd: Path,
    arguments: tuple[str, ...] = (),
) -> None:
    assert_hook_denies(WORKTREE_GUARD, event, cwd=cwd, arguments=arguments)


def test_worktree_guard_adds_the_current_boundary_to_subagent_context(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    result = run_worktree_guard(
        {
            "hook_event_name": "SubagentStart",
            "cwd": str(temporary_git_repository),
        },
        cwd=temporary_git_repository,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert str(temporary_git_repository) in context


def test_worktree_guard_allows_in_worktree_actions(
    temporary_git_repository: Path,
) -> None:
    result = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p build && touch build/output.txt"},
        },
        cwd=temporary_git_repository,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_worktree_guard_blocks_foreign_worktree_workdirs_and_command_references(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    events = (
        {"command": "pwd", "cwd": str(foreign_worktree)},
        {"command": "pwd", "workdir": str(foreign_worktree)},
        {"command": "git -C {0} status".format(foreign_worktree)},
    )
    for tool_input in events:
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": tool_input,
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_checks_all_apply_patch_target_kinds(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    allowed_patch = """*** Begin Patch
*** Add File: created.txt
+content
*** Update File: README.md
@@
-# Target project
+# Changed target project
*** Delete File: obsolete.txt
*** Move to: renamed.txt
*** End Patch
"""
    allowed = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "apply_patch",
            "tool_input": {"command": allowed_patch},
        },
        cwd=temporary_git_repository,
    )
    assert allowed.returncode == 0
    assert allowed.stdout == ""

    foreign_patch = """*** Begin Patch
*** Add File: {0}/foreign.txt
*** End Patch
""".format(foreign_worktree)
    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "apply_patch",
            "tool_input": {"command": foreign_patch},
        },
        cwd=temporary_git_repository,
    )


def test_worktree_guard_fails_closed_without_a_verifiable_boundary(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "apply_patch",
            "tool_input": {"command": "this is not an apply patch"},
        },
        cwd=temporary_git_repository,
    )

    not_a_repository = tmp_path / "not-a-repository"
    not_a_repository.mkdir()
    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(not_a_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        },
        cwd=not_a_repository,
    )


def test_worktree_guard_anchors_the_root_to_its_process_cwd(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    foreign_worktree.mkdir()

    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(foreign_worktree),
            "tool_name": "Bash",
            "tool_input": {"command": "touch would-write-foreign.txt"},
        },
        cwd=temporary_git_repository,
    )


def test_worktree_guard_denies_dynamic_path_operands_even_when_they_look_local(
    temporary_git_repository: Path,
) -> None:
    commands = (
        "TARGET=local.txt touch local.txt",
        "touch $(pwd)/created.txt",
    )
    for command in commands:
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_rejects_nested_shell_and_python_code_payloads(
    temporary_git_repository: Path,
) -> None:
    for command in (
        "bash -c 'touch nested-created.txt'",
        "python -c \"from pathlib import Path; Path('generated.txt').write_text('x')\"",
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_rejects_python_repls_and_opaque_unittest_paths(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = (
        tmp_path
        / "python-harness"
        / ".agent-worktrees"
        / "integration"
    )
    foreign_worktree.parent.mkdir(parents=True)
    run_process(
        ["git", "worktree", "add", "-b", "integration", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()
    normalized_foreign = foreign_worktree.parent / "runs" / ".." / foreign_worktree.name

    for command in (
        "python",
        "uv run python -m unittest discover {0}".format(normalized_foreign),
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_checks_newlines_equals_options_and_unknown_wrappers(
    temporary_git_repository: Path,
) -> None:
    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "Bash",
            "tool_input": {
                "command": "touch first.txt\nunknown-mutating-wrapper second.txt"
            },
        },
        cwd=temporary_git_repository,
    )


def test_worktree_guard_reports_unsupported_command_input_without_a_path_denial(
    temporary_git_repository: Path,
) -> None:
    result = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "rg --glob py needle ."},
        },
        cwd=temporary_git_repository,
    )
    reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == "Cannot verify option: --glob"


def test_worktree_guard_rejects_unsafe_command_forms(
    temporary_git_repository: Path,
) -> None:
    for command in (
        "git apply --unsafe-paths local.patch",
        "git rebase --exec='touch /tmp/escaped' main",
        "git -c core.pager=cat status",
        "sed -e 'w /tmp/escaped' README.md",
        "rg --pre='cat /tmp/foreign' pattern .",
        "grep -f /tmp/patterns README.md",
        "pytest -p malicious_plugin",
        "uv run --project /tmp/foreign pytest",
        "touch ../integ*/escaped.txt",
        "echo escaped >| /tmp/escaped.txt",
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_rejects_stateful_cwd_unknown_tools_and_symlink_escapes(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()
    subdirectory = temporary_git_repository / "subdir"
    subdirectory.mkdir()
    (subdirectory / "link").symlink_to(foreign_worktree, target_is_directory=True)

    for command in (
        "cd subdir && touch link/escaped.txt",
        "git -C subdir commit -F link/COMMIT_MESSAGE",
        "unknown-mutating-wrapper local-output.txt",
        "./git status",
        "cat .git",
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )

    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "unregistered_tool",
            "tool_input": {"command": "touch escaped.txt"},
        },
        cwd=temporary_git_repository,
    )


def test_worktree_guard_denies_symlinks_to_the_linked_worktree_git_file(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    linked_worktree = tmp_path / "git-file-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "git-file-target", str(linked_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    git_pointer = linked_worktree / "git-pointer"
    git_pointer.symlink_to(".git")

    for tool_name, command in (
        ("Bash", "tee git-pointer"),
        (
            "apply_patch",
            """*** Begin Patch
*** Update File: git-pointer
@@
-old
+new
*** End Patch
""",
        ),
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(linked_worktree),
                "tool_name": tool_name,
                "tool_input": {"command": command},
            },
            cwd=linked_worktree,
        )


def test_worktree_guard_allows_only_ticket_scoped_persistent_evidence(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    ticket_name = "7-source"
    harness_root = tmp_path / "harness"
    ticket_worktree = (
        harness_root
        / ".graphtraj"
        / ".agent-worktrees"
        / ticket_name
    )
    evidence = (
        harness_root / ".graphtraj" / "state" / "tickets" / ticket_name
    )
    config = harness_root / ".graphtraj" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """version: 1
paths:
  project_root: .
  docs: docs
  agent_worktrees: .graphtraj/.agent-worktrees
  state: .graphtraj/state
agent_runner:
  dispatch_depth: 2
  max_concurrency: 18
""",
        encoding="utf-8",
    )
    sibling_evidence = evidence.parent / "8-sibling"
    evidence.mkdir(parents=True)
    sibling_evidence.mkdir()
    run_process(
        ["git", "worktree", "add", "-b", "ticket-source", str(ticket_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()
    scoped_state = ticket_worktree / ".state"
    scoped_state.symlink_to(evidence, target_is_directory=True)
    report_view = scoped_state / "teams" / "1" / "rounds" / "1" / "engineer.md"
    report_target = evidence / "teams" / "1" / "rounds" / "1" / "engineer.md"
    authorization = (
        "--write-path",
        str(report_view),
        "--write-path",
        str(report_target),
    )

    for command in (
        "touch .state/teams/1/rounds/1/engineer.md",
        "touch {0}".format(report_target),
        "tee .state/teams/1/rounds/1/engineer.md",
    ):
        allowed = run_worktree_guard(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=ticket_worktree,
            arguments=authorization,
        )
        assert allowed.returncode == 0, allowed.stderr
        assert allowed.stdout == ""

    allowed_patch = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": """*** Begin Patch
*** Add File: .state/teams/1/rounds/1/engineer.md
+Engineer report
*** End Patch
"""
            },
        },
        cwd=ticket_worktree,
        arguments=authorization,
    )
    assert allowed_patch.returncode == 0, allowed_patch.stderr
    assert allowed_patch.stdout == ""

    denied_report = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "Bash",
            "tool_input": {
                "command": "touch .state/teams/1/rounds/1/validation.md"
            },
        },
        cwd=ticket_worktree,
        arguments=authorization,
    )
    denied_payload = json.loads(denied_report.stdout)
    reason = denied_payload["hookSpecificOutput"]["permissionDecisionReason"]
    assert denied_payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "source=Worktree Guard" in reason
    assert "current_worktree={0}".format(ticket_worktree) in reason
    assert "requested=.state/teams/1/rounds/1/validation.md" in reason
    assert "resolved=" in reason
    assert "condition=" in reason

    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "Bash",
            "tool_input": {"command": "touch {0}/direct-write.md".format(evidence)},
        },
        cwd=ticket_worktree,
    )

    nested_sibling = evidence / "sibling-link"
    nested_sibling.symlink_to(sibling_evidence, target_is_directory=True)
    for command in (
        "touch .state/sibling-link/result.md",
        "cp README.md .state/copied.md",
    ):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=ticket_worktree,
        )

    scoped_state.unlink()
    scoped_state.symlink_to(sibling_evidence, target_is_directory=True)
    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(ticket_worktree),
            "tool_name": "Bash",
            "tool_input": {"command": "touch .state/teams/1/rounds/1/engineer.md"},
        },
        cwd=ticket_worktree,
    )
