"""Progressive disclosure and strict execution through the shared gateway."""

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces import gateway, tools


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list:
    """Give one existing registry entry controlled material and an observable handler."""
    calls = []

    def handler(arguments: Mapping[str, Any], *, cwd: Path | None = None) -> tools.ToolResult:
        """Record exactly what the operation receives from the gateway."""
        calls.append((dict(arguments), cwd))
        return tools.ToolResult({"received": dict(arguments)})

    (tmp_path / "manual.txt").write_text("Selected fixture manual", encoding="utf-8")
    # A relative reference resolves to the delivered data location, so point
    # that location at the fixture material instead of a cwd guess.
    monkeypatch.setattr(gateway, "delivered_manuals_root", lambda: tmp_path)
    monkeypatch.setitem(tools.TOOLS, "alias_status", replace(
        tools.TOOLS["alias_status"], handler=handler, manual_ref="manual.txt",
        examples=({"aliases": ["child"]},),
    ))
    return calls


def test_disclosure_reads_only_selected_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: list,
) -> None:
    """Discovery omits schemas; describe reads exactly the selected registered file."""
    reads = []
    read_text = Path.read_text

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        """Record reads without replacing actual manual loading."""
        reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    found = gateway.handle_request({"action": "discover", "query": "ALIAS_STATUS"})
    assert found.document["features"] == [{
        "feature": "alias_status", "description": tools.TOOLS["alias_status"].description,
    }]
    assert reads == []
    assert not gateway.handle_request({"action": "discover", "query": "unmatched fixture"}).document["features"]

    described = gateway.handle_request({"action": "describe", "feature": "alias_status"}, cwd=tmp_path)
    assert not described.failed
    assert described.document["manual"] == "Selected fixture manual"
    assert described.document["input_schema"] == tools.TOOLS["alias_status"].input_schema
    assert described.document["examples"] == [{"aliases": ["child"]}]
    assert described.document["call"] == {"action": "execute", "feature": "alias_status", "arguments": {}}
    assert reads == [tmp_path / "manual.txt"]
    assert feature == []


def test_describe_tracks_single_source_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: list) -> None:
    """Later material and schema edits appear without a parallel help catalog."""
    (tmp_path / "manual.txt").write_text("Updated fixture", encoding="utf-8")
    schema = {"type": "object", "properties": {"sample": {"type": "string"}},
              "required": ["sample"], "additionalProperties": False}
    monkeypatch.setitem(tools.TOOLS, "alias_status", replace(tools.TOOLS["alias_status"], input_schema=schema))
    described = gateway.handle_request({"action": "describe", "feature": "alias_status"}, cwd=tmp_path)
    assert described.document["manual"] == "Updated fixture"
    assert described.document["input_schema"] == schema
    assert gateway.handle_request({"action": "execute", "feature": "alias_status", "arguments": {}}).failed
    result = gateway.handle_request({"action": "execute", "feature": "alias_status", "arguments": {"sample": "new"}}, cwd=tmp_path)
    assert result.document == {"received": {"sample": "new"}}


@pytest.mark.parametrize("arguments, field", [
    ({"aliases": "child"}, "aliases"),
    ({"aliases": [17]}, "aliases[0]"),
    ({"operation_total": 1}, "operation_total"),
    ({"baseline": False}, "baseline"),
    ({"actor": "Main"}, "actor"),
    ({"caller": "parent"}, "caller"),
    ({"cwd": "/tmp"}, "cwd"),
    ({"allowed_features": ["ticket_update"]}, "allowed_features"),
    ({"_meta": {"threadId": "parent"}}, "_meta"),
])
def test_selected_validation_rejects_wrong_types_and_context(
    feature: list, arguments: dict, field: str,
) -> None:
    """Model arguments cannot smuggle trusted context or bypass selected types."""
    result = gateway.handle_request({"action": "execute", "feature": "alias_status", "arguments": arguments})
    assert result.failed
    assert field in result.document["error"]
    assert set(result.document) == {"feature", "error"}
    assert feature == []


@pytest.mark.parametrize("envelope", [
    [], {}, {"action": "other"}, {"action": "describe"},
    {"action": "execute", "feature": "alias_status"},
    {"action": "execute", "feature": "alias_status", "arguments": []},
    {"action": "describe", "feature": "alias_status", "arguments": {}},
    {"action": "discover", "feature": "alias_status"},
    {"action": "discover", "query": 3},
    {"action": "discover", "caller": "Main"},
])
def test_invalid_envelope_is_a_local_failure(envelope: Any, feature: list) -> None:
    """Bad envelopes fail locally and never execute operations."""
    result = gateway.handle_request(envelope)
    assert result.failed
    assert set(result.document) == {"error"}
    assert feature == []


