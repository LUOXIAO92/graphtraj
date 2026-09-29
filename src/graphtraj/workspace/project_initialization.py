"""Plan and apply setup for a GraphTraj project and its Source Repository."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from graphtraj.runtimes.codex.codex_project import (
    CodexProjectError,
    CodexProjectFiles,
)
from graphtraj.workspace.project_files import (
    ProjectFiles,
    WorkspaceProjectError,
)
from graphtraj.workspace.git_repository import GitRepositoryError, GitTreeEntry, SourceRepository
from graphtraj.configuration.project_configuration import (
    ProjectConfiguration,
    ProjectConfigurationError,
    configuration_exists,
    configuration_file,
    default_configuration_content,
    default_project_configuration,
    load_project_configuration,
)
from graphtraj.configuration.project_roles import (
    ProjectRoles,
    ProjectRolesError,
    default_project_roles,
    default_roles_content,
    load_project_roles,
    roles_exist,
    roles_file,
)


INTEGRATION_BRANCH = "dev"


class ProjectSetupError(Exception):
    """The selected GraphTraj project cannot be initialized as planned."""


def _has_git_entry(directory: Path) -> bool:
    """Report a local Git entry on one candidate directory."""

    return os.path.lexists(str(directory / ".git"))


def existing_source_repository(harness_root: Path) -> Optional[Path]:
    """Return the only Source Repository candidate, or None when ambiguous.

    The Harness Project Root itself wins when it holds a Git entry. Otherwise
    a single Git child directory is the unambiguous candidate; a caller that
    needs a different choice must ask the operator explicitly.
    """

    if _has_git_entry(harness_root):
        return harness_root
    try:
        candidates = tuple(
            child.resolve()
            for child in harness_root.iterdir()
            if child.is_dir() and _has_git_entry(child)
        )
    except OSError as error:
        raise ProjectSetupError(
            "Setup could not inspect the Harness Project Root."
        ) from error
    return candidates[0] if len(candidates) == 1 else None


def require_source_repository(harness_root: Path, candidate: Path) -> Path:
    """Return one explicit choice after checking it is the root or its Git child."""

    root = harness_root.resolve()
    selected = candidate.resolve()
    if (
        (selected != root and selected.parent != root)
        or not _has_git_entry(selected)
    ):
        raise ProjectSetupError(
            "The selected Source Repository must be an existing direct Git "
            "child of the Harness Project Root."
        )
    return selected


@dataclass(frozen=True)
class PlannedSetupAction:
    """One operator-reviewable action and its preflight disposition."""

    disposition: str
    description: str


@dataclass(frozen=True)
class ProjectSetupPreview:
    """The complete conflict-free setup plan shown before mutation."""

    actions: Tuple[PlannedSetupAction, ...]


@dataclass(frozen=True)
class ProjectSetupResult:
    """Completed setup actions and the configured Integration Worktree."""

    integration_worktree: Path
    integration_action: Literal["created", "registered", "reused"]
    completed_actions: Tuple[str, ...]


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


def _entry_kind(path: Path) -> Optional[str]:
    entry = _filesystem_entry(path)
    return entry.kind if entry is not None else None


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


def _preflight_link(
    entry: Optional[GitTreeEntry],
    link: Path,
    target: Path,
    description: str,
    actions: List[PlannedSetupAction],
    conflicts: List[str],
) -> None:
    if entry is None:
        actions.append(PlannedSetupAction("CREATE", description))
    elif (link.name == "docs" and entry.kind in {"directory", "symlink"}) or (
        link.name == "CONTEXT.md" and entry.kind in {"file", "symlink"}
    ):
        actions.append(PlannedSetupAction("PRESERVE", str(link)))
    elif entry.kind == "symlink" and _symlink_resolves_to(
        link, entry.content, target
    ):
        actions.append(PlannedSetupAction("ALREADY CONFIGURED", description))
    else:
        _append_conflict(
            conflicts,
            "{0} conflicts at {1}.".format(description, link),
        )


@dataclass(frozen=True)
class ProjectSetupPlan:
    """One preflighted setup action with a single explicit mutation step."""

    harness_root: Path
    repository: SourceRepository
    configuration: ProjectConfiguration
    roles: ProjectRoles
    codex_files: CodexProjectFiles | None
    project_files: ProjectFiles
    write_default_configuration: bool
    write_default_roles: bool
    proposed_base: Optional[str]
    integration_revision: str

    @property
    def configuration_path(self) -> Path:
        return configuration_file(self.harness_root)

    @property
    def roles_path(self) -> Path:
        return roles_file(self.harness_root)

    @property
    def runtime_store(self) -> Path | None:
        """Return a store only when Codex project support applies."""
        if self.codex_files is None:
            return None
        return self.codex_files.runtime_store(self.harness_root)

    @property
    def runner_store(self) -> Path:
        return self.harness_root / ".graphtraj" / "runner"

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
        if self.write_default_roles:
            actions.append(
                PlannedSetupAction(
                    "CREATE", "GraphTraj Roles: {0}".format(self.roles_path)
                )
            )
        else:
            actions.append(
                PlannedSetupAction(
                    "ALREADY CONFIGURED", "GraphTraj Roles: {0}".format(self.roles_path)
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
        if self.runtime_store is not None:
            _preflight_directory(
                self.runtime_store,
                "Harness Runtime Store",
                actions,
                conflicts,
            )
        _preflight_directory(
            self.runner_store,
            "Harness Runner Directory",
            actions,
            conflicts,
        )
        self._preflight_runtime_resources(actions)

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

        materialized = (
            registered == canonical_integration
            and _entry_kind(integration) == "directory"
        )
        self._preflight_integration_links(
            actions,
            conflicts,
            materialized=materialized,
        )
        self._preflight_exclude_registration(actions, conflicts)

        _raise_conflicts(conflicts)
        return ProjectSetupPreview(tuple(actions))

    def _preflight_runtime_resources(
        self,
        actions: List[PlannedSetupAction],
    ) -> None:
        if self.codex_files is None or self.runtime_store is None:
            return
        if _entry_kind(self.runtime_store) not in {None, "directory"}:
            return
        if self.codex_files.has_obsolete_guard(self.runtime_store):
            actions.append(
                PlannedSetupAction(
                    "REMOVE",
                    self.codex_files.obsolete_guard_action(self.runtime_store),
                )
            )

    def _preflight_integration_links(
        self,
        actions: List[PlannedSetupAction],
        conflicts: List[str],
        *,
        materialized: bool,
    ) -> None:
        if materialized:
            entry_for = lambda name: _filesystem_entry(
                self.configuration.integration_worktree / name
            )
        else:
            entry_for = lambda name: self.repository.tree_entry(
                self.integration_revision, name
            )
        links = (
            (".state", self.configuration.state),
            ("CONTEXT.md", self.harness_root / "CONTEXT.md"),
            ("docs", self.configuration.docs),
        )
        for name, target in links:
            description = self.project_files.link_action(
                self.configuration.integration_worktree,
                name,
                target,
            )
            _preflight_link(
                entry_for(name),
                self.configuration.integration_worktree / name,
                target,
                description,
                actions,
                conflicts,
            )

    def _preflight_exclude_registration(
        self,
        actions: List[PlannedSetupAction],
        conflicts: List[str],
    ) -> None:
        common = self.repository.common_directory
        info = _filesystem_entry(common / "info")
        exclude = _filesystem_entry(common / "info" / "exclude")
        description = self.project_files.exclude_action(common)
        if info is not None and info.kind != "directory":
            _append_conflict(
                conflicts,
                "Git exclude registration is blocked at {0}.".format(common / "info"),
            )
        elif exclude is None:
            actions.append(PlannedSetupAction("REGISTER", description))
        elif exclude.kind != "file":
            _append_conflict(
                conflicts,
                "Git exclude registration is blocked at {0}.".format(
                    common / "info" / "exclude"
                ),
            )
        else:
            try:
                lines = (exclude.content or b"").decode().splitlines()
            except UnicodeError:
                _append_conflict(
                    conflicts,
                    "Git exclude registration is not valid text: {0}.".format(
                        common / "info" / "exclude"
                    ),
                )
            else:
                required = ("/.state", "/.scratch")
                disposition = (
                    "ALREADY CONFIGURED"
                    if all(path in lines for path in required)
                    and "/.state\n/.scratch\n/CONTEXT.md\n/docs\n" not in (exclude.content or b"").decode()
                    else "REGISTER"
                )
                actions.append(PlannedSetupAction(disposition, description))

    def apply(self) -> ProjectSetupResult:
        """Apply setup and return completed actions, without prompting.

        Calling apply authorizes the planned branch and Worktree creation.
        ProjectSetupError reports preflight conflicts or partial execution.
        """

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
                    default_configuration_content(
                        self.harness_root, self.configuration.project_root
                    ),
                    encoding="utf-8",
                )
                mark_completed("GraphTraj Config: {0}".format(self.configuration_path))
            if self.write_default_roles:
                self.roles_path.parent.mkdir(parents=True, exist_ok=True)
                self.roles_path.write_text(default_roles_content(), encoding="utf-8")
                mark_completed("GraphTraj Roles: {0}".format(self.roles_path))
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
            if self.runtime_store is not None:
                self.runtime_store.mkdir(parents=True, exist_ok=True)
                mark_completed(_directory_action("Harness Runtime Store", self.runtime_store))
            self.runner_store.mkdir(parents=True, exist_ok=True)
            mark_completed(
                _directory_action("Harness Runner Directory", self.runner_store)
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
                integration_action = "created"
            elif self.repository.worktree_for_branch(INTEGRATION_BRANCH) is None:
                self.repository.add_existing_branch_worktree(
                    INTEGRATION_BRANCH, self.configuration.integration_worktree
                )
                mark_completed(
                    _integration_worktree_action(self.configuration.integration_worktree)
                )
                integration_action = "registered"
            else:
                integration_action = "reused"
            if self.codex_files is not None and self.runtime_store is not None:
                self.codex_files.remove_obsolete_guard(
                    self.runtime_store,
                    mark_completed,
                )
            self.project_files.install_setup_resources(
                harness_root=self.harness_root,
                integration_worktree=self.configuration.integration_worktree,
                state_directory=self.configuration.state,
                documents_directory=self.configuration.docs,
                common_git_directory=self.repository.common_directory,
                on_action_complete=mark_completed,
            )
        except (
            CodexProjectError,
            WorkspaceProjectError,
            GitRepositoryError,
            OSError,
        ) as error:
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
        return ProjectSetupResult(
            self.configuration.integration_worktree, integration_action, tuple(completed)
        )


def plan_project_setup(
    harness_root: Path,
    source_repository: Path | None = None,
) -> ProjectSetupPlan:
    """Plan setup for one selected Source Repository without mutation."""

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
            if source_repository is None:
                raise ProjectSetupError(
                    "Setup could not select a Source Repository."
                )
            configuration = default_project_configuration(root, source_repository)
            write_default_configuration = True
        if roles_exist(root):
            roles = load_project_roles(root)
            write_default_roles = False
        else:
            parent_kind = _entry_kind(roles_file(root).parent)
            if parent_kind not in {None, "directory"}:
                raise ProjectSetupError(
                    "GraphTraj Roles is blocked by a non-directory path: {0}".format(
                        roles_file(root).parent
                    )
                )
            roles = default_project_roles()
            write_default_roles = True
        repository = SourceRepository.from_root(configuration.project_root)
        if configuration.project_root == root:
            repository.require_main()
        dev_exists = repository.branch_exists(INTEGRATION_BRANCH)
        proposed_base = None if dev_exists else repository.head
        integration_revision = (
            repository.revision(INTEGRATION_BRANCH)
            if dev_exists
            else proposed_base
        )
        codex_files = CodexProjectFiles.for_project(
            root, (preset.runtime for preset in roles.presets.values()),
        )
        project_files = ProjectFiles.load()
    except (
        CodexProjectError,
        WorkspaceProjectError,
        GitRepositoryError,
        OSError,
        ProjectConfigurationError,
        ProjectRolesError,
    ) as error:
        raise ProjectSetupError(str(error)) from error
    return ProjectSetupPlan(
        harness_root=root,
        repository=repository,
        configuration=configuration,
        roles=roles,
        codex_files=codex_files,
        project_files=project_files,
        write_default_configuration=write_default_configuration,
        write_default_roles=write_default_roles,
        proposed_base=proposed_base,
        integration_revision=integration_revision,
    )
