"""Native file restrictions for Runtime tools; Runner callbacks retain host access."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import (
    cli_directory as project_cli_directory,
    configuration_file as project_configuration_file,
    core_directory as project_core_directory,
    runner_directory as project_runner_directory,
)

import os
import sys
from pathlib import Path

import yaml

from graphtraj.configuration.project_configuration import configuration_exists, load_project_configuration


def private_filesystem(runtime_store: Path, runtime_home: str | None = None) -> dict[str, str]:
    """Allow project development reads while protecting credentials and control channels.

    Exact Worktree, Skill and owned-report grants are added by the caller. No
    account or Runtime configuration is rewritten; these are per-Session native
    filesystem entries. The host-side Runner remains outside the tool sandbox.
    """
    root = runtime_store.parent
    original_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).resolve()
    native_home = Path(runtime_home).resolve() if runtime_home else original_home
    filesystem = {
        str(root / '.graphtraj'): 'none',
        str(runtime_store): 'none',
        str(original_home): 'none',
        str(original_home / 'skills'): 'read',
        str(native_home): 'none',
        str(native_home / 'skills'): 'read',
        str(Path(sys.prefix).resolve()): 'read',
        str(Path(__file__).resolve().parents[2]): 'read',
    }
    filesystem.update(project_development_reads(root))
    # Public configuration is readable, but an Agent cannot change its own
    # control or launch policy through a native file tool.
    for path in (project_configuration_file(root), project_core_directory(root) / 'roles.yml'):
        filesystem[str(path)] = 'read'
    return filesystem


def project_development_reads(root: Path) -> dict[str, str]:
    """Return project-owned read grants shared by fresh and resumed native Sessions."""
    if not configuration_exists(root):
        return {}
    configuration = load_project_configuration(root)
    filesystem = {str(path): 'read' for path in (
        configuration.state, configuration.docs, configuration.agent_worktrees,
        project_runner_directory(root),
    )}
    filesystem.update({str(path): 'read' for path in project_history_files(root)})
    return filesystem


def member_project_reads(root: Path) -> dict[str, str]:
    """Return read-only project record grants for one delegated Codex member.

    Codex announces every ``none`` entry as a non-escalatable denied read, even
    when a more specific grant covers the member's own Worktree beneath it, so
    ``.graphtraj`` itself is read-only rather than denied. Write isolation comes
    from the workspace-write sandbox: only the Worktree and the exact control
    and Git grants added by the caller are writable, never state or Runner
    records. Other Sessions' control channels and the Claude host channel stay
    denied, as for Claude and Pi members; Runtime homes stay denied by
    :func:`private_filesystem`. Codex Main does not use these grants.
    """
    private    = root / '.graphtraj'
    filesystem = {
        str(private): 'read',
        str(project_cli_directory(root)): 'none',
        str(private / 'claude-host'): 'none',
    }
    filesystem.update(project_development_reads(root))
    return filesystem


def project_history_files(root: Path) -> set[Path]:
    """Select exact native JSONL files from this project's retained associations.

    Read only association metadata, never a Runtime home's directory or history
    contents. A file grant cannot expose unrelated Sessions or credential files
    alongside it. Missing associations remain missing rather than being guessed.
    """
    from agent_swarm import native_session_files
    from graphtraj.execution.runner_status import retained_session_directories
    from graphtraj.interfaces.agents import swarm_root

    runner = project_runner_directory(root)
    records = [
        *(runner / 'sessions').glob('*/session.yml'),
        *(directory / 'session.yml' for directory in retained_session_directories(runner)),
        *(runner / 'main-sessions').glob('*/session.yml'),
    ]
    files = set()
    for path in records:
        try:
            record = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or not record.get('session'):
                continue
            source = record.get('rollout_path') or record.get('activity', {}).get('trace_file')
            if isinstance(source, str):
                native = Path(source)
                if native.is_absolute() and native.suffix == '.jsonl' and native.is_file():
                    files.add(native.resolve())
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return files | set(native_session_files(swarm_root(root)))
