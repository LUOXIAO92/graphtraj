"""Task 535 P / Pr: one real-host probe of Codex's delegation cell (542 Q2 F2, Q4). No product code is changed.

usage: python -I probe535.py send <project> <since epoch> <out json>      (P: the ACTIVE venv's python, cwd = project)
       python -I probe535.py read <project> <since epoch> <sessions dir> <out json>   (Pr: read only)

send: the Main thread is the session of the last codex:SessionStart claim in <project>'s continuity.jsonl written at
or after <since> (as vr535). Its connection's codex_home is used the way host_events.send_event uses it:
CodexAppServer(cwd, command=(codex, 'app-server', 'proxy'), environment={'CODEX_HOME': ...}, experimental_api=True).
ONE `turn/start {threadId, input: [], toolOutput: {name: 'send_message_to_thread', namespace: 'codex_app', output}}`
goes through the public low-level `call` (send_host_event has no namespace), output = 542 F2's exact wrapper with
`& < >` XML-escaped. The turn/start result and the sent output are printed and written to <out json>.
read: prints the Main rollout's records from the probe's function_call_output on (what the model saw and did).
VERIFY535_PROBE_STUB=1 (rehearsal only) replaces the native transport, as fake_push535.py does.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

SOURCE = 'n535probe'
BODY = '\n'.join([
    f'[Graftling notice from {SOURCE} · completed · execution {"0" * 32}]', '',
    '## Probe heading', '', 'This is **bold** and `code`.', '', '- item one', '- item two', '',
    '> quoted line', '', f'Facts: execution_id `{"0" * 32}` · outcome `completed`'])


def wrapper(source: str, body: str) -> str:
    """542 F2: exactly this layout; the TUI parses it to draw 'Sent by Codex from task <source>'."""
    return (f'<codex_delegation>\n  <source_thread_id>{escape(source)}</source_thread_id>\n'
            f'  <input>{escape(body)}</input>\n</codex_delegation>')


def main_claim(project: Path, since: float) -> dict | None:
    path = project / '.graphtraj/runner/main-sessions/continuity.jsonl'
    try:
        claims = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        print(f'continuity unreadable: {path}: {error}')
        return None
    print(f'continuity {path}: {[(c.get("entry"), c.get("session")) for c in claims]}')
    main = [c for c in claims if float(c.get('at', 0)) >= since
            and str(c.get('entry') or '').startswith('codex:SessionStart')]
    return main[-1] if main else None


def send(project: Path, since: float, out: Path) -> int:
    from graphtraj.runtimes.codex.app_server import CodexAppServer
    from graphtraj.workspace.runner_project import runtime_executable

    claim = main_claim(project, since)
    if claim is None:
        print(f'FAIL: no codex:SessionStart Main claim at or after {since}: the USER starts codex first (see P)')
        return 1
    thread = claim['session']
    home = (claim.get('connection') or {}).get('codex_home') or os.environ.get('CODEX_HOME') or str(Path.home() / '.codex')
    params = {'threadId': thread, 'input': [], 'toolOutput': {
        'name': 'send_message_to_thread', 'namespace': 'codex_app', 'output': wrapper(SOURCE, BODY)}}
    print(f'Main thread: {thread} | CODEX_HOME {home}')
    print('toolOutput.output sent:'); print(params['toolOutput']['output'])
    if os.environ.get('VERIFY535_PROBE_STUB'):
        async def enter(self): return self
        async def leave(self, *args): return None
        async def call(self, method, params, **options):
            return {'turn': {'id': 'turn-probe', 'status': 'inProgress', 'items': []}, 'stub': True}
        CodexAppServer.__aenter__, CodexAppServer.__aexit__, CodexAppServer._call = enter, leave, call

    async def run() -> dict:
        async with CodexAppServer(cwd=project, command=(str(runtime_executable('codex')), 'app-server', 'proxy'),
                                  environment={'CODEX_HOME': home}, experimental_api=True) as client:
            return await client.call('turn/start', params, wait_for_session=True)

    try:
        result = asyncio.run(run())
    except Exception as error:  # noqa: BLE001 - printed: it is the probe's evidence
        print(f'turn/start FAILED: {type(error).__name__}: {error}')
        out.write_text(json.dumps({'thread': thread, 'params': params, 'error': str(error)}, indent=2))
        return 1
    print('turn/start result:', json.dumps(result, ensure_ascii=False))
    out.write_text(json.dumps({'thread': thread, 'params': params, 'result': result}, indent=2, ensure_ascii=False))
    return 0


def read(project: Path, since: float, sessions: Path, out: Path) -> int:
    claim = main_claim(project, since)
    if claim is None:
        print('FAIL: no Main claim'); return 1
    thread = claim['session']
    paths = []
    for path in sessions.rglob('rollout-*.jsonl'):
        try:
            with path.open(encoding='utf-8') as handle:
                if (json.loads(handle.readline()).get('payload') or {}).get('id') == thread:
                    paths.append(path)
        except (OSError, ValueError):
            continue
    if not paths:
        print(f'FAIL: no rollout under {sessions} for the Main {thread}'); return 1
    # One session can have several rollout files (resume): the one holding the probe, else the newest.
    paths.sort(key=lambda path: (SOURCE not in path.read_text(encoding='utf-8'), -path.stat().st_mtime))
    print(f'Main {thread}: rollout {paths[0]} (of {len(paths)} with that session id)')
    seen, rows = False, []
    for number, line in enumerate(paths[0].read_text(encoding='utf-8').splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        payload = record.get('payload') or {}
        if 'send_message_to_thread' in line and SOURCE in line:
            seen = True
        if seen:
            rows.append(number)
            kind = f"{record.get('type')}/{payload.get('type')}"
            text = (payload.get('output') or payload.get('message') or payload.get('last_agent_message')
                    or ''.join(part.get('text', '') for part in payload.get('content') or [] if isinstance(part, dict)))
            print(f'---- line {number} {kind} name={payload.get("name")} namespace={payload.get("namespace")}')
            if text:
                print(str(text)[:1200])
    out.write_text(json.dumps({'thread': thread, 'rollout': str(paths[0]), 'lines_from_probe': rows}))
    print('probe output in the Main rollout:', 'YES' if seen else 'NO')
    return 0 if seen else 1


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'send' and len(sys.argv) == 5:
        sys.exit(send(Path(sys.argv[2]).resolve(), float(sys.argv[3]), Path(sys.argv[4])))
    if mode == 'read' and len(sys.argv) == 6:
        sys.exit(read(Path(sys.argv[2]).resolve(), float(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])))
    print(__doc__)
    sys.exit(2)
