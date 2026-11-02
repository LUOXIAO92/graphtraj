"""Small release defects, each through the seam its caller reads (Task 438)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from agent_swarm import bind
from agent_swarm.control import AgentControl
from agent_swarm.pi.execution import PiExecution
from agent_swarm.runtime import RuntimeAdapterError
from graphtraj.interfaces.agents import GraphTrajAgents
from graphtraj.interfaces.cli.graphtraj import main
from test_agents_connections_presets import RecordingDriver, catalog, configured, create  # noqa: F401
from test_member_child_workspace import RecordingTurn, claimed_main, harness, request  # noqa: F401
from test_pi_generic_execution import generic
from test_pi_runtime import pi_environment  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_a_model_off_the_list_says_where_to_declare_it(tmp_path: Path, catalog: list) -> None:  # noqa: F811
    """A login can serve an id the catalog omits; the error names the field that admits it."""
    root = configured(tmp_path)
    document, failed = create(AgentControl(root, {'claude': RecordingDriver()}),
                              runtime='claude', model='claude-haiku-5-5')
    assert failed and document['error']['code'] == 'invalid-model'
    assert '`models`' in document['error']['message']
    assert str(root / 'config.yml') in document['error']['message']


def test_main_at_the_root_is_refused_a_pi_child_and_told_to_assign_a_workspace(
    harness: SimpleNamespace,  # noqa: F811
) -> None:
    """The refusal stays; its text names the field that resolves it."""
    started = len(RecordingTurn.started)
    created = bind(GraphTrajAgents(harness.root, harness.root), claimed_main(harness))(request('pi'))
    assert created.failed and created.document['error']['code'] == 'RUNTIME_ACCESS_DENIED'
    assert '`workspace`' in created.document['error']['message']
    assert len(RecordingTurn.started) == started


def test_a_suite_without_the_build_backend_stops_at_start(tmp_path: Path) -> None:
    """One clear message before collection, not one fixture error per test."""
    shadow = tmp_path / 'shadow' / 'setuptools'
    shadow.mkdir(parents=True)
    (shadow / '__init__.py').write_text("raise ImportError('setuptools is absent from this venv')\n")
    session = subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q',
         'tests/test_suite_environment.py::test_a_codex_without_the_sandbox_flag_is_refused_as_before'],
        cwd=PROJECT_ROOT, env={**os.environ, 'PYTHONPATH': str(shadow.parent)},
        capture_output=True, text=True, timeout=120,
    )
    output = session.stdout + session.stderr
    assert session.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert 'setuptools.build_meta' in output and 'pip install setuptools' in output
    assert 'passed' not in session.stdout


def test_a_missing_sandbox_tool_reads_as_the_missing_tool(
    tmp_path: Path, pi_environment: dict,  # noqa: F811
) -> None:
    """Pi ended by itself before any prompt: a start failure, whose stop stays uncertified."""
    directory = tmp_path / 'native'
    directory.mkdir()
    turn = PiExecution(generic(tmp_path, pi_environment, sandbox_path='/usr/bin:/bin', provider_domain='p.example'),
                       'unused', directory, lambda *_: None, lambda *_: None, tmp_path / 'trace.jsonl', None)
    with pytest.raises(RuntimeAdapterError) as caught:
        turn.run()
    assert caught.value.code == 'RUNTIME_START_FAILED'
    assert caught.value.message.startswith('Pi did not start: Pi requires installed srt')
    assert caught.value.terminal_confirmed is False


ROLES = """roles:
  sonnet:
    runtime: claude
    model: claude-sonnet-5-5
  mode:
    runtime: claude
    model: claude-opus-5-5
    claude:
      permission_mode: bypassPermissions
  opus:
    runtime: claude
    model: claude-opus-5-5
"""


def test_doctor_reports_the_claude_role_a_launch_would_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor reports the launch's own refusal; a Claude role that can start stays unmentioned."""
    (tmp_path / '.graphtraj').mkdir()
    (tmp_path / '.graphtraj/roles.yml').write_text(ROLES, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ['doctor'])
    assert result.exit_code == 1, result.output
    assert 'sonnet: Use exact claude-opus-5-5' in result.output
    assert 'mode: claude.permission_mode must be default or auto' in result.output
    assert 'opus:' not in result.output and 'roles: OK' not in result.output
