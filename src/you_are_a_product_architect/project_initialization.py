"""Plan and apply initialization for exactly one Harness Project."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .codex_project import CodexProjectError, CodexProjectFiles
from .git_repository import GitRepositoryError, GitTreeEntry, SourceRepository
from .skill_check import check_core_skills
from .supported_skills import SupportedSkills, SupportedSkillsError


INTEGRATION_BRANCH = "dev"


class ProjectSetupError(Exception):
    """The selected Harness Project cannot be initialized as planned."""


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


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _filesystem_entry(path: Path) -> Optional[GitTreeEntry]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        return GitTreeEntry(kind="symlink", content=os.readlink(path).encode())
    if stat.S_ISDIR(metadata.st_mode):
        return GitTreeEntry(kind="directory")
    if stat.S_ISREG(metadata.st_mode):
        return GitTreeEntry(kind="file", content=path.read_bytes())
    return GitTreeEntry(kind="other")


@dataclass(frozen=True)
class _TargetView:
    root: Path
    repository: Optional[SourceRepository] = None
    revision: Optional[str] = None

    def entry(self, relative_path: str) -> Optional[GitTreeEntry]:
        if self.repository is None:
            return _filesystem_entry(self.root / relative_path)
        if self.revision is None:
            raise ProjectSetupError("A Git tree view requires a fixed revision.")
        return self.repository.tree_entry(self.revision, relative_path)

    def display_path(self, relative_path: str) -> Path:
        return self.root / relative_path


def _append_conflict(conflicts: List[str], message: str) -> None:
    if message not in conflicts:
        conflicts.append(message)


def _parent_paths(relative_path: str) -> Tuple[str, ...]:
    parts = Path(relative_path).parts
    return tuple(Path(*parts[:index]).as_posix() for index in range(1, len(parts)))


def _preflight_file(
    view: _TargetView,
    relative_path: str,
    expected: bytes,
    description: str,
    actions: List[PlannedSetupAction],
    conflicts: List[str],
) -> None:
    for parent in _parent_paths(relative_path):
        entry = view.entry(parent)
        if entry is not None and entry.kind != "directory":
            _append_conflict(
                conflicts,
                "{0} redirects through or is blocked by a non-directory path: "
                "{1}".format(description, view.display_path(parent)),
            )
            return

    entry = view.entry(relative_path)
    target = view.display_path(relative_path)
    if entry is None:
        actions.append(PlannedSetupAction("CREATE", "{0}: {1}".format(description, target)))
        return
    if entry.kind == "file" and entry.content == expected:
        actions.append(
            PlannedSetupAction(
                "ALREADY CONFIGURED",
                "{0}: {1}".format(description, target),
            )
        )
        return
    if entry.kind == "file":
        detail = "different content"
    elif entry.kind == "symlink":
        detail = "a symlink that could redirect setup"
    else:
        detail = "a {0}, not the planned file".format(entry.kind)
    _append_conflict(
        conflicts,
        "{0} conflicts at {1}: existing target is {2}.".format(
            description,
            target,
            detail,
        ),
    )


def _preflight_directory(
    path: Path,
    description: str,
    actions: List[PlannedSetupAction],
    conflicts: List[str],
) -> None:
    entry = _filesystem_entry(path)
    if entry is None:
        actions.append(PlannedSetupAction("CREATE", "{0}: {1}".format(description, path)))
    elif entry.kind == "directory":
        actions.append(
            PlannedSetupAction(
                "ALREADY CONFIGURED",
                "{0}: {1}".format(description, path),
            )
        )
    else:
        _append_conflict(
            conflicts,
            "{0} conflicts at {1}: existing target is {2}.".format(
                description,
                path,
                entry.kind,
            ),
        )


def _raise_conflicts(conflicts: List[str]) -> None:
    if conflicts:
        raise ProjectSetupError(
            "Setup preflight found conflicts:\n{0}".format(
                "\n".join("- {0}".format(conflict) for conflict in conflicts)
            )
        )


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
    integration_revision: str

    def preflight(
        self,
        *,
        install_missing_skills: bool = False,
    ) -> ProjectSetupPreview:
        """Check every safely observable target before setup mutates anything."""

        actions: List[PlannedSetupAction] = []
        conflicts: List[str] = []
        _preflight_directory(
            self.worktree_root,
            "Worktree Directory",
            actions,
            conflicts,
        )
        _preflight_directory(
            self.state_directory,
            "Harness State Directory",
            actions,
            conflicts,
        )

        dev_exists = self.repository.branch_exists(INTEGRATION_BRANCH)
        registered = self.repository.worktree_for_branch(INTEGRATION_BRANCH)
        canonical_integration = self.integration_worktree.resolve()
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
        else:
            if not dev_exists:
                _append_conflict(conflicts, "The preflighted dev branch no longer exists.")
            elif self.repository.revision(INTEGRATION_BRANCH) != self.integration_revision:
                _append_conflict(
                    conflicts,
                    "dev changed after setup planning; rerun setup to review its targets.",
                )

        if registered is not None and registered != canonical_integration:
            _append_conflict(
                conflicts,
                "dev is already checked out at a different Worktree: {0}".format(
                    registered
                ),
            )
        if registered == canonical_integration:
            integration_entry = _filesystem_entry(self.integration_worktree)
            if integration_entry is None or integration_entry.kind != "directory":
                _append_conflict(
                    conflicts,
                    "The registered Integration Worktree is not a real directory: "
                    "{0}".format(self.integration_worktree),
                )
            else:
                actions.append(
                    PlannedSetupAction(
                        "ALREADY CONFIGURED",
                        "Integration Worktree on dev: {0}".format(
                            self.integration_worktree
                        ),
                    )
                )
        else:
            integration_entry = _filesystem_entry(self.integration_worktree)
            if integration_entry is not None:
                _append_conflict(
                    conflicts,
                    "The Integration Worktree path exists without the expected dev "
                    "registration: {0}".format(self.integration_worktree),
                )
            elif registered is None:
                action = (
                    "Create dev and its Integration Worktree from {0}".format(
                        self.proposed_base
                    )
                    if self.proposed_base is not None
                    else "Register the existing dev Integration Worktree"
                )
                actions.append(
                    PlannedSetupAction(
                        "CREATE",
                        "{0}: {1}".format(action, self.integration_worktree),
                    )
                )

        materialized = (
            registered == canonical_integration
            and _filesystem_entry(self.integration_worktree) is not None
            and _filesystem_entry(self.integration_worktree).kind == "directory"
        )
        integration_view = (
            _TargetView(self.integration_worktree)
            if materialized
            else _TargetView(
                self.integration_worktree,
                self.repository,
                self.integration_revision,
            )
        )
        for relative_path, content in self.codex_files.resources_by_path.items():
            _preflight_file(
                integration_view,
                ".codex/{0}".format(relative_path),
                content,
                "Codex Runtime resource",
                actions,
                conflicts,
            )

        scratch_path = ".scratch"
        scratch_entry = integration_view.entry(scratch_path)
        expected_link = self.codex_files.scratch_link_text(
            self.integration_worktree,
            self.state_directory,
        ).encode()
        if scratch_entry is None:
            actions.append(
                PlannedSetupAction(
                    "CREATE",
                    "Integration scratch link: {0} -> {1}".format(
                        self.integration_worktree / scratch_path,
                        self.state_directory,
                    ),
                )
            )
        elif scratch_entry.kind == "symlink" and scratch_entry.content == expected_link:
            actions.append(
                PlannedSetupAction(
                    "ALREADY CONFIGURED",
                    "Integration scratch link: {0} -> {1}".format(
                        self.integration_worktree / scratch_path,
                        self.state_directory,
                    ),
                )
            )
        else:
            _append_conflict(
                conflicts,
                "Integration scratch link conflicts at {0}.".format(
                    self.integration_worktree / scratch_path
                ),
            )

        common_view = _TargetView(self.repository.common_directory)
        runner_content = self.codex_files.runner_config_content(
            self.worktree_root,
            self.runtime_executable,
        ).encode()
        _preflight_file(
            common_view,
            "agent-runner/config.yml",
            runner_content,
            "Project Runner Config",
            actions,
            conflicts,
        )

        exclude_parent = common_view.entry("info")
        exclude_entry = common_view.entry("info/exclude")
        exclude_path = self.repository.common_directory / "info" / "exclude"
        if exclude_parent is not None and exclude_parent.kind != "directory":
            _append_conflict(
                conflicts,
                "Git exclude registration is blocked or redirected at {0}.".format(
                    self.repository.common_directory / "info"
                ),
            )
        elif exclude_entry is None:
            actions.append(
                PlannedSetupAction(
                    "REGISTER",
                    "Ignore Integration .scratch in {0}".format(exclude_path),
                )
            )
        elif exclude_entry.kind == "file":
            try:
                exclude_lines = exclude_entry.content.decode().splitlines()
            except UnicodeError:
                _append_conflict(
                    conflicts,
                    "Git exclude file is not valid text: {0}".format(exclude_path),
                )
            else:
                disposition = (
                    "ALREADY CONFIGURED"
                    if "/.scratch" in exclude_lines
                    else "REGISTER"
                )
                actions.append(
                    PlannedSetupAction(
                        disposition,
                        "Ignore Integration .scratch in {0}".format(exclude_path),
                    )
                )
        else:
            _append_conflict(
                conflicts,
                "Git exclude file is blocked or redirected at {0}.".format(
                    exclude_path
                ),
            )

        _raise_conflicts(conflicts)
        return ProjectSetupPreview(tuple(actions))

    def apply(self, *, install_missing_skills: bool = False) -> str:
        self.preflight(install_missing_skills=install_missing_skills)
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
        integration_revision=(
            repository.revision(INTEGRATION_BRANCH)
            if dev_exists
            else proposed_base
        ),
    )
