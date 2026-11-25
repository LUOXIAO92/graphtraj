"""Task 620 rehearsal (a): drive tests/linux_adoption_runtime.py app-server and its peer directly.

Usage: python -I scenario_driver.py <label> <dir holding linux_adoption_runtime.py and runner_codex_peer.py> <scratch>
Copies both files into <scratch>/<label>/tests, runs `linux_adoption_runtime.py app-server` with
CODEX_HOME=<scratch>/<label>/native-codex-home (the old, wrong rollout root), sends initialize, thread/start and
turn/start on stdin as the Adapter does, and reports turn/completed, the peer's stderr and the peer's rollout file.
If a Unix socket can be bound, it also plays linux_adoption_input.py's control listener (full exchange);
otherwise LINUX_ADOPTION_CONTROL names an unbound path and the scenario can get only as far as connect.
No model, no network, no provider credentials (the child environment is an allowlist).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

label, source, scratch = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
root = scratch / label
shutil.rmtree(root, ignore_errors=True)
tests = root / 'tests'
tests.mkdir(parents=True)
for name in ('linux_adoption_runtime.py', 'runner_codex_peer.py'):
    shutil.copy(source / name, tests / name)
control = root / 'c.sock'
listener = socket.socket(socket.AF_UNIX)
try:
    listener.bind(str(control))
    listener.listen(1)
    listener.settimeout(20)
    bound = True
except OSError as error:
    print(f'control socket bind: {error!r} (sandbox); scenario can reach only connect')
    listener.close()
    bound = False
exchange = {}


def serve() -> None:
    """Play linux_adoption_input.py's listener: wait for 'ready', then release with 'finish'."""
    try:
        with listener.accept()[0] as connection:
            exchange['received'] = connection.recv(128).decode()
            connection.sendall(b'finish')
    except OSError as error:
        exchange['error'] = repr(error)


if bound:
    threading.Thread(target=serve, daemon=True).start()
env = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'LANG': 'en_US.UTF-8',
       'CODEX_HOME': str(root / 'native-codex-home'), 'LINUX_ADOPTION_CONTROL': str(control)}
peer = subprocess.Popen([sys.executable, '-I', str(tests / 'linux_adoption_runtime.py'), 'app-server'],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env=env, cwd=root)
requests = [
    {'id': 1, 'method': 'initialize', 'params': {}},
    {'id': 2, 'method': 'thread/start', 'params': {'cwd': str(root), 'model': 'gpt-5.3-codex', 'config': {},
                                                   'developerInstructions': ''}},
    {'id': 3, 'method': 'turn/start', 'params': {'input': [{'type': 'text', 'text': 'Emit the controlled records.'}]}},
]
for request in requests:
    peer.stdin.write(json.dumps(request) + '\n')
peer.stdin.flush()
turn = completed = None
for line in peer.stdout:
    message = json.loads(line)
    if message.get('id') == 3:
        turn = message['result']['turn']['id']
    if message.get('method') == 'turn/completed':
        completed = message['params']['turn']
        break
peer.stdin.close()
peer.wait(20)
stderr = peer.stderr.read()
rollouts = sorted(root.rglob('rollout-*.jsonl'))
print('turn id:', turn)
print('turn/completed:', json.dumps(completed))
print('peer stderr (last 8 lines):')
for line in stderr.strip().splitlines()[-8:]:
    print('  ' + line.replace(str(scratch), '<scratch>'))
print('rollout files:', [str(p.relative_to(root)) for p in rollouts])
kinds = []
for path in rollouts:
    for record in map(json.loads, path.read_text().splitlines()):
        payload = record['payload']
        kinds.append(record['type'] + ':' + payload.get('type', '-')
                     + (':turn=' + payload['turn_id'] if 'turn_id' in payload else ''))
print('rollout records:', kinds)
print('control exchange:', exchange if bound else 'not bound')
want = ['turn_context:-:turn=' + str(turn), 'response_item:message', 'response_item:function_call',
        'response_item:function_call_output', 'event_msg:token_count']
appended = len(rollouts) == 1 and kinds[2:] == want
missing = 'FileNotFoundError' in stderr and 'native-codex-home' in stderr
connect_only = (not bound and completed and completed['status'] == 'failed'
                and any(line.strip().startswith('connection.connect(') for line in stderr.strip().splitlines()[-4:])
                and 'native-codex-home' not in stderr)
full = bound and completed and completed['status'] == 'completed' and exchange.get('received') == 'controlled records ready\n'
print(f'CHECK rollout read fails on the CODEX_HOME path: {"YES" if missing else "no"}')
print(f'CHECK controlled records appended to the peer rollout: {"YES" if appended else "no"}')
if bound:
    print(f'CHECK full exchange completed: {"YES" if full else "no"}')
else:
    print(f'CHECK fails only at the control-socket connect: {"YES" if connect_only and appended else "no"}')
