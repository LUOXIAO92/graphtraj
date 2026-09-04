"""Project discovery and Git Worktree provisioning for Agent Runner."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from .runner_models import (
    LOGICAL_ROLES,
    Project,
    RunnerError,
    Task,
)
from .project_configuration import (
    ProjectConfiguration,
    ProjectConfigurationError,
    load_project_configuration,
)


ALLOWLISTED_RUNTIMES = frozenset({"codex"})


def configured_worktree_root(runner_directory: Path) -> Path:
    """Read the canonical Ticket Worktree root needed by recovery checks."""

    configuration = _load_graphtraj_configuration(runner_directory.parent.parent)
    if runner_directory != configuration.harness_root / ".codex" / "agent-runner":
        raise RunnerError("PROJECT_CONFIG_MISMATCH", "GraphTraj Config is invalid.")
    if not configuration.agent_worktrees.is_dir():
        raise RunnerError("PROJECT_CONFIG_MISMATCH", "GraphTraj Config is invalid.")
    return configuration.agent_worktrees


def registered_worktree_owns_branch(worktree: Path, branch: str) -> bool:
    """Return whether Git registers this exact Worktree on this exact branch."""

    expected_worktree = worktree.resolve()
    expected_branch = "refs/heads/{0}".format(branch)
    matches = [
        record
        for record in registered_worktrees(worktree)
        if Path(record["worktree"]).resolve() == expected_worktree
    ]
    return len(matches) == 1 and matches[0].get("branch") == expected_branch


def provision_worktree(
    project: Project,
    task: Task,
    branch: str,
    worktree: Path,
) -> None:
    """Reuse or create the one deterministic Ticket Worktree from validated dev."""

    if preflight_worktree(project, task, branch, worktree):
        return
    expected_branch = "refs/heads/{0}".format(branch)
    branch_exists = git_succeeds(
        project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        expected_branch,
    )
    try:
        worktree.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RunnerError(
            "WORKTREE_PROVISION_FAILED",
            "The derived Ticket Worktree could not be provisioned from dev.",
        ) from error
    try:
        if branch_exists:
            run_git(project.repository, "worktree", "add", str(worktree), branch)
        else:
            run_git(
                project.repository,
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree),
                project.dev_commit,
            )
    except RunnerError as error:
        raise RunnerError(
            "WORKTREE_PROVISION_FAILED",
            "The derived Ticket Worktree could not be provisioned from dev.",
        ) from error
    record = next(
        (
            item
            for item in registered_worktrees(project.repository)
            if _resolve_path(
                Path(item["worktree"]),
                code="GIT_FAILED",
                message="A required Git operation failed.",
            )
            == worktree
        ),
        None,
    )
    if (
        record is None
        or record.get("branch") != expected_branch
        or run_git(worktree, "rev-parse", "--git-common-dir") == ""
        or (
            branch_exists
            and run_git(worktree, "rev-parse", "HEAD") != project.dev_commit
        )
    ):
        raise RunnerError(
            "WORKTREE_PROVISION_FAILED",
            "The derived Ticket Worktree could not be validated.",
        )


def preflight_worktree(
    project: Project,
    task: Task,
    branch: str,
    worktree: Path,
) -> bool:
    """Validate one derived Worktree without provisioning it.

    Return whether the exact registered Ticket Worktree already exists.
    """

    records = registered_worktrees(project.repository)
    expected_branch = "refs/heads/{0}".format(branch)
    ticket_runs = (project.worktree_root / "runs").resolve()
    registered = None
    for record in records:
        record_path = Path(record["worktree"]).resolve()
        record_branch = record.get("branch")
        if record_path == worktree:
            registered = record
        elif _registered_ticket_path_matches(record_path, ticket_runs, task):
            raise RunnerError(
                "TICKET_ALREADY_ACTIVE",
                "This ticket already has a live Ticket Worktree in another Run.",
            )
        if record_branch == expected_branch and record_path != worktree:
            raise RunnerError(
                "WORKTREE_CONFLICT",
                "The derived Ticket branch is registered at a different Worktree.",
            )
        if (
            record_branch is not None
            and record_branch.startswith("refs/heads/agent/")
            and record_branch != expected_branch
        ):
            relative_branch = record_branch[len("refs/heads/agent/") :]
            _, separator, ticket_part = relative_branch.partition("/")
            if separator and ticket_part.startswith(task.id_stem_prefix):
                raise RunnerError(
                    "TICKET_ALREADY_ACTIVE",
                    "This ticket already has a live Ticket Worktree in another Run.",
                )
    if registered is not None:
        if registered.get("branch") != expected_branch or not worktree.is_dir():
            raise RunnerError(
                "WORKTREE_CONFLICT",
                "The derived Ticket Worktree does not match its registered branch.",
            )
        return True
    if os.path.lexists(str(worktree)):
        raise RunnerError(
            "WORKTREE_CONFLICT",
            "The derived Ticket Worktree path exists but is not registered.",
        )

    branch_exists = git_succeeds(
        project.repository,
        "show-ref",
        "--verify",
        "--quiet",
        expected_branch,
    )
    if (
        branch_exists
        and run_git(project.repository, "rev-parse", expected_branch)
        != project.dev_commit
    ):
        raise RunnerError(
            "WORKTREE_CONFLICT",
            "The existing Ticket branch is not at the current validated dev state.",
        )
    return False


def _registered_ticket_path_matches(
    worktree: Path,
    ticket_runs: Path,
    task: Task,
) -> bool:
    """Return whether a registered run-scoped path owns the task identity."""

    try:
        relative = worktree.relative_to(ticket_runs)
    except ValueError:
        return False
    return (
        len(relative.parts) == 2
        and relative.parts[1].startswith(task.id_stem_prefix)
    )


def _worktree_for_branch(repository: Path, branch: str) -> Path:
    matches = [
        _resolve_path(
            Path(record["worktree"]),
            code="GIT_FAILED",
            message="A required Git operation failed.",
        )
        for record in registered_worktrees(repository)
        if record.get("branch") == "refs/heads/{0}".format(branch)
    ]
    if len(matches) != 1:
        raise RunnerError(
            "INTEGRATION_WORKTREE_INVALID",
            "The registered dev Integration Worktree is invalid.",
        )
    return matches[0]


def registered_worktrees(repository: Path) -> List[Dict[str, str]]:
    """Return the Source Repository's current porcelain Worktree records."""

    output = run_git(repository, "worktree", "list", "--porcelain")
    records: List[Dict[str, str]] = []
    record: Dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if record:
                records.append(record)
                record = {}
            continue
        key, separator, value = line.partition(" ")
        record[key] = value if separator else ""
    if record:
        records.append(record)
    return records


