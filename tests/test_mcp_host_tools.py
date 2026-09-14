"""Behavior of the installed MCP tool entry point and its Codex host client."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process
from runner_fixtures import configure_harness
from test_ticket_graph import _configure, _ticket, _write


TOOL_NAMES = {
    "alias_status",
    "continue",
    "dispatch",
    "interrupt",
    "pending_requests",
    "reply_to_request",
    "send_instruction",
    "ticket_graph",
    "ticket_register",
    "ticket_revise",
    "ticket_update",
}
VOLATILE_EVENT_KEYS = {
    "event_id", "captured_at", "definition_refs", "evidence_refs",
}


class McpServerProcess:
    """Drive the installed MCP server over its newline-delimited stdio seam."""

    def __init__(
        self,
        executable: Path,
        project_root: Path,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.process = subprocess.Popen(
            [str(executable)],
            cwd=project_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.sequence = 0

    def __enter__(self) -> "McpServerProcess":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def request(self, method: str, params: dict | None = None) -> dict:
        """Send one JSON-RPC request and return its single response message."""

        self.sequence += 1
        message = {
            "jsonrpc": "2.0",
            "id":      self.sequence,
            "method":  method,
            "params":  params if params is not None else {},
        }
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def notify(self, method: str, params: dict | None = None) -> None:
        """Send one JSON-RPC notification, which has no response."""

        self.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
            + "\n"
        )
        self.process.stdin.flush()

    def call(self, name: str, arguments: dict) -> dict:
        """Call one tool and return its JSON-RPC result or error message."""

        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait(timeout=30)
        assert self.process.returncode == 0, self.process.stderr.read()


@pytest.fixture
def mcp_executable(installed_commands: InstalledCommands) -> Path:
    return installed_commands.product.with_name("graphtraj-mcp")


def _cli(
    installed_commands: InstalledCommands, project: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return run_process(
        [str(installed_commands.product), *arguments], cwd=project
    )


def _runner(
    installed_commands: InstalledCommands,
    project: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # The invoking Agent's Codex Session must not bind the test Runner process.
    inherited = {
        name: value
        for name, value in (os.environ if environment is None else environment).items()
        if name != "CODEX_THREAD_ID"
    }
    return run_process(
        [str(installed_commands.runner), *arguments],
        cwd=project,
        env=inherited,
    )


def _started_mcp(
    mcp_executable: Path,
    project: Path,
    environment: dict[str, str] | None = None,
) -> McpServerProcess:
    server = McpServerProcess(mcp_executable, project, environment)
    initialized = server.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities":    {},
            "clientInfo":      {"name": "graphtraj-test", "version": "0.0.0"},
        },
    )
    assert initialized["result"]["serverInfo"]["name"] == "graphtraj"
    assert initialized["result"]["capabilities"] == {"tools": {}}
    server.notify("notifications/initialized")
    return server


def _stable_event(document: dict) -> dict:
    return {
        key: value
        for key, value in document.items()
        if key not in VOLATILE_EVENT_KEYS
    }


def test_installed_mcp_server_discovers_tools_and_reads_the_same_graph_as_the_cli(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """A host can discover every tool and read the project graph by structure."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)
    registered = _cli(
        installed_commands,
        project,
        "ticket",
        "register",
        "--ticket-file",
        str(_write(project / "issue.yml", _ticket("73", "shared-graph"))),
    )
    assert registered.returncode == 0, registered.stderr

    with _started_mcp(mcp_executable, project) as server:
        listed = server.request("tools/list")["result"]["tools"]
        assert {tool["name"] for tool in listed} == TOOL_NAMES
        assert all(
            tool["inputSchema"]["type"] == "object"
            and tool["description"]
            for tool in listed
        )

        call = server.call("ticket_graph", {})
        assert call["result"]["isError"] is False
        graph = _cli(installed_commands, project, "ticket", "graph")
        assert graph.returncode == 0, graph.stderr
        assert call["result"]["structuredContent"] == yaml.safe_load(graph.stdout)
        assert call["result"]["structuredContent"]["tickets"] == [{
            "ticket_id":    "73",
            "ticket_name":  "shared-graph",
            "status":       "pending",
            "active":       True,
            "ready":        True,
            "dependencies": [],
            "replaced_by":  [],
        }]
        # The rendered text is the CLI's own YAML for the same document.
        assert call["result"]["content"][0]["text"] == graph.stdout


