"""Resolve GraphTraj child responsibilities independently of their Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graphtraj.configuration.project_roles import RolePreset
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


def resolve_child_role(
    name: str, settings: RolePreset, harness_root: Path,
) -> ResolvedChildRole:
    """Read optional UTF-8 role text relative to the Harness, preserving identity.

    File reads use the caller's existing permissions. Text is passed through,
    never interpreted as a template or a list of required Skills.
    """
    instructions = ""
    if settings.instructions is not None:
        path = harness_root / settings.instructions
        try:
            instructions = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            raise RuntimeAdapterError(
                "ROLE_CONFIG_INVALID",
                f"Cannot read UTF-8 role instructions at {path}: {error}",
            ) from error

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
        name, instructions, (), settings,
    )
