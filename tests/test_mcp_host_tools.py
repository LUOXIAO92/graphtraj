"""Behavior of the installed MCP tool entry point and its Codex host client."""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest
import yaml

from conftest import FakeCodex, InstalledCommands, run_process, runner_command
from graphtraj.interfaces import gateway, tools
from runner_fixtures import configure_harness
from test_task_graph import _configure, _task, _write


# The original gateway remains alongside the two public function names.
TOOL_NAMES = {"agents", "tasks"}
MCP_TOOL_NAME = "tasks"
AGENT_ACTIONS = frozenset({'status', 'send', 'interrupt', 'requests', 'reply'})


def operation_document(result: dict, action: str) -> dict:
    """Unwrap agents metadata when comparing its result to the Runner operation."""
    if action in AGENT_ACTIONS and 'result' in result.get('structuredContent', {}):
        return {**result, 'structuredContent': result['structuredContent']['result']}
    return result


def tool_envelope(feature: str, arguments: dict) -> dict:
    """Wrap one feature call in the outer discover/describe/execute envelope."""

    return {"action": "execute", "feature": feature, "arguments": arguments}


VOLATILE_EVENT_KEYS = {
    "event_id", "captured_at", "definition_refs", "evidence_refs",
}


def require_no_retro_skill(root: Path) -> None:
    """Assert the controlled Harness root has no retro Skill to depend on.

    Setup no longer supplies packaged Skills, so stop delivery must work with
    the retro file absent instead of deleting a file it never installs.
    """
    retro = root / ".agents" / "skills" / "retro" / "SKILL.md"
    assert not retro.exists(), retro


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

    def call(
        self, name: str, arguments: dict, thread_id: str | None = None
    ) -> dict:
        """Call one feature through the single MCP tool and return its result.

        ``name`` selects the feature inside the outer envelope rather than a
        top-level tool. ``thread_id`` adds the caller identity a real Codex
        host sends as ``params._meta.threadId`` on its own tool request.
        """

        params = {"name": 'agents' if name in AGENT_ACTIONS else MCP_TOOL_NAME,
                  "arguments": tool_envelope(name, arguments)}
        if thread_id is not None:
            params["_meta"] = {"threadId": thread_id}
        response = self.request("tools/call", params)
        if 'result' in response:
            response['result'] = operation_document(response['result'], name)
        return response

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
        runner_command(installed_commands, *arguments),
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


def _associate_native_mains(
    commands: InstalledCommands, root: Path, environment: dict[str, str],
) -> None:
    """Enter the controlled Main peers through the real SessionStart carrier."""
    for session in environment['PEER_MAIN_THREADS'].split(','):
        rollout = root / (session + '.jsonl')
        rollout.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': session, 'source': 'cli',
        }}) + '\n')
        result = subprocess.run([
            str(commands.product.with_name('python')), '-m', 'graphtraj.runtimes.codex.stop_hook',
        ], cwd=root, env=environment, input=json.dumps({
            'hook_event_name': 'SessionStart', 'source': 'startup', 'cwd': str(root),
            'session_id': session + '-hook', 'transcript_path': str(rollout),
        }), capture_output=True, text=True, timeout=20)
        assert result.returncode == 0 and 'continue' not in json.loads(result.stdout), result.stdout + result.stderr


def _stable_event(document: dict) -> dict:
    return {
        key: value
        for key, value in document.items()
        if key not in VOLATILE_EVENT_KEYS
    }


