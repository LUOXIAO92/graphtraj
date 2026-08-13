"""Project discovery and Git Worktree provisioning for Agent Runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List

import yaml

from .runner_models import Project, RunnerError, Task


RUNNER_CONFIG_VERSION = 1


def discover_project(
    cwd: Path,
    *,
    require_clean_integration: bool = True,
    require_runtime_executable: bool = True,
) -> Project:
    """Discover and validate machine-local Runner configuration from Git."""

    try:
        repository = _resolve_path(
            Path(run_git(cwd, "rev-parse", "--show-toplevel")),
            code="PROJECT_NOT_FOUND",
            message="Agent Runner must be invoked from a configured Source Repository.",
        )
        common_text = run_git(cwd, "rev-parse", "--git-common-dir")
        common = Path(common_text)
        if not common.is_absolute():
            common = cwd / common
        common = _resolve_path(
            common,
            code="PROJECT_NOT_FOUND",
            message="Agent Runner must be invoked from a configured Source Repository.",
        )
    except RunnerError as error:
        raise RunnerError(
            "PROJECT_NOT_FOUND",
            "Agent Runner must be invoked from a configured Source Repository.",
        ) from error
    config_file = common / "agent-runner" / "config.yml"
    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RunnerError(
            "RUNNER_CONFIG_NOT_FOUND",
            "Project Runner Config was not found for this Source Repository.",
        ) from error
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Project Runner Config is not readable valid YAML.",
        ) from error
    if not isinstance(config, dict):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Project Runner Config must be a mapping.",
        )
    if config.get("version") != RUNNER_CONFIG_VERSION:
        raise RunnerError(
            "RUNNER_CONFIG_VERSION_UNSUPPORTED",
            "Project Runner Config version is not supported.",
        )

    runtime_name = os.environ.get("AGENT_RUNTIME", config.get("default_runtime"))
    runtimes = config.get("runtimes")
    if not isinstance(runtime_name, str) or not isinstance(runtimes, dict):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Project Runner Config does not define a valid default Runtime.",
        )
    runtime = runtimes.get(runtime_name)
    if not isinstance(runtime, dict):
        raise RunnerError(
            "RUNTIME_NOT_CONFIGURED",
            "The selected Agent Runtime is not configured for this project.",
        )
    if runtime_name != "codex":
        raise RunnerError(
            "RUNTIME_UNSUPPORTED",
            "The selected Agent Runtime is not supported by this Runner.",
        )

    worktree_value = config.get("worktree_root")
    branch = config.get("integration_branch")
    executable_value = runtime.get("executable")
    roles = runtime.get("roles")
    if (
        not isinstance(worktree_value, str)
        or not Path(worktree_value).is_absolute()
        or branch != "dev"
        or not isinstance(executable_value, str)
        or not Path(executable_value).is_absolute()
        or not isinstance(roles, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in roles.items()
        )
    ):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Project Runner Config contains invalid project or Codex settings.",
        )
    invalid_config = (
        "Project Runner Config contains invalid project or Codex settings."
    )
    worktree_root = _resolve_path(
        Path(worktree_value),
        code="RUNNER_CONFIG_INVALID",
        message=invalid_config,
    )
    if worktree_root.name != ".agent-worktrees" or not worktree_root.is_dir():
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "The configured Worktree Directory is invalid.",
        )
    runtime_executable = _resolve_path(
        Path(executable_value),
        code="RUNNER_CONFIG_INVALID",
        message=invalid_config,
        allow_missing=True,
    )
    if require_runtime_executable and (
        not runtime_executable.is_file()
        or not os.access(runtime_executable, os.X_OK)
    ):
        raise RunnerError(
            "RUNTIME_EXECUTABLE_INVALID",
            "The configured Codex Runtime executable is unavailable.",
        )

    integration = _worktree_for_branch(repository, branch)
    expected_integration = _resolve_path(
        worktree_root / "integration",
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
    dev_commit = run_git(
        repository, "rev-parse", "refs/heads/{0}".format(branch)
    )
    if run_git(integration, "rev-parse", "HEAD") != dev_commit:
        raise RunnerError(
            "INTEGRATION_WORKTREE_INVALID",
            "The dev Integration Worktree is not at the registered dev state.",
        )

    lexical_state = worktree_root.parent / "state"
    if lexical_state.is_symlink():
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid_config)
    return Project(
        repository=repository,
        common_directory=common,
        worktree_root=worktree_root,
        state_directory=_resolve_path(
            lexical_state,
            code="RUNNER_CONFIG_INVALID",
            message=invalid_config,
            allow_missing=True,
        ),
        integration_branch=branch,
        integration_worktree=integration,
        dev_commit=dev_commit,
        runtime_executable=runtime_executable,
        role_bindings=roles,
    )


def provision_worktree(
    project: Project,
    task: Task,
    branch: str,
    worktree: Path,
) -> None:
    """Reuse or create the one deterministic Ticket Worktree from validated dev."""

    records = registered_worktrees(project.repository)
    expected_branch = "refs/heads/{0}".format(branch)
    registered = None
    for record in records:
        record_path = _resolve_path(
            Path(record["worktree"]),
            code="GIT_FAILED",
            message="A required Git operation failed.",
        )
        record_branch = record.get("branch")
        if record_path == worktree:
            registered = record
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
        return
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