@pytest.mark.parametrize("name, arguments, field", [
    ("send_instruction", {"alias": "child"}, "instruction"),
    ("swarm", {"tasks": [{"role": "engineer", "caller": "Main"}]}, "tasks[0].caller"),
    ("swarm", {"tasks": [{"role": 1}]}, "tasks[0].role"),
    ("submit_result", {"commit": "abc", "completion": "done", "result_refs": []}, "result_refs"),
    ("decide_result", {"submission_id": "a", "commit": "abc", "decision": "maybe", "reason": "x", "evidence_refs": ["x"]}, "decision"),
    ("ticket_revise", {"product_preserving": 1, "caused_by_event_ids": [], "evidence_refs": [], "tickets": []}, "product_preserving"),
])
def test_real_selected_constraints(name: str, arguments: dict, field: str) -> None:
    """Nested, required, enum, const and cardinality constraints reject before execution."""
    result = gateway.handle_request({"action": "execute", "feature": name, "arguments": arguments})
    assert result.failed
    assert field in result.document["error"]


def test_missing_manual_does_not_gate_direct_core_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real graph reads work without describe or material, and help changes no files."""
    config = tmp_path / ".graphtraj/config.yml"
    config.parent.mkdir()
    config.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.setitem(tools.TOOLS, "ticket_graph", replace(tools.TOOLS["ticket_graph"], manual_ref="absent.txt"))
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    direct = gateway.handle_request({"action": "execute", "feature": "ticket_graph", "arguments": {}}, cwd=tmp_path)
    assert not direct.failed
    described = gateway.handle_request({"action": "describe", "feature": "ticket_graph"}, cwd=tmp_path)
    assert described.failed
    assert "absent.txt" in described.document["error"]
    assert described.document["input_schema"] == tools.TOOLS["ticket_graph"].input_schema
    assert gateway.handle_request({"action": "execute", "feature": "ticket_graph", "arguments": {}}, cwd=tmp_path) == direct
    assert gateway.handle_request({"action": "discover"}, cwd=tmp_path).document["features"]
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after


def test_delivered_guide_resolution_is_independent_of_the_process_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relative reference resolves to delivered data; absence is reported and never gates execution."""
    configuration = tmp_path / ".graphtraj/config.yml"
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    monkeypatch.setattr(
        gateway, "delivered_manuals_root", lambda: tmp_path / "delivered-material",
    )

    described = gateway.handle_request(
        {"action": "describe", "feature": "task-breakdown"}, cwd=tmp_path,
    )
    assert described.failed
    assert described.document["manual"] is None
    assert described.document["call"] is None
    assert "Cannot read manual manuals/task-breakdown/guide.md" in described.document["error"]

    refused = gateway.handle_request(
        {"action": "execute", "feature": "task-breakdown", "arguments": {}},
    )
    assert refused.failed
    assert refused.document == {"error": "Feature is not executable: task-breakdown"}

    executed = gateway.handle_request(
        {"action": "execute", "feature": "ticket_graph", "arguments": {}},
        cwd=tmp_path,
    )
    assert executed.document == {"tickets": []}


def test_method_only_rows_use_guide_names_and_frontmatter_descriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each method-only row is the delivered guide: same name, description and text."""
    monkeypatch.setattr(gateway, "delivered_manuals_root", lambda: REPOSITORY_ROOT)

    assert set(tools.METHOD_FEATURE_NAMES) == {
        "setup-project", "task-breakdown", "task-delivery", "research",
        "concept-clarification",
    }
    for name in tools.METHOD_FEATURE_NAMES:
        guide = REPOSITORY_ROOT / "manuals" / name / "guide.md"
        frontmatter = yaml.safe_load(guide.read_text(encoding="utf-8").split("---", 2)[1])
        row = tools.TOOLS[name]

        assert row.handler is None
        assert row.manual_ref == f"manuals/{name}/guide.md"
        assert row.description == frontmatter["description"]
        assert {entry["feature"] for entry in gateway.handle_request(
            {"action": "discover", "query": name}).document["features"]} == {name}

        described = gateway.handle_request({"action": "describe", "feature": name})
        assert not described.failed
        assert described.document["manual"] == guide.read_text(encoding="utf-8")
        assert described.document["call"] is None
        assert gateway.handle_request(
            {"action": "execute", "feature": name, "arguments": {}}).failed


def test_unknown_method_only_and_host_restriction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: list) -> None:
    """Unknown and method-only execution fail without invoking a handler."""
    monkeypatch.setitem(tools.TOOLS, "fixture_method", replace(tools.TOOLS["alias_status"], name="fixture_method", handler=None))
    described = gateway.handle_request({"action": "describe", "feature": "fixture_method"}, cwd=tmp_path)
    assert not described.failed
    assert described.document["call"] is None
    for name in ("unknown", "fixture_method"):
        result = gateway.handle_request({"action": "execute", "feature": name, "arguments": {}})
        assert result.failed
        assert name in result.document["error"]
    assert gateway.handle_request({"action": "describe", "feature": "unknown"}).failed
    assert gateway.handle_request({"action": "execute", "feature": "alias_status", "arguments": {}}, allowed_features=[]).failed
    assert gateway.handle_request({"action": "describe", "feature": "alias_status"}, allowed_features=[]).failed
    assert gateway.handle_request({"action": "discover"}, allowed_features=[]).document["features"] == []
    assert feature == []


def test_handler_result_and_business_rejection_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway neither reinterprets operation results nor replaces authorization."""
    expected = tools.ToolResult({"status": "stopped", "evidence_refs": ["retained"]}, failed=True)

    def handler(arguments: Mapping[str, Any]) -> tools.ToolResult:
        """Use the original no-cwd convention and return retained business state."""
        return expected

    monkeypatch.setitem(tools.TOOLS, "ticket_graph", replace(tools.TOOLS["ticket_graph"], handler=handler))
    request = {"action": "execute", "feature": "ticket_graph", "arguments": {}}
    assert gateway.handle_request(request) is expected

    def denied(arguments: Mapping[str, Any]) -> tools.ToolResult:
        """Represent the existing business authorization boundary."""
        raise PermissionError("not the parent")

    monkeypatch.setitem(tools.TOOLS, "ticket_graph", replace(tools.TOOLS["ticket_graph"], handler=denied))
    with pytest.raises(PermissionError, match="not the parent"):
        gateway.handle_request(request)


