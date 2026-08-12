from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from conftest import InstalledCommands, run_process


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = PROJECT_ROOT / "src" / "you_are_a_product_architect" / "resources" / "codex"
WORKTREE_GUARD = RESOURCE_ROOT / "hooks" / "worktree_guard.py"


def run_hook(
    hook: Path,
    event: dict,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(hook)],
        cwd=cwd,
        input=json.dumps(event),
        check=False,
        text=True,
        capture_output=True,
    )


def run_worktree_guard(event: dict, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return run_hook(WORKTREE_GUARD, event, cwd=cwd)


def assert_hook_denies(hook: Path, event: dict, *, cwd: Path) -> None:
    result = run_hook(hook, event, cwd=cwd)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def assert_worktree_guard_denies(event: dict, *, cwd: Path) -> None:
    assert_hook_denies(WORKTREE_GUARD, event, cwd=cwd)


def exercise_linked_worktree_git_file_guard(hook: Path, linked_worktree: Path) -> None:
    git_file = linked_worktree / ".git"
    git_pointer = linked_worktree / "git-pointer"
    assert git_file.is_file()
    git_pointer.symlink_to(".git")
    assert git_pointer.resolve() == git_file

    actions = (
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
    )
    for tool_name, command in actions:
        assert_hook_denies(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(linked_worktree),
                "tool_name": tool_name,
                "tool_input": {"command": command},
            },
            cwd=linked_worktree,
        )


def python_escape_commands(normalized_foreign_worktree: Path) -> tuple[str, ...]:
    return (
        "python",
        "python3",
        "uv run python",
        "uv run python3",
        "uv run -- python",
        "uv run -- python3",
        "python -m compileall",
        "python -m unittest discover {0}".format(normalized_foreign_worktree),
        "python3 -m unittest discover {0}".format(normalized_foreign_worktree),
        "uv run python -m unittest discover {0}".format(normalized_foreign_worktree),
    )


