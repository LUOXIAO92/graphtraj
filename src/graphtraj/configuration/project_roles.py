"""Read the reusable child-role settings for one GraphTraj project."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


ROLES_PATH = Path(".graphtraj") / "roles.yml"
# One top-level preset name or one group-qualified '<group>.<role>' reference.
# Configured names join their word groups with '_'; a retained name keeps '-'.
ROLE_NAME = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
ROLE_REFERENCE = re.compile(
    r"^[a-z0-9]+(?:[_-][a-z0-9]+)*(?:\.[a-z0-9]+(?:[_-][a-z0-9]+)*)?$"
)
# Retained Batch, Session and Team records may still name a former Engineer tier.
_RETAINED_ENGINEER_REFERENCES = {
    "engineer-junior": "coding-team.engineer",
    "engineer-senior": "coding-team.engineer",
    "engineer-expert": "coding-team.engineer",
    "coding-team.engineer-junior": "coding-team.engineer",
    "coding-team.engineer-senior": "coding-team.engineer",
    "coding-team.engineer-expert": "coding-team.engineer",
}
_REQUIRED_FIELDS = frozenset({"runtime", "model"})
_CONNECTION_FIELDS = frozenset({"base_url", "api_key_env"})
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DEFAULT_PRESETS: dict[str, dict[str, object]] = {
    "team_leader": {
        "runtime": "codex",
        "model": "gpt-5.6-sol",
        "allow_runtime_swarm": True,
    },
    "engineer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "standards_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "spec_reviewer": {"runtime": "codex", "model": "gpt-5.6-sol"},
    "delivery_state": {"runtime": "codex", "model": "gpt-5.6-luna"},
    "merge_resolver": {"runtime": "codex", "model": "gpt-5.6-sol"},
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
    """The validated reusable child-role presets for one Harness Project.

    Keys are configured references: one group-qualified '<group>.<role>' name
    per declared group role, plus one entry per top-level preset.
    """

    presets: Mapping[str, RolePreset]
    groups: frozenset[str] = frozenset()

    def resolve(self, reference: str) -> str:
        """Return the configured reference that one role reference selects.

        A named group selects exactly that group role, a top-level preset name
        selects itself, and a bare role name selects a group role only when
        exactly one configured group declares it. A flat roles.yml declares no
        group, so its former group token is read as part of the role name.
        """
        for candidate in _reference_spellings(reference):
            if candidate in self.presets:
                return candidate
        retained = retained_role_reference(reference)
        group, _, _ = retained.rpartition(".")
        if group and self.groups:
            raise ProjectRolesError((
                "roles.{0} is not a configured preset reference.".format(retained),
            ))
        name = logical_role(retained)
        matches = sorted(
            candidate
            for candidate in self.presets
            if logical_role(candidate) == name
        )
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ProjectRolesError((
                "roles.{0} is declared by more than one group: {1}.".format(
                    name, ", ".join(matches)
                ),
            ))
        raise ProjectRolesError((
            "roles.{0} is not a configured preset reference.".format(retained),
        ))

    def preset(self, reference: str) -> RolePreset:
        """Return the Runtime settings that one role reference selects."""
        return self.presets[self.resolve(reference)]


def logical_role(reference: str) -> str:
    """Return the role name one configured or retained reference selects.

    The group of a '<group>.<role>' reference only selects Runtime settings;
    the role name after the last dot keeps the packaged responsibility, one
    word group per '-', so a configured '_' spelling and an installed
    hyphenated template name the same role.
    """
    retained = _RETAINED_ENGINEER_REFERENCES.get(reference, reference)
    return retained.rpartition(".")[2].replace("_", "-")


def retained_role_reference(reference: str) -> str:
    """Return the configured reference spelling for one supplied reference."""
    return _RETAINED_ENGINEER_REFERENCES.get(reference, reference)


def _reference_spellings(reference: str) -> tuple[str, ...]:
    """Return the spellings one supplied reference may use for the configured roles.

    Retained Batch, Session and Team records may name a former Engineer tier,
    and either side of a rename may spell a group or role word group with '_'
    or '-'. The configured spelling is the one roles.yml declares.
    """
    spellings: list[str] = []
    for candidate in (retained_role_reference(reference), reference):
        for spelling in (candidate, candidate.replace("-", "_"), candidate.replace("_", "-")):
            if spelling not in spellings:
                spellings.append(spelling)
    return tuple(spellings)


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
        "coding_team": {
            name: preset for name, preset in _DEFAULT_PRESETS.items()
            if name != "delivery_state"
        },
        "delivery_state": _DEFAULT_PRESETS["delivery_state"],
    }}, sort_keys=False)


def default_project_roles() -> ProjectRoles:
    """Return the validated established reusable coding-role presets."""
    return _roles_from_document(yaml.safe_load(default_roles_content()))


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
    if not isinstance(name, str) or ROLE_REFERENCE.fullmatch(name) is None:
        raise ProjectRolesError(
            ("An inline Batch role must use a preset reference or lowercase kebab-case name.",)
        )
    name = logical_role(name)
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

    # A group maps its own role names to Runtime settings; its references are
    # '<group>.<role>'. A top-level entry is one preset named by itself. YAML
    # dots have no path meaning, so the group shape is read from its entries.
    grouped: dict[str, Any] = {}
    flat: dict[str, Any] = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or ROLE_NAME.fullmatch(name) is None:
            diagnostics.append("roles.yml.roles contains an unsupported name.")
        elif isinstance(entry, dict) and entry and all(
            isinstance(value, dict) for value in entry.values()
        ):
            grouped[name] = entry
        else:
            flat[name] = entry

    group_roles: set[str] = set()
    presets: dict[str, RolePreset] = {}
    for group_name, group in grouped.items():
        for name, entry in group.items():
            if not isinstance(name, str) or ROLE_NAME.fullmatch(name) is None:
                diagnostics.append(
                    "roles.{0} contains an unsupported role name.".format(group_name)
                )
                continue
            group_roles.add(name)
            _add_preset(group_name + "." + name, entry, presets, diagnostics)

    for name, entry in flat.items():
        if name in group_roles:
            diagnostics.append("{0} preset is defined more than once.".format(name))
            continue
        _add_preset(name, entry, presets, diagnostics)

    if diagnostics:
        raise ProjectRolesError(tuple(diagnostics))

    return ProjectRoles(presets=presets, groups=frozenset(grouped))


def _add_preset(
    reference: str,
    entry: object,
    presets: dict[str, RolePreset],
    diagnostics: list[str],
) -> None:
    """Validate one reference's Runtime settings and keep them by reference."""

    if reference in presets:
        diagnostics.append("{0} preset is defined more than once.".format(reference))
        return
    preset = _role_preset(reference, entry, diagnostics)
    if preset is not None:
        presets[reference] = preset


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
    if logical_role(name) == "team-leader":
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
    if (
        logical_role(name) == "team-leader"
        and "allow_runtime_swarm" in entry
        and not isinstance(entry["allow_runtime_swarm"], bool)
    ):
        diagnostics.append(
            "{0}.allow_runtime_swarm must be a boolean.".format(name)
        )
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
            if logical_role(name) == "team-leader"
            else False
        ),
        reasoning_effort=(
            str(entry["reasoning_effort"])
            if "reasoning_effort" in entry
            else None
        ),
    )
