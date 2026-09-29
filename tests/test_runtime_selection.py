"""First task preparation consumes the selected Runtime's actual Context."""

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import FakeCodex
from graphtraj.execution.runner_batch import retain_batch
from graphtraj.execution.runner_capacity import capacity_positions
from graphtraj.execution.runner_launch import launch_swarm
from graphtraj.execution.runner_models import Batch, Project, RunnerError
from graphtraj.graph.ticket_graph import register_ticket, update_ticket_state
from graphtraj.runtimes import runtime_adapter
from graphtraj.teams import team_round
from graphtraj.workspace.project_initialization import plan_project_setup
from test_ticket_graph import _ticket


class Prepared(Exception):
    """Stop the probe at the native Worker handoff, after real preparation."""


class TestContext:
    """Distinct test Context with no Codex request representation."""

    __test__ = False
    runtime = "test-runtime"

    def finalize(self) -> "TestContext":
        """Freeze the test preparation."""
        return self

    def launch_document(self) -> dict[str, Any]:
        """Return a request whose shape is owned by the test Adapter."""
        return {"runtime": self.runtime, "test_request": {"prepared": True}}

    def evidence_document(self) -> dict[str, Any]:
        """Return distinct evidence consumed by Runner."""
        return {"test_evidence": "selected"}

    def session_document(self) -> dict[str, Any]:
        """Return the test Runtime's native Session settings."""
        return {"test_session": True}

    def runtime_environment(self) -> dict[str, str]:
        """Return a distinguishable Worker environment."""
        return {"TEST_RUNTIME_SELECTED": "yes"}


@pytest.mark.parametrize("runtime", ["codex", "test-runtime", "unsupported"])
def test_first_task_preparation_uses_selected_context(
    runtime: str,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public launch prepares Codex or an injected Adapter, and rejects others."""
    root = temporary_git_repository.parent
    monkeypatch.setenv("HOME", str(tmp_path / "operator"))
    monkeypatch.setenv(
        "PATH", str(fake_codex.executable.parent) + os.pathsep + os.environ["PATH"],
    )
    monkeypatch.setenv("TEST_WORK_KEY", "fixture-only-key")
    plan_project_setup(root, temporary_git_repository).apply()
    roles_path = root / ".graphtraj/roles.yml"
    roles_path.write_text(yaml.safe_dump({
        "roles": {"author": {
            "runtime": runtime, "model": "selected-model",
            "reasoning_effort": "low", "worktree_access": "read",
            "reports": ["evidence.md"],
            "base_url": "https://work.example/v1", "api_key_env": "TEST_WORK_KEY",
            "codex": {"approval": {
                "model": "review-model", "base_url": "https://review.example/v1",
                "api_key_env": "TEST_REVIEW_KEY",
            }},
        }},
        "role_tree": {"author": {}},
    }))
    roles_before = roles_path.read_bytes()
    state = root / ".graphtraj/state"
    register_ticket(state, root, _ticket("213", "runtime-selection"))
    (root / "ready.md").write_text("Authorized preparation probe.\n")
    update_ticket_state(state, root, {
        "ticket_id": "213", "status": "ready", "active_team_ordinal": None,
        "worktree": None, "branch": None, "current_candidate": None,
        "caused_by_event_ids": [], "evidence_refs": ["ready.md"],
    })
    selected = []
    original_select = runtime_adapter.select_runtime_adapter

    class TestAdapter:
        """Supply a Context through the same first-preparation boundary."""

        def preflight_runtime_context(self, **kwargs: Any) -> TestContext:
            """Observe resolved settings without depending on Codex internals."""
            assert kwargs["role"].settings.runtime == "test-runtime"
            assert kwargs["role"].settings.model == "selected-model"
            assert kwargs["report_files"][0].name == "evidence.md"
            assert kwargs["worktree"].is_dir()
            store = kwargs["harness_root"] / "test-runtime-data"
            store.mkdir()
            (store / "context.txt").write_text("prepared")
            return TestContext()

    def select(name: str) -> runtime_adapter.RuntimePreparationAdapter:
        """Inject only the test Runtime at the common selection point."""
        selected.append(name)
        return TestAdapter() if name == "test-runtime" else original_select(name)

    def in_process_batch(
        project: Project,
        batch: Batch,
        retained: Path | None = None,
        parent_alias: str = "",
        capacity_fd: int | None = None,
    ) -> None:
        """Run task preparation in process so the selection injection is local."""
        with capacity_positions(project, 1, capacity_fd) as positions:
            team_round._deliver_ticket(
                project, batch.tasks[0], retain_batch(project.state_directory, batch),
                positions[0].fileno(),
            )

    handoff = {}

    def observe_worker(*args: Any) -> None:
        """Capture the actual durable launch and environment before execution."""
        handoff["launch"] = yaml.safe_load(args[1].read_text())
        handoff["environment"] = args[4]
        raise Prepared()

    monkeypatch.setattr(runtime_adapter, "select_runtime_adapter", select)
    monkeypatch.setattr(team_round, "_run_batch_workers", in_process_batch)
    monkeypatch.setattr(team_round, "_run_session_worker", observe_worker)
    request = {"tasks": [{"ticket_id": "213", "role": "author"}]}
    if runtime == "unsupported":
        with pytest.raises(RunnerError) as failure:
            launch_swarm(request, root)
        assert failure.value.code == "RUNTIME_UNSUPPORTED"
        assert failure.value.message == (
            "The selected Agent Runtime is not supported by this Runner."
        )
        assert not handoff
        assert not list((root / ".graphtraj/runner/sessions").glob("*/launch.yml"))
    else:
        with pytest.raises(Prepared):
            launch_swarm(request, root)
        launch = handoff["launch"]
        assert launch["runtime"] == launch["mapping"]["runtime"] == runtime
        assert launch["mapping"]["role"] == "author"
        assert launch["mapping"]["report_files"] == [
            ".state/teams/1/rounds/1/evidence.md"
        ]
        if runtime == "test-runtime":
            assert (root / "test-runtime-data/context.txt").read_text() == "prepared"
            assert not (root / ".codex").exists()
            assert launch["test_request"] == {"prepared": True}
            assert launch["context_evidence"] == {"test_evidence": "selected"}
            assert handoff["environment"]["TEST_RUNTIME_SELECTED"] == "yes"
        else:
            assert launch["context_evidence"]["model"] == "selected-model"
            parameters = launch["adapter_request"]["session_parameters"]
            assert parameters["model"] == "selected-model"
            assert parameters["config"]["model_reasoning_effort"] == "low"
            assert launch["connection"] == {
                "base_url": "https://work.example/v1", "api_key_env": "TEST_WORK_KEY",
            }
            assert launch["adapter_request"]["approval"] == {
                "model": "review-model", "base_url": "https://review.example/v1",
                "api_key_env": "TEST_REVIEW_KEY",
            }
            assert handoff["environment"]["OPENAI_API_KEY"] == "fixture-only-key"
            assert "fixture-only-key" not in yaml.safe_dump(launch)
    assert roles_path.read_bytes() == roles_before
    assert selected == [runtime]
    assert not fake_codex.log_file.exists()
