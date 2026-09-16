"""Read the reusable child-role settings for one GraphTraj project."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


ROLES_PATH = Path(".graphtraj") / "roles.yml"
# Keep the established policy and Session identifiers behind grouped references.
ROLE_NAMES = (
    "team-leader",
    "engineer",
    "standards-reviewer",
    "spec-reviewer",
    "delivery-state",
    "merge-resolver",
)
# Retained Batch, Session and Team records may still name one of these identities.
_LEGACY_ENGINEER_NAMES = ("engineer-junior", "engineer-senior", "engineer-expert")
ROLE_REFERENCES = {
    **{
        "coding-team." + name if name != "delivery-state" else name: name
        for name in ROLE_NAMES
    },
    **{name: "engineer" for name in _LEGACY_ENGINEER_NAMES},
    **{"coding-team." + name: "engineer" for name in _LEGACY_ENGINEER_NAMES},
}
_REQUIRED_FIELDS = frozenset({"runtime", "model"})
_CONNECTION_FIELDS = frozenset({"base_url", "api_key_env"})
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ROLE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_DEFAULT_PRESETS: dict[str, dict[str, object]] = {
    "team-leader": {
        "runtime": "codex",
        "model": "gpt-5.6-sol",
        "allow_runtime_swarm": True,
    },
    "engineer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "standards-reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "spec-reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "delivery-state": {"runtime": "codex", "model": "gpt-5.6-luna"},
    "merge-resolver": {"runtime": "codex", "model": "gpt-5.6-sol"},
}


class ProjectRolesError(Exception):
    """The reusable child-role configuration is missing or invalid."""

    def __init__(self, diagnostics: tuple[str, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__(
            "GraphTraj Roles is invalid.\n{0}".format(
                "\n".join("- {0}".format(item) for item in diagnostics)
            )
        )


@dataclass(frozen=True)
class RolePreset:
    """The Runtime settings selected for one reusable child role."""

    runtime: str
    model: str
    base_url: str | None
    api_key_env: str | None
    allow_runtime_swarm: bool = False
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class ProjectRoles:
    """The validated reusable child-role presets for one Harness Project."""

    presets: Mapping[str, RolePreset]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Treat duplicate YAML mapping keys as invalid configuration."""

    def construct_mapping(self, node: yaml.Node, deep: bool = False) -> object:
        self.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found duplicate key",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def roles_file(harness_root: Path) -> Path:
    """Return the fixed reusable role configuration location."""
    return harness_root / ROLES_PATH


def roles_exist(harness_root: Path) -> bool:
    """Return whether the role target exists, including a symbolic link."""
    return os.path.lexists(str(roles_file(harness_root)))


def default_roles_content() -> str:
    """Render the established reusable coding-role presets."""
    return yaml.safe_dump({"roles": {
        "coding-team": {
            name: preset for name, preset in _DEFAULT_PRESETS.items()
            if name != "delivery-state"
        },
        "delivery-state": _DEFAULT_PRESETS["delivery-state"],
    }}, sort_keys=False)


def default_project_roles() -> ProjectRoles:
    """Return the validated established reusable coding-role presets."""
    return _roles_from_document({"roles": _DEFAULT_PRESETS})


def load_project_roles(harness_root: Path) -> ProjectRoles:
    """Load the fixed reusable child-role configuration."""
    path = roles_file(harness_root)
    try:
        if not os.path.lexists(str(path)):
            raise FileNotFoundError(path)
        if path.is_symlink() or not path.is_file():
            raise OSError("roles.yml is not a regular file")
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except FileNotFoundError as error:
        raise ProjectRolesError(
            ("roles.yml was not found at {0}.".format(path),)
        ) from error
    except OSError as error:
        raise ProjectRolesError(
            ("roles.yml must be a regular readable file at {0}.".format(path),)
        ) from error
    except (UnicodeError, yaml.YAMLError) as error:
        raise ProjectRolesError(("roles.yml is not readable valid YAML.",)) from error
    return _roles_from_document(document)


def parse_inline_role(value: object) -> tuple[str, RolePreset]:
    """Validate one temporary Batch role with the reusable role schema."""

    if not isinstance(value, dict) or len(value) != 1:
        raise ProjectRolesError(
            ("An inline Batch role must contain exactly one role entry.",)
        )
    name, settings = next(iter(value.items()))
    if not isinstance(name, str) or (
        name not in ROLE_REFERENCES and not _ROLE_NAME.fullmatch(name)
    ):
        raise ProjectRolesError(
            ("An inline Batch role must use a preset reference or lowercase kebab-case name.",)
        )
    name = ROLE_REFERENCES.get(name, name)
    diagnostics: list[str] = []
    preset = _role_preset(name, settings, diagnostics)
    if diagnostics or preset is None:
        raise ProjectRolesError(tuple(diagnostics))
    return name, preset


