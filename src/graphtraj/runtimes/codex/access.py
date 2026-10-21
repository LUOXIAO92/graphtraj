"""Native file restrictions for Runtime tools; Runner callbacks retain host access."""

from __future__ import annotations

from graphtraj.configuration.project_configuration import (
    configuration_file as project_configuration_file,
    core_directory as project_core_directory,
    runner_directory as project_runner_directory,
)

import os
import sys
from pathlib import Path

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
    return {str(path): 'read' for path in (
        configuration.state, configuration.docs, configuration.agent_worktrees,
        project_runner_directory(root),
    )}
