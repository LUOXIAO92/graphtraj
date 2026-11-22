"""Task 576 helper for steps.zsh. Run with python3 -I; standard library only.

  init OUTJSON TIMEOUT CWD -- ARGV...   Start ARGV in CWD (environment inherited), send one stream-json user
                                        message, read stdout until the system/init event, then stop the process
                                        group. Writes {init, tools, exit, stderr_tail, elapsed} to OUTJSON.
  row LABEL OUTJSON [NAME...]           Print one diagnosis row: the raw init tools and present/absent per NAME;
                                        INCONCLUSIVE when there is no init event or its tools list is empty.
"""
import json
import os
import select
import signal
import subprocess
import sys
import time


def init(out: str, timeout: float, cwd: str, argv: list[str]) -> int:
    start = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    message = {'type': 'user', 'message': {'role': 'user', 'content': 'Reply with one word: diag.'}}
    found, lines, err = None, [], b''
    try:
        proc.stdin.write((json.dumps(message) + '\n').encode())
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    buffer = b''
    streams = [proc.stdout, proc.stderr]
    while streams and found is None and time.monotonic() - start < timeout:
        ready, _, _ = select.select(streams, [], [], 0.5)
        for stream in ready:
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                streams.remove(stream)
                continue
            if stream is proc.stderr:
                err += chunk
                continue
            buffer += chunk
            while b'\n' in buffer and found is None:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    event = json.loads(line)
                except ValueError:
                    lines.append(line.decode(errors='replace')[:300])
                    continue
                if isinstance(event, dict) and event.get('type') == 'system' and event.get('subtype') == 'init':
                    found = event
                else:
                    lines.append(json.dumps(event)[:300])
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        code = proc.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        code = proc.wait()
    result = {
        'init': found is not None,
        'tools': found.get('tools') if found else None,
        'model': found.get('model') if found else None,
        'permissionMode': found.get('permissionMode') if found else None,
        'mcp_servers': found.get('mcp_servers') if found else None,
        'exit': code, 'elapsed': round(time.monotonic() - start, 1),
        'timed_out': found is None and time.monotonic() - start >= timeout,
        'other_stdout': lines[-5:], 'stderr_tail': err.decode(errors='replace')[-800:],
    }
    with open(out, 'w') as handle:
        json.dump(result, handle, indent=1)
    return 0


def row(label: str, path: str, names: list[str]) -> int:
    data = json.load(open(path))
    tools = data.get('tools')
    print(f'-- {label}')
    print(f'   init event: {"yes" if data["init"] else "NO"}; exit {data["exit"]}; {data["elapsed"]} s;'
          f' model {data.get("model")}; permissionMode {data.get("permissionMode")}')
    print(f'   raw init tools ({len(tools or [])}): {json.dumps(tools)}')
    if not data['init'] or not tools:
        print(f'   INCONCLUSIVE: {"no system/init event" if not data["init"] else "empty tools list"}')
        print(f'   stdout before: {data["other_stdout"]}')
        print(f'   stderr tail: {data["stderr_tail"]!r}')
        return 1
    for name in names:
        print(f'   {name}: {"present" if name in tools else "absent"}')
    return 0


if __name__ == '__main__':
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'init':
        split = args.index('--')
        sys.exit(init(args[0], float(args[1]), args[2], args[split + 1:]))
    if command == 'row':
        sys.exit(row(args[0], args[1], args[2:]))
    sys.exit(f'unknown command {command}')
