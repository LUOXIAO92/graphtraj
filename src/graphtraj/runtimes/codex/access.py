"""Native file restrictions for Runtime tools; Runner callbacks retain host access."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from graphtraj.configuration.project_configuration import configuration_exists, load_project_configuration


def private_filesystem(runtime_store: Path) -> dict[str, str]:
    """Protect control records, native history and the installed control code.

    Exact Worktree, Skill and owned-report grants are added by the caller. No
    account or Runtime configuration is rewritten; these are per-Session native
    filesystem entries. The host-side Runner remains outside the tool sandbox.
    """
    root = runtime_store.parent
    native_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).resolve()
    filesystem = {
        str(root / '.graphtraj'): 'none',
        str(runtime_store): 'none',
        str(native_home): 'none',
        str(native_home / 'skills'): 'read',
        str(Path(sys.prefix).resolve()): 'read',
        str(Path(__file__).resolve().parents[2]): 'read',
    }
    if configuration_exists(root):
        configuration = load_project_configuration(root)
        filesystem[str(configuration.state)] = 'none'
        filesystem[str(configuration.docs)] = 'read'
    # Public configuration is readable, but an Agent cannot change its own
    # control or launch policy through a native file tool.
    for path in (root / '.graphtraj/config.yml', root / '.graphtraj/roles.yml'):
        filesystem[str(path)] = 'read'
    return filesystem