def run_git(
    repository: Path,
    *arguments: str,
    input_text: str | None = None,
) -> str:
    """Run a required Git operation with stable Runner failure semantics."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            input=input_text,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as error:
        raise RunnerError("GIT_FAILED", "A required Git operation failed.") from error
    if result.returncode != 0:
        raise RunnerError("GIT_FAILED", "A required Git operation failed.")
    return result.stdout.strip()


def git_succeeds(repository: Path, *arguments: str) -> bool:
    """Run a Git predicate, distinguishing a negative result from an error."""

    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise RunnerError("GIT_FAILED", "A required Git operation failed.") from error
    if result.returncode not in (0, 1):
        raise RunnerError("GIT_FAILED", "A required Git operation failed.")
    return result.returncode == 0


def _resolve_path(
    path: Path,
    *,
    code: str,
    message: str,
    allow_missing: bool = False,
) -> Path:
    """Resolve one trusted path or translate every resolution failure."""

    try:
        if allow_missing and not os.path.lexists(str(path)):
            return path.absolute()
        return path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RunnerError(code, message) from error


def discover_project(
    cwd: Path,
    selected_runtime: str | None = None,
    *,
    require_clean_integration: bool = True,
    require_runtime_executable: bool = True,
) -> Project:
    """Discover one project from its single general configuration."""

    configuration = _load_graphtraj_configuration(cwd)
    invalid = "GraphTraj Config contains invalid project paths."
    if configuration.project_root != configuration.harness_root:
        raise RunnerError("PROJECT_CONFIG_MISMATCH", invalid)
    repository = configuration.project_root
    common = _validate_source_repository(repository, invalid)
    runtime_name = "codex" if selected_runtime is None else selected_runtime
    if runtime_name not in ALLOWLISTED_RUNTIMES:
        raise RunnerError(
            "RUNTIME_UNSUPPORTED",
            "The selected Agent Runtime is not supported by this Runner.",
        )
    executable = shutil.which(runtime_name)
    runtime_executable = (
        _resolve_path(
            Path(executable),
            code="RUNTIME_EXECUTABLE_INVALID",
            message="The selected Agent Runtime executable is unavailable.",
        )
        if executable is not None
        else Path(runtime_name)
    )
    if require_runtime_executable and (
        not runtime_executable.is_file()
        or not os.access(runtime_executable, os.X_OK)
    ):
        raise RunnerError(
            "RUNTIME_EXECUTABLE_INVALID",
            "The configured Codex Runtime executable is unavailable.",
        )
    branch = "dev"
    integration = _worktree_for_branch(repository, branch)
    expected_integration = _resolve_path(
        configuration.integration_worktree,
        code="INTEGRATION_WORKTREE_INVALID",
        message="The registered dev Integration Worktree is invalid.",
    )
    if integration != expected_integration or not integration.is_dir():
        raise RunnerError(
            "INTEGRATION_WORKTREE_INVALID",
            "The registered dev Integration Worktree is invalid.",
        )
    if require_clean_integration and run_git(
        integration, "status", "--porcelain"
    ):
        raise RunnerError(
            "INTEGRATION_WORKTREE_DIRTY",
            "The dev Integration Worktree must be clean before launch.",
        )
    dev_commit = run_git(repository, "rev-parse", "refs/heads/{0}".format(branch))
    if run_git(integration, "rev-parse", "HEAD") != dev_commit:
        raise RunnerError(
            "INTEGRATION_WORKTREE_INVALID",
            "The dev Integration Worktree is not at the registered dev state.",
        )
    return Project(
        harness_root=configuration.harness_root,
        repository=repository,
        common_directory=common,
        runner_directory=configuration.harness_root / ".codex" / "agent-runner",
        worktree_root=configuration.agent_worktrees,
        state_directory=_resolve_path(
            configuration.state,
            code="PROJECT_CONFIG_MISMATCH",
            message=invalid,
            allow_missing=True,
        ),
        integration_branch=branch,
        integration_worktree=integration,
        dev_commit=dev_commit,
        runtime_executable=runtime_executable,
        role_bindings={role: role for role in LOGICAL_ROLES},
    )


def discover_runner_directory(cwd: Path) -> Path:
    """Locate Runner-owned transport state from the Harness Project Root."""
    configuration = _load_graphtraj_configuration(cwd)
    return configuration.harness_root / ".codex" / "agent-runner"


def _load_graphtraj_configuration(cwd: Path) -> ProjectConfiguration:
    root = _resolve_path(
        cwd,
        code="PROJECT_NOT_FOUND",
        message="Agent Runner must be invoked from the Harness Project Root.",
    )
    try:
        return load_project_configuration(root)
    except ProjectConfigurationError as error:
        raise RunnerError("PROJECT_CONFIG_MISMATCH", str(error)) from error


def _validate_source_repository(
    repository: Path,
    invalid: str,
) -> Path:
    try:
        top_level = _resolve_path(
            Path(run_git(repository, "rev-parse", "--show-toplevel")),
            code="PROJECT_CONFIG_MISMATCH",
            message=invalid,
        )
        common_text = run_git(repository, "rev-parse", "--git-common-dir")
        discovered_common = Path(common_text)
        if not discovered_common.is_absolute():
            discovered_common = repository / discovered_common
        discovered_common = _resolve_path(
            discovered_common,
            code="PROJECT_CONFIG_MISMATCH",
            message=invalid,
        )
    except RunnerError as error:
        raise RunnerError("PROJECT_CONFIG_MISMATCH", invalid) from error
    if top_level != repository:
        raise RunnerError("PROJECT_CONFIG_MISMATCH", invalid)
    return discovered_common
