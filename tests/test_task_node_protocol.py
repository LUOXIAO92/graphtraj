"""Task hierarchy and completion behavior through installed public entry points."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process
from test_ticket_graph import _configure


def task(ticket_id: str, parent: str | None = None, **changes: object) -> dict:
    """Build an explicit new-format task with a source independent of its ID."""
    return {
        "schema_version": 2, "ticket_id": ticket_id, "ticket_name": f"task-{ticket_id}",
        "source": f"local:requirement-{ticket_id}", "title": f"Outcome {ticket_id}",
        "body": f"Accept outcome {ticket_id}.\nPart of #999 is only prose.\n",
        "parent_id": parent, "dependencies": [], "disposition": "active",
        "replaced_by": [], "retirement_reason": None, **changes,
    }


class PublicProject:
    """Exercise one installed transport against an isolated project."""

    def __init__(self, root: Path, commands: InstalledCommands, transport: str) -> None:
        """Configure the test Harness and retain reusable acceptance evidence."""
        self.root = root
        self.commands = commands
        self.transport = transport
        self.state = _configure(root)
        (root / "evidence.md").write_text("The task owner checked the required scope.\n")

    def call(self, feature: str, arguments: dict, *, success: bool = True) -> dict:
        """Invoke the CLI, standalone Tool or MCP, checking the public outcome."""
        if self.transport == "cli":
            operation = feature.removeprefix("ticket_")
            argv = [str(self.commands.product), "ticket", operation]
            if operation == "graph":
                if arguments.get("schema"):
                    argv += ["--schema"]
            else:
                path = self.root / "request.yml"
                path.write_text(yaml.safe_dump(arguments))
                option = {"register": "ticket", "revise": "revision", "complete": "completion", "update": "state"}[operation]
                argv += [f"--{option}-file", str(path)]
            result = run_process(argv, cwd=self.root)
            assert (result.returncode == 0) is success, result.stderr + result.stdout
            return yaml.safe_load(result.stdout) if success else {"error": result.stderr}
        envelope = {"action": "execute", "feature": feature, "arguments": arguments}
        if self.transport == "tool":
            binary = self.commands.product.with_name("graphtraj-tool")
            request = envelope
        else:
            binary = self.commands.product.with_name("graphtraj-mcp")
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "graphtraj", "arguments": envelope}}
        import subprocess

        result = subprocess.run([str(binary)], input=json.dumps(request) + "\n",
                                cwd=self.root, text=True, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        response = json.loads(result.stdout)
        if self.transport == "tool":
            failed = response.get("failed", False)
            document = response.get("result", response)
        else:
            response = response["result"]
            failed = response["isError"]
            document = response.get("structuredContent", response)
        assert (not failed) is success, response
        return document

    def graph(self) -> dict[str, dict]:
        """Return publicly projected nodes by stable identity."""
        return {node["ticket_id"]: node for node in self.call("ticket_graph", {})["tickets"]}

    def revision(self, definitions: list[dict], **options: object) -> dict:
        """Bind each definition to the version observed through the public graph."""
        current = self.graph()
        return {"product_preserving": True, "caused_by_event_ids": [],
                "evidence_refs": ["evidence.md"],
                "tickets": [{**definition, "current_definition": current.get(definition["ticket_id"], {}).get("current_definition")}
                            for definition in definitions], **options}

    def complete(self, ticket_id: str, *, success: bool = True, **changes: object) -> dict:
        """Supply a task's own reason and the current immutable definition."""
        return self.call("ticket_complete", {
            "ticket_id": ticket_id, "current_definition": self.graph()[ticket_id]["current_definition"],
            "reason": "The owner accepts this task's outcome against its scope.",
            "cancelled_scope": {}, "caused_by_event_ids": [], "evidence_refs": ["evidence.md"],
            **changes,
        }, success=success)

    def retained(self) -> dict[str, bytes]:
        """Capture durable state to prove failed public calls wrote no facts."""
        return {path.relative_to(self.state).as_posix(): path.read_bytes()
                for path in self.state.rglob("*") if path.is_file() and path.name != ".lock"}


