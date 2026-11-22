"""Check the markers of Task 571's pair (graftling 0.7.0 + GraphTraj candidate) in a site-packages tree.

usage: markers.py <site-packages | directory holding graphtraj/ and graftling/> <expect: present|absent>

Each marker is a line the 571 pair has and production (560: graphtraj 8949caff + graftling 0.6.3) does not. Files are
read as text; nothing is imported. Exit 0 only when every marker is as expected: ``present`` for the candidate or the
installed venv, ``absent`` for production now.

  graftling 0.7.0: the version line; 551 extra_tool_table (extra_tools.py), Codex apply_tools (codex/driver.py),
                   Claude --tools only from a create's choice (claude/execution.py); 569 the DSH plugin's own Python
                   (dsh/plugin_python.py).
  graphtraj:       551 the agents driver imports extra_tool_table; 565 the Pi collector reads stdin by readline;
                   567 the definition migration names unreadable directories.
"""
import sys
from pathlib import Path

MARKERS = [
    ('571 graftling version 0.7.0', 'graftling/__init__.py', '__version__ = "0.7.0"'),
    ('551 graftling extra_tool_table', 'graftling/extra_tools.py',
     'def extra_tool_table(extra_tools: Sequence[ExtraTool] | None) -> dict[str, ExtraTool]:'),
    ('551 graftling Codex apply_tools', 'graftling/codex/driver.py',
     'def apply_tools(config: dict, tools: Mapping[str, Any], *, own_server: str | None = None,'),
    ('551 graftling Claude --tools only from a choice', 'graftling/claude/execution.py',
     "argv += ['--tools', ','.join(request['tools'])]"),
    ('569 graftling DSH plugin builds its own Python', 'graftling/dsh/plugin_python.py', 'def environment_name() -> str:'),
    ('551 graphtraj agents driver uses extra_tool_table', 'graphtraj/execution/agent_driver.py',
     'from graftling import extra_tool_table'),
    ('565 graphtraj Pi collector reads stdin by readline', 'graphtraj/runtimes/pi/collector.py',
     'while line := sys.stdin.readline():'),
    ('567 graphtraj migration names unreadable directories', 'graphtraj/workspace/definition_migration.py',
     'def _links_to_renamed(state: Path, harness: Path, plan: list[dict[str, Any]]) -> list[tuple[Path, Path]]:'),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    if expect not in ('present', 'absent'):
        print('expect must be present or absent'); return 2
    bad = 0
    for label, relative, text in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label}: line {'found' if found else 'not found'} in {path}"
              f"{'' if path.is_file() else ' (FILE MISSING)'}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
