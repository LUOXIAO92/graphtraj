"""Restricted human desktop settings bridge using shared role authorization.

The Electron main process owns this pipe and answers review requests with the
actual native dialog result. Renderer requests cannot supply a reviewer or an
Agent identity. No execution or task-control operation is exposed here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, TextIO
from urllib.parse import urlsplit

from graphtraj.configuration.role_definitions import resolve_child_role
from graphtraj.execution.role_organization import _changed, _validated, organize_child_roles
from graphtraj.execution.runner_models import RunnerError
from graphtraj.execution.runner_status import caller_alias
from graphtraj.runtimes.runtime_adapter import recovery_review
from graphtraj.workspace.runner_project import discover_project_root, discover_runner_directory


FIELDS = (
    "runtime", "model", "base_url", "api_key_env", "reasoning_effort",
    "instructions", "system_prompt", "developer_prompt", "connection",
    "approval_model", "approval_base_url", "approval_api_key_env",
)
EFFECT = (
    "Saved presets apply when a later dispatch resolves these roles. Existing Sessions "
    "keep their captured settings. Saving does not start, stop or restart any Agent."
)


def _entries(document: dict) -> dict:
    """Project only editable fields; never transmit unknown credential containers."""
    result = {}
    for reference in document["presets"]:
        group, _, name = reference.rpartition(".")
        entry = document["roles"][group][name] if group else document["roles"][name]
        result[reference] = {key: entry[key] for key in FIELDS if key in entry}
        approval = entry.get("codex", {}).get("approval", {})
        if isinstance(approval, dict):
            result[reference].update({f"approval_{key}": approval[key]
                                      for key in ("model", "base_url", "api_key_env") if key in approval})
        _check_connection(result[reference])
    return result


def _check_connection(settings: dict) -> None:
    """Keep credentials out of connection fields and their validation errors."""
    if any(key.startswith("approval_") for key in settings):
        _check_connection({key.removeprefix("approval_"): value for key, value in settings.items()
                           if key.startswith("approval_")})
    env = settings.get("api_key_env")
    if env is not None and (
        not isinstance(env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env)
    ):
        raise ValueError("api_key_env must be an environment variable NAME, not a credential value.")
    url = settings.get("base_url")
    if url is not None:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError(
                "Base URL must be an HTTP(S) endpoint without credentials, query or fragment. "
                "Use api_key_env for credentials."
            )


def settings_request(request: dict, cwd: Path, reviewer: Callable[[dict], dict]) -> dict:
    """Read safe fields or save a role/tree draft through native review.

    The reviewer is trusted host context, never a field accepted in request.
    Both reads and writes retain the actual process/callback caller boundary.
    """
    from graphtraj.configuration.runtime_connections import connection_context

    user_scope = isinstance(request, dict) and request.get("scope") == "user"
    root, runner_directory = connection_context(cwd) if user_scope else (
        discover_project_root(cwd), discover_runner_directory(cwd),
    )
    if caller_alias(runner_directory) is not None:
        raise RunnerError(
            "authority-denied",
            "Desktop settings require the human project owner; "
            "Agent callers must use their authorized native operations.",
        )
    if isinstance(request, dict) and request.get("scope") == "user":
        from graphtraj.configuration.runtime_connections import manage_connections
        from graphtraj.interfaces.gateway import _validate
        from graphtraj.interfaces.tools import TOOLS

        arguments = {key: value for key, value in request.items() if key != "scope"}
        _validate(arguments, TOOLS['runtime_connections'].input_schema, 'arguments')
        with recovery_review(reviewer):
            return manage_connections(arguments, cwd=root)
    if not isinstance(request, dict) or request.get("action") not in {"read", "preview", "save"}:
        raise ValueError("Choose read, preview or save settings.")
    allowed = {"action"} if request["action"] == "read" else {
        "action", "revision", "edits", "renames", "add_edges", "remove_edges", "remove_presets", "role_tree",
    }
    if set(request) - allowed:
        raise ValueError("Unsupported settings request field.")
    current = organize_child_roles({}, cwd=root)
    before = _entries(current)
    if request["action"] == "read":
        return {"revision": current["revision"], "roles": before,
                "edges": current["edges"], "role_tree": current["role_tree"], "effect": EFFECT}
    if request.get("revision") != current["revision"]:
        raise ValueError(
            "Configuration changed while editing. Reload settings and reapply "
            "your changes; nothing was written."
        )
    edits = request.get("edits", {})
    renames = request.get("renames", {})
    if not isinstance(edits, dict) or not isinstance(renames, dict):
        raise ValueError("Role edits and names must be mappings.")
    change: dict = {"set_presets": {}, "unset_fields": {}, "rename_presets": renames}
    for reference, fields in edits.items():
        if not isinstance(fields, dict) or set(fields) - set(FIELDS):
            raise ValueError("Edit a role using the supported settings fields.")
        if any(value is not None and not isinstance(value, str) for value in fields.values()):
            raise ValueError("Role fields must contain text, or null to clear an optional field.")
        _check_connection(fields)
        change["set_presets"][reference] = {
            key: value for key, value in fields.items() if value is not None and not key.startswith("approval_")
        }
        change["unset_fields"][reference] = [key for key, value in fields.items()
                                             if value is None and not key.startswith("approval_")]
        approval_edits = {key.removeprefix("approval_"): value for key, value in fields.items()
                          if key.startswith("approval_")}
        if approval_edits:
            group, _, name = reference.rpartition(".")
            entries = current["roles"].get(group, {}) if group else current["roles"]
            codex = dict(entries.get(name, {}).get("codex", {}))
            approval = {**codex.get("approval", {}), **approval_edits}
            approval = {key: value for key, value in approval.items() if value is not None}
            if approval:
                codex["approval"] = approval
            else:
                codex.pop("approval", None)
            change["set_presets"][reference]["codex"] = codex
    for old, new in renames.items():
        if (old not in before and old not in edits) or not isinstance(new, str):
            raise ValueError("Rename a declared role to a valid role reference.")
    for field in ("add_edges", "remove_edges"):
        edges = request.get(field, [])
        if not isinstance(edges, list) or any(
            not isinstance(edge, dict) or set(edge) != {"parent", "child"}
            or any(not isinstance(value, str) for value in edge.values()) for edge in edges
        ):
            raise ValueError("Dispatch edges require parent and child role references.")
        change[field] = edges
    removed = request.get("remove_presets", [])
    if not isinstance(removed, list) or any(not isinstance(ref, str) or ref not in before for ref in removed):
        raise ValueError("Remove existing role references.")
    if set(removed) & (set(edits) | set(renames)):
        raise ValueError("A removed role cannot also be edited or renamed.")
    change["remove_presets"] = removed
    if "role_tree" in request:
        change["role_tree"] = request["role_tree"]
    after = _changed(
        {"roles": current["roles"], "role_tree": current["role_tree"]}, change,
    )
    roles = _validated(after)
    previous = _validated({"roles": current["roles"], "role_tree": current["role_tree"]})
    if set(removed) & set(roles.children) or set(roles.children) - set(previous.children) - set(roles.presets):
        raise ValueError("The role tree contains a dangling role reference.")
    for old in set(edits) | set(renames):
        reference = renames.get(old, old)
        preset = roles.preset(reference)
        if preset.runtime not in {"codex", "pi", "dsh"}:
            raise ValueError("Choose a supported Runtime: codex, pi or dsh.")
        # Reuse native prompt capability and instruction-file validation without
        # preparing a Runtime, reading credentials or launching any process.
        resolved = resolve_child_role(reference, preset, root)
        if preset.runtime == "codex":
            from graphtraj.runtimes.codex.codex_adapter import _resolve_codex_role

            _resolve_codex_role(resolved, root)
        efforts = {
            "codex": {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
            "pi": {"off", "minimal", "low", "medium", "high", "xhigh"},
            "dsh": {"off", "low", "high", "max"},
        }
        if preset.reasoning_effort is not None and preset.reasoning_effort not in efforts[preset.runtime]:
            raise ValueError(
                f"Unsupported reasoning effort for {preset.runtime}; "
                f"choose {', '.join(sorted(efforts[preset.runtime]))}."
            )
        if preset.runtime == "pi":
            provider, separator, model = preset.model.partition("/")
            if not separator or not provider or not model:
                raise ValueError("Pi model must be provider/model-id with a nonempty provider and model.")
            if (preset.base_url and not preset.connection) or preset.codex:
                raise ValueError(
                    "Pi requires native provider configuration; clear Base URL and "
                    "update incompatible Codex settings through the native role entry."
                )
        if preset.runtime == "dsh" and not preset.connection and preset.model not in {
            "deepseek-flash", "deepseek-official/deepseek-flash",
        }:
            raise ValueError("DSH requires deepseek-official/deepseek-flash.")
        if preset.runtime == "dsh" and (
            preset.codex or preset.allow_runtime_swarm
            or (not preset.connection and preset.base_url and urlsplit(preset.base_url).scheme != "https")
        ):
            raise ValueError(
                "DSH requires HTTPS and does not support Codex settings or native helpers. "
                "Update incompatible native role settings first."
            )

    def review(proposal: dict) -> dict:
        """Show only edited safe fields, never the full native role document."""
        return reviewer({
            "project": str(root), "edits": edits, "renames": renames,
            "before": {ref: {field: before.get(ref, {}).get(field) for field in fields}
                       for ref, fields in edits.items()},
            "add_edges": change["add_edges"], "remove_edges": change["remove_edges"],
            "remove_presets": removed,
            "tree_before": current["role_tree"], "tree_after": after["role_tree"],
            "effect": EFFECT,
        })

    if request["action"] == "preview":
        return {"revision": current["revision"], "roles": _entries({**after, "presets": roles.presets}),
                "role_tree": after["role_tree"], "effect": EFFECT, "applied": False}

    with recovery_review(review):
        result = organize_child_roles(
            {"change": change, "expected_revision": request["revision"]}, cwd=root,
        )
    if result.get("status") == "stale":
        raise ValueError("Configuration changed during approval. Reload settings; nothing was written.")
    return {"revision": result["revision"], "roles": _entries(result), "edges": result["edges"],
            "role_tree": result["role_tree"], "effect": EFFECT, "applied": result["applied"]}


def serve(input_stream: TextIO, output_stream: TextIO, cwd: Path) -> None:
    """Serve one settings call and an optional native host approval exchange."""
    def emit(value: dict) -> None:
        """Flush a bounded structured response to the owning desktop process."""
        output_stream.write(json.dumps(value) + "\n")
        output_stream.flush()

    def review(proposal: dict) -> dict:
        """Obtain the actual main-process dialog decision over the owned pipe."""
        emit({"review": proposal})
        reply = json.loads(input_stream.readline())
        if reply not in ({"decision": "accept"}, {"decision": "decline"}):
            raise ValueError("Native settings approval failed; nothing was written.")
        return reply

    try:
        request = json.loads(input_stream.readline())
        result = settings_request(request, cwd, review)
        emit({"result": result, "failed": False})
    except Exception as error:
        emit({"failed": True, "error": str(error)})