def exercise_ticket_evidence_scope(
    hook: Path,
    *,
    source_repository: Path,
    harness_root: Path,
    suffix: str,
) -> None:
    run_id = "20260813-{0}".format(suffix)
    ticket_name = "7-{0}".format(suffix)
    ticket_worktree = (
        harness_root
        / ".agent-worktrees"
        / "runs"
        / run_id
        / ticket_name
    )
    evidence = (
        harness_root
        / "state"
        / "task-delivery"
        / run_id
        / "tickets"
        / ticket_name
    )
    sibling_evidence = evidence.parent / "8-sibling"
    mispointed_evidence = (
        harness_root
        / "state"
        / "task-delivery"
        / "other-run"
        / "tickets"
        / ticket_name
    )
    evidence.mkdir(parents=True)
    sibling_evidence.mkdir()
    mispointed_evidence.mkdir(parents=True)
    run_process(
        ["git", "worktree", "add", "-b", "ticket-{0}".format(suffix), str(ticket_worktree)],
        cwd=source_repository,
    ).check_returncode()
    scratch = ticket_worktree / ".scratch"
    scratch.mkdir()
    scoped_scratch = scratch / "task-delivery"
    scoped_scratch.symlink_to(evidence, target_is_directory=True)
    alias_report = (
        ".scratch/task-delivery/reviews/"
        "42-payment-retry@e1-r1-spec.md"
    )

    for command in (
        "touch .scratch/task-delivery/result.md",
        "touch .scratch/task-delivery/validation.md",
        "mkdir -p .scratch/task-delivery/reviews",
        "touch .scratch/task-delivery/reviews/{0}-r1-standards.md".format(suffix),
        "touch .scratch/task-delivery/reviews/{0}-r1-spec.md".format(suffix),
    ):
        allowed = run_hook(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=ticket_worktree,
        )
        assert allowed.returncode == 0, allowed.stderr
        assert allowed.stdout == "", (command, allowed.stdout)

    alias_actions = (
        ("Bash", "touch {0}".format(alias_report)),
        (
            "apply_patch",
            """*** Begin Patch
*** Add File: .scratch/task-delivery/reviews/42-payment-retry@e1-r1-spec.md
+Raw Spec Reviewer report
*** End Patch
""",
        ),
    )
    alias_results = [
        (
            tool_name,
            run_hook(
                hook,
                {
                    "hook_event_name": "PreToolUse",
                    "cwd": str(ticket_worktree),
                    "tool_name": tool_name,
                    "tool_input": {"command": command},
                },
                cwd=ticket_worktree,
            ),
        )
        for tool_name, command in alias_actions
    ]
    assert [result.returncode for _, result in alias_results] == [0, 0]
    assert [(tool_name, result.stdout) for tool_name, result in alias_results] == [
        ("Bash", ""),
        ("apply_patch", ""),
    ]

    assert_hook_denies(
        hook,
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
    nested_current_target = evidence / "current-target"
    nested_current_target.mkdir()
    nested_current = evidence / "current-link"
    nested_current.symlink_to(nested_current_target, target_is_directory=True)

    local_target = ticket_worktree / "local-target"
    local_target.mkdir()
    local_link_parent = ticket_worktree / "nested" / "deep"
    local_link_parent.mkdir(parents=True)
    relocatable_link = local_link_parent / "relocatable-link"
    relocatable_link.symlink_to("../../local-target", target_is_directory=True)
    assert relocatable_link.resolve() == local_target

    for command in (
        "touch .scratch/task-delivery/sibling-link/result.md",
        "touch .scratch/task-delivery/current-link/result.md",
        (
            "cp -a nested/deep/relocatable-link "
            ".scratch/task-delivery/copied-link"
        ),
        "ln -s {0} .scratch/task-delivery/linked-sibling".format(sibling_evidence),
    ):
        assert_hook_denies(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=ticket_worktree,
        )

    for wrong_evidence in (sibling_evidence, mispointed_evidence):
        scoped_scratch.unlink()
        scoped_scratch.symlink_to(wrong_evidence, target_is_directory=True)
        assert_hook_denies(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(ticket_worktree),
                "tool_name": "Bash",
                "tool_input": {"command": "touch .scratch/task-delivery/result.md"},
            },
            cwd=ticket_worktree,
        )


def semantic_and_expansion_bypasses() -> tuple[str, ...]:
    """Commands whose behavior cannot safely follow generic option parsing."""
    return (
        "git apply --unsafe-paths local.patch",
        "git rebase --exec='touch /tmp/escaped' main",
        "git rebase -x 'touch /tmp/escaped' main",
        "git diff --ext-diff",
        "git show --textconv HEAD",
        "git commit --gpg-sign -m candidate",
        "sed -e 'w /tmp/escaped' README.md",
        "rg --pre='cat /tmp/foreign' pattern .",
        "grep -f/tmp/patterns README.md",
        "grep -f /tmp/patterns README.md",
        "uv run --project=/tmp/foreign pytest",
        "uv run --project /tmp/foreign pytest",
        "uv run --env-file=/tmp/foreign.env pytest",
        "uv run --with-requirements /tmp/requirements.txt pytest",
        "pytest -p malicious_plugin",
        "touch {.,..}/{.,..}/{inside,integration}/escaped.txt",
        "touch ../integ*/escaped.txt",
        "touch ~/escaped.txt",
        "touch $@",
        "bash -ic 'touch escaped.txt'",
        "bash --rcfile /tmp/rc -c 'touch escaped.txt'",
        "echo escaped >| /tmp/escaped.txt",
    )


def test_packaged_config_defines_the_project_local_codex_workspace() -> None:
    config = (RESOURCE_ROOT / "config.toml").read_text(encoding="utf-8")

    assert 'model = "gpt-5.6-sol"' in config
    assert 'model_reasoning_effort = "xhigh"' in config
    assert 'sandbox_mode = "workspace-write"' in config
    assert 'writable_roots = [".scratch"]' in config
    assert 'max_concurrent_threads_per_session = 12' in config


