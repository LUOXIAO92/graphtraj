"""Task 535 Vb/V: write the isolated project's OWN .codex/config.toml and .codex/hooks.json.

usage: python -I codex_files535.py <project> <venv>     (<venv> = <BASE>/active/venv, the same path in Vb and V)

config.toml: the graphtraj MCP server with its tools pre-approved, as verify-484 (accepted) wrote it.
hooks.json: GraphTraj's Codex Main hooks exactly as graphtraj.runtimes.codex.finalize.hook() returns them
(SessionStart/Stop/SessionEnd -> stop_hook), plus GraphTraj's UI-only display hook
(graphtraj.runtimes.codex.display_hook, PostToolUse and Stop, its documented events) so sent agents messages
are shown. Every command names <venv>/bin/python, so B0 and B swap the code without changing these files.
Never writes ~/.codex or anything outside <project>/.codex.
"""
import json
import shlex
import sys
from pathlib import Path

from graphtraj.runtimes.codex.finalize import hook


def main(project: Path, venv: Path) -> int:
    python = str(venv / 'bin' / 'python')
    target = project / '.codex'
    target.mkdir(exist_ok=True)
    hooks = hook(project, {})
    stop = shlex.join([python, '-m', 'graphtraj.runtimes.codex.stop_hook'])
    for groups in hooks['hooks'].values():
        for group in groups:
            for entry in group['hooks']:
                entry['command'] = stop          # same module, the stable interpreter path
    display = {'type': 'command', 'command': shlex.join([
        python, '-m', 'graphtraj.runtimes.codex.display_hook',
        '--state-directory', str(project / '.codex' / 'graphtraj-display')])}
    hooks['hooks'].setdefault('PostToolUse', []).append({'hooks': [dict(display)]})
    hooks['hooks'].setdefault('Stop', []).append({'hooks': [dict(display)]})
    (target / 'hooks.json').write_text(json.dumps(hooks, indent=2) + '\n', encoding='utf-8')
    (target / 'config.toml').write_text(
        '[mcp_servers.graphtraj]\n'
        f'command = {json.dumps(str(venv / "bin" / "graphtraj-mcp"))}\n'
        'args = []\n'
        f'cwd = {json.dumps(str(project))}\n'
        'default_tools_approval_mode = "approve"\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).absolute()))
