"""Check the markers of the adopted Tasks 480, 481, 484, 485, 486 and 487 in a site-packages tree.

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line the diff a3fe1b92..9faa0274 adds under src/ (the verify scripts, tests and the AGENTS.md rule
are not installed). The files are read as text; nothing is imported. Exit 0 only when every marker is as expected:
``present`` for the candidate or the installed venv (9faa0274), ``absent`` for production (a3fe1b92).
"""
import sys
from pathlib import Path

ADD = 'add'
MARKERS = [
    ('480 Pi member writes its assigned reports', 'graphtraj/runtimes/pi/pi_adapter.py',
     "        'write_paths': list(request['reports']),", ADD),
    ('481 DSH Main patch entry', 'graphtraj/runtimes/dsh/main_entry.py', 'def main_patch(python: Path) -> list[dict]:', ADD),
    ('481 DSH tool.mjs attaches the Main MCP server', 'graphtraj/runtimes/dsh/tool.mjs', 'async function attachMain(agent, python) {', ADD),
    ('484 push error named', 'graftling/control.py', 'def _push_error(error: Exception) -> dict[str, str]:', ADD),
    ('484 notification_error recorded', 'graftling/control.py', "                                ended['notification_error'] = failure", ADD),
    ('484 notification_error in status', 'graftling/control.py',
     "                document['last_result']['notification_error'] = dict(last['notification_error'])", ADD),
    ('485 checker fork with Main permissions', 'graphtraj/runtimes/codex/finalize.py', '            child = await client.fork_session(parent)', ADD),
    ('486 MCP server stops its own Agents', 'graphtraj/interfaces/mcp.py', 'def stop_owned_agents() -> None:', ADD),
    ('486 SIGTERM ends serving', 'graphtraj/interfaces/mcp.py', 'def _terminated(signum: int, frame: object) -> None:', ADD),
    ('487 wait timeout leaves its waiter in the same write', 'graftling/control.py',
     '                        if waiters.pop(token, None) is not None and not waiters:', ADD),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
