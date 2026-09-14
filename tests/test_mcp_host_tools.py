"""Behavior of the installed MCP tool entry point and its Codex host client."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process
from test_ticket_graph import _configure, _ticket, _write


TOOL_NAMES = {
    "ticket_graph",
    "ticket_register",
    "ticket_revise",
    "ticket_update",
    "alias_status",
}
VOLATILE_EVENT_KEYS = {
    "event_id", "captured_at", "definition_refs", "evidence_refs",
}


class McpServerProcess:
    """Drive the installed MCP server over its newline-delimited stdio seam."""

    def __init__(self, executable: Path, project_root: Path) -> None:
        self.process = subprocess.Popen(
            [str(executable)],
            cwd=project_root,
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
    installed_commands: InstalledCommands, project: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    # The invoking Agent's Codex Session must not bind the test Runner process.
    environment = {
        name: value
        for name, value in os.environ.items()
        if name != "CODEX_THREAD_ID"
    }
    return run_process(
        [str(installed_commands.runner), *arguments],
        cwd=project,
        env=environment,
    )


def _started_mcp(
    mcp_executable: Path, project: Path
) -> McpServerProcess:
    server = McpServerProcess(mcp_executable, project)
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


class CodexHost:
    """Drive the installed Codex app-server as an isolated MCP host."""

    def __init__(self, project: Path, codex_home: Path) -> None:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
        self.process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
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
