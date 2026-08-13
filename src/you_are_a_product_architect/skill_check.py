"""Discover the core Skills required by a Harness Project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import click
import yaml


CORE_SKILL_NAMES = (
    "setup-matt-pocock-skills",
    "grill-with-docs",
    "grilling",
    "domain-modeling",
    "to-spec",
    "to-tickets",
    "task-delivery",
    "implement",
    "tdd",
    "code-review",
    "resolving-merge-conflicts",
)


@dataclass(frozen=True)
class SkillStatus:
    """One required Skill's name-only discovery result."""

    name: str
    discovered: bool


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


def _discover_names(skill_roots: Iterable[Path]) -> set[str]:
    discovered = set()
    for skill_root in skill_roots:
        try:
            candidates = tuple(skill_root.iterdir())
        except OSError:
            continue

        for candidate in candidates:
            name = _declared_skill_name(candidate / "SKILL.md")
            if name is not None:
                discovered.add(name)
    return discovered


def check_core_skills(
    integration_worktree: Path,
    user_skill_root: Path,
) -> Tuple[SkillStatus, ...]:
    """Check core names in the exact project-local and Runtime user scopes."""

    discovered = _discover_names(
        (
            integration_worktree / ".agents" / "skills",
            user_skill_root,
        )
    )
    return tuple(
        SkillStatus(name=name, discovered=name in discovered)
        for name in CORE_SKILL_NAMES
    )


@click.command()
def doctor() -> None:
    """Report required core Skills from the active Harness Project context."""

    harness_root = Path.cwd()
    statuses = check_core_skills(
        harness_root / ".agent-worktrees" / "integration",
        Path.home() / ".agents" / "skills",
    )
    for status in statuses:
        click.echo(
            "{0}: {1}".format(
                status.name,
                "OK" if status.discovered else "MISSING",
            )
        )

    if not all(status.discovered for status in statuses):
        raise click.exceptions.Exit(1)
