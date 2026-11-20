"""Rehearsal only: one Codex rollout whose pushed notice is what GraphTraj's REAL send_event writes.

usage: python -I fake_push535.py <rollout out> <project>     (run with the B0 or B venv's python, cwd = project)

GraphTraj's graphtraj.runtimes.codex.host_events.send_event and graftling's real CodexAppServer.send_host_event
run unchanged; only graftling's native transport (process start and JSON-RPC _call) is replaced, capturing the
turn/start toolOutput. The rollout gets a session_meta line (cwd = project) and that output as the
function_call_output named 'graftling', as 484's real rollout recorded it.
"""
import json
import sys
from pathlib import Path

from graftling.codex import app_server

EXECUTION = 'e' * 32
MESSAGE = '## Reply from n535\n\n- one `agents`\n- two\n\n> quoted'


def main(out: Path, project: Path) -> int:
    from graphtraj.runtimes.codex.host_events import send_event

    captured = []

    async def enter(self):
        return self

    async def leave(self, *args):
        return None

    async def call(self, method, params, **options):
        captured.append(params)
        return {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}

    app_server.CodexAppServer.__aenter__ = enter
    app_server.CodexAppServer.__aexit__ = leave
    app_server.CodexAppServer._call = call
    send_event({'session': '00000000-0000-4000-8000-000000000535', 'codex_home': str(out.parent)},
               {'source': 'graphtraj', 'alias': 'agent-n535', 'event': 'completed', 'message': MESSAGE,
                'execution': EXECUTION})
    [params] = captured
    rows = [{'type': 'session_meta', 'payload': {'cwd': str(project)}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'name': params['toolOutput']['name'],
                                                  'output': params['toolOutput']['output']}}]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    print('captured toolOutput (first line):', params['toolOutput']['output'].splitlines()[0])
    return 0


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1]).absolute(), Path(sys.argv[2]).resolve()))
