"""Local Tasks back up one way to explicitly mapped GitHub Issues."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from graphtraj.graph.github_backup import _progress
from graphtraj.interfaces import gateway
from graphtraj.interfaces.cli import graphtraj

# A stand-in for ``gh api`` that keeps one repository's Issues in a JSON file.
# ``mode`` selects offline failure or a creation whose response is lost.
_FAKE_GH = '''
import json, os, sys
from urllib.parse import urlsplit, parse_qs

path  = os.environ["FAKE_GH_STATE"]
state = json.load(open(path))
args  = sys.argv[1:]
method, target = args[args.index("--method") + 1], args[args.index("--method") + 2]
payload = json.load(sys.stdin) if "--input" in args else None
state["requests"].append({"method": method, "target": target, "payload": payload,
                          "environment": dict(os.environ)})

def finish(document, code=0):
    json.dump(state, open(path, "w"))
    if code:
        sys.stderr.write(document)
    else:
        sys.stdout.write(json.dumps(document))
    sys.exit(code)

if state["mode"] == "offline":
    finish("error connecting to api.github.com", 1)
url    = urlsplit(target)
parts  = url.path.split("/")
issues = state["issues"]
if len(parts) == 6:
    # Sub-issue endpoints: GET .../{child}/parent and POST .../{parent}/sub_issues.
    parents = state.setdefault("parents", {})
    if method == "POST":
        child = next(issue for issue in issues if issue["id"] == payload["sub_issue_id"])
        assert str(child["number"]) not in parents, "GitHub rejects a second parent"
        parents[str(child["number"])] = int(parts[4])
        finish(next(issue for issue in issues if issue["number"] == int(parts[4])))
    if parts[4] not in parents:
        finish("gh: Not Found (HTTP 404)", 1)
    finish(next(issue for issue in issues if issue["number"] == parents[parts[4]]))
if method == "POST":
    number = max([issue["number"] for issue in issues] + [0]) + 1
    issue  = {"number": number, "id": 9000 + number, "node_id": "I_%d" % number,
              "html_url": "https://github.com/%s/%s/issues/%d" % (parts[1], parts[2], number),
              "title": payload["title"], "body": payload["body"], "state": "open"}
    issues.append(issue)
    if state["mode"] == "lose-create-response":
        state["mode"] = "online"
        finish("connection reset", 1)
    finish(issue)
if len(parts) == 4:
    query = parse_qs(url.query)
    assert query["state"] == ["all"] and query["since"]
    finish(sorted(issues, key=lambda issue: -issue["number"]))
issue = next(issue for issue in issues if issue["number"] == int(parts[4]))
if method == "PATCH":
    issue.update(payload)
finish(issue)
'''


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the fake ``gh`` with 42 unrelated Issues, including an external #42."""
    executable = tmp_path / "bin" / "gh"
    executable.parent.mkdir()
    executable.write_text("#!{0}\n{1}".format(sys.executable, _FAKE_GH), encoding="utf-8")
    executable.chmod(0o755)
    issues = [{
        "number": number, "id": number, "node_id": "X_%d" % number,
        "html_url": "https://github.com/owner/repo/issues/%d" % number,
        "title": "Backup this task" if number == 42 else "External bug %d" % number,
        "body": "Reported by a user.", "state": "open",
    } for number in range(1, 43)]
    path = tmp_path / "remote.json"
    path.write_text(json.dumps({"issues": issues, "mode": "online", "requests": []}))
    monkeypatch.setenv("FAKE_GH_STATE", str(path))
    monkeypatch.setenv("PATH", "{0}:{1}".format(executable.parent, "/usr/bin:/bin"))
    return path


