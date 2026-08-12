"""Install the release-supported core Skill resources project-locally."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path
from typing import Dict, Iterable

from .skill_check import CORE_SKILL_NAMES


class SupportedSkillsError(Exception):
    """A release-supported Skill resource could not be installed."""


def _resource_path(name: str) -> tuple[str, ...]:
    if name == "task-delivery":
        return ("skills", name)
    return ("codex", "skills", name)


def _copy_resource_tree(source: Traversable, destination: Path) -> None:
    if source.is_dir():
        destination.mkdir()
        for child in source.iterdir():
            _copy_resource_tree(child, destination / child.name)
        return
    if source.is_file():
        destination.write_bytes(source.read_bytes())
        return
    raise SupportedSkillsError(
        "Release-supported Skill resource is neither a file nor directory: "
        "{0}".format(source)
    )


@dataclass(frozen=True)
class SupportedSkills:
    """The fixed release-supported copies of every required core Skill."""

    resources_by_name: Dict[str, Traversable]

    @classmethod
    def load(cls) -> "SupportedSkills":
        root = resources.files("you_are_a_product_architect.resources")
        resources_by_name = {
            name: root.joinpath(*_resource_path(name))
            for name in CORE_SKILL_NAMES
        }
        missing_resources = tuple(
            name
            for name, resource in resources_by_name.items()
            if not resource.is_dir()
        )
        if missing_resources:
            raise SupportedSkillsError(
                "Release-supported Skill resources are unavailable: {0}".format(
                    ", ".join(missing_resources)
                )
            )
        return cls(resources_by_name=resources_by_name)

    def install_missing(
        self,
        integration_worktree: Path,
        missing_names: Iterable[str],
    ) -> None:
        """Copy only preflighted missing names to the Integration Worktree."""

        names = tuple(missing_names)
        unknown_names = tuple(
            name for name in names if name not in self.resources_by_name
        )
        if unknown_names:
            raise SupportedSkillsError(
                "No release-supported Skill resource exists for: {0}".format(
                    ", ".join(unknown_names)
                )
            )

        skill_root = integration_worktree / ".agents" / "skills"
        targets = tuple(skill_root / name for name in names)
        existing_targets = tuple(
            target for target in targets if os.path.lexists(str(target))
        )
        if existing_targets:
            raise SupportedSkillsError(
                "Project-local Skill already exists: {0}".format(
                    ", ".join(str(target) for target in existing_targets)
                )
            )

        skill_root.mkdir(parents=True, exist_ok=True)
        for name, target in zip(names, targets):
            _copy_resource_tree(self.resources_by_name[name], target)
