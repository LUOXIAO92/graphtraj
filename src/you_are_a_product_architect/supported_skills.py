"""Install the release-supported core Skill resources project-locally."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path
from typing import Dict, Iterable, Tuple

from .skill_check import CORE_SKILL_NAMES


class SupportedSkillsError(Exception):
    """A release-supported Skill resource could not be installed."""


def _resource_path(name: str) -> tuple[str, ...]:
    if name == "task-delivery":
        return ("skills", name)
    return ("codex", "skills", name)


def _resource_at(root: Traversable, path: tuple[str, ...]) -> Traversable:
    resource = root
    for child in path:
        resource = resource.joinpath(child)
    return resource


def _resource_manifest(
    source: Traversable,
    prefix: str = "",
) -> Dict[str, bytes]:
    if not source.is_dir():
        raise SupportedSkillsError(
            "Release-supported Skill resource is not a directory: {0}".format(
                source
            )
        )

    manifest: Dict[str, bytes] = {}
    for child in source.iterdir():
        relative_path = "{0}/{1}".format(prefix, child.name) if prefix else child.name
        if child.is_dir():
            manifest.update(_resource_manifest(child, relative_path))
        elif child.is_file():
            manifest[relative_path] = child.read_bytes()
        else:
            raise SupportedSkillsError(
                "Release-supported Skill resource is neither a file nor "
                "directory: {0}".format(child)
            )
    return manifest


def _parents(relative_path: str) -> Tuple[str, ...]:
    parts = Path(relative_path).parts
    return tuple(Path(*parts[:index]).as_posix() for index in range(1, len(parts)))


def _existing_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


@dataclass(frozen=True)
class SupportedSkills:
    """The fixed release-supported copies of every required core Skill."""

    resources_by_name: Dict[str, Traversable]

    @classmethod
    def load(cls) -> "SupportedSkills":
        root = resources.files("you_are_a_product_architect.resources")
        resources_by_name = {
            name: _resource_at(root, _resource_path(name))
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

        manifests = {name: self.manifest(name) for name in names}
        skill_root = integration_worktree / ".agents" / "skills"
        for name, manifest in manifests.items():
            target = skill_root / name
            if os.path.lexists(str(target)) and _existing_kind(target) != "directory":
                raise SupportedSkillsError(
                    "Project-local Skill target is not a real directory: {0}".format(
                        target
                    )
                )
            allowed_paths = set(manifest)
            allowed_paths.update(
                parent
                for relative_path in manifest
                for parent in _parents(relative_path)
            )
            if target.is_dir():
                for existing in target.rglob("*"):
                    relative_path = existing.relative_to(target).as_posix()
                    if existing.is_symlink() or relative_path not in allowed_paths:
                        raise SupportedSkillsError(
                            "Project-local Skill contains unsupported or redirected "
                            "content: {0}".format(existing)
                        )
                for relative_path, content in manifest.items():
                    existing = target / relative_path
                    if not os.path.lexists(str(existing)):
                        continue
                    if (
                        _existing_kind(existing) != "file"
                        or existing.read_bytes() != content
                    ):
                        raise SupportedSkillsError(
                            "Project-local Skill resource differs: {0}".format(
                                existing
                            )
                        )

        skill_root.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = skill_root / name
            target.mkdir(parents=True, exist_ok=True)
            manifest = manifests[name]
            file_order = sorted(
                manifest,
                key=lambda path: (Path(path).name == "SKILL.md", path),
            )
            for relative_path in file_order:
                destination = target / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (
                    destination.exists()
                    and destination.read_bytes() == manifest[relative_path]
                ):
                    continue
                destination.write_bytes(manifest[relative_path])

    def manifest(self, name: str) -> Dict[str, bytes]:
        """Return one supported Skill as exact relative file content."""

        try:
            resource = self.resources_by_name[name]
        except KeyError as error:
            raise SupportedSkillsError(
                "No release-supported Skill resource exists for: {0}".format(name)
            ) from error
        return _resource_manifest(resource)