def test_nullable_and_empty_values_keep_schema_semantics(tmp_path: Path, feature: list) -> None:
    """Valid explicit nulls and false values reach the handler without conversion."""
    arguments = {"aliases": [], "baseline": None, "candidate": "", "operation_total": False}
    assert not gateway.handle_request({"action": "execute", "feature": "alias_status", "arguments": arguments}, cwd=tmp_path).failed
    assert feature == [(arguments, tmp_path)]


@pytest.mark.parametrize("material", [None, "invalid-utf8", "directory"])
def test_unavailable_material_is_reported_only_by_describe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: list, material: str | None,
) -> None:
    """Missing references, decode errors and directories cannot gate execution."""
    path = tmp_path / "bad-material"
    if material == "invalid-utf8":
        path.write_bytes(b"\xff")
    elif material == "directory":
        path.mkdir()
    reference = str(path) if material is not None else None
    monkeypatch.setitem(tools.TOOLS, "alias_status", replace(
        tools.TOOLS["alias_status"], manual_ref=reference,
    ))
    described = gateway.handle_request(
        {"action": "describe", "feature": "alias_status"}, cwd=tmp_path,
    )
    assert described.failed
    assert described.document["manual"] is None
    assert (reference or "alias_status") in described.document["error"]
    assert not gateway.handle_request(
        {"action": "execute", "feature": "alias_status", "arguments": {}},
        cwd=tmp_path,
    ).failed
    assert feature == [({}, tmp_path)]


def test_outer_schema_is_fixed_and_describe_accepts_absolute_manual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: list,
) -> None:
    """New registry rows require no catalog expansion in the initial schema."""
    from copy import deepcopy

    initial = deepcopy(gateway.INPUT_SCHEMA)
    monkeypatch.setitem(tools.TOOLS, "fixture_added", replace(
        tools.TOOLS["alias_status"], name="fixture_added",
        manual_ref=str(tmp_path / "manual.txt"),
    ))
    discovered = gateway.handle_request({"action": "discover", "query": "fixture_added"})
    assert discovered.document["features"][0]["feature"] == "fixture_added"
    assert gateway.INPUT_SCHEMA == initial
    assert set(initial["properties"]) == {"action", "query", "feature", "arguments"}
    assert initial["properties"]["feature"] == {"type": "string"}
    assert initial["properties"]["arguments"] == {"type": "object"}
    described = gateway.handle_request({"action": "describe", "feature": "fixture_added"})
    assert described.document["manual"] == "Selected fixture manual"
    assert feature == []


def test_unsupported_schema_constraint_fails_closed(
    monkeypatch: pytest.MonkeyPatch, feature: list,
) -> None:
    """A future schema constraint cannot be silently ignored during execution."""
    monkeypatch.setitem(tools.TOOLS, "alias_status", replace(
        tools.TOOLS["alias_status"], input_schema={"type": "object", "not": {}},
    ))
    result = gateway.handle_request({
        "action": "execute", "feature": "alias_status", "arguments": {},
    })
    assert result.failed
    assert "schema constraint" in result.document["error"]
    assert feature == []
