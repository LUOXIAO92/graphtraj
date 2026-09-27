"""Resolve GraphTraj child responsibilities independently of their Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import yaml

from graphtraj.configuration.project_roles import ROLE_NAME, RolePreset
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


@dataclass(frozen=True)
class ResolvedChildRole:
    """One role's installed responsibilities with its selected Runtime settings."""

    name: str
    instructions: str
    required_skills: tuple[str, ...]
    settings: RolePreset

    @property
    def allow_runtime_swarm(self) -> bool:
        """Return the explicitly configured native helper capability."""
        return self.settings.allow_runtime_swarm


def packaged_role_name(name: str) -> str:
    """Return the installed filename for an explicitly selected resource.

    Installed templates keep their hyphenated file names, so a configured
    underscore name selects the same template.
    """

    return name.replace("_", "-")


def has_packaged_role(name: str) -> bool:
    """Return whether an installed role template defines this role name."""

    if ROLE_NAME.fullmatch(name) is None:
        return False
    return resources.files("graphtraj.resources").joinpath(
        "roles", packaged_role_name(name) + ".yml"
    ).is_file()


def resolve_child_role(name: str, settings: RolePreset) -> ResolvedChildRole:
    """Load explicitly selected instructions and Skills, preserving actual identity."""

    template = packaged_role_name(settings.instructions)
    if not has_packaged_role(template):
        raise RuntimeAdapterError(
            "PACKAGED_ROLE_INVALID", f"Selected role resource {settings.instructions!r} was not found."
        )
    try:
        document = yaml.safe_load(resources.files("graphtraj.resources").joinpath(
            "roles", template + ".yml"
        ).read_text(encoding="utf-8"))
        instructions = document["instructions"]
        required_skills = document["required_skills"]
        if (
            not isinstance(instructions, str) or not instructions.strip()
            or not isinstance(required_skills, list)
            or any(not isinstance(skill, str) or not skill.strip() for skill in required_skills)
        ):
            raise ValueError("Invalid child responsibilities or Skills")
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, ValueError) as error:
        raise RuntimeAdapterError("PACKAGED_ROLE_INVALID", "The installed GraphTraj role definition is invalid.") from error

    instructions += (
        "\nNative helpers are permitted only for temporary read-only investigation. "
        "They cannot own a Team seat or replace formal "
        "agent-runner dispatch. They are excluded from Team state and Runner "
        "concurrency and have no independent GraphTraj Session Trace guarantee. "
        "Use agent-runner for work requiring an independent Trace.\n"
        if settings.allow_runtime_swarm else
        "\nDo not use Runtime-native swarm or dispatch native helpers.\n"
    ) + (
        "Never start an Agent Runtime directly; formal dispatch uses Runner "
        "and the configured role_tree.\n"
    )
    return ResolvedChildRole(
        name, instructions, tuple(dict.fromkeys((*required_skills, *settings.harness_skills))), settings,
    )
