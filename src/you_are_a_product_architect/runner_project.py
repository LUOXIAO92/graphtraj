"""Project discovery and Git Worktree provisioning for Agent Runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List

import yaml

from .runner_models import Project, RunnerError, Task


RUNNER_CONFIG_VERSION = 1
ALLOWLISTED_RUNTIMES = frozenset({"codex"})


def configured_worktree_root(runner_directory: Path) -> Path:
    """Read the canonical Ticket Worktree root needed by recovery checks."""

    config_file = runner_directory / "config.yml"
    try:
        if config_file.is_symlink() or not config_file.is_file():
            raise OSError("Runner Config is not a regular file")
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Project Runner Config is not readable valid YAML.",
        ) from error
    if (
        not isinstance(config, dict)
        or config.get("version") != RUNNER_CONFIG_VERSION
    ):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID", "Project Runner Config is invalid."
        )
    value = config.get("worktree_root")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RunnerError(
            "RUNNER_CONFIG_INVALID", "Project Runner Config is invalid."
        )
    root = Path(value).resolve()
    if root.name != ".agent-worktrees" or not root.is_dir():
        raise RunnerError(
            "RUNNER_CONFIG_INVALID", "Project Runner Config is invalid."
        )
    return root


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


_ROOT_RUNNER_CONFIG = (".codex", "agent-runner", "config.yml")
_ROOT_RUNNER_KEYS = frozenset(
    {
        "version",
        "harness_root",
        "repository",
        "common_directory",
        "default_runtime",
        "worktree_root",
        "integration_branch",
        "runtimes",
        "repository_skill_allowlist",
    }
)


def discover_project(
    cwd: Path,
    selected_runtime: str | None = None,
    *,
    require_clean_integration: bool = True,
    require_runtime_executable: bool = True,
) -> Project:
    """Discover one configured Harness Project only from its root entrypoint."""
    harness_root, config = _load_harness_runner_config(cwd)
    invalid = "Project Runner Config contains invalid project or Codex settings."
    if (
        set(config) != _ROOT_RUNNER_KEYS
        or config.get("version") != RUNNER_CONFIG_VERSION
    ):
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
    if config.get("harness_root") != str(harness_root):
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
    repository = _configured_absolute_directory(
        config.get("repository"),
        code="RUNNER_CONFIG_INVALID",
        message=invalid,
    )
    common = _configured_absolute_directory(
        config.get("common_directory"),
        code="RUNNER_CONFIG_INVALID",
        message=invalid,
    )
    worktree_root = _configured_absolute_directory(
        config.get("worktree_root"),
        code="RUNNER_CONFIG_INVALID",
        message=invalid,
    )
    if (
        repository.parent != harness_root
        or worktree_root != harness_root / ".agent-worktrees"
        or worktree_root.name != ".agent-worktrees"
    ):
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
    _validate_source_repository(repository, common, invalid)
    runtime_name = (
        config.get("default_runtime")
        if selected_runtime is None
        else selected_runtime
    )
    runtimes = config.get("runtimes")
    if not isinstance(runtime_name, str) or not isinstance(runtimes, dict):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Harness Runner Config does not define a valid default Runtime.",
        )
    runtime = runtimes.get(runtime_name)
    if not isinstance(runtime, dict):
        raise RunnerError(
            "RUNTIME_NOT_CONFIGURED",
            "The selected Agent Runtime is not configured for this project.",
        )
    if runtime_name not in ALLOWLISTED_RUNTIMES:
        raise RunnerError(
            "RUNTIME_UNSUPPORTED",
            "The selected Agent Runtime is not supported by this Runner.",
        )
    branch = config.get("integration_branch")
    executable_value = runtime.get("executable")
    roles = runtime.get("roles")
    allowlist = config.get("repository_skill_allowlist")
    if (
        branch != "dev"
        or set(runtime) != {"executable", "roles"}
        or not isinstance(executable_value, str)
        or not Path(executable_value).is_absolute()
        or not isinstance(roles, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in roles.items()
        )
        or not isinstance(allowlist, list)
        or any(not isinstance(name, str) or not name.strip() for name in allowlist)
        or len(allowlist) != len(set(allowlist))
    ):
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
    runtime_executable = _resolve_path(
        Path(executable_value),
        code="RUNNER_CONFIG_INVALID",
        message=invalid,
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
    dev_commit = run_git(repository, "rev-parse", "refs/heads/{0}".format(branch))
    if run_git(integration, "rev-parse", "HEAD") != dev_commit:
        raise RunnerError(
            "INTEGRATION_WORKTREE_INVALID",
            "The dev Integration Worktree is not at the registered dev state.",
        )
    state_directory = harness_root / "state"
    if state_directory.is_symlink():
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
    return Project(
        harness_root=harness_root,
        repository=repository,
        common_directory=common,
        runner_directory=harness_root / ".codex" / "agent-runner",
        worktree_root=worktree_root,
        state_directory=_resolve_path(
            state_directory,
            code="RUNNER_CONFIG_INVALID",
            message=invalid,
            allow_missing=True,
        ),
        integration_branch=branch,
        integration_worktree=integration,
        dev_commit=dev_commit,
        runtime_executable=runtime_executable,
        role_bindings=roles,
        repository_skill_allowlist=tuple(allowlist),
    )


def discover_runner_directory(cwd: Path) -> Path:
    """Locate Runner-owned transport state from the Harness Project Root."""
    harness_root, _ = _load_harness_runner_config(cwd)
    return harness_root / ".codex" / "agent-runner"


def _load_harness_runner_config(cwd: Path) -> tuple[Path, Dict[str, object]]:
    root = _resolve_path(
        cwd,
        code="PROJECT_NOT_FOUND",
        message="Agent Runner must be invoked from the Harness Project Root.",
    )
    config_file = root.joinpath(*_ROOT_RUNNER_CONFIG)
    try:
        if config_file.is_symlink() or not config_file.is_file():
            raise FileNotFoundError(config_file)
        config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RunnerError(
            "RUNNER_CONFIG_NOT_FOUND",
            "Harness Runner Config was not found at the Harness Project Root.",
        ) from error
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RunnerError(
            "RUNNER_CONFIG_INVALID",
            "Harness Runner Config is not readable valid YAML.",
        ) from error
    if not isinstance(config, dict):
        raise RunnerError(
            "RUNNER_CONFIG_INVALID", "Harness Runner Config must be a mapping."
        )
    return root, config


def _configured_absolute_directory(
    value: object,
    *,
    code: str,
    message: str,
) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RunnerError(code, message)
    return _resolve_path(Path(value), code=code, message=message)


def _validate_source_repository(
    repository: Path,
    common: Path,
    invalid: str,
) -> None:
    try:
        top_level = _resolve_path(
            Path(run_git(repository, "rev-parse", "--show-toplevel")),
            code="RUNNER_CONFIG_INVALID",
            message=invalid,
        )
        common_text = run_git(repository, "rev-parse", "--git-common-dir")
        discovered_common = Path(common_text)
        if not discovered_common.is_absolute():
            discovered_common = repository / discovered_common
        discovered_common = _resolve_path(
            discovered_common,
            code="RUNNER_CONFIG_INVALID",
            message=invalid,
        )
    except RunnerError as error:
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid) from error
    if top_level != repository or discovered_common != common:
        raise RunnerError("RUNNER_CONFIG_INVALID", invalid)
