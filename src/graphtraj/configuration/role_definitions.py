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
        return self.name == "team-leader" and self.settings.allow_runtime_swarm


def has_packaged_role(name: str) -> bool:
    """Return whether an installed role template defines this role name."""

    if ROLE_NAME.fullmatch(name) is None:
        return False
    return resources.files("graphtraj.resources").joinpath(
        "roles", name + ".yml"
    ).is_file()


def resolve_child_role(name: str, settings: RolePreset) -> ResolvedChildRole:
    """Resolve one configured role's responsibilities from its templates.

    A role name without its own installed template keeps its actual name and
    uses the generic temporary-role responsibilities.
    """

    template = name if has_packaged_role(name) else "temporary-role"
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
        "They cannot implement, Review, own a Team seat, or replace formal "
        "agent-runner dispatch. They are excluded from Team state and Runner "
        "concurrency and have no independent GraphTraj Session Trace guarantee. "
        "Use agent-runner for work requiring an independent Trace.\n"
        if name == "team-leader" and settings.allow_runtime_swarm else
        "\nDo not use Runtime-native swarm or dispatch native helpers.\n"
    ) + (
        "Do not invoke agent-runner or start an Agent Runtime directly.\n"
        if name != "team-leader" else
        "Never start an Agent Runtime directly; formal work uses agent-runner.\n"
    )
    return ResolvedChildRole(name, instructions, tuple(required_skills), settings)
