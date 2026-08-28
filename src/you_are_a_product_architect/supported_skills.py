"""Install the release-supported core Skill resources in the Runtime Store."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from importlib.abc import Traversable
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Set

from .path_safety import relative_parent_paths
from .skill_check import CORE_SKILL_NAMES, harness_skill_root


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


def allowed_manifest_paths(manifest: Mapping[str, bytes]) -> Set[str]:
    """Return every file and directory a supported manifest may contain."""

    allowed = set(manifest)
    allowed.update(
        parent
        for relative_path in manifest
        for parent in relative_parent_paths(relative_path)
    )
    return allowed


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

    @staticmethod
    def resource_action(
        runtime_store: Path,
        name: str,
        relative_path: str,
    ) -> str:
        """Describe one exact Harness-root Skill mutation."""

        return "Harness Skill {0}: {1}".format(
            name,
            harness_skill_root(runtime_store) / name / relative_path,
        )

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
        runtime_store: Path,
        missing_names: Iterable[str],
        on_action_complete: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Install preflighted release-supported Skill resources."""

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
        skill_root = harness_skill_root(runtime_store)
        for name, manifest in manifests.items():
            target = skill_root / name
            if os.path.lexists(str(target)) and _existing_kind(target) != "directory":
                raise SupportedSkillsError(
                    "Harness Skill target is not a real directory: {0}".format(
                        target
                    )
                )
            allowed_paths = allowed_manifest_paths(manifest)
            if target.is_dir():
                for existing in target.rglob("*"):
                    relative_path = existing.relative_to(target).as_posix()
                    if existing.is_symlink() or (
                        name != "task-delivery" and relative_path not in allowed_paths
                    ):
                        raise SupportedSkillsError(
                            "Harness Skill contains unsupported or redirected "
                            "content: {0}".format(existing)
                        )
                for relative_path, content in manifest.items():
                    existing = target / relative_path
                    if not os.path.lexists(str(existing)):
                        continue
                    if (
                        _existing_kind(existing) != "file"
                        or (
                            name != "task-delivery"
                            and existing.read_bytes() != content
                        )
                    ):
                        raise SupportedSkillsError(
                            "Harness Skill resource differs: {0}".format(
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
                if on_action_complete is not None:
                    on_action_complete(
                        self.resource_action(
                            runtime_store,
                            name,
                            relative_path,
                        )
                    )

    def manifest(self, name: str) -> Dict[str, bytes]:
        """Return one supported Skill as exact relative file content."""

        try:
            resource = self.resources_by_name[name]
        except KeyError as error:
            raise SupportedSkillsError(
                "No release-supported Skill resource exists for: {0}".format(name)
            ) from error
        return _resource_manifest(resource)