def test_packaged_engineer_roles_keep_the_accepted_models_and_review_defaults() -> None:
    expected_roles = {
        "engineer-junior.toml": ("gpt-5.6-luna", "gpt-5.6-terra"),
        "engineer-senior.toml": ("gpt-5.6-terra", "gpt-5.6-terra"),
        "engineer-expert.toml": ("gpt-5.6-sol", "gpt-5.6-sol"),
    }

    for filename, (model, reviewer_model) in expected_roles.items():
        role = (RESOURCE_ROOT / "agents" / filename).read_text(encoding="utf-8")

        assert 'model = "{0}"'.format(model) in role
        assert 'model_reasoning_effort = "max"' in role
        assert 'default_subagent_model = "{0}"'.format(reviewer_model) in role
        assert 'default_subagent_reasoning_effort = "max"' in role
        for skill in ("$implement", "$tdd", "$code-review"):
            assert skill in role
        assert 'sandbox_mode = "workspace-write"' in role
        assert "approval_policy" not in role
        assert "network_access" not in role
        assert '$(git rev-parse --show-toplevel)/.codex/hooks/worktree_guard.py' in role
        assert "${HOME}" not in role
        assert "~/.codex" not in role
        assert "[[hooks.PreToolUse]]" in role
        assert "[[hooks.SubagentStart]]" in role
        for evidence_instruction in (
            "`.scratch/task-delivery/result.md`",
            "`.scratch/task-delivery/validation.md`",
            "`reviews/<alias>-rN-standards.md`",
            "`reviews/<alias>-rN-spec.md`",
            "Do not declare review PASS",
            "The Runner owns `metadata.yml`",
            "The Delivery State Agent owns the ledger and DAG",
        ):
            assert evidence_instruction in role


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
    assert "Do not access any other Git worktree." in context


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
        {
            "command": "pwd",
            "cwd": str(temporary_git_repository),
            "workdir": str(foreign_worktree),
        },
        {"command": "git -C {0} status".format(foreign_worktree)},
        {"command": "cat {0}/README.md".format(foreign_worktree)},
        {"command": "rg target {0}".format(foreign_worktree)},
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

    foreign_headers = (
        "*** Add File:",
        "*** Update File:",
        "*** Delete File:",
        "*** Move to:",
    )
    for header in foreign_headers:
        foreign_patch = """*** Begin Patch
{0} {1}/foreign.txt
*** End Patch
""".format(header, foreign_worktree)
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "apply_patch",
                "tool_input": {"command": foreign_patch},
            },
            cwd=temporary_git_repository,
        )


