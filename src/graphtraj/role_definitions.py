"""Resolve GraphTraj child responsibilities independently of their Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import yaml

from .project_roles import ROLE_NAMES, ROLE_REFERENCES, RolePreset
from .runtime_adapter import RuntimeAdapterError


@dataclass(frozen=True)
class ResolvedChildRole:
    """Fixed responsibilities and required Skills with selected Runtime settings."""

    name: str
    instructions: str
    required_skills: tuple[str, ...]
    settings: RolePreset

    @property
    def allow_runtime_swarm(self) -> bool:
        return self.name == "team-leader" and self.settings.allow_runtime_swarm


def resolve_child_role(name: str, settings: RolePreset) -> ResolvedChildRole:
    """Resolve a known child policy; temporary Batch names use temporary-role."""
    name = ROLE_REFERENCES.get(name, name)
    if name not in (*ROLE_NAMES, "temporary-role"):
        raise RuntimeAdapterError("ROLE_NOT_SUPPORTED", "The child role is not supported by this Runner.")
    try:
        document = yaml.safe_load(resources.files("graphtraj.resources").joinpath(
            "roles", name + ".yml"
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
