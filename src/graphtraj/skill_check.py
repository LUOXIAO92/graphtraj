"""Discover the core Skills required by a Harness Project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import click
import yaml

from .git_repository import GitRepositoryError, SourceRepository
from .project_configuration import (
    ProjectConfigurationError,
    configuration_exists,
    load_project_configuration,
)
from .project_roles import ProjectRolesError, load_project_roles, roles_exist


CORE_SKILL_NAMES = (
    "setup-project",
    "grill-with-docs",
    "grilling",
    "domain-modeling",
    "to-spec",
    "to-tickets",
    "task-delivery",
    "implement",
    "handoff",
    "ponytail",
    "tdd",
    "code-review",
    "resolving-merge-conflicts",
    "task-breakdown",
    "research",
    "retro",
    "wayfinder",
    "prototype",
)


@dataclass(frozen=True)
class SkillStatus:
    """One required Skill's name-only discovery result."""

    name: str
    discovered: bool


def harness_skill_root(runtime_store: Path) -> Path:
    """Return the Harness Project's root-owned Skill directory."""

    return runtime_store.parent / ".agents" / "skills"


def declared_skill_name(content: bytes) -> Optional[str]:
    """Read one Skill's declared name without depending on a filesystem path."""

    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError:
        return None

    if not lines or lines[0].strip() != "---":
        return None

    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return None

    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None
    name = frontmatter.get("name")
    return name if isinstance(name, str) and name else None


def _declared_skill_name(skill_file: Path) -> Optional[str]:
    try:
        content = skill_file.read_bytes()
    except OSError:
        return None
    return declared_skill_name(content)


def core_skill_paths(
    runtime_store: Path,
    user_skill_root: Path,
    *,
    source_history_paths: frozenset[str] = frozenset(),
    include_user_skills: bool = True,
) -> Dict[str, Path]:
    """Resolve each core Skill to its Harness-root or Runtime-user file path."""

    resolved: Dict[str, Path] = {}
    for skill_root, ignore_source_history in (
        (harness_skill_root(runtime_store), True),
        (user_skill_root, False),
    ):
        if not ignore_source_history and not include_user_skills:
            continue
        try:
            candidates = tuple(sorted(skill_root.iterdir()))
        except OSError:
            continue
        for candidate in candidates:
            skill_file = candidate / "SKILL.md"
            if ignore_source_history and (
                skill_file.relative_to(runtime_store.parent).as_posix()
                in source_history_paths
            ):
                continue
            name = _declared_skill_name(skill_file)
            if name not in CORE_SKILL_NAMES or name in resolved:
                continue
            try:
                resolved[name] = skill_file.resolve(strict=True)
            except OSError:
                continue
    return resolved


def check_core_skills(
    runtime_store: Path,
    user_skill_root: Path,
    *,
    source_history_paths: frozenset[str] = frozenset(),
    include_user_skills: bool = True,
) -> Tuple[SkillStatus, ...]:
    """Check core names in the Harness-root and Runtime user scopes."""

    discovered = core_skill_paths(
        runtime_store,
        user_skill_root,
        source_history_paths=source_history_paths,
        include_user_skills=include_user_skills,
    )
    return tuple(
        SkillStatus(name=name, discovered=name in discovered)
        for name in CORE_SKILL_NAMES
    )


def source_history_skill_paths(
    repository: SourceRepository,
    revision: str,
) -> frozenset[str]:
    """Return Skill file paths present in one selected Source revision."""

    return frozenset(
        path
        for path in repository.tree_paths(revision, ".agents/skills")
        if Path(path).name == "SKILL.md"
    )


def _doctor_runtime_store(cwd: Path) -> Path:
    """Return the root store, rejecting a known Harness child worktree."""

    if configuration_exists(cwd):
        return cwd / ".codex"
    for ancestor in cwd.parents:
        if configuration_exists(ancestor):
            raise click.UsageError("Run doctor from the Harness Project Root.")
    return cwd / ".codex"


def _doctor_source_history_paths(runtime_store: Path) -> frozenset[str]:
    """Return tracked Skill paths only when the Harness and Source roots match."""

    try:
        harness_root = runtime_store.parent
        if configuration_exists(harness_root):
            configuration = load_project_configuration(harness_root)
            if configuration.project_root != configuration.harness_root:
                return frozenset()
            repository = SourceRepository.from_root(configuration.project_root)
        else:
            repository = SourceRepository.from_root(harness_root)
        return source_history_skill_paths(repository, repository.head)
    except (GitRepositoryError, OSError, ProjectConfigurationError):
        return frozenset()


@click.command()
def doctor() -> None:
    """Report required core Skills from the active Harness Project context."""

    runtime_store = _doctor_runtime_store(Path.cwd())
    statuses = check_core_skills(
        runtime_store,
        Path.home() / ".agents" / "skills",
        source_history_paths=_doctor_source_history_paths(runtime_store),
    )
    for status in statuses:
        click.echo(
            "{0}: {1}".format(
                status.name,
                "OK" if status.discovered else "MISSING",
            )
        )

    roles_ok = True
    if configuration_exists(runtime_store.parent) or roles_exist(runtime_store.parent):
        try:
            load_project_roles(runtime_store.parent)
        except ProjectRolesError as error:
            roles_ok = False
            click.echo(str(error))
        else:
            click.echo("roles: OK")
    if not all(status.discovered for status in statuses) or not roles_ok:
        raise click.exceptions.Exit(1)
