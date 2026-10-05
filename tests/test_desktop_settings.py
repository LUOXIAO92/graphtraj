"""Human desktop settings through the public restricted native pipe."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import yaml

from graphtraj.execution.runner_status import runtime_caller
from graphtraj.interfaces.desktop_settings import serve
from test_role_organization import project, roles_path, snapshot


def call(root: Path, request: dict, decision: str = "decline") -> list[dict]:
    """Exchange one settings request and a controlled host review reply."""
    output = io.StringIO()
    serve(io.StringIO(json.dumps(request) + "\n" + json.dumps({"decision": decision}) + "\n"), output, root)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def read(root: Path) -> dict:
    """Read the exact safe editable view from the native desktop entry."""
    reply = call(root, {"action": "read"})[-1]
    assert reply["failed"] is False, reply
    return reply["result"]


def draft(root: Path, **fields: object) -> dict:
    """Create a draft against the currently observed revision."""
    return {"action": "save", "revision": read(root)["revision"], "edits": {"analyst": fields}}


def test_save_preserves_unedited_fields_secrets_and_other_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A native save changes only requested fields and exposes no stored key."""
    document = yaml.safe_load(roles_path(project).read_text())
    document["roles"]["analyst"]["codex"] = {
        "future_extension": {"api_key": "hidden-existing-value"},
        "approval": {"model": "review-model", "base_url": "https://example.invalid/v1", "api_key_env": "REVIEW_KEY"},
    }
    roles_path(project).write_text(yaml.safe_dump(document))
    monkeypatch.setenv("ENGINEER_KEY", "never-render-this-secret")
    before = snapshot(project)
    request = draft(project, model="edited-model", base_url="https://example.invalid/v1", api_key_env="NEW_KEY", reasoning_effort="medium")
    replies = call(project, request, "accept")
    assert replies[0]["review"]["before"]["analyst"]["model"] == "analyst-model"
    assert replies[-1]["result"]["applied"] is True
    assert "hidden-existing-value" not in json.dumps(replies)
    assert "never-render-this-secret" not in json.dumps(replies)
    after = snapshot(project)
    assert {name for name in before if before[name] != after[name]} == {".graphtraj/roles.yml"}
    saved = yaml.safe_load(roles_path(project).read_text())
    assert saved["roles"]["coding_team"] == document["roles"]["coding_team"]
    assert saved["roles"]["analyst"]["codex"] == document["roles"]["analyst"]["codex"]
    assert saved["role_tree"] == document["role_tree"]


@pytest.mark.parametrize("decision", ["decline", "invalid-reply"])
def test_denial_or_review_failure_keeps_original(project: Path, decision: str) -> None:
    """Native review refusal and malformed replies never save the draft."""
    before = snapshot(project)
    replies = call(project, draft(project, model="rejected-model"), decision)
    assert "review" in replies[0]
    assert replies[-1]["failed"] is True
    assert snapshot(project) == before


def test_revision_conflict_before_and_during_review(project: Path) -> None:
    """External changes are detected at both draft and approval boundaries."""
    stale = draft(project, model="stale-draft")
    assert call(project, draft(project, model="external-native-change"), "accept")[-1]["result"]["applied"]
    before = snapshot(project)
    replies = call(project, stale, "accept")
    assert len(replies) == 1 and replies[0]["failed"]
    assert "changed while editing" in replies[0]["error"]
    assert snapshot(project) == before

    class ExternalChange(io.StringIO):
        """Apply a second native save when the first host receives its review."""

        def write(self, text: str) -> int:
            """Change through the public entry before returning approval."""
            if "review" in json.loads(text):
                call(project, draft(project, model="changed-during-review"), "accept")
            return super().write(text)

    output = ExternalChange()
    serve(io.StringIO(json.dumps(draft(project, model="must-not-win")) + '\n{"decision":"accept"}\n'), output, project)
    assert "changed during approval" in output.getvalue()
    assert read(project)["roles"]["analyst"]["model"] == "changed-during-review"


@pytest.mark.parametrize("fields", [
    {"runtime": "pi", "model": "provider/model", "developer_prompt": "unsupported"},
    {"api_key_env": "sk-plaintext-secret"},
    {"base_url": "https://user:secret@example.invalid/v1"},
    {"model": ""}, {"runtime": "unknown"}, {"reasoning_effort": "impossible"},
    {"instructions": "missing-instructions.txt"}, {"api_key": "not-supported"},
])
def test_invalid_drafts_fail_before_review(project: Path, fields: dict) -> None:
    """Invalid settings and unsupported prompt layers fail without side effects."""
    before = snapshot(project)
    replies = call(project, draft(project, **fields), "accept")
    assert len(replies) == 1 and replies[0]["failed"]
    assert "sk-plaintext-secret" not in json.dumps(replies)
    assert "user:secret" not in json.dumps(replies)
    assert snapshot(project) == before


def test_native_prompt_clear_rename_and_nested_edges(project: Path) -> None:
    """Renaming arbitrary grouped roles preserves nested trees and role fields."""
    path = roles_path(project)
    document = yaml.safe_load(path.read_text())
    document["roles"]["coding_team"]["engineer"]["developer_prompt"] = "old layer"
    document["role_tree"] = {"owner": {"coding_team.team_leader": {"coding_team.engineer": {"analyst": {}}}}}
    path.write_text(yaml.safe_dump(document))
    request = {"action": "save", "revision": read(project)["revision"],
               "edits": {"coding_team.engineer": {"developer_prompt": None}},
               "renames": {"coding_team.engineer": "research.builder"},
               "remove_edges": [{"parent": "coding_team.engineer", "child": "analyst"}]}
    reply = call(project, request, "accept")[-1]
    assert reply["failed"] is False, reply
    saved = yaml.safe_load(path.read_text())
    assert saved["roles"]["research"]["builder"] == {"runtime": "codex", "model": "engineer-model", "api_key_env": "ENGINEER_KEY"}
    assert saved["role_tree"] == {"owner": {"coding_team.team_leader": {"research.builder": {}}}}


def test_agent_caller_and_fabricated_approval_are_rejected(project: Path) -> None:
    """A desktop flag or request field cannot elevate an actual Agent caller."""
    request = draft(project, model="forbidden")
    before = snapshot(project)
    with runtime_caller(project / ".graphtraj" / "runner", "actual-agent"):
        assert call(project, {"action": "read"})[-1]["failed"]
        assert call(project, request, "accept")[-1]["failed"]
    request["decision"] = "accept"
    assert call(project, request, "accept")[-1]["failed"]
    assert snapshot(project) == before


def test_concurrent_approved_saves_do_not_overwrite_one_another(project: Path) -> None:
    """Two reviews of the same revision can commit only one candidate."""
    barrier = Barrier(2, timeout=5)
    revision = read(project)["revision"]

    class SimultaneousReview(io.StringIO):
        """Hold both host reviews until each candidate has been prepared."""

        def write(self, text: str) -> int:
            """Release both native operations from their review boundary."""
            if "review" in json.loads(text):
                barrier.wait()
            return super().write(text)

    def save(model: str) -> dict:
        """Use one owned native pipe for each independently approved draft."""
        request = {"action": "save", "revision": revision, "edits": {"analyst": {"model": model}}}
        output = SimultaneousReview()
        serve(io.StringIO(json.dumps(request) + '\n{"decision":"accept"}\n'), output, project)
        return json.loads(output.getvalue().splitlines()[-1])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ("first-model", "second-model")))
    assert sorted(result["failed"] for result in results) == [False, True]
    successful = next(result["result"] for result in results if not result["failed"])
    assert read(project)["roles"] == successful["roles"]
