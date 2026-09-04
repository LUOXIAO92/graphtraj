"""Plan and apply setup for a GraphTraj project in one Git repository."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .git_repository import GitRepositoryError, SourceRepository
from .project_configuration import (
    DEFAULT_CONFIG_CONTENT,
    ProjectConfiguration,
    ProjectConfigurationError,
    configuration_exists,
    configuration_file,
    default_project_configuration,
    load_project_configuration,
)


INTEGRATION_BRANCH = "dev"


class ProjectSetupError(Exception):
    """The selected GraphTraj project cannot be initialized as planned."""


@dataclass(frozen=True)
class PlannedSetupAction:
    """One operator-reviewable action and its preflight disposition."""

    disposition: str
    description: str


@dataclass(frozen=True)
class ProjectSetupPreview:
    """The complete conflict-free setup plan shown before mutation."""

    actions: Tuple[PlannedSetupAction, ...]

    def render(self) -> str:
        lines = ["Setup plan:"]
        lines.extend(
            "- {0}: {1}".format(action.disposition, action.description)
            for action in self.actions
        )
        return "\n".join(lines)


def _entry_kind(path: Path) -> Optional[str]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return "other"


def _append_conflict(conflicts: List[str], message: str) -> None:
    if message not in conflicts:
        conflicts.append(message)


def _raise_conflicts(conflicts: List[str]) -> None:
    if conflicts:
        raise ProjectSetupError(
            "Setup preflight found conflicts:\n{0}".format(
                "\n".join("- {0}".format(conflict) for conflict in conflicts)
            )
        )


def _directory_action(description: str, path: Path) -> str:
    return "{0}: {1}".format(description, path)


def _preflight_directory(
    path: Path,
    description: str,
    actions: List[PlannedSetupAction],
    conflicts: List[str],
) -> None:
    entry = _entry_kind(path)
    if entry is None:
        actions.append(
            PlannedSetupAction("CREATE", _directory_action(description, path))
        )
    elif entry == "directory":
        actions.append(
            PlannedSetupAction(
                "ALREADY CONFIGURED", _directory_action(description, path)
            )
        )
    else:
        _append_conflict(
            conflicts,
            "{0} conflicts at {1}: existing target is {2}.".format(
                description, path, entry
            ),
        )


def _new_dev_branch_action(base: str) -> str:
    return "Create dev branch from {0}".format(base)


def _existing_dev_branch_action(revision: str) -> str:
    return "dev branch at {0}".format(revision)


def _integration_worktree_action(path: Path) -> str:
    return "Integration Worktree on dev: {0}".format(path)


@dataclass(frozen=True)
class ProjectSetupPlan:
    """One preflighted setup action with a single explicit mutation step."""

    harness_root: Path
    repository: SourceRepository
    configuration: ProjectConfiguration
    write_default_configuration: bool
    proposed_base: Optional[str]
    integration_revision: str

    @property
    def configuration_path(self) -> Path:
        return configuration_file(self.harness_root)

    def preflight(self) -> ProjectSetupPreview:
        """Check every setup target before setup mutates the project."""

        try:
            return self._preflight()
        except ProjectSetupError:
            raise
        except (GitRepositoryError, OSError) as error:
            raise ProjectSetupError(
                "Setup preflight could not be completed: {0}".format(error)
            ) from error

    def _preflight(self) -> ProjectSetupPreview:
        actions: List[PlannedSetupAction] = []
        conflicts: List[str] = []
        if self.write_default_configuration:
            actions.append(
                PlannedSetupAction(
                    "CREATE", "GraphTraj Config: {0}".format(self.configuration_path)
                )
            )
        else:
            actions.append(
                PlannedSetupAction(
                    "ALREADY CONFIGURED",
                    "GraphTraj Config: {0}".format(self.configuration_path),
                )
            )

        _preflight_directory(
            self.configuration.agent_worktrees,
            "Agent Worktree Directory",
            actions,
            conflicts,
        )
        _preflight_directory(
            self.configuration.state,
            "Harness State Directory",
            actions,
            conflicts,
        )

        dev_exists = self.repository.branch_exists(INTEGRATION_BRANCH)
        registered = self.repository.worktree_for_branch(INTEGRATION_BRANCH)
        integration = self.configuration.integration_worktree
        canonical_integration = integration.resolve()
        if self.proposed_base is not None:
            if dev_exists:
                _append_conflict(
                    conflicts,
                    "dev was created after setup planning; rerun setup to review it.",
                )
            if self.repository.head != self.proposed_base:
                _append_conflict(
                    conflicts,
                    "The proposed dev base changed after setup planning.",
                )
            actions.append(
                PlannedSetupAction("CREATE", _new_dev_branch_action(self.proposed_base))
            )
        else:
            if not dev_exists:
                _append_conflict(
                    conflicts,
                    "The preflighted dev branch no longer exists.",
                )
            elif self.repository.revision(INTEGRATION_BRANCH) != self.integration_revision:
                _append_conflict(
                    conflicts,
                    "dev changed after setup planning; rerun setup to review it.",
                )
            actions.append(
                PlannedSetupAction(
                    "ALREADY CONFIGURED",
                    _existing_dev_branch_action(self.integration_revision),
                )
            )

        if registered is not None and registered != canonical_integration:
            _append_conflict(
                conflicts,
                "dev is already checked out at a different Worktree: {0}".format(
                    registered
                ),
            )
        elif registered == canonical_integration:
            if _entry_kind(integration) != "directory":
                _append_conflict(
                    conflicts,
                    "The dev Integration Worktree is registered at {0}, but that "
                    "directory is missing or invalid. Setup made no changes.".format(
                        integration
                    ),
                )
            else:
                actions.append(
                    PlannedSetupAction(
                        "ALREADY CONFIGURED", _integration_worktree_action(integration)
                    )
                )
        elif _entry_kind(integration) is not None:
            _append_conflict(
                conflicts,
                "The Integration Worktree path exists without the expected dev "
                "registration: {0}".format(integration),
            )
        else:
            actions.append(
                PlannedSetupAction("CREATE", _integration_worktree_action(integration))
            )

        _raise_conflicts(conflicts)
        return ProjectSetupPreview(tuple(actions))

    def apply(self) -> str:
        """Create the preflighted configuration, directories, branch, and Worktree."""

        preview = self.preflight()
        pending = tuple(
            action.description
            for action in preview.actions
            if action.disposition != "ALREADY CONFIGURED"
        )
        completed: List[str] = []

        def mark_completed(description: str) -> None:
            if description in pending and description not in completed:
                completed.append(description)

        try:
            if self.write_default_configuration:
                self.configuration_path.parent.mkdir(parents=True, exist_ok=True)
                self.configuration_path.write_text(
                    DEFAULT_CONFIG_CONTENT, encoding="utf-8"
                )
                mark_completed("GraphTraj Config: {0}".format(self.configuration_path))
            self.configuration.agent_worktrees.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action(
                    "Agent Worktree Directory", self.configuration.agent_worktrees
                )
            )
            self.configuration.state.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action("Harness State Directory", self.configuration.state)
            )
            if self.proposed_base is not None:
                self.repository.create_branch(INTEGRATION_BRANCH, self.proposed_base)
                mark_completed(_new_dev_branch_action(self.proposed_base))
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH, self.configuration.integration_worktree
                )
                mark_completed(
                    _integration_worktree_action(self.configuration.integration_worktree)
                )
                return "Created Integration Worktree on dev."
            if self.repository.worktree_for_branch(INTEGRATION_BRANCH) is None:
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH, self.configuration.integration_worktree
                )
                mark_completed(
                    _integration_worktree_action(self.configuration.integration_worktree)
                )
                return "Registered Integration Worktree on existing dev."
            return "Using registered Integration Worktree on dev."
        except (GitRepositoryError, OSError) as error:
            incomplete = tuple(
                description for description in pending if description not in completed
            )
            raise ProjectSetupError(
                "Setup execution stopped: {0}\n"
                "Completed actions were not rolled back.\n"
                "Completed actions:\n{1}\n"
                "Incomplete actions:\n{2}\n"
                "Correct the cause and rerun setup.".format(
                    error,
                    "\n".join("- {0}".format(action) for action in completed or ["none"]),
                    "\n".join("- {0}".format(action) for action in incomplete or ("none",)),
                )
            ) from error


def plan_project_setup(harness_root: Path) -> ProjectSetupPlan:
    """Plan default same-directory setup without mutating the repository."""

    root = harness_root.resolve()
    try:
        config_path = configuration_file(root)
        if configuration_exists(root):
            configuration = load_project_configuration(root)
            write_default_configuration = False
        else:
            parent_kind = _entry_kind(config_path.parent)
            if parent_kind not in {None, "directory"}:
                raise ProjectSetupError(
                    "GraphTraj Config is blocked by a non-directory path: {0}".format(
                        config_path.parent
                    )
                )
            configuration = default_project_configuration(root)
            write_default_configuration = True
        if configuration.project_root != root:
            raise ProjectSetupError(
                "This setup supports only the current Git repository as the "
                "Harness Project Root."
            )
        repository = SourceRepository.from_root(root)
        dev_exists = repository.branch_exists(INTEGRATION_BRANCH)
        proposed_base = None if dev_exists else repository.head
        integration_revision = (
            repository.revision(INTEGRATION_BRANCH)
            if dev_exists
            else proposed_base
        )
    except (GitRepositoryError, OSError, ProjectConfigurationError) as error:
        raise ProjectSetupError(str(error)) from error
    return ProjectSetupPlan(
        harness_root=root,
        repository=repository,
        configuration=configuration,
        write_default_configuration=write_default_configuration,
        proposed_base=proposed_base,
        integration_revision=integration_revision,
    )