@pytest.fixture(params=["cli", "tool", "mcp"])
def public_project(request: pytest.FixtureRequest, temporary_git_repository: Path,
                   installed_commands: InstalledCommands) -> PublicProject:
    """Run the same Task contract through every user-facing transport."""
    return PublicProject(temporary_git_repository, installed_commands, request.param)


def test_task_protocol_completion_and_atomic_reopen(public_project: PublicProject) -> None:
    """Children enable acceptance; added work explicitly reopens every ancestor."""
    api = public_project
    api.call("ticket_register", task("1"))
    api.call("ticket_register", task("2", "1"))
    api.call("ticket_register", task("3", "2"))
    before = api.retained()
    api.complete("1", success=False)
    assert api.retained() == before
    api.complete("3")
    assert api.graph()["2"]["status"] == "pending"
    api.complete("2")
    api.complete("1")
    graph = api.graph()
    assert graph["1"]["children"] == ["2"]
    assert graph["1"]["progress"] == {"total": 1, "completed": 1}
    assert graph["3"]["parent_id"] == "2"
    assert graph["1"]["body"] == task("1")["body"]
    assert all(node["parent_known"] and node["schema_version"] == 2 for node in graph.values())
    assert all(node["current_candidate"] is None and node["active_team_ordinal"] is None
               and node["worktree"] is None for node in graph.values())
    receipt = next(fact for fact in graph["3"]["delivery"] if fact["ticket_id"] == "2")
    assert receipt["event"] == "ticket-completed"
    assert receipt["accepted_definition"] == graph["3"]["current_definition"]
    assert receipt["reason"] and receipt["evidence_refs"] == ["evidence.md"]
    before = api.retained()
    api.call("ticket_register", task("4", "2"), success=False)
    api.call("ticket_revise", api.revision([task("4", "2")]), success=False)
    api.call("ticket_revise", api.revision([task("2", "1"), task("4", "2")],
                                         reopen_ticket_ids=["2"]), success=False)
    assert api.retained() == before
    revision = api.revision([task("1"), task("2", "1"), task("4", "2")],
                            reopen_ticket_ids=["1", "2"])
    preview = api.call("ticket_revise", {**revision, "dry_run": True})
    assert preview["dry_run"] is True and api.retained() == before
    api.call("ticket_revise", revision)
    assert api.graph()["1"]["status"] == api.graph()["2"]["status"] == "pending"
    assert api.graph()["3"]["status"] == "integrated"
    assert api.graph()["1"]["delivery"] == api.graph()["2"]["delivery"] == []
    assert all(fact["ticket_id"] == "3" for fact in api.graph()["3"]["delivery"])
    api.complete("4")
    api.complete("2")
    api.complete("1")
    assert all(api.retained()[path] == content for path, content in before.items()
               if path.endswith(".md"))


def test_relationship_failures_and_replacement_chain(public_project: PublicProject) -> None:
    """Reject all edge cycles and dangling targets; retain replacement chains."""
    api = public_project
    for definition in [task("1"), task("2", "1"), task("3"), task("4")]:
        api.call("ticket_register", definition)
    before = api.retained()
    for definitions in [
        [task("2", "999")], [task("1", "2")],
        [task("2", "1", dependencies=["1"])],
        [task("2", "1", dependencies=["3"]), task("3", dependencies=["1"])],
        [task("3", dependencies=["4"]), task("4", dependencies=["3"])],
        [task("2", "1", disposition="superseded", replaced_by=["999"], retirement_reason="Moved")],
        [task("3", disposition="superseded", replaced_by=["4"], retirement_reason="Moved"),
         task("4", disposition="superseded", replaced_by=["3"], retirement_reason="Moved")],
        [task("3", disposition="cancelled")],
        [task("3", disposition="active", replaced_by=["4"])],
    ]:
        api.call("ticket_revise", api.revision(definitions), success=False)
        assert api.retained() == before
    api.call("ticket_revise", api.revision([
        task("2", "1", disposition="superseded", replaced_by=["3"], retirement_reason="Moved to 3"),
        task("3", disposition="superseded", replaced_by=["4"], retirement_reason="Moved to 4"),
    ]))
    api.complete("1", success=False)
    api.complete("4")
    api.complete("1")
    graph = api.graph()
    assert graph["2"]["replaced_by"] == ["3"] and graph["3"]["replaced_by"] == ["4"]
    assert graph["2"]["parent_id"] == "1" and graph["4"]["parent_id"] is None
    assert graph["1"]["progress"] == {"total": 1, "completed": 1}
    assert any(fact["ticket_id"] == "1" for fact in graph["4"]["delivery"])
    assert graph["2"]["delivery"] == []


