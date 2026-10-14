"""Local custom-tool binding and the structured stdio bridge, without MCP."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.interfaces import gateway, local_tool, tools


ISSUE = {
    "task_id":   "900",
    "task_name": "probe-task",
    "source":      "https://github.com/example/project/issues/900",
    "title":       "Probe Task",
    "body":        "Deliver probe.",
    "dependencies": [],
}


@pytest.mark.parametrize("body", [ISSUE["body"], "---\ntask_type: research\n---\n\nA research task."])
def test_graph_monitor_reads_title_without_changing_delivery(project: Path, body: str) -> None:
    """The desktop's public read seam returns authored labels and delivery facts."""
    call = local_tool.bind(cwd=project)
    registered = call({
        "action": "execute", "feature": "task_register",
        "arguments": {**ISSUE, "title": "A human-readable graph title", "body": body},
    })
    assert not registered.failed
    request = {"action": "execute", "feature": "task_graph", "arguments": {}}
    observed = local_tool.answer(request, cwd=project, allowed_features=["task_graph"])
    assert observed["result"]["tasks"][0]["title"] == "A human-readable graph title"
    assert observed["result"]["tasks"][0]["status"] == "pending"
    assert local_tool.answer(request, cwd=project, allowed_features=["task_graph"]) == observed
    refused = local_tool.answer({
        "action": "execute", "feature": "task_register", "arguments": ISSUE,
    }, cwd=project, allowed_features=["task_graph"])
    assert refused["failed"]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a configured local project and controlled material for task_graph."""
    configuration = tmp_path / ".graphtraj/config.yml"
    configuration.parent.mkdir()
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    (tmp_path / "task-graph.md").write_text(
        "Fixture manual for task_graph.", encoding="utf-8"
    )
    # A relative reference resolves to the distribution's delivered data
    # location, so point that location at the fixture material.
    monkeypatch.setattr(gateway, "delivered_manuals_root", lambda: tmp_path)
    monkeypatch.setitem(tools.TOOLS, "task_graph", replace(
        tools.TOOLS["task_graph"], manual_ref="task-graph.md",
    ))
    # Ambient-directory handlers read the process working directory, exactly as
    # the host's spawned bridge process does.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_descriptor_registers_one_tool_over_the_shared_schema() -> None:
    """A host registers one graphtraj tool and no private schema copy."""
    descriptor = local_tool.tool_descriptor()
    assert descriptor["name"] == "graphtraj"
    assert descriptor["description"] == local_tool.TOOL_DESCRIPTION
    assert descriptor["input_schema"] is gateway.INPUT_SCHEMA
    assert set(descriptor["input_schema"]["properties"]) == {
        "action", "query", "feature", "arguments", "schema",
    }


def test_python_binding_discovers_describes_reads_and_writes(project: Path) -> None:
    """The direct binding performs discovery, description, graph read and a write."""
    call = local_tool.bind(cwd=project)

    discovered = call({"action": "discover", "query": "graph"})
    assert discovered.document["features"][0]["feature"] == "task_graph"

    described = call({"action": "describe", "feature": "task_graph"})
    assert Path(described.document["manual_ref"]).read_text() == "Fixture manual for task_graph."
    assert set(described.document) == {"feature", "description", "manual_ref"}
    parameters = call({"action": "describe", "feature": "task_graph", "schema": True})
    assert parameters.document == {"input_schema": tools.TOOLS["task_graph"].input_schema}

    assert call({"action": "execute", "feature": "task_graph", "arguments": {}}).document == {"schema_version": 2, "tasks": []}
    written = call({"action": "execute", "feature": "task_register", "arguments": ISSUE})
    assert not written.failed

    tasks = call({"action": "execute", "feature": "task_graph", "arguments": {}}).document["tasks"]
    assert [task["task_id"] for task in tasks] == ["900"]


def test_host_context_is_not_taken_from_the_request(project: Path) -> None:
    """Smuggled context fields are rejected and later calls still run."""
    call = local_tool.bind(cwd=project)
    smuggled = [
        {"action": "execute", "feature": "task_graph", "arguments": {}, "cwd": "/tmp"},
        {"action": "execute", "feature": "task_graph", "arguments": {},
         "allowed_features": ["task_register"]},
        {"action": "execute", "feature": "task_graph", "arguments": {"actor": "Main"}},
    ]
    for request in smuggled:
        rejected = call(request)
        assert rejected.failed
        assert "error" in rejected.document

    assert not call({"action": "execute", "feature": "task_graph", "arguments": {}}).failed


def test_host_launch_boundary_restricts_features(project: Path) -> None:
    """The binding's feature restriction comes from the host, not the request."""
    call = local_tool.bind(cwd=project, allowed_features=("task_graph",))
    assert [item["feature"] for item in call({"action": "discover"}).document["features"]] == ["task_graph"]

    denied = call({"action": "execute", "feature": "task_register", "arguments": ISSUE})
    assert denied.failed
    assert "Unknown feature" in denied.document["error"]
    assert not call({"action": "execute", "feature": "task_graph", "arguments": {}}).failed


