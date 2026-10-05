"""Read or authorized-change child role presets and dispatch edges.

The current role configuration stays the single source of truth: this path
reads ``roles.yml``, applies one explicit change to that document and validates
the result with the existing role parser before anything is written. The
selected host reviewer decides the exact reviewed document, and the write
happens only when the file still holds the reviewed content.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import yaml

from graphtraj.configuration.project_roles import (
    ProjectRoles,
    ProjectRolesError,
    _UniqueKeyLoader,
    _roles_from_document,
    roles_file,
)
from graphtraj.execution.runner_io import write_yaml_durably
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.workspace.runner_project import (
    discover_project_root,
    discover_runner_directory,
)


CHANGE_FIELDS = ("set_presets", "remove_presets", "add_edges", "remove_edges")


def organize_child_roles(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> dict:
    """Return the current role organization, or apply one approved change.

    Without ``change`` the call is a side-effect-free preview of the declared
    presets and direct dispatch edges. With ``change`` the actual caller must
    own the project, the selected reviewer must approve the exact resulting
    document, and ``roles.yml`` must still hold the reviewed content; a refusal,
    an unavailable reviewer or a target that changed after review writes
    nothing.
    """
    root = discover_project_root(cwd or Path.cwd())
    path = roles_file(root)
    before_text = _read_text(path)
    before = _load_document(before_text)
    current = _validated(before)

    change = arguments.get("change")
    if change is None:
        return _view(path, before, current)

    # The Runner's own process record decides the caller. A supplied role,
    # alias or reviewer field never confers authority over project role settings.
    caller = caller_alias(discover_runner_directory(root))
    if caller is not None:
        raise RunnerError(
            "authority-denied",
            "Only the caller that owns the Harness Project may organize its child roles.",
        )

    after = _changed(before, change)
    if after == before:
        return {**_view(path, before, current), "applied": False}
    reviewed = _validated(after)
    _approve({"request": dict(arguments), "before": before, "after": after}, root)
    if _read_text(path) != before_text:
        return {
            "applied":     False,
            "status":      "stale",
            "roles_file":  str(path),
            "message":     "roles.yml changed after review; nothing was written.",
        }
    write_yaml_durably(path, after)
    return {**_view(path, after, reviewed), "applied": True}


def _view(path: Path, document: Mapping[str, Any], roles: ProjectRoles) -> dict:
    """Render the current presets and direct edges without changing anything."""
    return {
        "roles_file": str(path),
        "roles":      document.get("roles", {}),
        "role_tree":  document.get("role_tree", {}),
        "presets":    sorted(roles.presets),
        "edges":      sorted(
            [parent, child]
            for parent, children in roles.children.items()
            for child in children
        ),
    }


def _changed(document: dict, change: object) -> dict:
    """Apply one explicit preset/edge change, leaving every other entry untouched."""
    if not isinstance(change, dict) or not change:
        raise RunnerError("invalid-input", "change must be a non-empty mapping.")
    unsupported = sorted(set(change) - set(CHANGE_FIELDS))
    if unsupported:
        raise RunnerError(
            "invalid-input", "change.{0} is not supported.".format(unsupported[0])
        )
    after = copy.deepcopy(document)
    roles = after.get("roles")
    if not isinstance(roles, dict):
        raise RunnerError("invalid-input", "roles.yml.roles must be a mapping.")
    tree = after.setdefault("role_tree", {})
    if not isinstance(tree, dict):
        raise RunnerError("invalid-input", "roles.yml.role_tree must be a mapping.")

    for reference, settings in change.get("set_presets", {}).items():
        _set_preset(roles, reference, settings)
    for reference in change.get("remove_presets", ()):
        _remove_preset(roles, reference)
    for edge in change.get("add_edges", ()):
        _change_edge(tree, edge, present=True)
    for edge in change.get("remove_edges", ()):
        _change_edge(tree, edge, present=False)
    return after


def _set_preset(roles: dict, reference: str, settings: object) -> None:
    """Add one preset, or merge settings into the declared one by exact reference."""
    group, _, name = reference.rpartition(".")
    if not group:
        _merge(roles, reference, settings)
        return
    group_entries = roles.get(group)
    if group_entries is None:
        roles[group] = {name: dict(settings)}
        return
    if not _is_group(group_entries):
        raise RunnerError(
            "invalid-input",
            "roles.{0} is a preset, not a role group.".format(group),
        )
    _merge(group_entries, name, settings)


def _merge(entries: dict, name: str, settings: object) -> None:
    """Keep unrelated declared settings and replace only the supplied fields."""
    declared = entries.get(name)
    entries[name] = {**declared, **settings} if isinstance(declared, dict) else dict(settings)


def _remove_preset(roles: dict, reference: str) -> None:
    """Remove one declared preset by exact reference, dropping an emptied group."""
    group, _, name = reference.rpartition(".")
    if group:
        group_entries = roles.get(group)
        if not _is_group(group_entries) or name not in group_entries:
            raise RunnerError(
                "invalid-input",
                "roles.{0} is not a configured preset.".format(reference),
            )
        del group_entries[name]
        if not group_entries:
            del roles[group]
        return
    if reference not in roles:
        raise RunnerError(
            "invalid-input", "roles.{0} is not a configured preset.".format(reference)
        )
    del roles[reference]


def _change_edge(tree: dict, edge: object, *, present: bool) -> None:
    """Add or remove one direct dispatch edge under its declaring parent."""
    parent = edge["parent"]
    child = edge["child"]
    children = tree.get(parent)
    if present:
        if children is None:
            children = tree[parent] = {}
        if not isinstance(children, dict):
            raise RunnerError(
                "invalid-input", "role_tree.{0} must be a mapping.".format(parent)
            )
        children.setdefault(child, {})
        return
    if not isinstance(children, dict) or child not in children:
        raise RunnerError(
            "invalid-input",
            "role_tree edge {0} -> {1} is not configured.".format(parent, child),
        )
    del children[child]
    if not children:
        del tree[parent]


def _is_group(entries: object) -> bool:
    """Report whether one roles entry declares a group of roles."""
    return (
        isinstance(entries, dict)
        and bool(entries)
        and all(isinstance(value, dict) for value in entries.values())
    )


def _approve(proposal: dict, root: Path) -> None:
    """Require the host's selected reviewer to accept this exact change."""
    from graphtraj.execution.approved_recovery import review_proposal

    decision = review_proposal(proposal, root, discover_runner_directory(root))
    if isinstance(decision, dict) and decision.get("decision") == "accept":
        return
    rationale = decision.get("rationale") if isinstance(decision, dict) else None
    message = "The selected reviewer did not approve this role change; nothing was written."
    if isinstance(rationale, str) and rationale.strip():
        message += " Reviewer reason: " + rationale
    raise RunnerError("role-change-denied", message)


def _read_text(path: Path) -> str:
    """Read the current role document without following a replaced link."""
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("roles.yml is not a regular file")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RunnerError(
            "invalid-config",
            "roles.yml must be a regular readable file at {0}.".format(path),
        ) from error


def _load_document(text: str) -> dict:
    """Parse the current document, rejecting duplicate keys and non-mappings."""
    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise RunnerError("invalid-input", "roles.yml is not readable valid YAML.") from error
    if not isinstance(document, dict):
        raise RunnerError("invalid-input", "roles.yml must contain a roles mapping.")
    return document


def _validated(document: dict) -> ProjectRoles:
    """Reuse the existing role parser so an invalid result is never written."""
    try:
        return _roles_from_document(document)
    except ProjectRolesError as error:
        raise RunnerError("invalid-input", str(error)) from error