def test_completed_inputs_can_be_recorded_without_reopening_accepted_scope(
    public_project: PublicProject,
) -> None:
    """An explicit evidenced correction preserves delivery and immutable history."""
    api = public_project
    for definition in [task("1"), task("2", "1"), task("3"), task("4")]:
        api.call("ticket_register", definition)
    for ticket_id in ["3", "2", "1"]:
        api.complete(ticket_id)
    before = api.retained()
    original = api.graph()
    corrected = task("2", "1", dependencies=["3"],
                     body=task("2")["body"] + "The accepted outcome already consumed result 3.")
    reason = {"2": "Owner verified the retained acceptance evidence: result 3 was already consumed."}
    revision = api.revision([corrected], completed_input_corrections=reason)

    # The ordinary product-preserving declaration is not a completion override.
    api.call("ticket_revise", api.revision([corrected]), success=False)
    for definitions, reasons in [
        ([task("2", "1", dependencies=["4"])], reason),
        ([task("2", "1", body="A new requirement")], reason),
        ([task("2", dependencies=["3"])], reason),
        ([corrected], {"2": " "}),
        ([corrected], {"999": "Unrelated declaration"}),
    ]:
        api.call("ticket_revise", api.revision(definitions, completed_input_corrections=reasons), success=False)
    assert api.retained() == before
    preview = api.call("ticket_revise", {**revision, "dry_run": True})
    assert preview["reopened_ticket_ids"] == [] and api.retained() == before
    event = api.call("ticket_revise", revision)
    assert event["completed_input_corrections"] == reason
    graph = api.graph()
    assert graph["2"]["dependencies"] == ["3"]
    assert graph["2"]["current_definition"] != original["2"]["current_definition"]
    for ticket_id in ["1", "2", "3"]:
        assert graph[ticket_id]["status"] == "integrated"
        assert graph[ticket_id]["current_candidate"] == original[ticket_id]["current_candidate"]
    assert all(api.retained()[path] == contents for path, contents in before.items() if path.endswith(".md"))

    retained = api.retained()
    # Neither removing old inputs nor adding unfinished work qualifies.
    api.call("ticket_revise", api.revision([task("2", "1", dependencies=["4"])],
                                         completed_input_corrections=reason), success=False)
    api.call("ticket_revise", api.revision([task("2", "1", dependencies=["3", "4"])],
                                         completed_input_corrections=reason), success=False)
    api.call("ticket_revise", api.revision([task("3")], reopen_ticket_ids=["3"],
                                         completed_input_corrections={"3": "No inputs added"}), success=False)
    assert api.retained() == retained


def test_cancellation_and_legacy_write_boundary(public_project: PublicProject) -> None:
    """Cancellation needs acceptance of withdrawn scope; old writes cannot erase v2."""
    api = public_project
    api.call("ticket_register", task("1"))
    api.call("ticket_register", task("2", "1"))
    api.call("ticket_revise", api.revision([
        task("2", "1", disposition="cancelled", retirement_reason="The owner withdrew this scope"),
    ]))
    before = api.retained()
    api.complete("1", success=False)
    api.complete("2", success=False)
    legacy = {key: task("1")[key] for key in ("ticket_id", "ticket_name", "source", "title", "body", "dependencies")}
    legacy["source"] = "https://github.com/example/project/issues/1"
    api.call("ticket_revise", {"product_preserving": True, "caused_by_event_ids": [],
                              "evidence_refs": ["evidence.md"],
                              "tickets": [{**legacy, "active": True, "replaced_by": []}]}, success=False)
    assert api.retained() == before
    api.complete("1", cancelled_scope={"2": "This scope was removed from the parent's accepted result."})
    assert api.graph()["2"]["disposition"] == "cancelled"
    assert api.graph()["2"]["status"] == "pending"
    assert api.graph()["1"]["progress"] == {"total": 1, "completed": 0}


