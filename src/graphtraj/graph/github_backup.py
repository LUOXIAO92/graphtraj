"""One-way backup of local Tasks to explicitly mapped GitHub Issues.

The local Task is the only authority. A backup publishes its explicit
definition and state fields to one mapped Issue and never reads remote fields
back into the Task graph. Mappings live in ``<state>/task-backups.yml``::

    task_id:    "42"            # local Task identity
    adapter:    github
    host:       github.com      # GitHub service address used by ``gh``
    repository: owner/name
    marker:     <random hex>    # embedded in the Issue body; identifies our creation
    issue:      {number, id, node_id, url} | null
    published:  {title, body, state} | null   # remote copy after our last write
    pending_since: <UTC time a creation was first attempted>
    last_error:   {at, message} | null
    last_published_at: <UTC time> | null

A Task with local children also publishes integrated / required child counts
and a dependency DAG of its children. After publishing, the Issue is attached
as a real Sub-issue to its mapped parent, and its mapped children to it;
endpoints are resolved only through mappings, unmapped ones are reported as
pending and a child already under another parent is reported, never moved.

Remote requests use the installed ``gh api`` command, so its existing login or
the standard ``GH_TOKEN`` / ``GITHUB_TOKEN`` variables supply credentials and
this module never handles a token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from graphtraj import file_lock
from graphtraj.graph.task_graph import read_graph

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_HOST       = re.compile(r"[A-Za-z0-9.-]+(?::\d+)?\Z")
_FIELDS     = ("title", "body", "state")


class RemoteError(Exception):
    """A GitHub request did not complete; local Tasks are unaffected."""


def gh_api(host: str, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    """Send one REST request through ``gh api`` and return its decoded JSON.

    Raises
    ------
    RemoteError
        When ``gh`` is missing, times out, or reports a failed request.
    """
    command = ["gh", "api", "--hostname", host, "--method", method, path]
    if payload is not None:
        command += ["--input", "-"]
    try:
        completed = subprocess.run(
            command,
            input          = json.dumps(payload) if payload is not None else None,
            capture_output = True,
            text           = True,
            timeout        = 60,
            check          = False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RemoteError(f"gh api {method} {path} failed: {error}") from error
    if completed.returncode != 0:
        message = (completed.stderr.strip() or completed.stdout.strip())[-500:]
        raise RemoteError(f"gh api {method} {path} failed: {message}")
    return json.loads(completed.stdout)


def backup_task(
    state: Path,
    task_id: str,
    repository: str,
    host: str = "github.com",
    confirm_remote: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Publish one local Task to its mapped GitHub Issue, creating it once.

    Parameters
    ----------
    state
        The project's Harness State Directory.
    task_id, repository, host
        The local Task and the explicit remote target; together they select
        one mapping.
    confirm_remote
        ``remote_digest`` from a reported conflict. The Agent supplies it after
        reviewing the differences (and revising the local Task if needed) to
        publish over exactly that observed remote copy.

    Returns
    -------
    tuple
        The result document and whether the backup failed. ``outcome`` is
        ``created``, ``updated``, ``unchanged``, ``conflict`` or ``failed``.
    """
    if _REPOSITORY.fullmatch(repository) is None or _HOST.fullmatch(host) is None:
        raise ValueError("repository must be owner/name and host a GitHub host name")
    # Unregistered Tasks raise the same ValueError from the graph query.
    graph   = read_graph(state, "full", details=[task_id])
    task    = graph["details"][task_id]
    records = {record["task_id"]: record for record in graph["tasks"]}

    descriptor = os.open(str(state / ".task-backups.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    file_lock.flock(descriptor, file_lock.LOCK_EX)
    try:
        backups = _load(state)
        mapping = next((item for item in backups if (
            item["task_id"], item["host"], item["repository"]) == (task_id, host, repository)), None)
        retry   = mapping is not None
        if mapping is None:
            mapping = {
                "task_id": task_id, "adapter": "github", "host": host, "repository": repository,
                "marker": secrets.token_hex(16), "issue": None, "published": None,
                "pending_since": _now(), "last_error": None, "last_published_at": None,
            }
            backups.append(mapping)

            # Persist the creation intent first so a retry looks for this marker
            # instead of creating a second Issue.
            _save(state, backups)
        desired = _render(task, mapping["marker"], records)
        try:
            outcome, conflict = _publish(mapping, desired, retry, confirm_remote)
            hierarchy = [] if conflict is not None else _link(backups, mapping, records)
        except RemoteError as error:
            mapping["last_error"] = {"at": _now(), "message": str(error)}
            _save(state, backups)
            return {"outcome": "failed", "error": str(error), "backup": mapping}, True
        if conflict is not None:
            mapping["last_error"] = {"at": _now(), "message": "remote Issue changed since the last backup"}
            _save(state, backups)
            return {"outcome": "conflict", **conflict, "backup": mapping}, True
        mapping.update(last_error=None, last_published_at=_now())
        _save(state, backups)
        return {"outcome": outcome, "hierarchy": hierarchy, "backup": mapping}, False
    finally:
        file_lock.flock(descriptor, file_lock.LOCK_UN)
        os.close(descriptor)


def _publish(
    mapping: dict[str, Any],
    desired: dict[str, str],
    retry: bool,
    confirm_remote: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """Create or update the mapped Issue; return the outcome or a conflict report."""
    host, base = mapping["host"], "repos/{0}/issues".format(mapping["repository"])
    outcome    = "updated"
    if mapping["issue"] is None:
        outcome = "created"
        found   = _find_created(mapping) if retry else None
        posted  = found is None
        if posted:
            found = gh_api(host, "POST", base, {"title": desired["title"], "body": desired["body"]})
        mapping["issue"] = {
            "number": found["number"], "id": found["id"],
            "node_id": found["node_id"], "url": found["html_url"],
        }
        mapping["published"] = _content(found)

        # A fresh open Issue already matches; an adopted one may predate local edits.
        if posted and desired["state"] == "open":
            return outcome, None

    remote = gh_api(host, "GET", "{0}/{1}".format(base, mapping["issue"]["number"]))
    if mapping["issue"]["node_id"] is None:
        # One-time imported mappings know the confirmed URL/number, not an
        # invented object ID or a full published baseline. Read only that Issue.
        if (remote.get("number") != mapping["issue"]["number"]
                or remote.get("html_url") != mapping["issue"]["url"]
                or type(remote.get("id")) is not int
                or not isinstance(remote.get("node_id"), str) or not remote["node_id"]):
            raise RemoteError("the imported Issue URL does not match the remote object")
        mapping["issue"].update(id=remote["id"], node_id=remote["node_id"])
    if remote["node_id"] != mapping["issue"]["node_id"]:
        raise RemoteError("the mapped Issue number now refers to a different remote object")
    current = _content(remote)
    digest  = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
    published = mapping["published"] or {}
    if current != mapping["published"] and confirm_remote != digest:
        return "conflict", {
            "remote_digest": digest,
            "differences": {
                field: {"published": published.get(field), "remote": current[field],
                        "local": desired[field]}
                for field in _FIELDS if current[field] != published.get(field)
            },
        }
    if current == desired:
        mapping["published"] = current
        return ("unchanged" if outcome == "updated" else outcome), None
    patched = gh_api(host, "PATCH", "{0}/{1}".format(base, mapping["issue"]["number"]), desired)
    mapping["published"] = _content(patched)
    return outcome, None


def _link(
    backups: list[dict[str, Any]],
    mapping: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the mapped Issue to its mapped parent and its mapped children as Sub-issues.

    Remote Issues are resolved only through mappings of the same host and
    repository. A child already under another parent is reported, never moved;
    an unmapped endpoint is reported as pending.
    """
    def mapped(key: str | None) -> dict[str, Any] | None:
        return next((item["issue"] for item in backups if item["issue"] is not None and (
            item["task_id"], item["host"], item["repository"]) == (
            key, mapping["host"], mapping["repository"])), None)

    task_id = mapping["task_id"]
    pairs   = [(records[task_id]["parent_id"], task_id)] if records[task_id]["parent_id"] else []
    pairs  += [(task_id, child) for child in records[task_id]["children"] if mapped(child)]
    host, base = mapping["host"], "repos/{0}/issues".format(mapping["repository"])
    report  = []
    for parent_id, child_id in pairs:
        parent, child = mapped(parent_id), mapped(child_id)
        entry = {"parent": parent_id, "child": child_id}
        report.append(entry)
        if parent is None:
            entry["outcome"] = "pending"
            continue
        try:
            current = gh_api(host, "GET", "{0}/{1}/parent".format(base, child["number"]))["number"]
        except RemoteError as error:
            if "HTTP 404" not in str(error):
                raise
            current = None
        if current is None:
            gh_api(host, "POST", "{0}/{1}/sub_issues".format(base, parent["number"]),
                   {"sub_issue_id": child["id"]})
            entry["outcome"] = "linked"
        elif current == parent["number"]:
            entry["outcome"] = "unchanged"
        else:
            entry.update(outcome="other-parent", expected_parent_issue=parent["number"],
                         remote_parent_issue=current)
    return report


def _find_created(mapping: dict[str, Any]) -> dict[str, Any] | None:
    """Find the Issue an interrupted attempt created, by its unique body marker only."""
    # ponytail: one page of 100 recent Issues; page further if a repository
    # receives more than that within the hour before a retried creation.
    since = datetime.fromisoformat(mapping["pending_since"]) - timedelta(hours=1)
    path  = "repos/{0}/issues?state=all&sort=created&direction=desc&per_page=100&since={1}".format(
        mapping["repository"], since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    line  = _marker_line(mapping)
    for issue in gh_api(mapping["host"], "GET", path):
        if "pull_request" not in issue and line in (issue.get("body") or "").splitlines():
            return issue
    return None


def _render(
    task: dict[str, Any], marker: str, records: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Build the remote copy from explicit Task definition and state fields only."""
    body = "\n".join([
        _marker_line({"marker": marker, "task_id": task["task_id"]}),
        "Backup of local GraphTraj Task {0} (`{1}`). The local Task is authoritative; "
        "remote edits are not imported.".format(task["task_id"], task["task_name"]),
        "",
        "- Status: {0}".format(records[task["task_id"]]["status"]),
        "- Disposition: {0}".format(task["disposition"]),
        "- Parent: {0}".format(task["parent_id"] or "none"),
        "- Dependencies: {0}".format(", ".join(task["dependencies"]) or "none"),
        "- Replaced by: {0}".format(", ".join(task["replaced_by"]) or "none"),
        *_progress(records, records[task["task_id"]]["children"]),
        "",
        "---",
        "",
        task["body"],
    ])
    closed = task["status"] == "integrated" or not task["active"]
    return {"title": task["title"], "body": body, "state": "closed" if closed else "open"}


_MARKS = {"integrated": "✅", "pending": "⏳", "ready": "⏳", "blocked": "⛔", "escalated": "⛔"}


def _progress(records: dict[str, dict[str, Any]], children: list[str]) -> list[str]:
    """Render a summary's child progress and dependency DAG from local state only."""
    if not children:
        return []
    # Required children are the active ones; superseded or cancelled children
    # are shown but not counted, and their replacements are counted instead.
    required   = [key for key in children if records[key]["disposition"] == "active"]
    integrated = [key for key in required if records[key]["status"] == "integrated"]
    lines = ["", "## Progress", "",
             "Integrated required children: {0} / {1}".format(len(integrated), len(required)),
             "", "```mermaid", "flowchart LR"]
    # External prerequisites appear as context nodes; they are not counted.
    inputs = [source for key in children for source in records[key]["dependencies"]
              if source not in children]
    for key in dict.fromkeys([*inputs, *children]):
        record = records[key]
        state  = record["status"] if record["disposition"] == "active" else record["disposition"]
        mark   = _MARKS.get(state, "🔄") if record["disposition"] == "active" else "➖"
        lines.append('  T{0}["{1} {0} {2}<br/>{3}"]'.format(
            key, mark, record["title"].replace('"', "#quot;"), state))
    lines += ["  T{0} --> T{1}".format(source, key)
              for key in children for source in records[key]["dependencies"]]
    return lines + [
        "```", "",
        "Legend: ✅ integrated · 🔄 in progress (implementing, reviewing, reworking or "
        "integrating) · ⏳ pending or ready · ⛔ blocked or escalated · ➖ not required "
        "(superseded or cancelled). An arrow points from a dependency to the Task that needs it.",
    ]


def _marker_line(mapping: dict[str, Any]) -> str:
    """Return the hidden body line identifying this mapping's created Issue."""
    return "<!-- graphtraj-task-backup task={0} marker={1} -->".format(
        mapping["task_id"], mapping["marker"])


def _content(issue: dict[str, Any]) -> dict[str, str]:
    """Return the published fields of one remote Issue, normalizing line endings."""
    return {"title": issue["title"], "body": (issue.get("body") or "").replace("\r\n", "\n"),
            "state": issue["state"]}


def _load(state: Path) -> list[dict[str, Any]]:
    """Read the project's mapping list; a missing file means no mappings."""
    path = state / "task-backups.yml"
    if not path.is_file():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8"))["backups"]


def _save(state: Path, backups: list[dict[str, Any]]) -> None:
    """Atomically replace the mapping list."""
    path      = state / "task-backups.yml"
    temporary = path.with_name(".task-backups.yml.tmp")
    temporary.write_text(yaml.safe_dump({"backups": backups}, sort_keys=False), encoding="utf-8")
    os.replace(temporary, path)


def _now() -> str:
    """Return the current UTC time in ISO 8601 form."""
    return datetime.now(timezone.utc).isoformat()