def _roles_from_document(document: Any) -> ProjectRoles:
    diagnostics: list[str] = []
    if not isinstance(document, dict):
        raise ProjectRolesError(("roles.yml must contain a roles mapping.",))
    for field in document:
        if field != "roles":
            diagnostics.append("roles.yml.{0} is not supported.".format(field))
    entries = document.get("roles")
    if not isinstance(entries, dict):
        diagnostics.append("roles.yml.roles must be a mapping.")
        raise ProjectRolesError(tuple(diagnostics))

    # Resolve the one supported team explicitly; YAML dots have no path meaning.
    # Read older flat presets without rewriting operator settings or history.
    entries = dict(entries)
    if "coding-team" in entries:
        coding = entries.pop("coding-team")
        if not isinstance(coding, dict):
            diagnostics.append("roles.coding-team must be a mapping.")
        else:
            for name, value in coding.items():
                if name not in ROLE_NAMES or name == "delivery-state":
                    diagnostics.append("roles.coding-team.{0} is not a supported preset.".format(name))
                elif name in entries:
                    diagnostics.append("{0} preset is defined more than once.".format(name))
                else:
                    entries[name] = value

    known_entries: dict[str, object] = {}
    for name, value in entries.items():
        if not isinstance(name, str):
            diagnostics.append("roles.yml.roles contains an unsupported preset name.")
            continue
        if name not in ROLE_NAMES:
            diagnostics.append("roles.{0} is not a supported preset.".format(name))
            continue
        known_entries[name] = value

    presets: dict[str, RolePreset] = {}
    for name in ROLE_NAMES:
        entry = known_entries.get(name)
        if entry is None:
            diagnostics.append("{0} preset is required.".format(name))
            continue
        preset = _role_preset(name, entry, diagnostics)
        if preset is not None:
            presets[name] = preset

    if diagnostics:
        raise ProjectRolesError(tuple(diagnostics))

    return ProjectRoles(presets=presets)


def _role_preset(
    name: str,
    entry: object,
    diagnostics: list[str],
) -> RolePreset | None:
    """Return one validated Runtime-setting-only role entry."""

    if not isinstance(entry, dict):
        diagnostics.append("{0} must be a mapping.".format(name))
        return None
    initial_count = len(diagnostics)
    allowed = _REQUIRED_FIELDS | _CONNECTION_FIELDS | {"reasoning_effort"}
    if name == "team-leader":
        allowed = allowed | {"allow_runtime_swarm"}
    for field in entry:
        if field not in allowed:
            diagnostics.append("{0}.{1} is not supported.".format(name, field))
    for field in _REQUIRED_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                "{0}.{1} must be a non-empty string.".format(name, field)
            )
    for field in _CONNECTION_FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                "{0}.{1} must be a non-empty string when supplied.".format(
                    name, field
                )
            )
        elif field == "api_key_env" and not _ENVIRONMENT_NAME.fullmatch(value):
            diagnostics.append(
                "{0}.api_key_env must name an environment variable.".format(name)
            )
    if "reasoning_effort" in entry and (
        not isinstance(entry["reasoning_effort"], str)
        or not entry["reasoning_effort"].strip()
    ):
        diagnostics.append(
            "{0}.reasoning_effort must be a non-empty string when supplied.".format(
                name
            )
        )
    if name == "team-leader" and "allow_runtime_swarm" in entry and not isinstance(
        entry["allow_runtime_swarm"], bool
    ):
        diagnostics.append("team-leader.allow_runtime_swarm must be a boolean.")
    if len(diagnostics) != initial_count:
        return None
    return RolePreset(
        runtime=str(entry["runtime"]),
        model=str(entry["model"]),
        base_url=str(entry["base_url"]) if "base_url" in entry else None,
        api_key_env=(
            str(entry["api_key_env"]) if "api_key_env" in entry else None
        ),
        allow_runtime_swarm=(
            bool(entry.get("allow_runtime_swarm", True))
            if name == "team-leader"
            else False
        ),
        reasoning_effort=(
            str(entry["reasoning_effort"])
            if "reasoning_effort" in entry
            else None
        ),
    )
