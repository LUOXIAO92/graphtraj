"""Plan and apply initialization for exactly one Harness Project."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .codex_project import CodexProjectError, CodexProjectFiles
from .git_repository import GitRepositoryError, GitTreeEntry, SourceRepository
from .path_safety import relative_parent_paths
from .skill_check import CORE_SKILL_NAMES, check_core_skills, core_skill_paths
from .supported_skills import (
    SupportedSkills,
    SupportedSkillsError,
    allowed_manifest_paths,
)


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

    def paths_under(self, relative_root: str) -> Tuple[str, ...]:
        if self.repository is not None:
            if self.revision is None:
                raise ProjectSetupError("A Git tree view requires a fixed revision.")
            paths = self.repository.tree_paths(self.revision, relative_root)
            prefix = "{0}/".format(relative_root.rstrip("/"))
            return tuple(
                path[len(prefix) :]
                for path in paths
                if path.startswith(prefix)
            )

        root = self.root / relative_root
        entry = _filesystem_entry(root)
        if entry is None or entry.kind != "directory":
            return ()
        return tuple(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
        )


def _append_conflict(conflicts: List[str], message: str) -> None:
    if message not in conflicts:
        conflicts.append(message)


def _symlink_resolves_to(
    link: Path,
    encoded_target: Optional[bytes],
    expected: Path,
) -> bool:
    if encoded_target is None:
        return False
    try:
        target = Path(encoded_target.decode())
    except UnicodeError:
        return False
    if not target.is_absolute():
        target = link.parent / target
    return target.resolve() == expected.resolve()


def _preflight_file(
    view: _TargetView,
    relative_path: str,
    expected: bytes,
    description: str,
    actions: List[PlannedSetupAction],
    conflicts: List[str],
) -> None:
    for parent in relative_parent_paths(relative_path):
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
        actions.append(
            PlannedSetupAction(
                "CREATE",
                "{0}: {1}".format(description, target),
            )
        )
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
        actions.append(
            PlannedSetupAction(
                "CREATE",
                _directory_action(description, path),
            )
        )
    elif entry.kind == "directory":
        actions.append(
            PlannedSetupAction(
                "ALREADY CONFIGURED",
                _directory_action(description, path),
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


def _directory_action(description: str, path: Path) -> str:
    return "{0}: {1}".format(description, path)


def _new_dev_branch_action(base: str) -> str:
    return "Create dev branch from {0}".format(base)


def _existing_dev_branch_action(revision: str) -> str:
    return "dev branch at {0}".format(revision)


def _integration_worktree_action(path: Path) -> str:
    return "Integration Worktree on dev: {0}".format(path)


def _raise_conflicts(conflicts: List[str]) -> None:
    if conflicts:
        raise ProjectSetupError(
            "Setup preflight found conflicts:\n{0}".format(
                "\n".join("- {0}".format(conflict) for conflict in conflicts)
            )
        )


def _recoverable_supported_skills(
    view: _TargetView,
    supported_skills: SupportedSkills,
) -> Tuple[str, ...]:
    recoverable = []
    for name in CORE_SKILL_NAMES:
        manifest = supported_skills.manifest(name)
        root = "skills/{0}".format(name)
        root_entry = view.entry(root)
        if root_entry is None or root_entry.kind != "directory":
            continue
        existing_paths = set(view.paths_under(root))
        expected_directories = {
            parent
            for relative_path in manifest
            for parent in relative_parent_paths(relative_path)
        }
        if not existing_paths or not existing_paths.issubset(
            set(manifest).union(expected_directories)
        ):
            continue

        matching_files = 0
        valid_subset = True
        for relative_path, content in manifest.items():
            entry = view.entry("{0}/{1}".format(root, relative_path))
            if entry is None:
                continue
            if entry.kind != "file" or entry.content != content:
                valid_subset = False
                break
            matching_files += 1
        if not valid_subset:
            continue
        for relative_path in expected_directories.intersection(existing_paths):
            entry = view.entry("{0}/{1}".format(root, relative_path))
            if entry is None or entry.kind != "directory":
                valid_subset = False
                break
        if valid_subset and matching_files and matching_files < len(manifest):
            recoverable.append(name)
    return tuple(recoverable)


@dataclass(frozen=True)
class ProjectSetupPlan:
    """One preflighted setup action with a single explicit mutation step."""

    harness_root: Path
    runtime_store: Path
    runtime_user_skill_root: Path
    repository: SourceRepository
    worktree_root: Path
    integration_worktree: Path
    state_directory: Path
    runtime_executable: Path
    codex_files: CodexProjectFiles
    supported_skills: SupportedSkills
    missing_skills: Tuple[str, ...]
    recoverable_skills: Tuple[str, ...]
    proposed_base: Optional[str]
    registered_dev_worktree: Optional[Path]
    integration_revision: str

    def _skill_names_to_install(
        self,
        install_missing_skills: bool,
    ) -> Tuple[str, ...]:
        selected = set(self.recoverable_skills)
        if install_missing_skills:
            selected.update(self.missing_skills)
        return tuple(name for name in CORE_SKILL_NAMES if name in selected)

    def _runtime_skill_paths(
        self,
        installed_skill_names: Tuple[str, ...],
    ) -> tuple[Path, ...]:
        """Choose the exact root-or-user core Skill paths Main will receive."""

        available = core_skill_paths(
            self.runtime_store,
            self.runtime_user_skill_root,
        )
        installed = set(installed_skill_names)
        return tuple(
            (
                self.runtime_store / "skills" / name / "SKILL.md"
            ).resolve()
            if name in installed
            else available.get(
                name,
                (self.runtime_store / "skills" / name / "SKILL.md").resolve(),
            )
            for name in CORE_SKILL_NAMES
        )

    def preflight(
        self,
        *,
        install_missing_skills: bool = False,
    ) -> ProjectSetupPreview:
        """Translate all read-only planning failures to the setup interface."""

        try:
            return self._preflight(
                install_missing_skills=install_missing_skills,
            )
        except ProjectSetupError:
            raise
        except (
            CodexProjectError,
            GitRepositoryError,
            OSError,
            SupportedSkillsError,
        ) as error:
            raise ProjectSetupError(
                "Setup preflight could not be completed: {0}".format(error)
            ) from error

    def _preflight(
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
        _preflight_directory(
            self.runtime_store,
            "Harness Runtime Store",
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
            actions.append(
                PlannedSetupAction(
                    "CREATE",
                    _new_dev_branch_action(self.proposed_base),
                )
            )
        else:
            if not dev_exists:
                _append_conflict(
                    conflicts,
                    "The preflighted dev branch no longer exists.",
                )
            elif (
                self.repository.revision(INTEGRATION_BRANCH)
                != self.integration_revision
            ):
                _append_conflict(
                    conflicts,
                    "dev changed after setup planning; rerun setup to review its "
                    "targets.",
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
        if registered == canonical_integration:
            integration_entry = _filesystem_entry(self.integration_worktree)
            if integration_entry is None:
                _append_conflict(
                    conflicts,
                    "The dev Integration Worktree is registered at {0}, but that "
                    "directory is missing; this is a stale or prunable Git Worktree "
                    "registration. Setup made no changes. Inspect `git worktree list "
                    "--porcelain`, then manually restore the directory at {0} or "
                    "remove the exact stale registration for {0} before rerunning "
                    "setup.".format(self.integration_worktree),
                )
            elif integration_entry.kind != "directory":
                _append_conflict(
                    conflicts,
                    "The registered Integration Worktree is not a real directory: "
                    "{0}".format(self.integration_worktree),
                )
            else:
                actions.append(
                    PlannedSetupAction(
                        "ALREADY CONFIGURED",
                        _integration_worktree_action(self.integration_worktree),
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
                actions.append(
                    PlannedSetupAction(
                        "CREATE",
                        _integration_worktree_action(self.integration_worktree),
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
        runtime_view = _TargetView(self.runtime_store)
        skill_names = self._skill_names_to_install(install_missing_skills)
        runtime_skill_paths = self._runtime_skill_paths(skill_names)
        if skill_names:
            for name in skill_names:
                manifest = self.supported_skills.manifest(name)
                skill_relative_root = "skills/{0}".format(name)
                allowed_paths = allowed_manifest_paths(manifest)
                unexpected_paths = tuple(
                    path
                    for path in runtime_view.paths_under(skill_relative_root)
                    if path not in allowed_paths
                )
                for unexpected_path in unexpected_paths:
                    _append_conflict(
                        conflicts,
                        "Harness Skill contains unsupported content: {0}".format(
                            runtime_view.display_path(
                                "{0}/{1}".format(
                                    skill_relative_root,
                                    unexpected_path,
                                )
                            )
                        ),
                    )
                for resource_path, content in manifest.items():
                    _preflight_file(
                        runtime_view,
                        "{0}/{1}".format(skill_relative_root, resource_path),
                        content,
                        "Harness Skill {0}".format(name),
                        actions,
                        conflicts,
                    )

        for relative_path, content in self.codex_files.runtime_resources(
            runtime_skill_paths
        ).items():
            _preflight_file(
                runtime_view,
                relative_path,
                content,
                "Harness Runtime resource",
                actions,
                conflicts,
            )

        scratch_path = ".scratch"
        scratch_entry = integration_view.entry(scratch_path)
        if scratch_entry is None:
            actions.append(
                PlannedSetupAction(
                    "CREATE",
                    self.codex_files.scratch_action(
                        self.integration_worktree,
                        self.state_directory,
                    ),
                )
            )
        elif scratch_entry.kind == "symlink" and _symlink_resolves_to(
            self.integration_worktree / scratch_path,
            scratch_entry.content,
            self.state_directory,
        ):
            actions.append(
                PlannedSetupAction(
                    "ALREADY CONFIGURED",
                    self.codex_files.scratch_action(
                        self.integration_worktree,
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
                    self.codex_files.exclude_action(
                        self.repository.common_directory
                    ),
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
                        self.codex_files.exclude_action(
                            self.repository.common_directory
                        ),
                    )
                )
        else:
            _append_conflict(
                conflicts,
                "Git exclude file is blocked or redirected at {0}.".format(
                    exclude_path
                ),
            )

        runner_content = self.codex_files.runner_config_content(
            self.harness_root,
            self.repository.primary_worktree,
            self.repository.common_directory,
            self.worktree_root,
            self.runtime_executable,
        ).encode()
        _preflight_file(
            runtime_view,
            "agent-runner/config.yml",
            runner_content,
            "Harness Runner Config",
            actions,
            conflicts,
        )

        _raise_conflicts(conflicts)
        return ProjectSetupPreview(tuple(actions))

    def apply(self, *, install_missing_skills: bool = False) -> str:
        preview = self.preflight(install_missing_skills=install_missing_skills)
        skill_names = self._skill_names_to_install(install_missing_skills)
        runtime_skill_paths = self._runtime_skill_paths(skill_names)
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
            self.worktree_root.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action("Worktree Directory", self.worktree_root)
            )
            self.state_directory.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action("Harness State Directory", self.state_directory)
            )
            self.runtime_store.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action("Harness Runtime Store", self.runtime_store)
            )
            if self.proposed_base is not None:
                self.repository.create_branch(
                    INTEGRATION_BRANCH,
                    self.proposed_base,
                )
                mark_completed(_new_dev_branch_action(self.proposed_base))
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH,
                    self.integration_worktree,
                )
                mark_completed(
                    _integration_worktree_action(self.integration_worktree)
                )
                result = "Created Integration Worktree on dev."
            elif self.registered_dev_worktree is None:
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH,
                    self.integration_worktree,
                )
                mark_completed(
                    _integration_worktree_action(self.integration_worktree)
                )
                result = "Registered Integration Worktree on existing dev."
            else:
                result = "Using registered Integration Worktree on dev."

            for name in skill_names:
                self.supported_skills.install_missing(
                    self.runtime_store,
                    (name,),
                    on_action_complete=mark_completed,
                )
            self.codex_files.install(
                harness_root=self.harness_root,
                source_repository=self.repository.primary_worktree,
                skill_paths=runtime_skill_paths,
                integration_worktree=self.integration_worktree,
                state_directory=self.state_directory,
                common_git_directory=self.repository.common_directory,
                worktree_root=self.worktree_root,
                runtime_executable=self.runtime_executable,
                on_action_complete=mark_completed,
            )
        except (
            CodexProjectError,
            GitRepositoryError,
            OSError,
            SupportedSkillsError,
        ) as error:
            incomplete = tuple(
                description
                for description in pending
                if description not in completed
            )
            completed_lines = completed or ["none"]
            incomplete_lines = incomplete or ("none",)
            raise ProjectSetupError(
                "Setup execution stopped: {0}\n"
                "Completed actions were not rolled back.\n"
                "Completed actions:\n{1}\n"
                "Incomplete actions:\n{2}\n"
                "Correct the cause and rerun setup.".format(
                    error,
                    "\n".join("- {0}".format(action) for action in completed_lines),
                    "\n".join("- {0}".format(action) for action in incomplete_lines),
                )
            ) from error
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
    runtime_store = harness_root / ".codex"
    runtime_user_skill_root = Path.home() / ".agents" / "skills"
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
        skill_statuses = check_core_skills(
            runtime_store,
            runtime_user_skill_root,
        )
        discovered_skills = {
            status.name for status in skill_statuses if status.discovered
        }
        dev_exists = repository.branch_exists(INTEGRATION_BRANCH)
        registered_dev_worktree = repository.worktree_for_branch(
            INTEGRATION_BRANCH
        )
        proposed_base = None if dev_exists else repository.head
        integration_revision = (
            repository.revision(INTEGRATION_BRANCH)
            if dev_exists
            else proposed_base
        )
        missing_skills = tuple(
            name for name in CORE_SKILL_NAMES if name not in discovered_skills
        )
        recoverable_skills = _recoverable_supported_skills(
            _TargetView(runtime_store),
            supported_skills,
        )
    except (GitRepositoryError, OSError, SupportedSkillsError) as error:
        raise ProjectSetupError(str(error)) from error

    return ProjectSetupPlan(
        harness_root=harness_root,
        runtime_store=runtime_store,
        runtime_user_skill_root=runtime_user_skill_root,
        repository=repository,
        worktree_root=worktree_root,
        integration_worktree=integration_worktree,
        state_directory=state_directory,
        runtime_executable=runtime_executable,
        codex_files=codex_files,
        supported_skills=supported_skills,
        missing_skills=missing_skills,
        recoverable_skills=recoverable_skills,
        proposed_base=proposed_base,
        registered_dev_worktree=registered_dev_worktree,
        integration_revision=integration_revision,
    )
