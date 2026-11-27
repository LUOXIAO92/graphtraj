"""Task 650 rehearsal only (macOS): a stand-in for claude.exe, pi.cmd, dsh.cmd and the DSH owner, so that every case of
vm/drive650.py runs end to end off Windows (V650_STANDIN=<this file>). It leaves what the real Runtime and graftling
would leave for the driver to read: Claude's stream-json, Pi's JSON events, DSH's headless text, graftling's host.log,
channel.json, agent records, the venv record lines (when the driver's .pth is in place), DSH patch rows and session
logs, and child processes whose command lines name the markers the driver looks for (host, MCP server, holding tool,
DSH service named ``node``). The model's choices come from the prompt; V650_STANDIN_MODE=no-tool makes it call nothing.
Nothing here is evidence about the real Runtimes.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

MODE = os.environ.get('V650_STANDIN_MODE', '')
VENV = Path(os.environ['V650_VENV'])
BASE = getattr(sys, '_base_executable', sys.executable)
# A child that lives until its parent ends (stdin EOF or a new parent), writing what a graftling host would.
CHILD = r'''
import json, os, sys, time
from pathlib import Path
spec = json.loads(sys.argv[1])
venv = Path(spec['venv'])
if (venv / 'site' / 'zz_record_648.pth').exists():
    with open(venv / 'starts-648.jsonl', 'a', encoding='utf-8') as out:
        out.write(json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'prefix': str(venv),
                              'executable': str(venv / 'bin' / 'python'), 'argv': sys.argv}) + '\n')
log = Path(spec['log']) if spec.get('log') else None
channel = Path(spec['channel']) if spec.get('channel') else None
if channel:
    channel.parent.mkdir(parents=True, exist_ok=True)
    channel.write_text(json.dumps({'parent': os.getppid(), 'executable': 'claude.exe', 'address': 'stand-in'}))
if log:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, 'a', encoding='utf-8') as out:
        for line in spec.get('lines', []):
            out.write(line + '\n')
parent = os.getppid()
if spec.get('stdin'):
    sys.stdin.read()
else:
    while os.getppid() == parent:
        time.sleep(0.2)
if channel:
    channel.unlink(missing_ok=True)
if log:
    with open(log, 'a', encoding='utf-8') as out:
        out.write('2026-11-27T00:00:00 subagents host recorded its children stopped.\n')
'''


def child(markers: list[str], **spec) -> subprocess.Popen:
    spec['venv'] = str(VENV)
    return subprocess.Popen([BASE, '-c', CHILD, json.dumps(spec), *markers], stdin=subprocess.PIPE if spec.get('stdin') else None)


def record(root: Path, agent: str, runtime: str, token: str, outcome: str = 'completed') -> None:
    path = root / 'control' / 'agents' / f'{agent}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'runtime': runtime, 'executions': [
        {'state': 'standby', 'last_result': {'outcome': outcome, 'last_message': token}, 'process': {}}]},
        ensure_ascii=False), encoding='utf-8')


def emit(document: dict) -> None:
    print(json.dumps(document, ensure_ascii=False), flush=True)


def token_in(prompt: str) -> str:
    found = re.search(r'Reply with exactly (?:the word )?(\S+?)(?: and|\.|$)', prompt)
    return found.group(1) if found else 'OK'


def run_script(prompt: str) -> None:
    found = re.search(r'bash (\S+\.sh)', prompt)
    if found:
        subprocess.run(['bash', found.group(1)], check=False)


def claude(args: list[str]) -> int:
    if args[:1] == ['--version']:
        print('2.1.314 (Claude Code) (stand-in)')
        return 0
    if args[:1] == ['plugin']:
        print('stand-in: claude plugin ' + ' '.join(args[1:3]))
        return 0
    prompt = args[args.index('-p') + 1]
    cwd = Path.cwd()
    model = os.environ.get('ANTHROPIC_MODEL', '')
    servers, uses, results, host = [], [], [], None
    root = cwd / '.agents-control'
    if '--plugin-dir' in args:
        manifest = json.loads((Path(args[args.index('--plugin-dir') + 1]) / '.claude-plugin' / 'plugin.json').read_text())
        server = manifest['mcpServers']['probe650']
        command = re.sub(r'\$\{(\w+):-([^}]*)\}', lambda m: os.environ.get(m.group(1)) or m.group(2), server['command'])
        probe = subprocess.Popen([command, *server['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        probe.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}) + '\n')
        probe.stdin.flush()
        servers.append({'name': 'plugin:probe650:probe650', 'status': 'connected' if probe.stdout.readline() else 'failed'})
        probe.stdin.close()
        probe.wait(10)
        print('[DEBUG] MCP server "plugin:probe650:probe650": connected (stand-in)', file=sys.stderr)
    elif (cwd / '.mcp.json').exists():
        lines = []
        servers.append({'name': 'graftling', 'status': 'connected'})
        if MODE != 'no-tool' and 'subagents' in prompt:
            lines.append('2026-11-27T00:00:00 subagents-call execute (stand-in)')
        host = child(['-m', 'graftling.claude.host', 'serve'], log=str(root / 'host.log'),
                     channel=str(root / 'live' / 'channel.json'), lines=lines, stdin=True)
        time.sleep(1.5)
    elif (cwd / '.claude' / 'settings.json').exists() or 'MARKET' in prompt:
        servers.append({'name': 'plugin:graftling:subagents', 'status': 'failed'})
        if 'usr/bin' in os.environ.get('PATH', '').replace('\\', '/'):
            log = root / 'host.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, 'a') as out:
                out.write('graftling plugin: the subagents host did not start: the graftling marketplace plugin is not '
                          'supported on native Windows. Use configuration --write (stand-in)\n')
    emit({'type': 'system', 'subtype': 'init', 'mcp_servers': servers, 'model': model,
          'claude_code_version': '2.1.314', 'cwd': str(cwd)})
    answer = token_in(prompt)
    if MODE != 'no-tool':
        if 'runtime claude' in prompt:
            uses.append({'type': 'tool_use', 'id': 'u1', 'name': 'mcp__graftling__subagents', 'input': {}})
            results.append({'type': 'tool_result', 'tool_use_id': 'u1', 'is_error': True, 'content': [{'type': 'text', 'text':
                json.dumps({'error': {'code': 'unsupported-runtime', 'message': 'A Claude child cannot run on native '
                                      'Windows: Claude Code has no OS sandbox there (stand-in)'}})}]})
            answer = 'unsupported-runtime'
        elif 'runtime dsh' in prompt:
            uses.append({'type': 'tool_use', 'id': 'u1', 'name': 'mcp__graftling__subagents', 'input': {}})
            results.append({'type': 'tool_result', 'tool_use_id': 'u1', 'content': '{"agent": "a1"}'})
            record(root, 'a1', 'dsh', answer)
        elif 'bash ' in prompt:
            uses.append({'type': 'tool_use', 'id': 'u2', 'name': 'Bash', 'input': {}})
            run_script(prompt)
            results.append({'type': 'tool_result', 'tool_use_id': 'u2', 'content': 'O4-DONE'})
    if uses:
        emit({'type': 'assistant', 'message': {'content': uses}})
        emit({'type': 'user', 'message': {'content': results}})
    emit({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': answer, 'num_turns': 2,
          'modelUsage': {model: {}}})
    if host is not None:
        host.stdin.close()
        host.wait(10)
    return 0


def pi(args: list[str]) -> int:
    prompt, model = args[-1], args[args.index('--model') + 1]
    cwd = Path.cwd()
    root = cwd / '.agents-control'
    (root / 'live' / 'pi-host' / 'control-standin').mkdir(parents=True, exist_ok=True)
    host = child(['-I', '-m', 'graftling.pi.host'], stdin=True)
    server = child(['-I', '-m', 'graftling.mcp'], stdin=True)
    time.sleep(1.5)
    emit({'type': 'session', 'model': model})
    answer = token_in(prompt)
    if MODE != 'no-tool':
        if 'runtime pi' in prompt:
            emit({'type': 'tool_execution_start', 'toolName': 'mcp__graftling__subagents'})
            emit({'type': 'tool_execution_end', 'result': json.dumps({'error': {'code': 'unsupported-runtime', 'message':
                  'Pi children are not supported on Windows: a Pi child runs only inside srt (stand-in)'}})})
        elif 'runtime dsh' in prompt:
            emit({'type': 'tool_execution_start', 'toolName': 'mcp__graftling__subagents'})
            record(root, 'a1', 'dsh', answer)
        elif 'feature status' in prompt:
            emit({'type': 'tool_execution_start', 'toolName': 'mcp__graftling__subagents'})
            emit({'type': 'tool_execution_end', 'result': json.dumps({'result': {'agents': []}})})
        if 'bash ' in prompt:
            emit({'type': 'tool_execution_start', 'toolName': 'bash', 'args': {'command': 'bash h7.sh'}})
            run_script(prompt)
        found = re.search(r'sleep (\d+)', prompt)
        if found:
            emit({'type': 'tool_execution_start', 'toolName': 'bash'})
            subprocess.Popen(['/bin/sleep', found.group(1)])
            time.sleep(120)  # held: the driver kills this "node"
    emit({'type': 'message_end', 'model': model, 'text': answer})
    for process in (host, server):
        process.stdin.close()
        process.wait(10)
    return 0


def dsh(args: list[str]) -> int:
    if '--help' in args:
        print('Usage: dsh headless [options] <task> (stand-in)')
        return 0
    prompt = args[-1]
    cwd = Path.cwd()
    root = cwd / '.agents-control'
    (root / 'live' / 'dsh-host' / 'x').mkdir(parents=True, exist_ok=True)
    host = child(['-I', '-m', 'graftling.dsh.host'], stdin=True)
    server = child(['-I', '-m', 'graftling.mcp'], stdin=True)
    time.sleep(1.5)
    answer = token_in(prompt)
    if MODE != 'no-tool' and 'runtime dsh' in prompt:
        record(root, 'a1', 'dsh', answer)
        patch = root / 'native' / 'a1' / 'profile.patch.yml'
        patch.parent.mkdir(parents=True, exist_ok=True)
        patch.write_text('- insert:\n    - id: agents-mcp\n      name: file:///C:/stand-in/graftling/dsh/plugin.mjs\n')
    print(answer, flush=True)
    for process in (host, server):
        process.stdin.close()
        process.wait(10)
    return 0


# The DSH owner (cases dsh-stop, dsh-kill): requests on stdin, documents on stdout, like drive650.py's OWNER.
SERVICE = r'''
import os, subprocess, sys, time
parent = os.getppid()
held = None
for line in iter(sys.stdin.readline, ''):
    if line.startswith('hold '):
        held = subprocess.Popen([sys.argv[1], '-c', 'import os, time\np = os.getppid()\nwhile os.getppid() == p: time.sleep(0.2)',
                                 'Start-Sleep', line.split()[1]])
    elif line.startswith('stop') and held:
        held.kill(); held.wait(); held = None
'''


def owner(args: list[str]) -> int:
    root = Path(args[0])
    emit({'pid': os.getpid()})
    service = None
    turns = 0
    for line in sys.stdin:
        request = json.loads(line)
        action = request.get('action')
        if action == 'create':
            service = subprocess.Popen(['bash', '-c', 'exec -a node "$0" -c "$1" "$0" web', BASE, SERVICE],
                                       stdin=subprocess.PIPE, text=True)
            record(root, 'a1', 'dsh', 'TURN1-650-OK')
            log = root / 'dsh-home' / 'sessions' / 's1' / 'v4.jsonl'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(json.dumps({'turn': 1, 'text': 'TURN1-650-OK'}) + '\n')
            emit({'agent': 'a1', 'session': 's1'})
        elif action == 'send':
            turns += 1
            found = re.search(r'Start-Sleep (\d+)', request.get('message', ''))
            if found and service is None:
                service = subprocess.Popen(['bash', '-c', 'exec -a node "$0" -c "$1" "$0" web', BASE, SERVICE],
                                           stdin=subprocess.PIPE, text=True)
            if found:
                service.stdin.write(f'hold {found.group(1)}\n')
                service.stdin.flush()
            emit({'result': {'agent': 'a1', 'session': 's1'}})
        elif action == 'wait':
            outcome = 'interrupted' if turns and request.get('timeout_seconds') == 120 else 'completed'
            emit({'result': {'state': 'standby', 'last_result': {'outcome': outcome, 'last_message': 'TURN1-650-OK'}}})
        elif action == 'interrupt':
            if service:
                service.stdin.write('stop\n')
                service.stdin.flush()
            emit({'result': {'interrupt': 'requested'}})
        elif action == 'retire':
            if service:
                service.stdin.close()
                service.kill()
                service.wait()
            emit({'result': {'state': 'retired'}})
        else:
            emit({'result': {}})
    return 0


if __name__ == '__main__':
    kind, *rest = sys.argv[1:]
    sys.exit({'claude': claude, 'pi': pi, 'dsh': dsh, 'owner': owner}[kind](rest))