def test_mcp_agents_preserves_verified_main_and_helper_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stdio function uses native verification, never a caller argument.

    Native metadata verification is controlled here; this is not real-host
    evidence. The MCP parser, gateway and independent control stay real.
    """
    from io import StringIO
    from graphtraj.interfaces.mcp import serve
    from graphtraj.runtimes import runtime_adapter
    from graphtraj.runtimes.codex import session_entry
    from graphtraj.execution.runner_models import RunnerError

    _configure(tmp_path)
    monkeypatch.chdir(tmp_path)
    connection = {'runtime': 'codex', 'session': 'verified-main', 'codex_home': str(tmp_path)}
    monkeypatch.setattr(runtime_adapter, 'current_host_connection', lambda: connection)
    monkeypatch.setattr(session_entry, 'routed_connection', lambda runner, value: value)

    def verify(runner: Path, value: dict) -> str | None:
        """Represent the existing native verifier's distinct source outcomes."""
        if value['session'] == 'stale':
            raise RunnerError('authority-denied', 'Stale native source.')
        return None if value['session'] == 'verified-main' else value['session']

    monkeypatch.setattr(session_entry, 'caller_identity', verify)
    monkeypatch.setattr(session_entry, 'owns_native_root', lambda runner, value: False)

    def call(arguments: dict) -> dict:
        """Exercise a full newline-delimited MCP tools/call exchange."""
        output = StringIO()
        serve(StringIO(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                  'params': {'name': 'agents', 'arguments': {'action': 'execute', 'feature': arguments['action'], 'arguments': {key: value for key, value in arguments.items() if key != 'action'}}}}) + '\n'), output)
        return json.loads(output.getvalue())['result']

    assert call({'action': 'status'})['isError'] is False
    forged = call({'action': 'status', 'caller': 'another-main'})
    assert forged['isError'] is True
    connection['session'] = 'native-helper'
    denied = call({'action': 'create', 'runtime': 'codex', 'instruction': 'must not launch'})
    assert denied['structuredContent']['error']['code'] == 'authority-denied'
    connection['session'] = 'stale'
    assert call({'action': 'status'})['isError'] is True


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
        "task",
        "register",
        "--task-file",
        str(_write(project / "issue.yml", _task("73", "shared-graph"))),
    )
    assert registered.returncode == 0, registered.stderr

    with _started_mcp(mcp_executable, project) as server:
        listed = server.request("tools/list")["result"]["tools"]
        assert {tool["name"] for tool in listed} == TOOL_NAMES
        descriptors = {tool['name']: tool for tool in listed}
        descriptor = descriptors['tasks']
        assert descriptor["description"]
        # Tasks retains the gateway envelope; agents uses its independent contract.
        assert descriptors['agents']['inputSchema'] == gateway.INPUT_SCHEMA
        assert descriptors['tasks']['inputSchema'] == gateway.INPUT_SCHEMA
        assert descriptor["inputSchema"] == gateway.INPUT_SCHEMA
        assert set(descriptor["inputSchema"]["properties"]) == {
            "action", "query", "feature", "arguments", "schema",
        }

        # discover and describe are reached through the same single tool.
        found = server.request("tools/call", {
            "name": MCP_TOOL_NAME,
            "arguments": {"action": "discover", "query": "task graph"},
        })["result"]
        assert found["isError"] is False
        assert "task_graph" in {
            feature["feature"] for feature in found["structuredContent"]["features"]
        }

        described = server.request("tools/call", {
            "name": MCP_TOOL_NAME,
            "arguments": {"action": "describe", "feature": "task_graph"},
        })["result"]
        description = described["structuredContent"]
        assert description["feature"] == "task_graph"
        assert set(description) == {"feature", "description", "manual_ref"}
        reference = Path(description["manual_ref"])
        assert reference.is_absolute() and reference.read_text(encoding="utf-8")
        parameters = server.request("tools/call", {
            "name": MCP_TOOL_NAME,
            "arguments": {"action": "describe", "feature": "task_graph", "schema": True},
        })["result"]
        assert parameters["structuredContent"] == {"input_schema": tools.TOOLS["task_graph"].input_schema}
        assert described["isError"] is ("error" in description)

        call = server.call("task_graph", {})
        assert call["result"]["isError"] is False
        graph = _cli(installed_commands, project, "task", "graph")
        assert graph.returncode == 0, graph.stderr
        assert call["result"]["structuredContent"] == yaml.safe_load(graph.stdout)
        node = call["result"]["structuredContent"]["tasks"][0]
        expected = {
            "task_id":    "73",
            "task_name":  "shared-graph",
            "status":       "pending",
            "active":       True,
            "ready":        True,
            "dependencies": [],
            "replaced_by":  [],
        }
        assert {key: node[key] for key in expected} == expected
        assert node["parent_id"] is None and node["disposition"] == "active"
        # The rendered text is the CLI's own YAML for the same document.
        assert call["result"]["content"][0]["text"] == graph.stdout
        tasks_call = server.request('tools/call', {
            'name': 'tasks', 'arguments': tool_envelope('task_graph', {}),
        })
        assert tasks_call['result'] == call['result']
        agents_call = server.request('tools/call', {
            'name': 'agents', 'arguments': {'action': 'execute', 'feature': 'status', 'arguments': {}},
        })
        assert agents_call['result']['isError'] is True
        assert agents_call['result']['structuredContent']['error']['code'] == 'authority-unavailable'


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
    issue = _task("73", "shared-graph")
    dependent = _task("74", "second-graph", dependencies=["73"])
    revision = {
        "product_preserving":  True,
        "caused_by_event_ids": [],
        "evidence_refs":       ["evidence.md"],
        "tasks":             [
            {**_task("74", "second-graph"), "current_definition": "task.md"}
        ],
    }
    change = {
        "task_id":           "74",
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
            registered = server.call("task_register", definition)["result"]
            assert registered["isError"] is False
            host_directories.append(
                Path(registered["structuredContent"]["task_directory"])
            )
        revised = server.call("task_revise", revision)["result"]
        assert revised["isError"] is False
        updated = server.call("task_update", change)["result"]
        assert updated["isError"] is False
        host_graph = server.call("task_graph", {})["result"]["structuredContent"]

    for definition, host_directory in zip((issue, dependent), host_directories):
        cli_registered = _cli(
            installed_commands,
            cli_project,
            "task",
            "register",
            "--task-file",
            str(_write(cli_project / "issue.yml", definition)),
        )
        assert cli_registered.returncode == 0, cli_registered.stderr
        assert host_directory.relative_to(host_project) == Path(
            cli_registered.stdout.strip()
        ).relative_to(cli_project)
    cli_revised = _cli(
        installed_commands,
        cli_project,
        "task",
        "revise",
        "--revision-file",
        str(_write(cli_project / "revision.yml", revision)),
    )
    assert cli_revised.returncode == 0, cli_revised.stderr
    cli_updated = _cli(
        installed_commands,
        cli_project,
        "task",
        "update",
        "--state-file",
        str(_write(cli_project / "change.yml", change)),
    )
    assert cli_updated.returncode == 0, cli_updated.stderr
    cli_graph = _cli(installed_commands, cli_project, "task", "graph")
    assert cli_graph.returncode == 0, cli_graph.stderr

    assert set(revised["structuredContent"]) == set(yaml.safe_load(cli_revised.stdout))
    assert _stable_event(revised["structuredContent"]) == _stable_event(
        yaml.safe_load(cli_revised.stdout)
    )
    assert set(updated["structuredContent"]) == set(yaml.safe_load(cli_updated.stdout))
    assert _stable_event(updated["structuredContent"]) == _stable_event(
        yaml.safe_load(cli_updated.stdout)
    )
    cli_view = yaml.safe_load(cli_graph.stdout)
    for host_node, cli_node in zip(host_graph["tasks"], cli_view["tasks"], strict=True):
        assert {key: value for key, value in host_node.items() if key != "current_definition"} == {
            key: value for key, value in cli_node.items() if key != "current_definition"
        }
        directory = f".graphtraj/state/tasks/{host_node['task_id']}-{host_node['task_name']}"
        assert (host_project / directory / host_node["current_definition"]).read_bytes() == (
            cli_project / directory / cli_node["current_definition"]
        ).read_bytes()
    assert [task["status"] for task in host_graph["tasks"]] == [
        "pending", "ready",
    ]


def test_installed_mcp_server_requires_verified_agent_status_caller(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Agent queries cannot create an anonymous Main identity in a new project."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)

    with _started_mcp(mcp_executable, project) as server:
        call = server.call('status', {'agent': "missing@l1"})["result"]

    assert call["isError"] is True
    assert call['structuredContent']['error']['code'] in {
        'authority-unavailable', 'authority-denied',
    }


def test_installed_mcp_server_reports_invalid_input_and_unknown_requests(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Rejected operations keep their message instead of becoming empty results."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)
    invalid = {"task_id": "74"}

    with _started_mcp(mcp_executable, project) as server:
        rejected = server.call("task_register", invalid)["result"]
        unknown_tool = server.request(
            "tools/call", {"name": "task_send", "arguments": {}}
        )
        unknown_feature = server.call("task_send", {})["result"]
        unknown_method = server.request("resources/list", {})

    cli = _cli(
        installed_commands,
        project,
        "task",
        "register",
        "--task-file",
        str(_write(project / "invalid.yml", invalid)),
    )
    assert cli.returncode == 2
    assert rejected["isError"] is True
    assert "required" in rejected["structuredContent"]["error"]
    assert rejected["content"][0]["text"]
    assert unknown_tool["error"]["code"] == -32602
    assert unknown_feature["isError"] is True
    assert "task_send" in unknown_feature["structuredContent"]["error"]
    assert unknown_method["error"]["code"] == -32601


def test_installed_mcp_server_survives_a_rejected_agent_status_call(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Task diagnostics are not parameters of Agent status; rejection keeps MCP alive."""

    project = tmp_path / "project"
    project.mkdir()
    _configure(project)

    with _started_mcp(mcp_executable, project) as server:
        rejected = server.call(
            'status', {'agent': "missing@l1", 'baseline': "abc123"}
        )["result"]
        # The same process must keep serving the other tools afterwards.
        after = server.call("task_graph", {})["result"]

    assert rejected["isError"] is True
    assert 'baseline' in rejected["content"][0]["text"]
    assert after["isError"] is False
    assert after["structuredContent"]["tasks"] == []


def test_installed_mcp_server_reports_a_missing_project_root_like_the_graph_tools(
    installed_commands: InstalledCommands, mcp_executable: Path, tmp_path: Path
) -> None:
    """Both hosted surfaces reject an absent project without creating one."""

    plain = tmp_path / "plain"
    plain.mkdir()

    with _started_mcp(mcp_executable, plain) as server:
        status = server.call('status', {'agent': "missing@l1"})["result"]
        graph = server.call("task_graph", {})["result"]

    cli = _cli(installed_commands, plain, "task", "graph")
    assert cli.returncode == 1
    message = cli.stderr.strip().removeprefix("Error: ")
    assert status["isError"] is True
    assert graph["isError"] is True
    assert status['structuredContent']['error']['code'] == 'PROJECT_NOT_FOUND'
    assert graph["content"][0]["text"] == message
    assert not (plain / '.graphtraj').exists()


@dataclass(frozen=True)
class ManagedMcp:
    """An installed MCP server over a project whose Runtime is a controlled peer."""

    root: Path
    cause: str
    server: McpServerProcess
    environment: dict[str, str]

    def call(self, name: str, arguments: dict) -> dict:
        """Call one execution or interaction tool and return its MCP result."""

        thread_id = "managed-main"
        return self.server.call(name, arguments, thread_id=thread_id)["result"]

    def document(self, name: str, arguments: dict) -> dict:
        """Call one tool that must succeed and return its structured document."""

        result = self.call(name, arguments)
        assert result["isError"] is False, result
        return result["structuredContent"]


def _inline_task(instruction: str = "hold") -> dict:
    """Select the existing inline temporary role for the registered task."""

    return {
        "task_id":   "113",
        "task_name": "managed-probe",
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
        status = managed.document('status', {'agent': alias})["aliases"][0]
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
    from graphtraj.graph.task_graph import register_task

    root, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    state = root / ".graphtraj/state"
    register_task(state, root, _task("113", "managed-probe"))
    from test_task_graph import _change_status
    _change_status(installed_commands, root, '113', 'ready')
    roles_file = root / '.graphtraj/roles.yml'
    roles = yaml.safe_load(roles_file.read_text())
    roles['role_tree']['managed-probe'] = {}
    roles_file.write_text(yaml.safe_dump(roles))
    (root / "instruction.md").write_text(
        "Exercise the dispatched child.\n", encoding="utf-8"
    )
    cause = append_project_worldline_event(state, root, {
        "event":                "main-decision",
        "decision":            "Exercise the dispatched child.",
        "caused_by_event_ids": [],
        "evidence_refs":       ["instruction.md"],
    })["event_id"]
    fake_codex.executable.write_text(
        "#!" + sys.executable + "\n"
        + "import sys, runpy\nif sys.argv[1:3] == ['app-server', 'proxy']:\n"
        + "    runpy.run_path(" + repr(str(Path(__file__).with_name('codex_stdio_peer.py'))) + ")\n    raise SystemExit(0)\n"
        + Path(__file__).with_name("managed_codex_peer.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fake_codex.executable.chmod(0o755)
    environment.update(
        {
            "MANAGED_NATIVE_ROOT": str(tmp_path / "native"),
            "CODEX_HOME":          str(tmp_path / "codex-home"),
            "PEER_MAIN_THREADS":   'managed-main',
        }
    )
    environment.pop("PYTHONPATH", None)
    environment.pop("CODEX_THREAD_ID", None)
    _associate_native_mains(installed_commands, root, environment)

    with _started_mcp(mcp_executable, root, environment) as server:
        managed = ManagedMcp(
            root=root, cause=cause, server=server, environment=environment
        )
        yield managed
        for mapping in (root / ".graphtraj/runner/sessions").glob("*/mapping.yml"):
            # Leave no controlled execution running behind the fixture.
            server.call('interrupt', {'agent': mapping.parent.name})


def test_installed_mcp_server_dispatches_and_controls_a_managed_child(
    installed_commands: InstalledCommands, managed_mcp: ManagedMcp
) -> None:
    """A host dispatches one managed child and controls it by its identity."""

    root, cause = managed_mcp.root, managed_mcp.cause
    require_no_retro_skill(root)
    managed_mcp.environment["CODEX_THREAD_ID"] = "managed-main"
    dispatched = managed_mcp.document("swarm", {"tasks": [_inline_task()]})
    assert set(dispatched) == {"retained_batch_file", "tasks"}
    task, = dispatched["tasks"]
    assert task["launch_status"] == "launched"
    assert task["task_id"] == "113"
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
    assert managed_mcp.document('status', {'agent': alias}) == (
        yaml.safe_load(cli.stdout)
    )

    # An explicit instruction from the user reaches the owned execution.
    sent = managed_mcp.document(
        'send',
        {'agent': alias, 'message': "unhandled request"},
    )
    assert sent == {"alias": alias, "send_status": "sent",
                    "session": session, "execution_id": running["execution_id"]}

    # The native approval request returns through the one interaction path.
    _observe(managed_mcp, alias, "running", waiting_for="runtime-request")
    queried = managed_mcp.document('requests', {'agent': alias})
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
        'reply',
        {'agent': alias, 'request': request, 'response': {"decision": "accept"}},
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
        'reply',
        {'agent': alias, 'request': request, 'response': {"decision": "accept"}},
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
        'send',
        {'agent': alias, 'message': "request:approval"},
    )
    active = _observe(managed_mcp, alias, "running", waiting_for="runtime-request")
    assert active["execution_id"] != completed["execution_id"]
    assert managed_mcp.document('interrupt', {'agent': alias}) == {
        "alias": alias, "interrupt_status": "interrupted",
        "members": [{"alias": alias, "interrupt_status": "interrupted"}],
    }
    after = _observe(managed_mcp, alias, "idle", "interrupted")
    assert after["execution_id"] == active["execution_id"]
    assert after["session"] == session
    assert managed_mcp.document('requests', {'agent': alias})["requests"] == []

    # Explicit interruption stops the entity; neither surface may revive it.
    cli_sent = _runner(installed_commands, root, "send", alias, "--instruction", "hold",
                       "--caused-by-event-id", cause, environment=managed_mcp.environment)
    denied = managed_mcp.call('send', {'agent': alias, 'message': "hold"})
    assert cli_sent.returncode == 1
    assert denied['isError'] is True
    assert yaml.safe_load(cli_sent.stdout)['error']['code'] == 'subtree-stopped'
    assert _observe(managed_mcp, alias, 'idle', 'interrupted')['session'] == session
    repeated = managed_mcp.document('interrupt', {'agent': alias})
    assert repeated['members'] == [{'alias': alias, 'interrupt_status': 'stopped'}]


def test_installed_mcp_server_rejects_execution_input_like_the_cli(
    installed_commands: InstalledCommands, managed_mcp: ManagedMcp
) -> None:
    """Rejected dispatch, control and interaction calls keep the CLI's message."""

    root, cause = managed_mcp.root, managed_mcp.cause
    require_no_retro_skill(root)
    managed_mcp.environment["CODEX_THREAD_ID"] = "managed-main"
    empty_batch = _write(root / "empty-batch.yml", {"tasks": []})
    unregistered = _write(
        root / "unregistered-batch.yml", {"tasks": [_inline_task() | {"task_id": "999"}]}
    )
    stale_request = _write(root / "stale-request.yml", {"alias": "missing@l1"})
    cases = (
        ("swarm", {"tasks": []}, ["--swarm-input", str(empty_batch)]),
        ("swarm", {"tasks": [_inline_task() | {"task_id": "999"}]},
         ["--swarm-input", str(unregistered)]),
        ('send', {'agent': "missing@l1", 'message': "steer"},
         ["send", "missing@l1", "--instruction", "steer", "--caused-by-event-id", cause]),
        ('interrupt', {'agent': "missing@l1"}, ["interrupt", "missing@l1"]),
        ('requests', {'agent': "missing@l1"}, ["requests", "missing@l1"]),
        ('reply', {'agent': "missing@l1", 'request': {"alias": "missing@l1"}, 'response': {}},
         ["reply", "missing@l1", "--request-file", str(stale_request),
          "--response", "{}"]),
        ("continue", {"task_id": "113", "caused_by_event_ids": [cause]},
         ["continue", "--task-id", "113", "--caused-by-event-id", cause]),
        ("continue", {"task_id": "999", "caused_by_event_ids": [cause]},
         ["continue", "--task-id", "999", "--caused-by-event-id", cause]),
        ("continue", {"task_id": "113", "caused_by_event_ids": []},
         ["continue", "--task-id", "113", "--caused-by-event-id", ""]),
    )

    for tool, arguments, cli_arguments in cases:
        result = managed_mcp.call(tool, arguments)
        cli = _runner(
            installed_commands, root, *cli_arguments,
            environment=managed_mcp.environment,
        )
        assert result["isError"] is True, (tool, result)
        assert cli.returncode == 1, (tool, cli.stderr)
        cli_document = yaml.safe_load(cli.stdout)
        cli_error = cli_document.get("error") or cli_document["tasks"][0]["error"]
        if "structuredContent" in result:
            document = result["structuredContent"]
            error = document.get("error") or document["tasks"][0]["error"]
            assert error == cli_error, tool
        else:
            assert result["content"][0]["text"] == cli_error["message"], tool

    # The server keeps serving the same project after rejected calls.
    cli_missing = _runner(
        installed_commands, root, "status", "missing@l1",
        environment=managed_mcp.environment,
    )
    missing = managed_mcp.call('status', {'agent': "missing@l1"})
    assert cli_missing.returncode == 1
    assert missing["isError"] is True
    assert missing["structuredContent"] == yaml.safe_load(cli_missing.stdout)


def test_installed_mcp_server_continues_a_stopped_task_with_unchanged_semantics(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The dispatch stop and the explicit continue are the existing D.3 path."""

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    _register_ready_task(installed_commands, harness, body=_budget_body(total=1))
    clock = tmp_path / "mcp-continue-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    environment, protocol = _controlled_budget_server(
        installed_commands, fake_codex, harness, environment, tmp_path,
        BUDGET_CLOCK=str(clock), FAKE_CODEX_FINAL_LEADER_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
    )
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"

    with _started_mcp(mcp_executable, harness, environment) as server:
        stopped = server.call("swarm", {"tasks": [{
            "task_id":   "76",
            "task_name": "session-alias-control",
            "role":        "coding-team.team-leader",
        }]}, thread_id="thread-main")["result"]
        assert stopped["isError"] is False, stopped
        _await_retained_stop(task_directory)
        _assert_native_budget_stop(protocol, task_directory, "thread-main")
        usage_before = yaml.safe_load((task_directory / "execution-budget.yml").read_text())
        assert usage_before["stopped"] is True
        state = yaml.safe_load((task_directory / "task.yml").read_text())
        assert state["status"] == "implementing"
        assert state['current_candidate'] is None
        candidate = next(json.loads(line)['candidate']
                         for shard in (harness / '.graphtraj/state/worldline').glob('*.jsonl')
                         for line in shard.read_text().splitlines()
                         if json.loads(line)['event'] == 'result-submitted')
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
                "event":                "task-continuation-decided",
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
            "tasks":             [
                {
                    **_task("76", "session-alias-control"),
                    "body":        _budget_body(
                        total=10,
                        revision_reason="Main accepted the retained stop diagnosis.",
                    ),
                    "current_definition": "task.md",
                }
            ],
        })
        revised = _cli(
            installed_commands, harness, "task", "revise",
            "--revision-file", str(revision),
        )
        assert revised.returncode == 0, revised.stderr
        again = server.call("swarm", {"tasks": [{
            "task_id":   "76",
            "task_name": "session-alias-control",
            "role":        "coding-team.team-leader",
        }]})["result"]
        assert again["isError"] is True
        assert again["structuredContent"]["tasks"][0]["launch_status"] == "stopped"
        continued = server.call("continue", {
            "task_id": "76", "caused_by_event_ids": [decision_id],
        })["result"]

    assert continued["isError"] is False, continued
    continuation = continued["structuredContent"]
    assert continuation["tasks"]
    assert all(task["send_status"] == "sent" for task in continuation["tasks"])
    from runner_fixtures import wait_for_task_status
    wait_for_task_status(installed_commands, harness, "76", "awaiting-integration")
    after = yaml.safe_load((task_directory / "task.yml").read_text())
    assert after["status"] == "awaiting-integration"
    assert after["active_team_ordinal"] == 1
    assert after["current_candidate"] == candidate
    usage = yaml.safe_load((task_directory / "execution-budget.yml").read_text())
    assert usage["stopped"] is False
    for field in (
        "started_at", "sessions", "corrections", "allowance_minutes",
        "stopping_checks", "notifications", "parent_notices",
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
    assert recorded["event"] == "team-continuation-started"
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
    issue = _task("73", "shared-graph")

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
                "tool":      MCP_TOOL_NAME,
                "arguments": tool_envelope("task_register", issue),
            },
        )["result"]
        assert registered["isError"] is False

        # A rejected call must not close the host's transport to this server.
        rejected = host.request(
            "mcpServer/tool/call",
            {
                "server":    "graphtraj",
                "threadId":  host.thread_id,
                "tool":      "agents",
                "arguments": tool_envelope(
                    'status', {'agent': "missing@l1", 'baseline': "abc123"}
                ),
            },
        )["result"]
        assert rejected["isError"] is True
        assert 'baseline' in rejected["content"][0]["text"]

        graph = host.request(
            "mcpServer/tool/call",
            {
                "server":    "graphtraj",
                "threadId":  host.thread_id,
                "tool":      MCP_TOOL_NAME,
                "arguments": tool_envelope("task_graph", {}),
            },
        )["result"]

    assert Path(registered["structuredContent"]["task_directory"]).name == (
        "73-shared-graph"
    )
    cli = _cli(installed_commands, project, "task", "graph")
    assert cli.returncode == 0, cli.stderr
    assert graph["structuredContent"] == yaml.safe_load(cli.stdout)
    assert graph["structuredContent"]["tasks"][0]["task_name"] == "shared-graph"


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
            "tool":      'agents' if tool in AGENT_ACTIONS else MCP_TOOL_NAME,
            "arguments": tool_envelope(tool, arguments),
        },
        timeout=60,
    )["result"]
    _record_host_exchange(probe, tool, arguments, result)
    return operation_document(result, tool)


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
        result = _host_tool(host, probe, 'status', {'agent': alias})
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
    from graphtraj.graph.task_graph import register_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    state = harness / ".graphtraj/state"
    register_task(state, harness, _task("113", "managed-probe"))
    (harness / "instruction.md").write_text(
        "Exercise the dispatched child.\n", encoding="utf-8"
    )
    cause = append_project_worldline_event(state, harness, {
        "event":                "main-decision",
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

        dispatched = _host_tool(host, probe, "swarm", {"tasks": [_inline_task()]})
        assert dispatched["isError"] is False, dispatched
        task, = dispatched["structuredContent"]["tasks"]
        assert task["launch_status"] == "launched"
        alias, session = task["alias"], task["session"]
        running = _host_observe(host, probe, alias, "running")
        assert running["session"] == session
        assert running["execution_id"]

        sent = _host_tool(
            host, probe, 'send',
            {'agent': alias, 'message': "unhandled request"},
        )
        assert sent["structuredContent"] == {"alias": alias, "send_status": "sent"}
        waiting = _host_observe(
            host, probe, alias, "running", waiting_for="runtime-request"
        )
        queried = _host_tool(host, probe, 'requests', {'agent': alias})
        request, = queried["structuredContent"]["requests"]
        assert request["execution_id"] == waiting["execution_id"]
        replied = _host_tool(
            host, probe, 'reply',
            {'agent': alias, 'request': request, 'response': {"decision": "accept"}},
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
            host, probe, 'send',
            {'agent': alias, 'message': "request:approval"},
        )
        active = _host_observe(
            host, probe, alias, "running", waiting_for="runtime-request"
        )
        assert active["execution_id"] != completed["execution_id"]
        interrupted = _host_tool(host, probe, 'interrupt', {'agent': alias})
        assert interrupted["structuredContent"] == {
            "alias": alias, "interrupt_status": "interrupted",
            "members": [{"alias": alias, "interrupt_status": "interrupted"}],
        }
        after = _host_observe(host, probe, alias, "idle", "interrupted")
        assert after["execution_id"] == active["execution_id"]
        assert after["session"] == session
        assert _host_tool(host, probe, 'requests', {'agent': alias})[
            "structuredContent"
        ]["requests"] == []

        continued = _host_tool(
            host, probe, "continue",
            {"task_id": "113", "caused_by_event_ids": [cause]},
        )

    # The D.3 continuation is the same operation the CLI exposes; this project
    # has no stopped Team, so both interfaces report the same rejection.
    cli = _runner(
        installed_commands, harness, "continue", "--task-id", "113",
        "--caused-by-event-id", cause, environment=environment,
    )
    assert cli.returncode == 1, cli.stderr
    assert continued["isError"] is True
    assert continued["content"][0]["text"] == (yaml.safe_load(cli.stdout).get("error") or yaml.safe_load(cli.stdout)["tasks"][0]["error"])["message"]

def _native_queue_submissions(protocol: Path) -> list[dict]:
    """Return any native Main queue input the controlled app-server peer received."""

    if not protocol.is_file():
        return []
    messages = [
        json.loads(line) for line in protocol.read_text(encoding="utf-8").splitlines()
    ]
    return [
        message for message in messages if message.get("method") == "thread/queue/add"
    ]


def _await_retained_stop(task_directory: Path, timeout: float = 90) -> None:
    """Wait until Runner retains a budget stop for the Task.

    A dispatch whose member has a native parent route returns after the
    member's registration; its stop is then sampled while the member runs.
    """
    deadline = time.monotonic() + timeout
    while not yaml.safe_load(
        (task_directory / "execution-budget.yml").read_text(encoding="utf-8")
    )["stopped"]:
        assert time.monotonic() < deadline, "the dispatched member was never stopped"
        time.sleep(0.02)


def _assert_native_budget_stop(
    protocol: Path,
    task_directory: Path,
    thread_id: str,
) -> list[dict]:
    """Check one retained stop and its receipt on the actual parent's native route."""
    # The awaited stop can return before the separate parent receipt is retained.
    deadline = time.monotonic() + 10
    while True:
        usage = yaml.safe_load((task_directory / "execution-budget.yml").read_text())
        if all(notice["delivered"] for notice in usage["parent_notices"]):
            break
        assert time.monotonic() < deadline, usage
        time.sleep(0.02)
    assert usage["stopped"] is True
    stops = [notice for notice in usage["parent_notices"]
             if notice["key"] == "stochastic_stop:2"]
    assert len(stops) == 1
    stop = stops[0]
    assert stop["delivered"] is True
    assert not stop.get("channel_written", False)
    event = stop["event"]
    task_id, task_name = task_directory.name.split("-", 1)
    sessions = task_directory.parents[2] / "runner" / "sessions"
    roots = [mapping for file in sessions.glob("*/mapping.yml")
             if (mapping := yaml.safe_load(file.read_text())).get("task_id") == task_id
             and mapping.get("parent") is None]
    assert len(roots) == 1
    alias = roots[0]["alias"]
    assert roots[0]["parent_connection"]["session"] == thread_id
    assert event["task"] == {"task_id": task_id, "task_name": task_name}
    assert event["threshold"] == {"kind": "stochastic_stop", "limit": 2}
    triggered_at = datetime.fromisoformat(event["occurred_at"])
    assert triggered_at.utcoffset() is not None
    assert event["actual"]["elapsed_minutes"] > 0
    assert re.search(r"Elapsed time: \d{2}:\d{2}:\d{2}", stop["message"])

    received = []
    for line in protocol.read_text().splitlines():
        message = json.loads(line)
        params = message.get("params", {})
        if message.get("method") != "turn/start" or "toolOutput" not in params:
            continue
        notice = json.loads(params["toolOutput"]["output"])
        if notice["alias"] == alias and notice["message"] == stop["message"]:
            assert params["input"] == []
            assert params["toolOutput"]["name"] == "graphtraj"
            assert params["threadId"] == thread_id
            assert notice["source"] == "graphtraj"
            assert notice["event"] == "execution-budget-exceeded"
            received.append(message)
    assert len(received) == 1

    receipts = [json.loads(line) for line in
                (sessions / alias / "parent-notices.jsonl")
                .read_text().splitlines()]
    acknowledged = [receipt for receipt in receipts
                    if receipt.get("identity", {}).get("key") == stop["key"]
                    and receipt["delivery"] == "received"]
    assert len(acknowledged) == 1
    assert acknowledged[0]["parent_connection"]["session"] == thread_id
    assert isinstance(acknowledged[0]["at"], (int, float))
    return received


def _controlled_budget_server(
    installed_commands: InstalledCommands,
    fake_codex: FakeCodex,
    harness: Path,
    environment: dict[str, str],
    tmp_path: Path,
    **control: str,
) -> tuple[dict[str, str], Path]:
    """Return a controlled server environment and its Main queue protocol log.

    The budget clock and draw are fixed through a ``sitecustomize`` module the
    server and its Workers inherit. Explicit app-server proxy calls reach the
    Main peer even from a Worker directory; ordinary dispatched Runtime calls
    keep the controlled Runtime executable. ``MCP_MAIN_CWD`` also routes the
    server's caller-discovery queries to the Main peer. ``control`` adds the per-check
    ``BUDGET_CLOCK``, leader clock and release settings.
    """

    controls = tmp_path / "mcp-budget-controls"
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
    bin_directory = tmp_path / "mcp-main-bin"
    bin_directory.mkdir()
    peer = Path(__file__).with_name("codex_stdio_peer.py")
    codex = bin_directory / "codex"
    codex.write_text(
        "#!" + sys.executable + "\n"
        "import os, sys\n"
        "target = (\n"
        "    " + repr(str(peer)) + "\n"
        "    if sys.argv[1:3] == ['app-server', 'proxy'] or os.getcwd() == os.environ['MCP_MAIN_CWD']\n"
        "    else " + repr(str(fake_codex.executable)) + "\n"
        ")\n"
        "os.execv(sys.executable, [sys.executable, target, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    protocol = tmp_path / "mcp-main-protocol.jsonl"
    configured = {
        **environment,
        "CODEX_HOME":                 str(tmp_path / "codex-home"),
        "FAKE_CODEX_APPEND_LOG":       "1",
        "FAKE_CODEX_CAPTURE_ROLE":     "1",
        "FAKE_CODEX_LIFECYCLE_ACTION": "complete-team-round",
        "GRAPHTRAJ_AGENT_RUNNER":      str(installed_commands.runner),
        "MCP_MAIN_CWD":                str(harness),
        "PATH":                        str(bin_directory) + os.pathsep + environment["PATH"],
        "PEER_PROTOCOL_LOG":           str(protocol),
        "PEER_MAIN_THREADS":           'thread-main,thread-one,thread-two,other-caller',
        "PYTHONPATH":                  str(controls),
        **control,
    }
    _associate_native_mains(installed_commands, harness, configured)
    return configured, protocol


def test_installed_mcp_server_returns_a_budget_stop_to_the_request_caller(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """An MCP dispatch with a native parent route stops and notifies its Main once.

    The dispatch returns after registration; the stop reaches the bound Main
    through its native route rather than in the returned document.
    """

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=1))
    clock = tmp_path / "mcp-caller-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    mcp_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_FINAL_LEADER_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
    )
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"
    task = {
        "task_id":   "76",
        "task_name": "session-alias-control",
        "role":        "coding-team.team-leader",
    }

    with _started_mcp(mcp_executable, harness, mcp_environment) as server:
        stopped = server.call(
            "swarm", {"tasks": [task]}, thread_id="thread-main"
        )["result"]
        assert stopped["isError"] is False, stopped
        # The stop is sampled at the leader's final stage, after its children.
        _await_retained_stop(task_directory)

        # Accounting and retention keep the existing shapes and thresholds.
        usage = yaml.safe_load(
            (task_directory / "execution-budget.yml").read_text(encoding="utf-8")
        )
        assert usage["stopped"] is True
        assert len(usage["notifications"]) > 1

        # Bound Main receives the stop through its owning native connection.
        # The separate caller-channel shape remains covered by Adapter tests.
        delivered = _assert_native_budget_stop(protocol, task_directory, "thread-main")
        assert "stop_deliveries" not in stopped["structuredContent"]
        assert _native_queue_submissions(protocol) == []

        # A repeated delivery of one stop stays deduplicated, and a request
        # without Codex caller metadata keeps the generic behaviour.
        repeated = server.call("swarm", {"tasks": [task]})["result"]
        assert repeated["isError"] is True, repeated
        assert repeated["structuredContent"]["tasks"][0]["launch_status"] == "stopped"
        assert "stop_deliveries" not in repeated["structuredContent"]
        assert _assert_native_budget_stop(protocol, task_directory, "thread-main") == delivered
        assert _native_queue_submissions(protocol) == []


def test_installed_runner_returns_a_budget_stop_with_the_awaiting_call(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The installed CLI stops and delivers the notice to its owning Main."""

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=1))
    clock = tmp_path / "cli-caller-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    run_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_FINAL_LEADER_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
    )
    batch = harness / "cli-caller-batch.yml"
    batch.write_text(
        "tasks:\n"
        '  - task_id: "76"\n'
        "    task_name: session-alias-control\n"
        "    role: coding-team.team-leader\n",
        encoding="utf-8",
    )
    completed = run_process(
        [str(installed_commands.runner), "--swarm-input", str(batch)],
        cwd=harness,
        env={**run_environment, "CODEX_THREAD_ID": "thread-main"},
        timeout=300,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    document = yaml.safe_load(completed.stdout)
    assert document["tasks"][0]["launch_status"] == "stopped"
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"
    _assert_native_budget_stop(protocol, task_directory, "thread-main")
    assert "stop_deliveries" not in document
    assert _native_queue_submissions(protocol) == []


def test_installed_mcp_server_returns_each_caller_its_own_stop(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """Two request identities served by one server do not cross-deliver."""

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task
    from test_task_graph import _change_status, _register, _task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=1))
    _register(
        installed_commands,
        harness,
        {**_task("77", "mcp-cross-caller"), "body": _budget_body(total=1)},
    )
    _change_status(installed_commands, harness, "77", "ready")
    clock = tmp_path / "mcp-cross-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    mcp_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_FINAL_LEADER_CLOCK=str(clock),
    )
    tasks = {
        "76": {
            "task_id":   "76",
            "task_name": "session-alias-control",
            "role":        "coding-team.team-leader",
        },
        "77": {
            "task_id":   "77",
            "task_name": "mcp-cross-caller",
            "role":        "coding-team.team-leader",
        },
    }

    with _started_mcp(mcp_executable, harness, mcp_environment) as server:
        for task_id, thread_id in (("76", "thread-one"), ("77", "thread-two")):
            stopped = server.call(
                "swarm", {"tasks": [tasks[task_id]]}, thread_id=thread_id
            )["result"]
            assert stopped["isError"] is False, stopped
            task_directory = harness / ".graphtraj/state/tasks" / (
                task_id + "-" + tasks[task_id]["task_name"]
            )
            _await_retained_stop(task_directory)
            _assert_native_budget_stop(
                protocol, task_directory, thread_id,
            )
            assert "stop_deliveries" not in stopped["structuredContent"]

        assert _native_queue_submissions(protocol) == []


def test_installed_mcp_swarm_returns_after_registration_and_stops_on_the_native_route(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A Main with a native parent route gets its swarm result while the member runs.

    The member's later stop still reaches that Main once through the native
    route, with no further call from it; another Main's call carries nothing.
    """

    from graphtraj.execution.runner_process import process_is_alive
    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=0.01))
    started = time.time()
    clock = tmp_path / "mcp-registration-clock"
    clock.write_text(str(started), encoding="utf-8")
    # Absent release file: the controlled Runtime holds its first turn open.
    release = tmp_path / "mcp-registration-release"
    mcp_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
        FAKE_CODEX_RELEASE_FILE=str(release),
    )
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"
    task = {
        "task_id":   "76",
        "task_name": "session-alias-control",
        "role":        "coding-team.team-leader",
    }

    with _started_mcp(mcp_executable, harness, mcp_environment) as server:
        try:
            launched = server.call(
                "swarm", {"tasks": [task]}, thread_id="thread-main"
            )["result"]
            assert launched["isError"] is False, launched
            alias = launched["structuredContent"]["tasks"][0]["alias"]
            mapping = yaml.safe_load(
                (harness / ".graphtraj/runner/sessions" / alias / "mapping.yml").read_text()
            )
            assert mapping["parent_connection"]["session"] == "thread-main"
            assert process_is_alive(mapping["worker_pid"]), "swarm waited for the Worker to exit"

            clock.write_text(str(started + 260), encoding="utf-8")
            _await_retained_stop(task_directory)
            delivered = _assert_native_budget_stop(protocol, task_directory, "thread-main")
        finally:
            release.touch()

        observed = server.call(
            'status', {'agent': alias}, thread_id="other-caller"
        )["result"]
        assert observed["isError"] is False
        assert "stop_deliveries" not in observed["structuredContent"]
        assert _assert_native_budget_stop(protocol, task_directory, "thread-main") == delivered
        assert _native_queue_submissions(protocol) == []


def test_installed_mcp_server_does_not_queue_a_late_stop_without_a_waiting_call(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """A stop sampled after the tool call returned has no in-band carrier.

    A generic request resumes detached work without a caller channel. Its later
    stop stays retained in the Task's budget state and is not attached to a
    different caller's next request or queued into Main's native input.
    """

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=0.01))
    started = time.time()
    clock = tmp_path / "mcp-late-clock"
    clock.write_text(str(started), encoding="utf-8")
    # The controlled Runtime holds the resumed Session open only after the
    # dispatch, exactly like the CLI late-notice check.
    release = tmp_path / "mcp-late-release"
    release.touch()
    mcp_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
        FAKE_CODEX_RELEASE_FILE=str(release),
    )
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"
    task = {
        "task_id":   "76",
        "task_name": "session-alias-control",
        "role":        "coding-team.team-leader",
    }

    with _started_mcp(mcp_executable, harness, mcp_environment) as server:
        launched = server.call(
            "swarm", {"tasks": [task]}, thread_id="thread-main"
        )["result"]
        assert launched["isError"] is False, launched
        alias = launched["structuredContent"]["tasks"][0]["alias"]
        assert _native_queue_submissions(protocol) == []
        cause = [
            json.loads(line)["event_id"]
            for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ][-1]

        release.unlink()
        try:
            sent = server.call(
                'send',
                {'agent': alias, 'message': "Inspect the retained result."},
            )["result"]
            assert sent["isError"] is False, sent
            sent_task = sent['structuredContent']
            assert sent_task['alias'] == alias and sent_task['send_status'] == 'sent'
            assert sent_task['session'] == launched['structuredContent']['tasks'][0]['session']
            assert sent_task['execution_id']
            clock.write_text(str(started + 260), encoding="utf-8")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if yaml.safe_load(
                    (task_directory / "execution-budget.yml").read_text(encoding="utf-8")
                )["stopped"]:
                    break
                time.sleep(0.02)
        finally:
            release.touch()

        observed = server.call(
            'status', {'agent': alias}, thread_id="other-caller"
        )["result"]
        assert observed["isError"] is False
        assert "stop_deliveries" not in observed["structuredContent"]
        assert _native_queue_submissions(protocol) == []

    usage = yaml.safe_load((task_directory / "execution-budget.yml").read_text(encoding="utf-8"))
    assert usage["stopped"] is True