def test_worktree_guard_fails_closed_for_unparseable_or_non_git_tool_events(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    malformed_patch = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "apply_patch",
            "tool_input": {"command": "this is not an apply patch"},
        },
        cwd=temporary_git_repository,
    )
    assert json.loads(malformed_patch.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    nonmutating = run_worktree_guard(
        {
            "hook_event_name": "Stop",
            "cwd": str(temporary_git_repository),
        },
        cwd=temporary_git_repository,
    )
    assert nonmutating.returncode == 0
    assert nonmutating.stdout == ""

    not_a_repository = tmp_path / "not-a-repository"
    not_a_repository.mkdir()
    failed_discovery = run_worktree_guard(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(not_a_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        },
        cwd=not_a_repository,
    )
    assert json.loads(failed_discovery.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_worktree_guard_anchors_the_root_to_its_process_cwd(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

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
        'TARGET=local.txt rm "$TARGET"',
        'SOURCE=local.txt cp "$SOURCE" copied.txt',
        'env TARGET=local.txt mv "$TARGET" renamed.txt',
        "rm ${TARGET}",
        "touch $(pwd)/created.txt",
        "rm `pwd`/created.txt",
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
    tmp_path: Path,
) -> None:
    foreign_worktree = tmp_path / "foreign-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "foreign", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    for command in (
        "bash -c 'touch nested-created.txt'",
        "sh -c 'touch nested-sh-created.txt'",
        "bash -c 'rm {0}/README.md'".format(foreign_worktree),
        "sh -c 'cp README.md {0}/copied.md'".format(foreign_worktree),
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
    normalized_command = "python -m unittest discover {0}".format(normalized_foreign)
    assert "/.agent-worktrees/runs/../integration" in str(normalized_foreign)
    assert str(foreign_worktree) not in normalized_command
    assert os.path.relpath(foreign_worktree, temporary_git_repository) not in normalized_command

    for command in python_escape_commands(normalized_foreign):
        result = run_worktree_guard(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
        if command == normalized_command:
            assert (
                payload["hookSpecificOutput"]["permissionDecisionReason"]
                == "Cannot verify Python payload."
            )


def test_worktree_guard_checks_newlines_equals_options_and_unknown_wrappers(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-the-worktree"
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


def test_worktree_guard_fails_closed_for_environment_and_short_option_wrappers(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-the-worktree"
    for command in (
        "GIT_EXTERNAL_DIFF=/bin/sh git diff",
        "env GIT_EXTERNAL_DIFF=/bin/sh git diff",
        "git -c alias.escape='!rm /tmp/escaped' status",
        "git -C{0} status".format(outside),
        "./git status",
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

    for option in ("-C", "--directory", "--work-tree", "--git-dir", "--output", "--output-directory", "--prefix", "--path", "--workdir", "--cwd"):
        assert_worktree_guard_denies(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": "git {0}={1} status".format(option, outside)},
            },
            cwd=temporary_git_repository,
        )

    assert_worktree_guard_denies(
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "unknown-mutating-wrapper local-output.txt"},
        },
        cwd=temporary_git_repository,
    )


def test_worktree_guard_fails_closed_for_command_semantics_and_shell_expansion(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    # This is a registered sibling worktree that the brace expansion below
    # would reach as .././integration from the primary worktree.
    foreign_worktree = (
        tmp_path
        / "installed-foreign-harness"
        / ".agent-worktrees"
        / "integration"
    )
    foreign_worktree.parent.mkdir(parents=True)
    run_process(
        ["git", "worktree", "add", "-b", "integration", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    for command in semantic_and_expansion_bypasses():
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
        "pushd subdir; touch link/escaped.txt",
        "popd && touch escaped.txt",
        "unknown-mutating-wrapper local-output.txt",
        "./git status",
        "git -C subdir commit -F link/COMMIT_MESSAGE",
        "git -Csubdir commit -F link/COMMIT_MESSAGE",
        "git -C=subdir commit -F link/COMMIT_MESSAGE",
        "uv run --directory subdir touch link/escaped.txt",
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

    for command in (
        "cat .git",
        "tee .git/config",
        "rm -r .git",
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


def test_worktree_guard_denies_symlinks_to_the_linked_worktree_git_file(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    linked_worktree = tmp_path / "git-file-worktree"
    run_process(
        ["git", "worktree", "add", "-b", "git-file-target", str(linked_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()

    exercise_linked_worktree_git_file_guard(WORKTREE_GUARD, linked_worktree)


def test_worktree_guard_allows_only_ticket_scoped_persistent_evidence(
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    exercise_ticket_evidence_scope(
        WORKTREE_GUARD,
        source_repository=temporary_git_repository,
        harness_root=tmp_path / "harness",
        suffix="source",
    )


def test_worktree_guard_keeps_a_small_useful_command_surface(
    temporary_git_repository: Path,
) -> None:
    for command in (
        "mkdir -p build && touch build/output.txt",
        "cat README.md | tee build/copied.txt",
        "rg target .",
        "git status --short",
        "git diff --check",
        "git add README.md",
        "git commit -m candidate",
        "uv run pytest -q",
        "python -m pytest -q",
        "python --version",
        "python3 -V",
        "uv run python --version",
        "python -m compileall -q .",
    ):
        result = run_worktree_guard(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", (command, result.stdout)


def test_packaged_merge_resolver_is_confined_to_integration_reconciliation() -> None:
    resolver = (RESOURCE_ROOT / "agents" / "merge-resolver.toml").read_text(
        encoding="utf-8"
    )

    assert 'model = "gpt-5.6-sol"' in resolver
    assert 'model_reasoning_effort = "max"' in resolver
    assert "$resolving-merge-conflicts" in resolver
    for prohibition in (
        "current Integration Worktree",
        "Do not change merge order",
        "integrate additional commits",
        "reopen settled scope",
        "redesign the ticket or spec",
    ):
        assert prohibition in resolver
    assert 'sandbox_mode = "workspace-write"' in resolver
    assert "approval_policy" not in resolver
    assert "network_access" not in resolver
    assert '$(git rev-parse --show-toplevel)/.codex/hooks/worktree_guard.py' in resolver


def test_installed_package_exposes_complete_codex_resources(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    tmp_path: Path,
) -> None:
    interpreter = installed_commands.product.resolve().parent / "python"
    purelib = subprocess.run(
        [str(interpreter), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    installed_resources = Path(purelib) / "you_are_a_product_architect" / "resources" / "codex"
    expected_files = (
        installed_resources / "config.toml",
        installed_resources / "hooks" / "worktree_guard.py",
        installed_resources / "agents" / "engineer-junior.toml",
        installed_resources / "agents" / "engineer-senior.toml",
        installed_resources / "agents" / "engineer-expert.toml",
        installed_resources / "agents" / "merge-resolver.toml",
    )
    assert all(path.is_file() for path in expected_files)

    for resource in expected_files:
        assert resource.read_text(encoding="utf-8")
    assert tomllib.loads((installed_resources / "config.toml").read_text(encoding="utf-8"))[
        "sandbox_workspace_write"
    ]["writable_roots"] == [".scratch"]

    hook = installed_resources / "hooks" / "worktree_guard.py"
    result = run_hook(
        hook,
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(temporary_git_repository),
            "tool_name": "Bash",
            "tool_input": {"command": "touch installed-hook-check"},
        },
        cwd=temporary_git_repository,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    foreign_worktree = (
        tmp_path
        / "installed-foreign-harness"
        / ".agent-worktrees"
        / "integration"
    )
    foreign_worktree.parent.mkdir(parents=True)
    run_process(
        ["git", "worktree", "add", "-b", "integration", str(foreign_worktree)],
        cwd=temporary_git_repository,
    ).check_returncode()
    foreign_event = run_hook(
        hook,
        {
            "hook_event_name": "PreToolUse",
            "cwd": str(foreign_worktree),
            "tool_name": "Bash",
            "tool_input": {"command": "touch escaped-installed-hook.txt"},
        },
        cwd=temporary_git_repository,
    )
    assert json.loads(foreign_event.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    exercise_linked_worktree_git_file_guard(hook, foreign_worktree)

    normalized_foreign = foreign_worktree.parent / "runs" / ".." / foreign_worktree.name
    assert "/.agent-worktrees/runs/../integration" in str(normalized_foreign)
    assert str(foreign_worktree) not in str(normalized_foreign)
    assert (
        os.path.relpath(foreign_worktree, temporary_git_repository)
        not in str(normalized_foreign)
    )
    for command in python_escape_commands(normalized_foreign):
        assert_hook_denies(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )

    exercise_ticket_evidence_scope(
        hook,
        source_repository=temporary_git_repository,
        harness_root=tmp_path / "installed-harness",
        suffix="installed",
    )

    for command in semantic_and_expansion_bypasses():
        assert_hook_denies(
            hook,
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(temporary_git_repository),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=temporary_git_repository,
        )
