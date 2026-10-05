"""Resolve GraphTraj child responsibilities independently of their Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


# Each Runtime exposes only the native prompt layers it actually provides:
# Pi appends to its system prompt, DSH sets its system prompt, and Codex sets
# developer instructions. There is no shared hierarchy beyond this mapping and
# no Runtime may be handed content for a layer it does not expose.
_RUNTIME_PROMPT_LAYERS = {
    "pi":    frozenset({"system"}),
    "dsh":   frozenset({"system"}),
    "codex": frozenset({"developer"}),
}
# Configured preset field to the native layer its text names.
_PROMPT_FIELDS = (
    ("system_prompt", "system"),
    ("developer_prompt", "developer"),
)


@dataclass(frozen=True)
class ResolvedChildRole:
    """One role's installed responsibilities with its selected Runtime settings."""

    name: str
    instructions: str
    settings: RolePreset

    @property
    def allow_runtime_swarm(self) -> bool:
        """Return the explicitly configured native helper capability."""
        return self.settings.allow_runtime_swarm


def resolve_child_role(
    name: str, settings: RolePreset, harness_root: Path,
) -> ResolvedChildRole:
    """Read optional UTF-8 role text and compose the supported native prompt.

    File reads use the caller's existing permissions. Text is passed through,
    never interpreted as a template or a list of required Skills. Authored
    system/developer content is added only for the layer the selected Runtime
    exposes; a declared layer that Runtime does not expose is refused before
    any dispatch and is never folded into another layer.
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

    instructions += _authored_prompt(name, settings)
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
        name, instructions, settings,
    )


def _authored_prompt(name: str, settings: RolePreset) -> str:
    """Return configured prompt text for the layers this Runtime exposes.

    A declared layer the selected Runtime does not expose raises
    ``ROLE_CONFIG_UNSUPPORTED`` naming both the field and the layers that
    Runtime does expose. An unknown Runtime keeps its existing unsupported
    Runtime result from Adapter selection, so this adds no new meaning to an
    unimplemented Runtime name.
    """
    supported = _RUNTIME_PROMPT_LAYERS.get(settings.runtime)
    if supported is None:
        return ""

    parts: list[str] = []
    for field, layer in _PROMPT_FIELDS:
        value = getattr(settings, field)
        if value is None:
            continue
        if layer not in supported:
            raise RuntimeAdapterError(
                "ROLE_CONFIG_UNSUPPORTED",
                "Role {0} declares {1}, but the selected {2} Runtime exposes only "
                "these native prompt layers: {3}.".format(
                    name, field, settings.runtime, ", ".join(sorted(supported))
                ),
            )
        parts.append(value.rstrip("\n"))

    return "".join("\n{0}\n".format(part) for part in parts)