def test_stale_versions_and_failed_completion_leave_state_unchanged(public_project: PublicProject) -> None:
    """Version checks, evidence checks and file-delivery guards precede mutation."""
    api = public_project
    api.call("ticket_register", task("1"))
    revision = api.revision([task("1", title="Revised outcome")])
    api.call("ticket_revise", revision)
    before = api.retained()
    api.call("ticket_register", task("2", body=(
        "---\ntask:\n  schema_version: 2\nexecution_budget: invalid\n---\nScope\n"
    )), success=False)
    api.call("ticket_revise", revision, success=False)
    api.complete("1", success=False, current_definition="ticket.md")
    api.complete("1", success=False, reason=" ")
    api.complete("1", success=False, evidence_refs=["absent.md"])
    assert api.retained() == before
    api.call("ticket_update", {"ticket_id": "1", "status": "ready", "active_team_ordinal": None,
                              "worktree": "actual-work", "branch": "actual-branch", "current_candidate": "a" * 40,
                              "caused_by_event_ids": [], "evidence_refs": ["evidence.md"]})
    before = api.retained()
    api.complete("1", success=False)
    assert api.retained() == before


def test_legacy_projection_upgrade_and_schema(public_project: PublicProject) -> None:
    """Native migration preserves historical bytes and marks unknown legacy facts."""
    api = public_project
    from test_ticket_graph import _ticket

    old = _ticket("1", "task-1")
    old["body"] = (
        "---\ntask:\n  schema_version: 2\n---\n"
        "Part of #90\nDeliver the existing task."
    )
    api.call("ticket_register", old)
    api.call("ticket_revise", {"product_preserving": True, "caused_by_event_ids": [],
                              "evidence_refs": ["evidence.md"],
                              "tickets": [{**old, "active": False, "replaced_by": []}]})
    legacy = api.graph()["1"]
    assert legacy["schema_version"] == 1 and legacy["parent_known"] is False
    assert legacy["disposition"] is None and "parent_id" not in legacy
    retained = api.retained()
    modern = task("1", source=old["source"], body=old["body"], disposition="cancelled",
                  retirement_reason="The owner confirmed the old inactive record was cancelled")
    revision = api.revision([modern])
    api.call("ticket_revise", {**revision, "dry_run": True})
    assert api.retained() == retained
    api.call("ticket_revise", revision)
    upgraded = api.graph()["1"]
    assert upgraded["schema_version"] == 2 and upgraded["parent_known"] is True
    assert upgraded["disposition"] == "cancelled" and upgraded["status"] == legacy["status"]
    assert all(api.retained()[path] == content for path, content in retained.items() if path.endswith(".md"))
    before = api.retained()
    api.call("ticket_revise", {"product_preserving": True, "caused_by_event_ids": [],
                              "evidence_refs": ["evidence.md"],
                              "tickets": [{**old, "active": True, "replaced_by": []}]}, success=False)
    assert api.retained() == before
    schema = api.call("ticket_graph", {"schema": True})
    assert set(upgraded) == set(schema["properties"])
    assert set(schema["required"]) <= set(upgraded)
    for missing in ("parent_id", "disposition", "retirement_reason", "schema_version"):
        malformed = task("2")
        malformed.pop(missing)
        api.call("ticket_register", malformed, success=False)
    assert api.retained() == before


