"""Task 535 Vb/V: write the isolated project's OWN .codex/config.toml and .codex/hooks.json.

usage: python -I codex_files535.py <project> <venv>     (<venv> = <BASE>/active/venv, the same path in Vb and V)

config.toml: the graphtraj MCP server with its tools pre-approved, as verify-484 (accepted) wrote it.
hooks.json (correction round 1, Vb try 1):
  - SessionStart -> main_start535.py: GraphTraj's Main claim (stop_hook), passed on ONLY for the interactive TUI
    session (rollout source 'cli'). The push needs that claim (agents.py _main_notice: current_main), but the
    unfiltered finalize.hook() SessionStart also ran in the `codex exec` child, which then became the current Main
    and received the notice in its ended thread (pre-existing defect, reported, not fixed by 535).
  - finalize.hook()'s Stop (completion checker: a paid reviewer with no Task, 'Hook stopped') and SessionEnd are
    NOT installed: 535 shows messages, not the completion check.
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
             'command': shlex.join([python, '-I', str(Path(__file__).resolve().parent / 'main_start535.py')])}
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