@pytest.fixture
def project(temporary_git_repository: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a project with local Task 42 registered through the public entry."""
    project = temporary_git_repository
    config  = project / ".graphtraj" / "config.yml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({
        "version": 1,
        "paths": {"project_root": ".", "docs": "docs",
                  "agent_worktrees": ".graphtraj/worktrees", "state": ".graphtraj/state"},
        "agent_runner": {"dispatch_depth": 1, "max_concurrency": 2},
    }), encoding="utf-8")
    monkeypatch.chdir(project)
    _operate("task_register", _task())
    return project


def _task(**facts: Any) -> dict[str, Any]:
    """Return local Task 42's complete definition."""
    return {
        "task_id": "42", "task_name": "backup-this-task", "source": "local:42",
        "title": "Backup this task", "body": "Deliver the backup.\n", "dependencies": [],
        "schema_version": 2, "parent_id": None, "disposition": "active",
        "replaced_by": [], "retirement_reason": None, **facts,
    }


def _operate(feature: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one local public operation and require success."""
    result = gateway.handle_request({"action": "execute", "feature": feature, "arguments": arguments})
    assert not result.failed, result.document
    return result.document


def _revise(**facts: Any) -> None:
    """Revise local Task 42 from its current definition."""
    current = next(task for task in _operate("task_graph", {})["tasks"] if task["task_id"] == "42")
    _operate("task_revise", {
        "product_preserving": True, "caused_by_event_ids": [],
        "evidence_refs": ["README.md"],
        "tasks": [{**_task(**facts), "current_definition": current["current_definition"]}],
    })


def _backup(*options: str) -> tuple[int, dict[str, Any]]:
    """Run the public backup command and return its exit code and document."""
    result = CliRunner().invoke(graphtraj.main, ["task", "backup", "--task-id", "42", *options])
    return result.exit_code, yaml.safe_load(result.output.split("Error:")[0])


def _issues(remote: Path) -> dict[int, dict[str, Any]]:
    """Return the fake repository's Issues by number."""
    return {issue["number"]: issue for issue in json.loads(remote.read_text())["issues"]}


def _set_mode(remote: Path, mode: str) -> None:
    """Switch the fake remote between online, offline and lost creation responses."""
    document = json.loads(remote.read_text())
    document["mode"] = mode
    remote.write_text(json.dumps(document))


def test_backup_maps_task_42_to_a_new_remote_number_and_retries_idempotently(
    project: Path, remote: Path,
) -> None:
    """External #42 with the same title is neither matched nor modified."""
    external = _issues(remote)[42]

    code, created = _backup("--repository", "owner/repo")
    code_again, again = _backup("--repository", "owner/repo")

    assert (code, created["outcome"], code_again, again["outcome"]) == (0, "created", 0, "unchanged")
    backup = created["backup"]
    assert (backup["task_id"], backup["adapter"], backup["host"], backup["repository"]) == (
        "42", "github", "github.com", "owner/repo")
    assert backup["issue"] == {"number": 43, "id": 9043, "node_id": "I_43",
                               "url": "https://github.com/owner/repo/issues/43"}
    assert len(_issues(remote)) == 43 and _issues(remote)[42] == external
    stored = yaml.safe_load((project / ".graphtraj/state/task-backups.yml").read_text())
    assert stored["backups"] == [again["backup"]]

    # A second repository is a separate explicit mapping for the same Task.
    code, other = _backup("--repository", "owner/mirror")
    assert (code, other["outcome"], other["backup"]["repository"]) == (0, "created", "owner/mirror")
    assert len(yaml.safe_load((project / ".graphtraj/state/task-backups.yml").read_text())["backups"]) == 2


def test_retry_after_lost_creation_response_adopts_the_marked_issue(
    project: Path, remote: Path,
) -> None:
    """The creation intent is durable, so retrying finds the Issue instead of duplicating it."""
    _set_mode(remote, "lose-create-response")

    code, failed = _backup("--repository", "owner/repo")
    assert (code, failed["outcome"], failed["backup"]["issue"]) == (1, "failed", None)
    assert "connection reset" in failed["backup"]["last_error"]["message"]

    code, retried = _backup("--repository", "owner/repo")
    assert (code, retried["outcome"], retried["backup"]["issue"]["number"]) == (0, "created", 43)
    assert retried["backup"]["last_error"] is None
    assert len(_issues(remote)) == 43


def test_offline_backup_never_blocks_local_tasks_and_succeeds_after_recovery(
    project: Path, remote: Path,
) -> None:
    """Failures are recorded on the mapping; local operations continue unchanged."""
    _set_mode(remote, "offline")
    code, failed = _backup("--repository", "owner/repo")
    assert (code, failed["outcome"]) == (1, "failed")

    _operate("task_update", {"task_id": "42", "status": "ready", "active_team_ordinal": None,
                             "worktree": None, "branch": None, "current_candidate": None,
                             "caused_by_event_ids": [], "evidence_refs": ["README.md"]})
    stored = yaml.safe_load((project / ".graphtraj/state/task-backups.yml").read_text())
    assert "error connecting" in stored["backups"][0]["last_error"]["message"]

    _set_mode(remote, "online")
    code, recovered = _backup("--repository", "owner/repo")
    assert (code, recovered["outcome"]) == (0, "created")
    assert "- Status: ready" in _issues(remote)[43]["body"]
    assert len(_issues(remote)) == 43


def test_remote_edits_are_reported_and_only_overwritten_after_confirmation(
    project: Path, remote: Path,
) -> None:
    """Conflicts return differences; the local Task stays authoritative."""
    _backup("--repository", "owner/repo")
    document = json.loads(remote.read_text())
    edited   = next(issue for issue in document["issues"] if issue["number"] == 43)
    edited.update(title="Edited remotely", state="closed")
    remote.write_text(json.dumps(document))
    _revise(title="Backup this task locally")

    code, conflict = _backup("--repository", "owner/repo")
    assert (code, conflict["outcome"]) == (1, "conflict")
    assert conflict["differences"] == {
        "title": {"published": "Backup this task", "remote": "Edited remotely",
                  "local": "Backup this task locally"},
        "state": {"published": "open", "remote": "closed", "local": "open"},
    }
    local = next(task for task in _operate("task_graph", {})["tasks"] if task["task_id"] == "42")
    assert (local["title"], local["status"]) == ("Backup this task locally", "pending")
    assert _issues(remote)[43]["title"] == "Edited remotely"

    code, confirmed = _backup("--repository", "owner/repo",
                              "--confirm-remote", conflict["remote_digest"])
    assert (code, confirmed["outcome"]) == (0, "updated")
    assert (_issues(remote)[43]["title"], _issues(remote)[43]["state"]) == (
        "Backup this task locally", "open")

    # Cancelling the local Task closes its remote copy on the next backup.
    _revise(disposition="cancelled", retirement_reason="No longer needed.")
    code, closed = _backup("--repository", "owner/repo")
    assert (code, closed["outcome"], _issues(remote)[43]["state"]) == (0, "updated", "closed")


def test_backup_publishes_only_task_fields_without_credentials_or_sessions(
    project: Path, remote: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session files and token values in the environment never enter remote payloads."""
    monkeypatch.setenv("GITHUB_TOKEN", "token-value-never-published")
    session = project / ".graphtraj/state/sessions/one/session.sqlite3"
    session.parent.mkdir(parents=True)
    session.write_text("Session transcript never published")

    _backup("--repository", "owner/repo")

    requests = json.loads(remote.read_text())["requests"]
    payloads = [request["payload"] for request in requests if request["payload"] is not None]
    assert [set(payload) for payload in payloads] == [{"title", "body"}]
    published = json.dumps(payloads)
    assert "token-value-never-published" not in published
    assert "Session transcript" not in published
    assert payloads[0]["body"].endswith("---\n\nDeliver the backup.\n")
    # gh itself still receives the standard credential variable.
    assert requests[0]["environment"]["GITHUB_TOKEN"] == "token-value-never-published"


def _register_summary() -> None:
    """Register local summary 1 with children 2 and 3, where 3 depends on 2."""
    _operate("task_register", _task(task_id="1", task_name="summary", title="Summary"))
    _operate("task_register", _task(task_id="2", task_name="first", title="First", parent_id="1"))
    _operate("task_register", _task(task_id="3", task_name="second", title="Second",
                                    parent_id="1", dependencies=["2"]))


def _backup_task(task_id: str, *options: str) -> dict[str, Any]:
    """Back up one local Task to owner/repo and require success."""
    result = CliRunner().invoke(graphtraj.main, [
        "task", "backup", "--task-id", task_id, "--repository", "owner/repo", *options])
    assert result.exit_code == 0, result.output
    return yaml.safe_load(result.output)


def _sub_issue_writes(remote: Path) -> list[dict[str, Any]]:
    """Return the fake remote's Sub-issue creation requests."""
    return [request for request in json.loads(remote.read_text())["requests"]
            if request["target"].endswith("/sub_issues")]


def test_sub_issues_follow_mappings_not_local_ids_and_repeat_without_writes(
    project: Path, remote: Path,
) -> None:
    """Local 1/2/3 map to remote #44/#43/#45; repeated backups neither duplicate nor move."""
    _register_summary()

    child = _backup_task("2")
    assert child["hierarchy"] == [{"parent": "1", "child": "2", "outcome": "pending"}]
    summary = _backup_task("1")
    # Only the mapped child is linked; unmapped Task 3 gets no Issue.
    assert summary["hierarchy"] == [{"parent": "1", "child": "2", "outcome": "linked"}]
    assert len(_issues(remote)) == 44
    later = _backup_task("3")
    assert later["hierarchy"] == [{"parent": "1", "child": "3", "outcome": "linked"}]

    numbers = {task_id: _backup_task(task_id)["backup"]["issue"]["number"] for task_id in "123"}
    assert numbers == {"1": 44, "2": 43, "3": 45}
    assert json.loads(remote.read_text())["parents"] == {"43": 44, "45": 44}
    assert [request["payload"] for request in _sub_issue_writes(remote)] == [
        {"sub_issue_id": 9043}, {"sub_issue_id": 9045}]
    again = _backup_task("1")
    assert (again["outcome"], [entry["outcome"] for entry in again["hierarchy"]]) == (
        "unchanged", ["unchanged", "unchanged"])
    assert len(_sub_issue_writes(remote)) == 2 and len(_issues(remote)) == 45

    # The summary body follows local progress: cancelling 3 leaves one required child.
    body = _issues(remote)[44]["body"]
    assert "Integrated required children: 0 / 2" in body and "  T2 --> T3" in body
    assert "Legend:" in body and "#43" not in body
    _operate("task_revise", {
        "product_preserving": True, "caused_by_event_ids": [], "evidence_refs": ["README.md"],
        "tasks": [{**_task(task_id="3", task_name="second", title="Second", parent_id="1",
                           dependencies=["2"], disposition="cancelled",
                           retirement_reason="Not needed."),
                   "current_definition": next(task for task in _operate("task_graph", {})["tasks"]
                                              if task["task_id"] == "3")["current_definition"]}],
    })
    assert _backup_task("1")["outcome"] == "updated"
    body = _issues(remote)[44]["body"]
    assert "Integrated required children: 0 / 1" in body
    assert 'T3["➖ 3 Second<br/>cancelled"]' in body


def test_other_remote_parent_is_reported_and_never_moved_or_imported(
    project: Path, remote: Path,
) -> None:
    """A child already under external #1 keeps that parent; local records stay unchanged."""
    _register_summary()
    _backup_task("2")
    document = json.loads(remote.read_text())
    document["parents"] = {"43": 1}
    remote.write_text(json.dumps(document))

    summary = _backup_task("1")
    assert summary["hierarchy"] == [{
        "parent": "1", "child": "2", "outcome": "other-parent",
        "expected_parent_issue": 44, "remote_parent_issue": 1,
    }]
    assert _backup_task("2")["hierarchy"][0]["outcome"] == "other-parent"
    assert json.loads(remote.read_text())["parents"] == {"43": 1}
    assert _sub_issue_writes(remote) == []
    local = {task["task_id"]: task for task in _operate("task_graph", {})["tasks"]}
    assert (local["2"]["parent_id"], local["2"]["status"]) == ("1", "pending")


def test_progress_counts_only_active_children_and_marks_each_state() -> None:
    """Completed children count even when a current view would fold them; inputs are context only."""
    def record(title: str, status: str, disposition: str = "active",
               dependencies: tuple[str, ...] = ()) -> dict[str, Any]:
        return {"title": title, "status": status, "disposition": disposition,
                "dependencies": list(dependencies)}

    records = {
        "5": record("done", "integrated"), "6": record("old", "implementing", "superseded"),
        "7": record('new "x"', "reviewing", dependencies=("5", "99")), "8": record("wait", "ready"),
        "99": record("base", "integrated"),
    }
    lines = _progress(records, ["5", "6", "7", "8"])
    assert "Integrated required children: 1 / 3" in lines
    assert lines[lines.index("flowchart LR") + 1:lines.index("```", lines.index("flowchart LR"))] == [
        '  T99["✅ 99 base<br/>integrated"]',
        '  T5["✅ 5 done<br/>integrated"]', '  T6["➖ 6 old<br/>superseded"]',
        '  T7["🔄 7 new #quot;x#quot;<br/>reviewing"]', '  T8["⏳ 8 wait<br/>ready"]',
        "  T5 --> T7", "  T99 --> T7",
    ]
    assert _progress(records, []) == []