def test_reopening_replacement_and_cancelled_scope_requires_ancestor_acceptance(
    public_project: PublicProject,
) -> None:
    """Cross-parent replacement results and withdrawn scope affect acceptance."""
    api = public_project
    for definition in [task("1"), task("2", "1"), task("3")]:
        api.call("ticket_register", definition)
    replaced = task("2", "1", disposition="superseded", replaced_by=["3"], retirement_reason="Delivered elsewhere")
    api.call("ticket_revise", api.revision([replaced]))
    api.complete("3")
    api.complete("1")
    before = api.retained()
    api.call("ticket_revise", api.revision([task("3")], reopen_ticket_ids=["3"]), success=False)
    assert api.retained() == before
    api.call("ticket_revise", api.revision([task("1"), task("3")], reopen_ticket_ids=["1", "3"]))
    api.complete("3")
    api.complete("1")
    cancelled = task("4", "1", disposition="cancelled", retirement_reason="Withdrawn before implementation")
    before = api.retained()
    api.call("ticket_register", cancelled, success=False)
    assert api.retained() == before
    api.call("ticket_revise", api.revision([task("1"), cancelled], reopen_ticket_ids=["1"]))
    api.complete("1", success=False)
    api.complete("1", cancelled_scope={"4": "Explicitly withdraw the newly recorded scope"})


def test_migration_restores_tickets_when_worldline_append_is_refused(
    public_project: PublicProject,
) -> None:
    """A failed append restores migrated and newly created Tickets on every entry."""
    import os

    from test_ticket_graph import _ticket

    api = public_project
    old = _ticket("1", "task-1")
    api.call("ticket_register", old)
    api.call("ticket_update", {
        "ticket_id": "1", "status": "ready", "active_team_ordinal": None,
        "worktree": "retained-work", "branch": "retained-branch",
        "current_candidate": "a" * 40, "caused_by_event_ids": [],
        "evidence_refs": ["evidence.md"],
    })
    before = api.retained()
    original = api.graph()
    revision = api.revision([
        task("2"),
        task("1", "2", source=old["source"], body=original["1"]["body"]),
    ])
    api.call("ticket_revise", {**revision, "dry_run": True})
    assert api.retained() == before

    shard = next((api.state / "worldline").glob("*.jsonl"))
    mode = shard.stat().st_mode
    shard.chmod(0o444)
    try:
        if os.access(shard, os.W_OK):
            pytest.skip("This environment cannot deny writes with file permissions")
        api.call("ticket_revise", revision, success=False)
        assert api.retained() == before
        assert api.graph() == original
    finally:
        shard.chmod(mode)

    api.call("ticket_revise", revision)
    migrated = api.graph()
    assert migrated["1"]["parent_id"] == "2"
    for field in ("status", "worktree", "branch", "current_candidate"):
        assert migrated["1"][field] == original["1"][field]
    retained = api.retained()
    assert all(retained[path] == content for path, content in before.items()
               if path.endswith(".md"))
    api.call("ticket_revise", revision, success=False)
    assert api.retained() == retained


def test_cancelled_replacement_acceptance_survives_unrelated_revision(public_project: PublicProject) -> None:
    """A withdrawn replacement scope remains accepted until that scope changes."""
    api = public_project
    for definition in [task("1"), task("2", "1"), task("3")]:
        api.call("ticket_register", definition)
    api.call("ticket_revise", api.revision([
        task("2", "1", disposition="superseded", replaced_by=["3"], retirement_reason="Reassigned"),
        task("3", disposition="cancelled", retirement_reason="The whole replacement scope was withdrawn"),
    ]))
    api.complete("1", success=False)
    api.complete("1", cancelled_scope={"3": "The replacement scope has been explicitly withdrawn"})
    api.call("ticket_register", task("4"))
    assert api.graph()["1"]["status"] == "integrated"
    before = api.retained()
    api.call("ticket_revise", api.revision([task("3")]), success=False)
    assert api.retained() == before
    api.call("ticket_revise", api.revision([task("1"), task("3")], reopen_ticket_ids=["1"]))
    api.complete("1", success=False)
