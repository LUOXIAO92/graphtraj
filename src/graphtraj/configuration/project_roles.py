"""Read the reusable child-role settings for one GraphTraj project."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
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
_REQUIRED_FIELDS = frozenset({"runtime", "model"})
_CONNECTION_FIELDS = frozenset({"base_url", "api_key_env"})
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
    """Explicit content, access and Runtime settings for one reusable child role."""

    runtime: str
    model: str
    base_url: str | None
    api_key_env: str | None
    allow_runtime_swarm: bool = False
    reasoning_effort: str | None = None
    codex: Mapping[str, object] | None = None
    pi: Mapping[str, object] | None = None
    instructions: str | None = None
    system_prompt: str | None = None
    developer_prompt: str | None = None
    worktree_access: str = "write"
    reports: tuple[str, ...] = ()
    connection: str | None = None
    connection_revision: str | None = None
    runtime_home: str | None = None
    provider_api: str | None = None
    runtime_provider: str | None = None
    model_source: str | None = None


@dataclass(frozen=True)
class ProjectRoles:
    """The validated reusable child-role presets for one Harness Project.

    Keys are configured references: one group-qualified '<group>.<role>' name
    per declared group role, plus one entry per top-level preset.
    """

    presets: Mapping[str, RolePreset]
    groups: frozenset[str] = frozenset()
    roots: frozenset[str] = frozenset()
    children: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def permits_dispatch(self, parent: str | None, child: str) -> bool:
        """Check an explicit root or direct edge; role names confer no authority.

        References are the exact references declared in role_tree. This checks
        configuration only; the Runner must separately bind the actual caller.
        """
        return child in (self.roots if parent is None else self.children.get(parent, ()))

    def dispatch_preset(self, parent: str | None, role: object) -> RolePreset:
        """Resolve permitted execution settings, including declared inline roles."""
        if isinstance(role, str):
            reference = role
            inline = None
        else:
            _, inline = parse_inline_role(role)
            reference = next(iter(role))
        if not self.permits_dispatch(parent, reference):
            raise ProjectRolesError(("role_tree does not permit this direct dispatch.",))
        return inline if inline is not None else self.preset(reference)

    def resolve(self, reference: str) -> str:
        """Resolve current configuration without inferring historical role aliases.

        Exact configured spellings win. A bare name may select the sole group
        declaring that name; a qualified name must select its declared group.
        """
        for candidate in _reference_spellings(reference):
            if candidate in self.presets:
                return candidate
        group, _, _ = reference.rpartition(".")
        if not (group and self.groups):
            name = configured_role_name(reference)
            matches = sorted(
                candidate for candidate in self.presets
                if configured_role_name(candidate) == name
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
            "roles.{0} is not a configured preset reference.".format(reference),
        ))

    def preset(self, reference: str) -> RolePreset:
        """Return the Runtime settings declared for the selected current role."""
        return resolve_preset(self.presets[self.resolve(reference)])


def configured_role_name(reference: str) -> str:
    """Return the role name one current configured reference declares.

    The group of a '<group>.<role>' reference only selects Runtime settings;
    the name after the last dot is the role's own identity, one word group per
    '-'. A former Engineer tier spelling stays a distinct role name here
    instead of being rewritten to the unified Engineer seat.
    """
    return reference.rpartition(".")[2].replace("_", "-")


def _reference_spellings(reference: str) -> tuple[str, ...]:
    """Return the spellings one supplied reference may use for the configured roles.

    Either side of a word group may spell a group or role word group with '_'
    or '-'. The configured spelling is the one roles.yml declares.
    """
    spellings: list[str] = []
    for spelling in (
        reference,
        reference.replace("-", "_"),
        reference.replace("_", "-"),
    ):
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
    """Render the empty role selection an operator fills in for this project.

    No role is preselected: a project declares only the roles its own work
    uses, and role presets are one such selection rather than a default.
    """
    return yaml.safe_dump({"roles": {}})


def default_project_roles() -> ProjectRoles:
    """Return the validated default role selection, which selects no role."""
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


def parse_inline_role(value: object, *, retained: bool = False) -> tuple[str, RolePreset]:
    """Validate an inline role, leaving retired resource selections in history."""

    if not isinstance(value, dict) or len(value) != 1:
        raise ProjectRolesError(
            ("An inline Batch role must contain exactly one role entry.",)
        )
    name, settings = next(iter(value.items()))
    if not isinstance(name, str) or ROLE_REFERENCE.fullmatch(name) is None:
        raise ProjectRolesError(
            ("An inline Batch role must use a preset reference or lowercase kebab-case name.",)
        )
    name = configured_role_name(name)
    if retained and isinstance(settings, dict):
        # Old names are historical input, not selections for a new Runtime.
        settings = {key: item for key, item in settings.items()
                    if key not in {"skills", "harness_skills", "required_skills"}}
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
        if field not in {"roles", "role_tree"}:
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

    roots, children = _role_tree(document.get("role_tree", {}))
    return ProjectRoles(
        presets=presets, groups=frozenset(grouped), roots=roots, children=children,
    )


def _role_tree(value: object) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Collect direct edges and reject cycles, including across repeated roles."""
    edges: dict[str, set[str]] = {}

    def collect(nodes: object, ancestors: frozenset[str]) -> None:
        """Validate each nested mapping while collecting its declared edges."""
        if not isinstance(nodes, dict):
            raise ProjectRolesError(("role_tree nodes must be mappings.",))
        for reference, children in nodes.items():
            if not isinstance(reference, str) or ROLE_REFERENCE.fullmatch(reference) is None:
                raise ProjectRolesError(("role_tree contains an invalid role reference.",))
            if reference in ancestors:
                raise ProjectRolesError(("role_tree must not contain cycles.",))
            collect(children, ancestors | {reference})
            edges.setdefault(reference, set()).update(children)

    collect(value, frozenset())
    visited: set[str] = set()

    def visit(reference: str, ancestors: frozenset[str]) -> None:
        """Detect cycles formed by edges declared in separate tree branches."""
        if reference in ancestors:
            raise ProjectRolesError(("role_tree must not contain cycles.",))
        if reference not in visited:
            for child in edges[reference]:
                visit(child, ancestors | {reference})
            visited.add(reference)

    for reference in edges:
        visit(reference, frozenset())
    return frozenset(value), {name: frozenset(children) for name, children in edges.items()}


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
    """Return one validated role selection without inferring behavior from its name."""

    if not isinstance(entry, dict):
        diagnostics.append("{0} must be a mapping.".format(name))
        return None
    initial_count = len(diagnostics)
    reference = entry.get("connection")
    if reference is not None:
        if (not isinstance(reference, str)
                or re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", reference) is None
                or set(entry) & (_REQUIRED_FIELDS | _CONNECTION_FIELDS)):
            diagnostics.append(f"{name}.connection must be a reference without inline connection fields.")
            return None
    allowed = _REQUIRED_FIELDS | _CONNECTION_FIELDS | {
        "reasoning_effort", "codex", "pi", "allow_runtime_swarm", "instructions",
        "system_prompt", "developer_prompt", "worktree_access", "reports", "connection",
    }
    if "instructions" in entry and (
        not isinstance(entry["instructions"], str)
        or not entry["instructions"].strip()
        or "\x00" in entry["instructions"]
    ):
        diagnostics.append(f"{name}.instructions must reference a UTF-8 instruction file.")
    for field in ("system_prompt", "developer_prompt"):
        if field in entry and (
            not isinstance(entry[field], str)
            or not entry[field].strip()
            or "\x00" in entry[field]
        ):
            diagnostics.append(f"{name}.{field} must be non-empty UTF-8 prompt text.")
    if entry.get("worktree_access", "write") not in ("read", "write"):
        diagnostics.append(f"{name}.worktree_access must be read or write.")
    reports = entry.get("reports", [])
    if (
        not isinstance(reports, list)
        or any(not isinstance(value, str) or not value for value in reports)
    ):
        diagnostics.append(f"{name}.reports must be a list of names.")
    elif len(set(reports)) != len(reports) or any(
        ROLE_NAME.fullmatch(value.removesuffix(".md")) is None
        or not value.endswith(".md")
        for value in reports
    ):
        diagnostics.append(f"{name}.reports must contain distinct safe names.")
    if "codex" in entry and not isinstance(entry["codex"], dict):
        diagnostics.append("{0}.codex must be a mapping.".format(name))
    if "pi" in entry and not isinstance(entry["pi"], dict):
        diagnostics.append("{0}.pi must be a mapping.".format(name))
    for field in entry:
        if field in {"skills", "harness_skills", "required_skills"}:
            diagnostics.append(
                f"{name}.{field} is no longer supported; use Runtime native Skill "
                "selection or explicit external resource references."
            )
        elif field not in allowed:
            diagnostics.append("{0}.{1} is not supported.".format(name, field))
    for field in (() if reference is not None else _REQUIRED_FIELDS):
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
        "allow_runtime_swarm" in entry
        and not isinstance(entry["allow_runtime_swarm"], bool)
    ):
        diagnostics.append(
            "{0}.allow_runtime_swarm must be a boolean.".format(name)
        )
    if len(diagnostics) != initial_count:
        return None
    return RolePreset(
        connection=reference,
        codex=entry.get("codex"),
        pi=entry.get("pi"),
        runtime=str(entry.get("runtime", "")),
        model=str(entry.get("model", "")),
        base_url=str(entry["base_url"]) if "base_url" in entry else None,
        api_key_env=(
            str(entry["api_key_env"]) if "api_key_env" in entry else None
        ),
        allow_runtime_swarm=entry.get("allow_runtime_swarm", False),
        instructions=entry.get("instructions"),
        system_prompt=entry.get("system_prompt"),
        developer_prompt=entry.get("developer_prompt"),
        worktree_access=entry.get("worktree_access", "write"),
        reports=tuple(entry.get("reports", [])),
        reasoning_effort=(
            str(entry["reasoning_effort"])
            if "reasoning_effort" in entry
            else None
        ),
    )


def resolve_preset(preset: RolePreset) -> RolePreset:
    """Resolve a fresh reference once; retained Runtime contexts never use the catalog."""
    if preset.connection is None or preset.connection_revision is not None:
        return preset
    from graphtraj.configuration.runtime_connections import resolve_connection

    try:
        return replace(preset, **resolve_connection(preset.connection, preset.reasoning_effort))
    except (ValueError, OSError) as error:
        raise ProjectRolesError((str(error),)) from error
