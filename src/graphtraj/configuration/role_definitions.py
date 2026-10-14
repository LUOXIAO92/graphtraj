"""Resolve GraphTraj child responsibilities independently of their Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graphtraj.configuration.project_roles import RolePreset, resolve_preset
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


# The layer each Runtime's existing instructions file and role boilerplate use.
# Codex delivers them as developer instructions; Pi and DSH have one system
# prompt channel and merge authored developer text into that channel.
_RUNTIME_INSTRUCTION_LAYER = {
    "claude": "system",
    "pi":    "system",
    "dsh":   "system",
    "codex": "developer",
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
    # System-layer text for a Runtime that keeps it apart from ``instructions``
    # (Codex base instructions); empty when ``instructions`` already is that
    # layer, as it is for Pi and DSH.
    system_instructions: str = ""

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
    system/developer content uses Codex's separate native layers. Pi and DSH
    append both to their single system channel; developer text is labeled but
    does not gain a separate native priority level.
    """
    settings = resolve_preset(settings)
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

    system_instructions, authored = _authored_prompt(settings)
    instructions += authored
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
        name, instructions, settings, system_instructions,
    )


def _authored_prompt(settings: RolePreset) -> tuple[str, str]:
    """Return (system text kept apart, text for the instruction channel).

    Codex keeps base (system) and developer instructions in
    separate native parameters, so its ``system_prompt`` is returned separately;
    Pi and DSH have one system-prompt channel, so both authored layers join
    ``instructions``. An unknown Runtime keeps its existing unsupported Runtime
    result from Adapter selection and contributes no text.
    """
    primary = _RUNTIME_INSTRUCTION_LAYER.get(settings.runtime)
    if primary is None:
        return "", ""

    separate = ""
    joined: list[str] = []
    for field, layer in _PROMPT_FIELDS:
        value = getattr(settings, field)
        if value is None:
            continue
        if layer == "system" and primary != "system":
            # This Runtime carries system text in its own native parameter.
            separate = value.rstrip("\n")
        else:
            text = value.rstrip("\n")
            if layer == "developer" and primary == "system":
                text = "Developer prompt (merged into the Runtime system prompt):\n" + text
            joined.append(text)

    return separate, "".join("\n{0}\n".format(part) for part in joined)
