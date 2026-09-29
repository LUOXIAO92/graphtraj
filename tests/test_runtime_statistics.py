"""The public operation total is interpreted by the Session's Runtime Adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from graphtraj.configuration.project_configuration import default_configuration_content
from graphtraj.execution.runner_status import status_aliases
from graphtraj.runtimes import runtime_adapter


def _record(payload: str) -> str:
    """Render one complete native Codex record line."""
    return '{"type":"response_item","payload":' + payload + "}\n"


COMPLETE_RECORDS = (
    _record('{"type":"custom_tool_call","call_id":"call-exec"}')
    + _record('{"type":"custom_tool_call","call_id":"call-exec"}')
    + _record('{"type":"custom_tool_call_output","call_id":"call-exec"}')
    + _record('{"type":"function_call","call_id":"call-mcp"}')
    + _record('{"type":"local_shell_call","id":"legacy-shell"}')
    + _record('{"type":"tool_search_call","id":"call-tool-search"}')
    + _record('{"type":"web_search_call","id":"web-search"}')
    + _record('{"type":"image_generation_call","id":"image-generation"}')
    + '{"type":"event_msg","payload":{"type":"item_completed"}}\n'
)
EXPECTED_CODEX_OPERATIONS = 6


@pytest.fixture
def harness(tmp_path: Path) -> Path:
    """Prepare an empty Harness Project Root for one status observation."""
    configuration = tmp_path / ".graphtraj" / "config.yml"
    configuration.parent.mkdir(parents=True)
    configuration.write_text(default_configuration_content(tmp_path, tmp_path))
    return tmp_path


def _session(root: Path, alias: str, runtime: str, trace_text: str) -> Path:
    """Write one recorded Session and its native Trace, without a Runtime."""
    directory = root / ".graphtraj" / "runner" / "sessions" / alias
    directory.mkdir(parents=True)
    (directory / "execution.yml").write_text("outcome: completed\n", encoding="utf-8")
    trace = directory / "native.jsonl"
    trace.write_text(trace_text, encoding="utf-8")
    (directory / "mapping.yml").write_text(
        yaml.safe_dump(
            {
                "alias": alias,
                "runtime": runtime,
                "session": "native-session",
                "ticket_id": "216",
                "team_generation": 1,
                "role": "engineer",
                "parent": None,
                "retained_batch_file": "batch.yml",
                "worktree_path": str(root),
                "trace_file": str(trace),
                "worker_pid": 1,
                "runtime_pid": 1,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return trace


def _alias(document: dict, alias: str) -> dict:
    """Return one alias' status document from the public response."""
    return next(entry for entry in document["aliases"] if entry["alias"] == alias)


@pytest.mark.parametrize(
    ("trailing", "expected"),
    [
        (_record('{"type":"custom_tool_call","call_id":"unwritten"}').rstrip("\n"),
         EXPECTED_CODEX_OPERATIONS),
        (_record('{"type":"custom_tool_call","call_id":"written"}'),
         EXPECTED_CODEX_OPERATIONS + 1),
    ],
)
def test_codex_statistics_are_preserved(
    harness: Path, trailing: str, expected: int
) -> None:
    """Codex counts one operation per call ID and ignores an unfinished record."""
    _session(harness, "codex-stats@e1", "codex", COMPLETE_RECORDS + trailing)

    status = status_aliases(["codex-stats@e1"], harness, operation_total=True)

    assert status.succeeded
    assert _alias(status.document, "codex-stats@e1")["operation_total"] == expected


def test_selected_adapter_supplies_its_own_operation_total(
    harness: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different-format Adapter returns its statistic through public status."""

    class CountingAdapter:
        """A Runtime that counts its own operation records."""

        def operation_total(self, trace_file: Path, session: str) -> int:
            """Count the test Runtime's own operation lines."""
            assert session == "native-session"
            return sum(
                1
                for line in trace_file.read_text(encoding="utf-8").splitlines()
                if line.startswith("operation ")
            )

    _session(
        harness, "test-runtime@e1", "test-runtime",
        "operation one\noperation two\nnoise\n",
    )
    injected: list[str] = []
    original_select = runtime_adapter.select_runtime_adapter

    def select(runtime: str) -> runtime_adapter.RuntimePreparationAdapter:
        """Inject the test Runtime only at the common selection point."""
        injected.append(runtime)
        return (
            CountingAdapter() if runtime == "test-runtime"
            else original_select(runtime)
        )

    monkeypatch.setattr(runtime_adapter, "select_runtime_adapter", select)

    status = status_aliases(["test-runtime@e1"], harness, operation_total=True)

    assert status.succeeded
    assert _alias(status.document, "test-runtime@e1")["operation_total"] == 2
    assert injected == ["test-runtime"]


def test_unknown_runtime_is_reported_per_alias(harness: Path) -> None:
    """An unselectable Runtime is unsupported for its alias, never zero."""
    _session(harness, "codex-stats@e1", "codex", COMPLETE_RECORDS)
    _session(harness, "other-runtime@e1", "other-runtime", "")

    status = status_aliases(
        ["other-runtime@e1", "codex-stats@e1"], harness, operation_total=True
    )

    assert not status.succeeded
    assert _alias(status.document, "other-runtime@e1")["error"] == {
        "code": "unsupported-runtime",
        "message": "The selected Agent Runtime is not supported by this Runner.",
    }
    assert _alias(status.document, "codex-stats@e1")["operation_total"] == (
        EXPECTED_CODEX_OPERATIONS
    )


def test_invalid_native_record_is_a_diagnostic_failure(harness: Path) -> None:
    """A record the Adapter cannot read fails instead of counting zero."""
    _session(harness, "broken-stats@e1", "codex", "not a native record\n")

    status = status_aliases(["broken-stats@e1"], harness, operation_total=True)

    assert not status.succeeded
    assert _alias(status.document, "broken-stats@e1")["error"] == {
        "code": "operation-failed",
        "message": "The requested Session diagnostics could not be read.",
    }
