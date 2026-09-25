from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from conftest import InstalledCommands, run_process
from graphtraj.graph.delivery_state import _validate_implementation_rejection
from test_ticket_graph import _configure, _register, _ticket, _change_status


_CANDIDATE = "a" * 40
_COMPARISON = "b" * 40
_LEADER_REJECTION = (
    "Decision: REJECT\nDiagnosis: implementation\nReviews: compliant\n"
    "Action: rework\nRationale: bounded correction.\n"
)
_FINDING = (
    "Finding: Missing delivered content\n"
    "Rule: Accepted Ticket delivery requirement\n"
    "Input: Run the delivered command\n"
    "Trace: The command reads TEAM_ROUND_DELIVERED.txt\n"
    "Failure: Required content is missing\n"
    "Evidence: TEAM_ROUND_DELIVERED.txt:1\n"
)


def _review_report(
    axis: str,
    finding: str,
    candidate: str = _CANDIDATE,
    comparison: str = _COMPARISON,
) -> str:
    return "Candidate commit: {0}\nAxis: {1}\nComparison: {2}\n{3}".format(
        candidate, axis, comparison, finding
    )


def _write_round_directory(directory: Path, reports: dict[str, str]) -> None:
    directory.mkdir()
    (directory / "leader.md").write_text(_LEADER_REJECTION, encoding="utf-8")
    for name, text in reports.items():
        (directory / name).write_text(text, encoding="utf-8")


def _write_rework_reports(directory: Path, standards: str, spec: str) -> None:
    _write_round_directory(
        directory,
        {
            "standards.md": _review_report("Standards", standards),
            "spec.md": _review_report("Spec", spec),
        },
    )


def test_implementation_rejection_without_selected_review_reports(tmp_path: Path) -> None:
    reports = tmp_path / "round"
    _write_round_directory(reports, {})

    _validate_implementation_rejection(reports, _CANDIDATE)


def test_implementation_rejection_with_one_selected_review_report(tmp_path: Path) -> None:
    reports = tmp_path / "round"
    _write_round_directory(reports, {"standards.md": _review_report("Standards", _FINDING)})

    _validate_implementation_rejection(reports, _CANDIDATE)


@pytest.mark.parametrize(
    "reports",
    (
        {"standards.md": _review_report("Standards", _FINDING, candidate="c" * 40)},
        {
            "standards.md": _review_report("Standards", _FINDING),
            "spec.md": _review_report("Spec", _FINDING, comparison="c" * 40),
        },
        {
            "standards.md": "Candidate commit: {0}\nComparison: {1}\n{2}".format(
                _CANDIDATE, _COMPARISON, _FINDING
            )
        },
        {"standards.md": _review_report("Standards", "Finding: none\n")},
    ),
    ids=("wrong-candidate", "mismatched-comparison", "missing-axis-field", "no-implementation-finding"),
)
def test_implementation_rejection_rejects_invalid_selected_reports(
    tmp_path: Path, reports: dict[str, str]
) -> None:
    directory = tmp_path / "round"
    _write_round_directory(directory, reports)

    with pytest.raises(ValueError):
        _validate_implementation_rejection(directory, _CANDIDATE)


@pytest.mark.parametrize(
    "leader",
    (
        _LEADER_REJECTION.replace("Decision: REJECT", "Decision: ACCEPT"),
        _LEADER_REJECTION.replace("Rationale: bounded correction.\n", ""),
    ),
    ids=("wrong-decision", "missing-rationale"),
)
def test_implementation_rejection_requires_a_confirmed_leader_rejection(
    tmp_path: Path, leader: str
) -> None:
    directory = tmp_path / "round"
    directory.mkdir()
    (directory / "leader.md").write_text(leader, encoding="utf-8")

    with pytest.raises(ValueError):
        _validate_implementation_rejection(directory, _CANDIDATE)


def test_implementation_rejection_requires_a_leader_report(tmp_path: Path) -> None:
    directory = tmp_path / "round"
    directory.mkdir()

    with pytest.raises(FileNotFoundError):
        _validate_implementation_rejection(directory, _CANDIDATE)


def test_implementation_rejection_allows_explanation_after_none(tmp_path: Path) -> None:
    reports = tmp_path / "round"
    _write_rework_reports(
        reports,
        "Finding: none\nExplanation: prose may contain Finding: without a field.\n",
        _FINDING,
    )

    _validate_implementation_rejection(reports, _CANDIDATE)


@pytest.mark.parametrize(
    ("standards", "spec", "axis"),
    (
        ("Finding: none\n", _FINDING.removesuffix("Evidence: TEAM_ROUND_DELIVERED.txt:1\n"), "Spec"),
        ("Finding: none\n" + _FINDING, _FINDING, "Standards"),
    ),
)
def test_implementation_rejection_reports_the_axis_for_invalid_findings(
    tmp_path: Path, standards: str, spec: str, axis: str
) -> None:
    reports = tmp_path / "round"
    _write_rework_reports(reports, standards, spec)

    with pytest.raises(ValueError) as error:
        _validate_implementation_rejection(reports, _CANDIDATE)

    assert "Axis: {0}".format(axis) in str(error.value)
    assert str(reports / (axis.lower() + ".md")) in str(error.value)


def test_delivery_state_request_rolls_back_state_when_its_event_is_invalid(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
) -> None:
    project = temporary_git_repository
    state = _configure(project)
    _register(installed_commands, project, _ticket("74", "complete-team-round"))
    _change_status(installed_commands, project, "74", "ready")
    ticket = state / "tickets" / "74-complete-team-round"
    ticket_before = (ticket / "ticket.yml").read_bytes()
    worldline_before = {
        path: path.read_bytes() for path in (state / "worldline").glob("*.jsonl")
    }
    predecessor = [
        json.loads(line)
        for path in worldline_before
        for line in path.read_text(encoding="utf-8").splitlines()
    ][-1]["event_id"]
    request = project / "delivery-state-request.yml"
    request.write_text(
        yaml.safe_dump(
            {
                "phase": "start",
                "ticket_id": "74",
                "caused_by_event_ids": [predecessor],
                "evidence_refs": ["missing-batch.yml"],
                "worktree": ".graphtraj/worktrees/74-complete-team-round",
                "branch": "agent/74-complete-team-round",
                "members": {
                    "team_leader": {"role": "team-leader", "session_ref": "74-complete-team-round@l1"},
                    "engineer": {"role": "engineer", "session_ref": None},
                    "standards_reviewer": {"role": "standards-reviewer", "session_ref": None},
                    "spec_reviewer": {"role": "spec-reviewer", "session_ref": None},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    facts = project / "delivery-state-facts.yml"
    facts.write_bytes(request.read_bytes())

    result = run_process(
        [
            str(installed_commands.product),
            "delivery-state",
            "apply",
            "--request-file",
            str(request),
            "--facts-file",
            str(facts),
        ],
        cwd=project,
    )

    assert result.returncode == 1
    assert (ticket / "ticket.yml").read_bytes() == ticket_before
    assert not (ticket / "teams").exists()
    assert {path: path.read_bytes() for path in worldline_before} == worldline_before