def test_launch_option_restricts_features(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bridge command reads its feature restriction from the launch options."""
    monkeypatch.setattr(sys, "argv", ["graphtraj-tool", "--allowed-features", "task_graph"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join([
        json.dumps({"action": "discover"}),
        json.dumps({"action": "execute", "feature": "task_register", "arguments": ISSUE}),
        json.dumps({"action": "execute", "feature": "task_graph", "arguments": {}}),
    ]) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)

    local_tool.main()

    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [item["feature"] for item in replies[0]["result"]["features"]] == ["task_graph"]
    assert replies[1]["failed"] and "Unknown feature" in replies[1]["result"]["error"]
    assert replies[2]["result"] == {"schema_version": 2, "tasks": []}


def test_bridge_answers_bad_requests_and_keeps_serving(project: Path) -> None:
    """Bad lines, unknown requests and rejections do not end the stream."""
    lines = [
        json.dumps({"action": "discover", "query": "graph"}),
        "not json",
        json.dumps(["not", "an", "object"]),
        json.dumps({"action": "other"}),
        json.dumps({"action": "execute", "feature": "unknown", "arguments": {}}),
        json.dumps({"action": "describe", "feature": "task_graph"}),
        json.dumps({"action": "execute", "feature": "task_graph", "arguments": {}}),
        json.dumps({"action": "execute", "feature": "task_register", "arguments": ISSUE}),
        json.dumps({"action": "execute", "feature": "task_graph", "arguments": {}}),
    ]
    output = io.StringIO()
    local_tool.serve(io.StringIO("\n".join(lines) + "\n"), output, cwd=project)

    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(replies) == len(lines)
    assert replies[0]["result"]["features"][0]["feature"] == "task_graph"
    assert replies[1] == {"failed": True, "error": "Parse error"}
    assert replies[2] == {"failed": True, "error": "Invalid request"}
    assert replies[3]["failed"] and "error" in replies[3]["result"]
    assert replies[4]["failed"] and "Unknown feature" in replies[4]["result"]["error"]
    assert Path(replies[5]["result"]["manual_ref"]).read_text() == "Fixture manual for task_graph."
    assert replies[6]["result"] == {"schema_version": 2, "tasks": []}
    assert not replies[7]["failed"]
    assert Path(replies[7]["result"]["task_directory"]).is_dir()
    assert [task["task_id"] for task in replies[8]["result"]["tasks"]] == ["900"]


def test_process_bridge_uses_launch_context_without_mcp(project: Path) -> None:
    """A spawned process serves requests from its launch directory, never MCP."""
    source = Path(__file__).resolve().parents[1] / "src"
    script = '''
import sys
from dataclasses import replace
from pathlib import Path

class NoMcp:
    """Fail any local tool path that imports the MCP entry point."""
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "graphtraj.interfaces.mcp":
            raise ModuleNotFoundError("MCP is unavailable")

source = sys.argv[1]
sys.meta_path.insert(0, NoMcp())
sys.path.insert(0, source)
from graphtraj.interfaces import local_tool, tools
assert Path(tools.__file__).is_relative_to(Path(source)), tools.__file__
tools.TOOLS["task_graph"] = replace(
    tools.TOOLS["task_graph"],
    manual_ref=str(Path(sys.argv[2]) / "task-graph.md"),
)
sys.argv = ["graphtraj-tool"]
local_tool.main()
sys.stderr.write("mcp_imported={0}\\n".format("graphtraj.interfaces.mcp" in sys.modules))
'''
    lines = [
        "not json",
        json.dumps({"action": "discover", "query": "graph"}),
        json.dumps({"action": "describe", "feature": "task_graph"}),
        json.dumps({"action": "execute", "feature": "task_graph", "arguments": {}}),
        json.dumps({"action": "execute", "feature": "task_register", "arguments": ISSUE}),
    ]
    completed = subprocess.run(
        [sys.executable, "-c", script, str(source), str(project)],
        input="\n".join(lines) + "\n",
        cwd=project, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "mcp_imported=False" in completed.stderr

    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert replies[0] == {"failed": True, "error": "Parse error"}
    assert replies[1]["result"]["features"][0]["feature"] == "task_graph"
    assert Path(replies[2]["result"]["manual_ref"]).read_text() == "Fixture manual for task_graph."
    assert replies[3]["result"] == {"schema_version": 2, "tasks": []}
    assert not replies[4]["failed"]
    # The write landed in the host's launch directory, not the test process one.
    assert (project / ".graphtraj/state/tasks/900-probe-task").is_dir()


def test_event_receiver_is_trusted_host_context_and_has_explicit_lifetime(project: Path) -> None:
    """Closing a host binding prevents further calls; model input cannot bind a receiver."""
    from graphtraj.execution.runner_models import RunnerError

    with local_tool.bind(project, event_receiver=lambda event: None) as call:
        rejected = call({'action': 'execute', 'feature': 'task_graph',
                         'arguments': {}, 'event_receiver': 'replace owner'})
        assert rejected.failed
        assert not call({'action': 'execute', 'feature': 'task_graph', 'arguments': {}}).failed
    with pytest.raises(RunnerError, match='closed'):
        call({'action': 'execute', 'feature': 'task_graph', 'arguments': {}})
