"""Project discovery and Git Worktree provisioning for Agent Runner."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from graphtraj.execution.runner_models import (
    Project,
    RunnerError,
    Task,
)
from graphtraj.configuration.project_configuration import (
    ProjectConfiguration,
    ProjectConfigurationError,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import ProjectRolesError, load_project_roles


ALLOWLISTED_RUNTIMES = frozenset({"codex"})


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
    registered = None
    for record in records:
        record_path = Path(record["worktree"]).resolve()
        record_branch = record.get("branch")
        if record_path == worktree:
            registered = record
        if record_branch == expected_branch and record_path != worktree:
            raise RunnerError(
                "WORKTREE_CONFLICT",
                "The derived Ticket branch is registered at a different Worktree.",
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


def runtime_executable(runtime_name: str) -> Path:
    """Resolve the executable for one selected reusable role Runtime."""
    if runtime_name not in ALLOWLISTED_RUNTIMES:
        raise RunnerError(
            "RUNTIME_UNSUPPORTED",
            "The selected Agent Runtime is not supported by this Runner.",
        )
    executable = shutil.which(runtime_name)
    if executable is None:
        raise RunnerError(
            "RUNTIME_EXECUTABLE_INVALID",
            "The configured Codex Runtime executable is unavailable.",
        )
    resolved = _resolve_path(
        Path(executable),
        code="RUNTIME_EXECUTABLE_INVALID",
        message="The selected Agent Runtime executable is unavailable.",
    )
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RunnerError(
            "RUNTIME_EXECUTABLE_INVALID",
            "The configured Codex Runtime executable is unavailable.",
        )
    return resolved


def discover_project(
    cwd: Path,
    *,
    require_clean_integration: bool = True,
) -> Project:
    """Discover one project from its single general configuration."""

    configuration = _load_graphtraj_configuration(cwd)
    try:
        roles = load_project_roles(configuration.harness_root)
    except ProjectRolesError as error:
        raise RunnerError("ROLE_CONFIG_INVALID", str(error)) from error
    invalid = "GraphTraj Config contains invalid project paths."
    repository = configuration.project_root
    common = _validate_source_repository(repository, invalid)
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
        runner_directory=configuration.harness_root / ".graphtraj" / "runner",
        worktree_root=configuration.agent_worktrees,
        state_directory=_resolve_path(
            configuration.state,
            code="PROJECT_CONFIG_MISMATCH",
            message=invalid,
            allow_missing=True,
        ),
        documents_directory=configuration.docs,
        integration_branch=branch,
        integration_worktree=integration,
        dev_commit=dev_commit,
        roles=roles,
        max_concurrency=configuration.max_concurrency,
    )


def discover_runner_directory(cwd: Path) -> Path:
    """Locate Runner-owned transport state from the Harness Project Root."""
    configuration = _load_graphtraj_configuration(cwd)
    return configuration.harness_root / ".graphtraj" / "runner"


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