def test_installed_mcp_server_keeps_the_continue_path_on_the_request_caller(
    installed_commands: InstalledCommands,
    mcp_executable: Path,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """The D.3 continuation runs on the caller binding it started over."""

    from test_execution_budgets import _budget_body
    from test_session_alias_control import _register_ready_task
    from test_task_graph import _task

    harness, _, _, environment = configure_harness(
        installed_commands, temporary_git_repository, fake_codex, tmp_path,
    )
    require_no_retro_skill(harness)
    _register_ready_task(installed_commands, harness, body=_budget_body(total=1))
    clock = tmp_path / "mcp-continue-clock"
    clock.write_text(str(time.time()), encoding="utf-8")
    mcp_environment, protocol = _controlled_budget_server(
        installed_commands,
        fake_codex,
        harness,
        environment,
        tmp_path,
        BUDGET_CLOCK=str(clock),
        FAKE_CODEX_CAPTURE_STDIN="1",
        FAKE_CODEX_FINAL_LEADER_CLOCK=str(clock),
    )
    task_directory = harness / ".graphtraj/state/tasks/76-session-alias-control"
    task = {
        "task_id":   "76",
        "task_name": "session-alias-control",
        "role":        "coding-team.team-leader",
    }

    with _started_mcp(mcp_executable, harness, mcp_environment) as server:
        stopped = server.call(
            "swarm", {"tasks": [task]}, thread_id="thread-main"
        )["result"]
        assert stopped["isError"] is False, stopped
        _await_retained_stop(task_directory)
        _assert_native_budget_stop(
            protocol, task_directory, "thread-main",
        )
        assert "stop_deliveries" not in stopped["structuredContent"]
        assert _native_queue_submissions(protocol) == []

        # Main records the continuation decision and revises the retained budget,
        # exactly as the accepted D.3 flow requires.
        diagnosis = harness / "stopped-team-diagnosis.md"
        diagnosis.write_text(
            "Main diagnosed the sampled stop and chose continuation.\n",
            encoding="utf-8",
        )
        stop_event = [
            json.loads(line)["event_id"]
            for path in (harness / ".graphtraj/state/worldline").glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ][-1]
        decision_file = _write(
            harness / "continuation-decision.yml",
            {
                "event":                "task-continuation-decided",
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
        revision = _write(
            harness / "continuation-budget-revision.yml",
            {
                "product_preserving":  True,
                "caused_by_event_ids": [decision_id],
                "evidence_refs":       ["stopped-team-diagnosis.md"],
                "tasks":             [
                    {
                        **_task("76", "session-alias-control"),
                        "body":        _budget_body(
                            total=10,
                            revision_reason="Main accepted the retained stop diagnosis.",
                        ),
                        "current_definition": "task.md",
                    }
                ],
            },
        )
        revised = _cli(
            installed_commands, harness, "task", "revise",
            "--revision-file", str(revision),
        )
        assert revised.returncode == 0, revised.stderr

        continued = server.call(
            "continue",
            {"task_id": "76", "caused_by_event_ids": [decision_id]},
            thread_id="thread-main",
        )["result"]
        assert continued["isError"] is False, continued
        continuation = continued["structuredContent"]
        assert continuation["continuation_event_id"]
        # A continuation that did not stop again submits nothing new, even
        # though the same binding served it.
        assert continuation["tasks"]
        assert all(task["send_status"] == "sent" for task in continuation["tasks"])
        assert continuation["continuation_event_id"]
        # The continuation is served by the same request-scoped caller binding
        # and delivers no new stop.
        assert "stop_deliveries" not in continuation
        assert _native_queue_submissions(protocol) == []

    from runner_fixtures import wait_for_task_status
    wait_for_task_status(installed_commands, harness, "76", "awaiting-integration")
    after = yaml.safe_load((task_directory / "task.yml").read_text(encoding="utf-8"))
    assert after["status"] == "awaiting-integration"
    usage = yaml.safe_load((task_directory / "execution-budget.yml").read_text(encoding="utf-8"))
    assert usage["stopped"] is False