def test_installed_mcp_server_submits_the_same_graph_operations_as_the_cli(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Register, revise and update through the host match the CLI outcomes."""

    host_project = tmp_path / "host-project"
    cli_project = tmp_path / "cli-project"
    for project in (host_project, cli_project):
        project.mkdir()
        _configure(project)
        (project / "evidence.md").write_text("Validated.\n", encoding="utf-8")
    issue = _ticket("73", "shared-graph")
    dependent = _ticket("74", "second-graph", dependencies=["73"])
    revision = {
        "product_preserving":  True,
        "caused_by_event_ids": [],
        "evidence_refs":       ["evidence.md"],
        "tickets":             [
            {**_ticket("74", "second-graph"), "active": True, "replaced_by": []}
        ],
    }
    change = {
        "ticket_id":           "74",
        "status":              "ready",
        "active_team_ordinal": None,
        "worktree":            None,
        "branch":              None,
        "current_candidate":   None,
        "caused_by_event_ids": [],
        "evidence_refs":       ["evidence.md"],
    }

    host_directories = []
    with _started_mcp(mcp_executable, host_project) as server:
        for definition in (issue, dependent):
            registered = server.call("ticket_register", definition)["result"]
            assert registered["isError"] is False
            host_directories.append(
                Path(registered["structuredContent"]["ticket_directory"])
            )
        revised = server.call("ticket_revise", revision)["result"]
        assert revised["isError"] is False
        updated = server.call("ticket_update", change)["result"]
        assert updated["isError"] is False
        host_graph = server.call("ticket_graph", {})["result"]["structuredContent"]

    for definition, host_directory in zip((issue, dependent), host_directories):
        cli_registered = _cli(
            installed_commands,
            cli_project,
            "ticket",
            "register",
            "--ticket-file",
            str(_write(cli_project / "issue.yml", definition)),
        )
        assert cli_registered.returncode == 0, cli_registered.stderr
        assert host_directory.relative_to(host_project) == Path(
            cli_registered.stdout.strip()
        ).relative_to(cli_project)
    cli_revised = _cli(
        installed_commands,
        cli_project,
        "ticket",
        "revise",
        "--revision-file",
        str(_write(cli_project / "revision.yml", revision)),
    )
    assert cli_revised.returncode == 0, cli_revised.stderr
    cli_updated = _cli(
        installed_commands,
        cli_project,
        "ticket",
        "update",
        "--state-file",
        str(_write(cli_project / "change.yml", change)),
    )
    assert cli_updated.returncode == 0, cli_updated.stderr
    cli_graph = _cli(installed_commands, cli_project, "ticket", "graph")
    assert cli_graph.returncode == 0, cli_graph.stderr

    assert set(revised["structuredContent"]) == set(yaml.safe_load(cli_revised.stdout))
    assert _stable_event(revised["structuredContent"]) == _stable_event(
        yaml.safe_load(cli_revised.stdout)
    )
    assert set(updated["structuredContent"]) == set(yaml.safe_load(cli_updated.stdout))
    assert _stable_event(updated["structuredContent"]) == _stable_event(
        yaml.safe_load(cli_updated.stdout)
    )
    assert host_graph == yaml.safe_load(cli_graph.stdout)
    assert [ticket["status"] for ticket in host_graph["tickets"]] == [
        "pending", "ready",
    ]


def test_installed_mcp_server_reports_the_same_alias_status_as_the_cli(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Alias queries reuse the D.2.2 status operation and its document."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)

    with _started_mcp(mcp_executable, project) as server:
        call = server.call("alias_status", {"aliases": ["missing@l1"]})["result"]

    assert call["isError"] is True
    cli = _runner(installed_commands, project, "status", "missing@l1")
    assert cli.returncode == 1
    assert call["structuredContent"] == yaml.safe_load(cli.stdout)
    assert call["structuredContent"]["aliases"][0]["error"]["code"] == "alias-not-found"


def test_installed_mcp_server_reports_invalid_input_and_unknown_requests(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Rejected operations keep their message instead of becoming empty results."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)
    invalid = {"ticket_id": "74"}

    with _started_mcp(mcp_executable, project) as server:
        rejected = server.call("ticket_register", invalid)["result"]
        unknown_tool = server.call("ticket_send", {})
        unknown_method = server.request("resources/list", {})

    cli = _cli(
        installed_commands,
        project,
        "ticket",
        "register",
        "--ticket-file",
        str(_write(project / "invalid.yml", invalid)),
    )
    assert cli.returncode == 1
    assert rejected["isError"] is True
    assert rejected["content"][0]["text"] in cli.stderr
    assert unknown_tool["error"]["code"] == -32602
    assert unknown_method["error"]["code"] == -32601


def test_installed_mcp_server_survives_a_rejected_alias_status_call(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """An incomplete Git diagnostics pair is a tool failure, not a crash."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)

    with _started_mcp(mcp_executable, project) as server:
        rejected = server.call(
            "alias_status", {"aliases": ["missing@l1"], "baseline": "abc123"}
        )["result"]
        # The same process must keep serving the other tools afterwards.
        after = server.call("ticket_graph", {})["result"]

    cli = _runner(
        installed_commands,
        project,
        "status",
        "missing@l1",
        "--baseline",
        "abc123",
    )
    assert cli.returncode == 1
    assert rejected["isError"] is True
    assert rejected["content"][0]["text"] == yaml.safe_load(cli.stdout)["error"]["message"]
    assert after["isError"] is False
    assert after["structuredContent"] == {"tickets": []}


def test_installed_mcp_server_reports_a_missing_project_root_like_the_graph_tools(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """A status query outside a Harness Project Root fails like the graph tools."""

    plain = tmp_path / "plain"
    plain.mkdir()

    with _started_mcp(mcp_executable, plain) as server:
        status = server.call("alias_status", {"aliases": ["missing@l1"]})["result"]
        graph = server.call("ticket_graph", {})["result"]

    cli = _cli(installed_commands, plain, "ticket", "graph")
    assert cli.returncode == 1
    message = cli.stderr.strip().removeprefix("Error: ")
    assert status["isError"] is True
    assert graph["isError"] is True
    assert status["content"][0]["text"] == message
    assert graph["content"][0]["text"] == message


@dataclass(frozen=True)
class ManagedMcp:
    """An installed MCP server over a project whose Runtime is a controlled peer."""

    root: Path
    cause: str
    server: McpServerProcess
    environment: dict[str, str]

    def call(self, name: str, arguments: dict) -> dict:
        """Call one execution or interaction tool and return its MCP result."""

        return self.server.call(name, arguments)["result"]

    def document(self, name: str, arguments: dict) -> dict:
        """Call one tool that must succeed and return its structured document."""

        result = self.call(name, arguments)
        assert result["isError"] is False, result
        return result["structuredContent"]


def _inline_task(instruction: str = "hold") -> dict:
    """Select the existing inline temporary role for the registered task."""

    return {
        "ticket_id":   "113",
        "ticket_name": "managed-probe",
        "role":        {
            "managed-probe": {
                "runtime":          "codex",
                "model":            "gpt-5.6",
                "reasoning_effort": "low",
            }
        },
        "instruction": instruction,
    }


def _observe(
    managed: ManagedMcp,
    alias: str,
    activity: str,
    outcome: str | None = None,
    waiting_for: str | None = None,
    timeout: float = 10,
) -> dict:
    """Wait for an observable execution state through the host tool alone."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = managed.document("alias_status", {"aliases": [alias]})["aliases"][0]
        if (
            status.get("activity") == activity
            and (outcome is None or status.get("last_outcome") == outcome)
            and (waiting_for is None or status.get("waiting_for") == waiting_for)
        ):
            return status
        time.sleep(0.02)
    raise AssertionError(status)


@pytest.fixture
def managed_mcp(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> Iterator[ManagedMcp]:
    """Configure a project and dispatch its controlled Runtime through MCP.

    Only the Runtime executable's model work is substituted, exactly like
    ``tests/test_managed_sessions.py``; the installed MCP server, the Runner and
    the Codex Adapter stay real. The invoking Agent's Codex Session must not bind
    the server or its workers.
    """

    from graphtraj.graph.delivery_worldline import append_project_worldline_event
    from graphtraj.graph.ticket_graph import register_ticket

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    state = root / ".graphtraj/state"
    register_ticket(state, root, _ticket("113", "managed-probe"))
    (root / "instruction.md").write_text(
        "Exercise the dispatched child.\n", encoding="utf-8"
    )
    cause = append_project_worldline_event(state, root, {
        "kind":                "main-decision",
        "decision":            "Exercise the dispatched child.",
        "caused_by_event_ids": [],
        "evidence_refs":       ["instruction.md"],
    })["event_id"]
    fake_codex.executable.write_text(
        "#!" + sys.executable + "\n"
        + Path(__file__).with_name("managed_codex_peer.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_codex.executable.chmod(0o755)
    environment.update(
        {
            "MANAGED_NATIVE_ROOT": str(tmp_path / "native"),
            "CODEX_HOME":          str(tmp_path / "codex-home"),
        }
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("CODEX_THREAD_ID", None)

    with _started_mcp(mcp_executable, root, environment) as server:
        managed = ManagedMcp(
            root=root, cause=cause, server=server, environment=environment
        )
        yield managed
        for mapping in (root / ".graphtraj/runner/sessions").glob("*/mapping.yml"):
            # Leave no controlled execution running behind the fixture.
            server.call("interrupt", {"alias": mapping.parent.name})


def test_installed_mcp_server_dispatches_and_controls_a_managed_child(
    installed_commands: InstalledCommands, managed_mcp: ManagedMcp
) -> None:
    """A host dispatches one managed child and controls it by its identity."""

    root, cause = managed_mcp.root, managed_mcp.cause
    dispatched = managed_mcp.document("dispatch", {"tasks": [_inline_task()]})
    assert set(dispatched) == {"retained_batch_file", "tasks"}
    task, = dispatched["tasks"]
    assert task["launch_status"] == "launched"
    assert task["ticket_id"] == "113"
    assert task["role"] == "managed-probe"
    alias, session = task["alias"], task["session"]
    assert Path(dispatched["retained_batch_file"]).is_file()

    running = _observe(managed_mcp, alias, "running")
    assert running["alias"] == alias
    assert running["session"] == session
    assert running["execution_id"]
    # The same identity is readable through the CLI the user already uses.
    cli = _runner(
        installed_commands, root, "status", alias, environment=managed_mcp.environment
    )
    assert cli.returncode == 0, cli.stderr
    assert managed_mcp.document("alias_status", {"aliases": [alias]}) == (
        yaml.safe_load(cli.stdout)
    )

    # An explicit instruction from the user reaches the owned execution.
    sent = managed_mcp.document(
        "send_instruction",
        {"alias": alias, "instruction": "unhandled request",
         "caused_by_event_ids": [cause]},
    )
    assert sent == {"alias": alias, "send_status": "sent"}

    # The native approval request returns through the one interaction path.
    _observe(managed_mcp, alias, "running", waiting_for="runtime-request")
    queried = managed_mcp.document("pending_requests", {"alias": alias})
    cli_query = _runner(
        installed_commands, root, "requests", alias,
        "--execution-id", queried["execution_id"],
        environment=managed_mcp.environment,
    )
    assert cli_query.returncode == 0, cli_query.stderr
    assert queried == yaml.safe_load(cli_query.stdout)
    request, = queried["requests"]
    assert request["request_id"] == "approval"
    replied = managed_mcp.document(
        "reply_to_request",
        {"alias": alias, "request": request, "response": {"decision": "accept"}},
    )
    assert replied == {
        "alias":        alias,
        "session":      session,
        "execution_id": request["execution_id"],
        "request_id":   "approval",
        "reply_status": "submitted",
    }
    completed = _observe(managed_mcp, alias, "idle", "completed")
    assert completed["execution_id"] == request["execution_id"]
    from graphtraj.execution.runner_status import read_alias_mapping
    from graphtraj.runtimes.codex.codex_adapter import read_codex_last_agent_message

    mapping, _ = read_alias_mapping(root / ".graphtraj/runner", alias)
    assert read_codex_last_agent_message(Path(mapping["trace_file"])) == "approval:accept"

    # A stale reply is rejected by the shared operation, not by this tool.
    stale = managed_mcp.call(
        "reply_to_request",
        {"alias": alias, "request": request, "response": {"decision": "accept"}},
    )
    request_file = _write(root / "request.yml", request)
    cli_stale = _runner(
        installed_commands, root, "reply", alias, "--request-file", str(request_file),
        "--response", '{"decision": "accept"}',
        environment=managed_mcp.environment,
    )
    assert cli_stale.returncode == 1
    assert stale["isError"] is True
    assert stale["content"][0]["text"] == yaml.safe_load(cli_stale.stdout)["error"]["message"]

    # The same identity addresses a second waiting execution and its interrupt.
    managed_mcp.document(
        "send_instruction",
        {"alias": alias, "instruction": "request:approval",
         "caused_by_event_ids": [cause]},
    )
    active = _observe(managed_mcp, alias, "running", waiting_for="runtime-request")
    assert active["execution_id"] != completed["execution_id"]
    assert managed_mcp.document("interrupt", {"alias": alias}) == {
        "alias": alias, "interrupt_status": "interrupted",
    }
    after = _observe(managed_mcp, alias, "idle", "interrupted")
    assert after["execution_id"] == active["execution_id"]
    assert after["session"] == session
    assert managed_mcp.document("pending_requests", {"alias": alias})["requests"] == []

    # Equivalent instructions return the same document from both interfaces.
    cli_sent = _runner(
        installed_commands, root, "send", alias, "--instruction", "hold",
        "--caused-by-event-id", cause,
        environment=managed_mcp.environment,
    )
    assert cli_sent.returncode == 0, cli_sent.stderr
    _observe(managed_mcp, alias, "running")
    assert managed_mcp.document(
        "send_instruction",
        {"alias": alias, "instruction": "hold", "caused_by_event_ids": [cause]},
    ) == yaml.safe_load(cli_sent.stdout)
    _observe(managed_mcp, alias, "idle", "completed")
    second = managed_mcp.call("interrupt", {"alias": alias})
    cli_second = _runner(
        installed_commands, root, "interrupt", alias,
        environment=managed_mcp.environment,
    )
    assert cli_second.returncode == 1
    assert second["isError"] is True
    assert second["content"][0]["text"] == yaml.safe_load(cli_second.stdout)["error"]["message"]


def test_installed_mcp_server_rejects_execution_input_like_the_cli(
    installed_commands: InstalledCommands, managed_mcp: ManagedMcp
) -> None:
    """Rejected dispatch, control and interaction calls keep the CLI's message."""

    root, cause = managed_mcp.root, managed_mcp.cause
    empty_batch = _write(root / "empty-batch.yml", {"tasks": []})
    unregistered = _write(
        root / "unregistered-batch.yml", {"tasks": [_inline_task() | {"ticket_id": "999"}]}
    )
    stale_request = _write(root / "stale-request.yml", {"alias": "missing@l1"})
    cases = (
        ("dispatch", {"tasks": []}, ["--batch-input", str(empty_batch)]),
        ("dispatch", {"tasks": [_inline_task() | {"ticket_id": "999"}]},
         ["--batch-input", str(unregistered)]),
        ("send_instruction", {"alias": "missing@l1", "instruction": "steer",
                              "caused_by_event_ids": []},
         ["send", "missing@l1", "--instruction", "steer"]),
        ("interrupt", {"alias": "missing@l1"}, ["interrupt", "missing@l1"]),
        ("pending_requests", {"alias": "missing@l1"}, ["requests", "missing@l1"]),
        ("reply_to_request", {"alias": "missing@l1", "request": {"alias": "missing@l1"},
                              "response": {}},
         ["reply", "missing@l1", "--request-file", str(stale_request),
          "--response", "{}"]),
        ("continue", {"ticket_id": "113", "caused_by_event_ids": [cause]},
         ["continue", "--ticket-id", "113", "--caused-by-event-id", cause]),
        ("continue", {"ticket_id": "999", "caused_by_event_ids": [cause]},
         ["continue", "--ticket-id", "999", "--caused-by-event-id", cause]),
        ("continue", {"ticket_id": "113", "caused_by_event_ids": []},
         ["continue", "--ticket-id", "113", "--caused-by-event-id", ""]),
    )

    for tool, arguments, cli_arguments in cases:
        result = managed_mcp.call(tool, arguments)
        cli = _runner(
            installed_commands, root, *cli_arguments,
            environment=managed_mcp.environment,
        )
        assert result["isError"] is True, (tool, result)
        assert cli.returncode == 1, (tool, cli.stderr)
        assert result["content"][0]["text"] == (
            yaml.safe_load(cli.stdout)["error"]["message"]
        ), tool

    # The server keeps serving the same project after rejected calls.
    cli_missing = _runner(
        installed_commands, root, "status", "missing@l1",
        environment=managed_mcp.environment,
    )
    missing = managed_mcp.call("alias_status", {"aliases": ["missing@l1"]})
    assert cli_missing.returncode == 1
    assert missing["isError"] is True
    assert missing["structuredContent"] == yaml.safe_load(cli_missing.stdout)


def test_installed_mcp_server_continues_a_stopped_ticket_with_unchanged_semantics(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The dispatch stop and the explicit continue are the existing D.3 path."""

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_ticket

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_ticket(installed_commands, harness, body=_budget_body(total=1))
    clock = tmp_path / "mcp-continue-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    controls = tmp_path / "mcp-continue-controls"
    controls.mkdir()
    (controls / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "try:\n"
        "    import graphtraj.execution.execution_budget as budget\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    budget.time.time = lambda: float(Path(os.environ['BUDGET_CLOCK']).read_text())\n"
        "    budget.random.uniform = lambda lower, upper: lower\n"
        "    budget.random.random = lambda: 0.99\n",
        encoding="utf-8",
    )
    environment = {
        **environment,
        "BUDGET_CLOCK":                 str(clock),
        "FAKE_CODEX_APPEND_LOG":        "1",
        "FAKE_CODEX_CAPTURE_STDIN":     "1",
        "FAKE_CODEX_CAPTURE_ROLE":      "1",
        "FAKE_CODEX_FINAL_LEADER_CLOCK": str(clock),
        "FAKE_CODEX_LIFECYCLE_ACTION":  "complete-team-round",
        "GRAPHTRAJ_AGENT_RUNNER":       str(installed_commands.runner),
        "PYTHONPATH":                   str(controls),
    }
    ticket = harness / ".graphtraj/state/tickets/76-session-alias-control"

    with _started_mcp(mcp_executable, harness, environment) as server:
        stopped = server.call("dispatch", {"tasks": [{
            "ticket_id":   "76",
            "ticket_name": "session-alias-control",
            "role":        "coding-team.team-leader",
        }]})["result"]
        assert stopped["isError"] is False
        assert stopped["structuredContent"]["tasks"][0]["launch_status"] == "stopped"
        usage_before = yaml.safe_load((ticket / "execution-budget.yml").read_text())
        assert usage_before["stopped"] is True
        state = yaml.safe_load((ticket / "ticket.yml").read_text())
        assert state["status"] == "reviewing"
        candidate = state["current_candidate"]
        assert candidate is not None
        diagnosis = harness / "stopped-team-diagnosis.md"
        diagnosis.write_text(
            "Main diagnosed the sampled stop and chose continuation.\n", encoding="utf-8"
        )
        # The stop is recorded with its own causal event, as the D.3 flow expects.
        events = [
            json.loads(line)
            for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        stop_event = events[-1]["event_id"]
        decision_file = _write(
            harness / "continuation-decision.yml",
            {
                "kind":                "ticket-continuation-decided",
                "caused_by_event_ids": [stop_event],
                "evidence_refs":       ["stopped-team-diagnosis.md"],
                "decision":            "continue",
            },
        )
        decision = _cli(
            installed_commands, harness, "worldline", "append",
            "--event-file", str(decision_file),
        )
        assert decision.returncode == 0, decision.stderr
        decision_id = yaml.safe_load(decision.stdout)["event_id"]
        revision = _write(harness / "continuation-budget-revision.yml", {
            "product_preserving":  True,
            "caused_by_event_ids": [decision_id],
            "evidence_refs":       ["stopped-team-diagnosis.md"],
            "tickets":             [
                {
                    **_ticket("76", "session-alias-control"),
                    "body":        _budget_body(
                        total=10,
                        revision_reason="Main accepted the retained stop diagnosis.",
                    ),
                    "active":      True,
                    "replaced_by": [],
                }
            ],
        })
        revised = _cli(
            installed_commands, harness, "ticket", "revise",
            "--revision-file", str(revision),
        )
        assert revised.returncode == 0, revised.stderr
        again = server.call("dispatch", {"tasks": [{
            "ticket_id":   "76",
            "ticket_name": "session-alias-control",
            "role":        "coding-team.team-leader",
        }]})["result"]
        assert again["isError"] is False
        assert again["structuredContent"]["tasks"][0]["launch_status"] == "stopped"
        continued = server.call("continue", {
            "ticket_id": "76", "caused_by_event_ids": [decision_id],
        })["result"]

    assert continued["isError"] is False, continued
    continuation = continued["structuredContent"]
    assert continuation["launch_status"] == "accepted"
    after = yaml.safe_load((ticket / "ticket.yml").read_text())
    assert after["status"] == "awaiting-integration"
    assert after["active_team_ordinal"] == 1
    assert after["current_candidate"] == candidate
    usage = yaml.safe_load((ticket / "execution-budget.yml").read_text())
    assert usage["stopped"] is False
    for field in (
        "started_at", "sessions", "corrections", "allowance_minutes",
        "stopping_checks", "notifications", "leader_notices",
    ):
        assert usage[field] == usage_before[field]
    assert usage["budget"]["execution_budget"]["estimated_minutes"]["total"] == 10
    events = [
        json.loads(line)
        for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    recorded = next(
        event for event in events
        if event["event_id"] == continuation["continuation_event_id"]
    )
    assert recorded["kind"] == "team-continuation-started"
    assert recorded["caused_by_event_ids"] == [decision_id]


class CodexHost:
    """Drive the installed Codex app-server as an isolated MCP host."""

    def __init__(
        self,
        project: Path,
        codex_home: Path,
        environment: dict[str, str] | None = None,
        executable: str = "codex",
    ) -> None:
        environment = dict(os.environ if environment is None else environment)
        environment["CODEX_HOME"] = str(codex_home)
        environment.pop("CODEX_THREAD_ID", None)
        self.process = subprocess.Popen(
            [executable, "app-server", "--listen", "stdio://"],
            cwd=project,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self.sequence = 0
        self.thread_id: str | None = None

    def __enter__(self) -> "CodexHost":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.process.terminate()
        self.process.wait(timeout=30)

    def _read_message(self, timeout: float) -> dict:
        ready, _, _ = select.select([self.process.stdout], [], [], timeout)
        assert ready, "Timed out waiting for a Codex app-server response"
        return json.loads(self.process.stdout.readline())

    def request(self, method: str, params: dict, timeout: float = 30) -> dict:
        """Send one app-server request and return its matching response."""

        self.sequence += 1
        request_id = self.sequence
        self.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id":      request_id,
                    "method":  method,
                    "params":  params,
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            message = self._read_message(max(deadline - time.monotonic(), 0.1))
            if message.get("id") == request_id:
                return message

    def notify(self, method: str, params: dict) -> None:
        self.process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        )
        self.process.stdin.flush()


@pytest.mark.skipif(
    os.environ.get("CODEX_REAL_MCP_HOST") != "1" or shutil.which("codex") is None,
    reason="set CODEX_REAL_MCP_HOST=1 with an installed codex executable",
)
def test_real_codex_host_discovers_and_calls_the_mcp_graph_tools_offline(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """An isolated real host discovers the tools and their results match the CLI."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        "[mcp_servers.graphtraj]\n"
        'command = "{0}"\n'
        "args = []\n"
        'cwd = "{1}"\n'
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 30\n".format(mcp_executable, project),
        encoding="utf-8",
    )
    issue = _ticket("73", "shared-graph")

    with CodexHost(project, codex_home) as host:
        host.request(
            "initialize",
            {
                "clientInfo":   {"name": "graphtraj-host-test", "version": "0.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        host.notify("initialized", {})
        started = host.request("thread/start", {"cwd": str(project)})
        host.thread_id = started["result"]["thread"]["id"]

        inventory = host.request(
            "mcpServerStatus/list",
            {"threadId": host.thread_id, "detail": "full"},
        )["result"]["data"]
        discovered = next(
            server for server in inventory if server["name"] == "graphtraj"
        )
        assert set(discovered["tools"]) == TOOL_NAMES
        assert discovered["toolsError"] is None

        registered = host.request(
            "mcpServer/tool/call",
            {
                "server":    "graphtraj",
                "threadId":  host.thread_id,
                "tool":      "ticket_register",
                "arguments": issue,
            },
        )["result"]
        assert registered["isError"] is False

        # A rejected call must not close the host's transport to this server.
        rejected = host.request(
            "mcpServer/tool/call",
            {
                "server":    "graphtraj",
                "threadId":  host.thread_id,
                "tool":      "alias_status",
                "arguments": {"aliases": ["missing@l1"], "baseline": "abc123"},
            },
        )["result"]
        assert rejected["isError"] is True
        assert rejected["content"][0]["text"] == (
            "Git diagnostics require both --baseline and --candidate."
        )

        graph = host.request(
            "mcpServer/tool/call",
            {
                "server":    "graphtraj",
                "threadId":  host.thread_id,
                "tool":      "ticket_graph",
                "arguments": {},
            },
        )["result"]

    assert Path(registered["structuredContent"]["ticket_directory"]).name == (
        "73-shared-graph"
    )
    cli = _cli(installed_commands, project, "ticket", "graph")
    assert cli.returncode == 0, cli.stderr
    assert graph["structuredContent"] == yaml.safe_load(cli.stdout)
    assert graph["structuredContent"]["tickets"][0]["ticket_name"] == "shared-graph"


HOST_PROBE = Path(
    os.environ.get("GRAPHTRAJ_MCP_HOST_PROBE_LOG", "/tmp/mcp118-host/probe.log")
)


def _record_host_exchange(probe: Path, tool: str, arguments: dict, result: dict) -> None:
    """Retain one real host tool exchange under /tmp for later inspection."""

    probe.parent.mkdir(parents=True, exist_ok=True)
    with probe.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "tool":              tool,
                    "arguments":         arguments,
                    "isError":           result.get("isError"),
                    "structuredContent": result.get("structuredContent"),
                    "text":              (result.get("content") or [{}])[0].get("text"),
                },
                sort_keys=True,
            )
            + "\n"
        )


def _host_tool(host: "CodexHost", probe: Path, tool: str, arguments: dict) -> dict:
    """Call one discovered tool through the real Codex host."""

    result = host.request(
        "mcpServer/tool/call",
        {
            "server":    "graphtraj",
            "threadId":  host.thread_id,
            "tool":      tool,
            "arguments": arguments,
        },
        timeout=60,
    )["result"]
    _record_host_exchange(probe, tool, arguments, result)
    return result


def _host_observe(
    host: "CodexHost",
    probe: Path,
    alias: str,
    activity: str,
    outcome: str | None = None,
    waiting_for: str | None = None,
    timeout: float = 30,
) -> dict:
    """Wait for an observable state using only host tool calls."""

    deadline = time.monotonic() + timeout
    status: dict = {}
    while time.monotonic() < deadline:
        result = _host_tool(host, probe, "alias_status", {"aliases": [alias]})
        assert result.get("isError") is False, result
        status = result["structuredContent"]["aliases"][0]
        if (
            status.get("activity") == activity
            and (outcome is None or status.get("last_outcome") == outcome)
            and (waiting_for is None or status.get("waiting_for") == waiting_for)
        ):
            return status
        time.sleep(0.2)
    raise AssertionError(status)


@pytest.mark.skipif(
    os.environ.get("CODEX_REAL_MCP_HOST") != "1" or shutil.which("codex") is None,
    reason="set CODEX_REAL_MCP_HOST=1 with an installed codex executable",
)
def test_real_codex_host_dispatches_and_controls_a_managed_child_offline(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A real host call produces a managed child it can keep controlling.

    The host, the MCP server, the Runner and the Codex Adapter are real; only the
    dispatched Runtime executable's model work is the controlled peer, because
    this sandbox has no model access. The exchange is retained under /tmp.
    """

    from graphtraj.graph.delivery_worldline import append_project_worldline_event
    from graphtraj.graph.ticket_graph import register_ticket

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    state = harness / ".graphtraj/state"
    register_ticket(state, harness, _ticket("113", "managed-probe"))
    (harness / "instruction.md").write_text(
        "Exercise the dispatched child.\n", encoding="utf-8"
    )
    cause = append_project_worldline_event(state, harness, {
        "kind":                "main-decision",
        "decision":            "Exercise the dispatched child.",
        "caused_by_event_ids": [],
        "evidence_refs":       ["instruction.md"],
    })["event_id"]
    fake_codex.executable.write_text(
        "#!" + sys.executable + "\n"
        + Path(__file__).with_name("managed_codex_peer.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_codex.executable.chmod(0o755)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    # The host passes an MCP server a filtered environment, so the controlled
    # Runtime boundary the dispatched child resolves must be declared here.
    (codex_home / "config.toml").write_text(
        "[mcp_servers.graphtraj]\n"
        'command = "{0}"\n'
        "args = []\n"
        'cwd = "{1}"\n'
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 30\n"
        "[mcp_servers.graphtraj.env]\n"
        'MANAGED_NATIVE_ROOT = "{2}"\n'
        'CODEX_HOME = "{3}"\n'.format(
            mcp_executable, harness, tmp_path / "native", codex_home
        ),
        encoding="utf-8",
    )
    environment.update(
        {
            "MANAGED_NATIVE_ROOT": str(tmp_path / "native"),
            "CODEX_HOME":          str(codex_home),
        }
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("CODEX_THREAD_ID", None)
    real_codex = shutil.which("codex")
    probe = HOST_PROBE
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("", encoding="utf-8")

    with CodexHost(harness, codex_home, environment, executable=real_codex) as host:
        host.request(
            "initialize",
            {
                "clientInfo":   {"name": "graphtraj-execution-host-test", "version": "0.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        host.notify("initialized", {})
        started = host.request("thread/start", {"cwd": str(harness)})
        host.thread_id = started["result"]["thread"]["id"]
        inventory = host.request(
            "mcpServerStatus/list",
            {"threadId": host.thread_id, "detail": "full"},
        )["result"]["data"]
        discovered = next(
            server for server in inventory if server["name"] == "graphtraj"
        )
        assert set(discovered["tools"]) == TOOL_NAMES
        assert discovered["toolsError"] is None

        dispatched = _host_tool(host, probe, "dispatch", {"tasks": [_inline_task()]})
        assert dispatched["isError"] is False, dispatched
        task, = dispatched["structuredContent"]["tasks"]
        assert task["launch_status"] == "launched"
        alias, session = task["alias"], task["session"]
        running = _host_observe(host, probe, alias, "running")
        assert running["session"] == session
        assert running["execution_id"]

        sent = _host_tool(
            host, probe, "send_instruction",
            {"alias": alias, "instruction": "unhandled request",
             "caused_by_event_ids": [cause]},
        )
        assert sent["structuredContent"] == {"alias": alias, "send_status": "sent"}
        waiting = _host_observe(
            host, probe, alias, "running", waiting_for="runtime-request"
        )
        queried = _host_tool(host, probe, "pending_requests", {"alias": alias})
        request, = queried["structuredContent"]["requests"]
        assert request["execution_id"] == waiting["execution_id"]
        replied = _host_tool(
            host, probe, "reply_to_request",
            {"alias": alias, "request": request, "response": {"decision": "accept"}},
        )
        assert replied["structuredContent"] == {
            "alias":        alias,
            "session":      session,
            "execution_id": waiting["execution_id"],
            "request_id":   "approval",
            "reply_status": "submitted",
        }
        completed = _host_observe(host, probe, alias, "idle", "completed")
        assert completed["execution_id"] == waiting["execution_id"]

        _host_tool(
            host, probe, "send_instruction",
            {"alias": alias, "instruction": "request:approval",
             "caused_by_event_ids": [cause]},
        )
        active = _host_observe(
            host, probe, alias, "running", waiting_for="runtime-request"
        )
        assert active["execution_id"] != completed["execution_id"]
        interrupted = _host_tool(host, probe, "interrupt", {"alias": alias})
        assert interrupted["structuredContent"] == {
            "alias": alias, "interrupt_status": "interrupted",
        }
        after = _host_observe(host, probe, alias, "idle", "interrupted")
        assert after["execution_id"] == active["execution_id"]
        assert after["session"] == session
        assert _host_tool(host, probe, "pending_requests", {"alias": alias})[
            "structuredContent"
        ]["requests"] == []

        continued = _host_tool(
            host, probe, "continue",
            {"ticket_id": "113", "caused_by_event_ids": [cause]},
        )

    # The D.3 continuation is the same operation the CLI exposes; this project
    # has no stopped Team, so both interfaces report the same rejection.
    cli = _runner(
        installed_commands, harness, "continue", "--ticket-id", "113",
        "--caused-by-event-id", cause, environment=environment,
    )
    assert cli.returncode == 1, cli.stderr
    assert continued["isError"] is True
    assert continued["content"][0]["text"] == yaml.safe_load(cli.stdout)["error"]["message"]
