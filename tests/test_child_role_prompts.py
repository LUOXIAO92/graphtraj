"""Authored child-role prompt content in each Runtime's native prompt channel.

The public operation persists ``system_prompt`` / ``developer_prompt`` through
``roles.yml``; these checks assert that the resolved content reaches the native
request each Runtime actually exposes and that the dispatch instruction stays a
separate channel.
"""

from contextlib import ExitStack
import json
from pathlib import Path

import yaml

from graphtraj.configuration.project_roles import RolePreset
from graphtraj.configuration.role_definitions import resolve_child_role
from test_dsh_runtime import peer, run_turn
from test_pi_runtime import execution, pi_environment
from test_result_submission import result_project
from test_role_organization import accept, execute, project


SYSTEM_TEXT = (
    "Deliver only the layer the selected Runtime exposes.\n"
    "Keep the dispatch instruction in its own channel."
)
DEVELOPER_TEXT = "Treat the accepted specification as the contract."
TASK_TEXT = "task-input-marker-do-not-fold-into-the-prompt-layer"


def test_pi_argv_appends_the_authored_system_prompt_and_not_the_task(
    tmp_path: Path, pi_environment: dict,
) -> None:
    """Pi carries authored system text in --append-system-prompt; the task stays separate."""
    result_project(tmp_path)
    with ExitStack() as stack:
        turn, _, _ = execution(
            tmp_path, pi_environment, 'research@x1', TASK_TEXT, stack,
            system_prompt=SYSTEM_TEXT,
        )
        assert turn.run()['outcome'] == 'completed'

    spec = json.loads(
        (tmp_path / '.graphtraj/runner/sessions/research@x1/pi-process.json').read_text()
    )
    argv = spec['argv']
    index = argv.index('--append-system-prompt')
    appended = Path(argv[index + 1]).read_text(encoding='utf-8')
    assert SYSTEM_TEXT in appended
    assert TASK_TEXT not in appended


def test_dsh_persona_suffix_carries_the_authored_system_prompt_and_not_the_task(
    tmp_path: Path, peer: list,
) -> None:
    """DSH's system-prompt suffix carries authored text; session/prompt keeps the task."""
    turn, thread, outcome = run_turn(tmp_path, instructions=SYSTEM_TEXT)
    config = yaml.safe_load(
        (tmp_path / 'dsh-home/profiles/web/cordis.patch.yml').read_text(encoding='utf-8')
    )
    persona = next(
        row['config']['personaSuffix'] for row in config if row.get('id') == 'system-prompt'
    )
    assert SYSTEM_TEXT in persona
    assert TASK_TEXT not in persona

    prompts = [body for method, body in peer[0].calls if method == 'session/prompt']
    assert [body['content'][0]['text'] for body in prompts] == ['Original instruction']
    assert SYSTEM_TEXT not in prompts[0]['content'][0]['text']

    peer[0].frames.extend(['assistant/message', 'turn/end'])
    thread.join(3)
    assert outcome['result']['outcome'] == 'completed'


def test_codex_developer_instructions_carry_the_authored_developer_prompt(
    tmp_path: Path, temporary_git_repository: Path,
) -> None:
    """Codex's developer layer carries authored text and no task instruction."""
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    executable = tmp_path / 'codex'
    executable.write_text('#!/bin/sh\necho --sandbox\n', encoding='utf-8')
    executable.chmod(0o755)

    role = resolve_child_role(
        'engineer',
        RolePreset('codex', 'gpt-5.6-sol', None, None, developer_prompt=DEVELOPER_TEXT),
        tmp_path,
    )
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    evidence = tmp_path / 'evidence'
    evidence.mkdir()

    context = preflight_runtime_context(
        runtime_store=tmp_path / 'harness' / '.codex',
        executable=executable,
        git_common_directory=temporary_git_repository / '.git',
        role=role,
        worktree=worktree,
        evidence=evidence,
        requested_skills=(),
    ).finalize()
    developer = context.session_document()['adapter_request']['developerInstructions']
    assert DEVELOPER_TEXT in developer
    assert TASK_TEXT not in developer
    # With no authored system text, Codex keeps its own built-in base prompt.
    assert 'baseInstructions' not in context.session_document()['adapter_request']


def test_codex_keeps_the_authored_system_prompt_in_the_base_layer(
    tmp_path: Path, temporary_git_repository: Path,
) -> None:
    """Codex's base/system layer is a separate native parameter, not the developer layer."""
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    executable = tmp_path / 'codex'
    executable.write_text('#!/bin/sh\necho --sandbox\n', encoding='utf-8')
    executable.chmod(0o755)

    role = resolve_child_role(
        'engineer',
        RolePreset('codex', 'gpt-5.6-sol', None, None,
                   system_prompt=SYSTEM_TEXT, developer_prompt=DEVELOPER_TEXT),
        tmp_path,
    )
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    evidence = tmp_path / 'evidence'
    evidence.mkdir()

    context = preflight_runtime_context(
        runtime_store=tmp_path / 'harness' / '.codex',
        executable=executable,
        git_common_directory=temporary_git_repository / '.git',
        role=role,
        worktree=worktree,
        evidence=evidence,
        requested_skills=(),
    ).finalize()
    params = context.session_document()['adapter_request']
    assert params['baseInstructions'] == SYSTEM_TEXT
    assert SYSTEM_TEXT not in params['developerInstructions']
    assert DEVELOPER_TEXT in params['developerInstructions']
    assert TASK_TEXT not in params['baseInstructions']
    assert TASK_TEXT not in params['developerInstructions']


def test_approved_role_prompt_reaches_the_next_codex_native_request(
    project: Path, temporary_git_repository: Path,
) -> None:
    """Content approved through the public entry is what the next Codex dispatch sends."""
    from graphtraj.configuration.project_roles import load_project_roles
    from graphtraj.runtimes.codex.codex_adapter import preflight_runtime_context

    assert execute(
        project,
        {"change": {"set_presets": {"analyst": {
            "system_prompt": SYSTEM_TEXT,
            "developer_prompt": DEVELOPER_TEXT,
        }}}},
        accept,
    ).document["applied"] is True

    resolved = resolve_child_role(
        'analyst', load_project_roles(project).preset('analyst'), project,
    )
    executable = project / 'codex'
    executable.write_text('#!/bin/sh\necho --sandbox\n', encoding='utf-8')
    executable.chmod(0o755)
    worktree = project / 'worktree'
    worktree.mkdir()
    evidence = project / 'evidence'
    evidence.mkdir()

    context = preflight_runtime_context(
        runtime_store=project / 'harness' / '.codex',
        executable=executable,
        git_common_directory=temporary_git_repository / '.git',
        role=resolved,
        worktree=worktree,
        evidence=evidence,
        requested_skills=(),
    ).finalize()
    params = context.session_document()['adapter_request']
    assert params['baseInstructions'] == SYSTEM_TEXT
    assert DEVELOPER_TEXT in params['developerInstructions']
    assert TASK_TEXT not in params['baseInstructions']
    assert TASK_TEXT not in params['developerInstructions']
