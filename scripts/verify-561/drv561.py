"""Task 561 real-entry probe: the installed `dsh` with the graftling DSH plugin receives one agents message.

    python -I drv561.py <label> <run dir> <project dir>   (graftling importable from the running venv)

The real native process is the installed `dsh` (`dsh --profile web --patch ... web --no-open --port 0`), started
and authenticated by graftling's own DshService (the same class DshExecution uses). Its profile loads graftling's
plugin.mjs (row `agents`, as DshExecution's `plugin` request does), which registers the `agentMessages` Remote
service. The probe creates one native Session, follows it, and sends the exact `agentMessages/receive` request
that graftling's owning host sends (execution.py: completion notice and `receive`; plugin.mjs: host notices call the
same `agentMessages.receive`). No model is called. Observable: the native result envelope (ok/error message), the
DSH output lines naming the error, and the Session's next-step inbox projection.
Writes only under <run dir> (DSH_HOME, logs) and <project dir> (the Session cwd).
"""
import json
import os
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import graftling
from graftling.dsh import service as native
from graftling.dsh.execution import _dump_profile_patches
from graftling.dsh.service import DshError, DshService

label, run, project = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
plugin = Path(graftling.__file__).parent / 'dsh' / 'plugin.mjs'
dsh = shutil.which('dsh')
print(f'[{label}] graftling {graftling.__version__} from {graftling.__file__}')
print(f'[{label}] plugin {plugin}')
print(f'[{label}] dsh {dsh} -> {Path(dsh).resolve() if dsh else None}')
if dsh is None:
    sys.exit('STOP: dsh is not on PATH')
package = json.loads((Path(dsh).resolve().parent.parent / 'package.json').read_text())
print(f'[{label}] installed DSH package {package["name"]} {package["version"]}')

home = run / 'dsh-home'
profile = home / 'profiles' / 'web'
shutil.rmtree(run, ignore_errors=True)
profile.mkdir(parents=True)
project.mkdir(parents=True, exist_ok=True)
(profile / 'package.json').write_text(json.dumps({'private': True, 'dsh': {'profile': {
    'bundles': ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app']}}}))
(profile / 'cordis.patch.yml').write_text(_dump_profile_patches([
    {'id': 'hmr', 'disabled': True},
    {'id': 'session-persistence-jsonl', 'config': {'root': str(run / 'logs'), 'compression': 'none'}},
    {'insert': [{'id': 'agents', 'name': str(plugin)}]},
]))

# Read-only tap on DshService's own output drain: every non-launch-URL DSH line passes redact_native.
output: list[str] = []
redact = native.redact_native
native.redact_native = lambda text, secrets: output.append(redacted := redact(text, secrets)) or redacted

environment = {'HOME': os.environ['HOME'], 'PATH': os.environ['PATH'], 'TMPDIR': os.environ.get('TMPDIR', '/tmp'),
               'LANG': os.environ.get('LANG', 'en_US.UTF-8'), 'DSH_HOME': str(home), 'NO_COLOR': '1'}
service = DshService(dsh, project, environment, profile_patch=profile / 'cordis.patch.yml')


def call(method: str, request: dict) -> dict:
    """The DshService wire call, returning the whole native result (DshService keeps only the error code)."""
    body = {'type': 'client-request', 'rpcId': uuid.uuid4().hex, 'method': method,
            'payload': {'args': {'request': request}}}
    call = urllib.request.Request(service.origin + '/api/' + method, data=json.dumps(body).encode(), headers={
        'Content-Type': 'application/json', 'Cookie': service.cookie, 'Origin': service.origin})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(call, timeout=20) as response:
        return json.load(response)['result']


code = 1
try:
    service.start()
    print(f'[{label}] DSH web started (pid {service.process.pid}), authenticated')
    session = service.rpc('session/create', {'cwd': str(project)})['sessionId']
    snapshot = service.follow(session)
    print(f'[{label}] native Session {session} (snapshot header id {snapshot["header"]["id"]})')
    message = {'id': f'verify-561-{label}', 'sessionId': session, 'senderSessionId': 'verify-561-child-session',
               'sender': 'verify-561-child', 'recipient': 'verify-561-main',
               'body': f'verify-561 agents message ({label})'}
    print(f'[{label}] agentMessages/receive request: {json.dumps(message)}')
    result = call('agentMessages/receive', message)
    print(f'[{label}] agentMessages/receive result: {json.dumps(result)}')
    try:
        service.rpc('agentMessages/receive', message)
        print(f'[{label}] DshService.rpc (as execution.py calls it): accepted')
    except DshError as error:
        print(f'[{label}] DshService.rpc (as execution.py calls it): {error.code} {error.message}')
    time.sleep(1)
    inbox = (service.rpc('session/projections', {'sessionId': session}) or {}).get('values', {}).get('inbox')
    queued = [m for target in (inbox or {}).values() for m in target
              if (m.get('source') or {}).get('communicationId') == message['id']]
    print(f'[{label}] Session inbox holds the message: {"YES" if queued else "no"} ({json.dumps(inbox)[:300]})')
    seen = [line for line in output if 'inject' in line or 'agentMessages' in line or 'communication.mjs' in line]
    print(f'[{label}] DSH output lines naming the error ({len(seen)}):')
    for line in seen[:12]:
        print(f'[{label}]   {line}')
    delivered = result.get('ok') is True and (result.get('value') or {}).get('accepted') is True
    print(f'[{label}] OBSERVABLE: {"DELIVERED" if delivered else "NOT DELIVERED"}'
          f' ({"accepted" if delivered else (result.get("error") or {}).get("message", result)})')
    code = 0
except DshError as error:
    print(f'[{label}] OBSERVABLE: STOP ({error.code} {error.message.splitlines()[0]})')
    print('\n'.join(f'[{label}]   dsh: {line}' for line in output[-20:] if line.strip()))
finally:
    try:
        service.close()
    except DshError as error:
        print(f'[{label}] close: {error.code} {error.message}')
sys.exit(code)
