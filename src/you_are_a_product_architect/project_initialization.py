"""Plan and apply initialization for exactly one Harness Project."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .codex_project import CodexProjectError, CodexProjectFiles
from .git_repository import GitRepositoryError, SourceRepository
from .skill_check import check_core_skills
from .supported_skills import SupportedSkills, SupportedSkillsError


INTEGRATION_BRANCH = "dev"


class ProjectSetupError(Exception):
    """The selected Harness Project cannot be initialized as planned."""


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ProjectSetupPlan:
    """One preflighted setup action with a single explicit mutation step."""

    repository: SourceRepository
    worktree_root: Path
    integration_worktree: Path
    state_directory: Path
    runtime_executable: Path
    codex_files: CodexProjectFiles
    supported_skills: SupportedSkills
    missing_skills: Tuple[str, ...]
    proposed_base: Optional[str]
    registered_dev_worktree: Optional[Path]

    def apply(self, *, install_missing_skills: bool = False) -> str:
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        try:
            if self.proposed_base is not None:
                self.repository.add_new_branch_worktree(
                    INTEGRATION_BRANCH,
                    self.integration_worktree,
                    self.proposed_base,
                )
                result = "Created Integration Worktree on dev."
            elif self.registered_dev_worktree is None:
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH,
                    self.integration_worktree,
                )
                result = "Registered Integration Worktree on existing dev."
            else:
                result = "Using registered Integration Worktree on dev."

            if install_missing_skills:
                self.supported_skills.install_missing(
                    self.integration_worktree,
                    self.missing_skills,
                )
            self.codex_files.install(
                integration_worktree=self.integration_worktree,
                state_directory=self.state_directory,
                common_git_directory=self.repository.common_directory,
                worktree_root=self.worktree_root,
                runtime_executable=self.runtime_executable,
            )
        except (
            CodexProjectError,
            GitRepositoryError,
            OSError,
            SupportedSkillsError,
        ) as error:
            raise ProjectSetupError(str(error)) from error
        return result


def plan_project_setup(
    harness_root: Path,
    primary_worktree: Path,
    runtime_executable: Path,
) -> ProjectSetupPlan:
    """Preflight the success-path plan without mutating the Harness Project."""

    worktree_root = harness_root / ".agent-worktrees"
    integration_worktree = worktree_root / "integration"
    state_directory = harness_root / "state"
    try:
        repository = SourceRepository.from_primary(
            harness_root,
            primary_worktree,
        )
        resolved_worktree_root = worktree_root.resolve()
        if _is_within(resolved_worktree_root, repository.primary_worktree):
            raise ProjectSetupError(
                "The Worktree Directory must remain outside the Primary Worktree."
            )

        codex_files = CodexProjectFiles.load()
        supported_skills = SupportedSkills.load()
        missing_skills = tuple(
            status.name
            for status in check_core_skills(
                integration_worktree,
                Path.home() / ".agents" / "skills",
            )
            if not status.discovered
        )
        dev_exists = repository.branch_exists(INTEGRATION_BRANCH)
        registered_dev_worktree = repository.worktree_for_branch(
            INTEGRATION_BRANCH
        )
        if (
            registered_dev_worktree is not None
            and registered_dev_worktree != integration_worktree.resolve()
        ):
            raise ProjectSetupError(
                "dev is already checked out at a different Worktree: {0}".format(
                    registered_dev_worktree
                )
            )
        if (
            dev_exists
            and registered_dev_worktree is None
            and os.path.lexists(str(integration_worktree))
        ):
            raise ProjectSetupError(
                "The Integration Worktree path already exists but is not registered."
            )
        proposed_base = None if dev_exists else repository.head
    except (GitRepositoryError, OSError, SupportedSkillsError) as error:
        raise ProjectSetupError(str(error)) from error

    return ProjectSetupPlan(
        repository=repository,
        worktree_root=worktree_root,
        integration_worktree=integration_worktree,
        state_directory=state_directory,
        runtime_executable=runtime_executable,
        codex_files=codex_files,
        supported_skills=supported_skills,
        missing_skills=missing_skills,
        proposed_base=proposed_base,
        registered_dev_worktree=registered_dev_worktree,
    )
