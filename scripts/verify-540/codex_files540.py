"""Task 540 Vb/V: write the isolated project's OWN .codex/config.toml and .codex/hooks.json.

usage: <venv>/bin/python -I codex_files540.py <project>     (<venv> = <BASE>/active/venv, the same path in Vb and V)

hooks.json is GraphTraj's public Codex adoption material, graphtraj.runtimes.codex.finalize.hook() (what
`python -m graphtraj.runtimes.codex.stop_hook --configuration` prints), run by the active venv so its command names
<venv>/bin/python: SessionStart (the Main claim) and SessionEnd. Its Stop entry (the completion checker, a paid
reviewer with no Task: Task 541) is left out; the defect is at SessionStart.
config.toml: the graphtraj MCP server with its tools pre-approved, as verify-535 (accepted) wrote it.
Never writes ~/.codex or anything outside <project>/.codex.
"""
import json
import sys
from pathlib import Path

from graphtraj.runtimes.codex.finalize import hook


def main(project: Path) -> int:
    target = project / '.codex'
    target.mkdir(exist_ok=True)
    material = hook(Path(), {})
    hooks = {'hooks': {event: material['hooks'][event] for event in ('SessionStart', 'SessionEnd')}}
    (target / 'hooks.json').write_text(json.dumps(hooks, indent=2) + '\n', encoding='utf-8')
    venv = Path(sys.executable).parent.parent
    (target / 'config.toml').write_text(
        '[mcp_servers.graphtraj]\n'
        f'command = {json.dumps(str(venv / "bin" / "graphtraj-mcp"))}\n'
        'args = []\n'
        f'cwd = {json.dumps(str(project))}\n'
        'default_tools_approval_mode = "approve"\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]).resolve()))
