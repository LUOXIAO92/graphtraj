"""Task 535 Vb/V: write the isolated project's OWN .codex/config.toml and .codex/hooks.json.

usage: python -I codex_files535.py <project> <venv>     (<venv> = <BASE>/active/venv, the same path in Vb and V)

config.toml: the graphtraj MCP server with its tools pre-approved, as verify-484 (accepted) wrote it.
hooks.json (correction round 1, tries 1-2):
  - SessionStart -> graphtraj.runtimes.codex.stop_hook directly: GraphTraj's Main claim, which the push needs
    (agents.py _main_notice: current_main). The child is a Claude member now (roles535.py), so no child runs these
    Codex hooks; a Codex child had claimed Main in both tries (pre-existing defect, Task 540). main_start535.py
    (the earlier source filter) is deleted.
  - finalize.hook()'s Stop (completion checker: a paid reviewer with no Task, Task 541) and SessionEnd are NOT
    installed: 535 shows messages, not the completion check.
  - GraphTraj's UI-only display hook (graphtraj.runtimes.codex.display_hook) on PostToolUse and Stop.
Every command names <venv>/bin/python, so B0 and B swap the code without changing these files.
Never writes ~/.codex or anything outside <project>/.codex.
"""
import json
import shlex
import sys
from pathlib import Path


def main(project: Path, venv: Path) -> int:
    python = str(venv / 'bin' / 'python')
    target = project / '.codex'
    target.mkdir(exist_ok=True)
    claim = {'type': 'command', 'statusMessage': 'GraphTraj: associating Main session',
             'command': shlex.join([python, '-m', 'graphtraj.runtimes.codex.stop_hook'])}
    display = {'type': 'command', 'command': shlex.join([
        python, '-m', 'graphtraj.runtimes.codex.display_hook',
        '--state-directory', str(project / '.codex' / 'graphtraj-display')])}
    hooks = {'hooks': {'SessionStart': [{'hooks': [claim]}],
                       'PostToolUse': [{'hooks': [dict(display)]}],
                       'Stop': [{'hooks': [dict(display)]}]}}
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
