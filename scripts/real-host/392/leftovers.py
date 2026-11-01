"""Record the processes 392's real run left behind, and what step 91's member did. Sends no signal.

Usage: python -I leftovers.py <agents-392 root> <evidence directory> <pid> [<pid> ...]

Nothing here reads the DeepSeek value: the step removes it from this process's environment, and
save_step.py scans the evidence afterwards. Every process line is masked before it is written.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

AG, OUT = Path(sys.argv[1]), Path(sys.argv[2])
GIVEN = [int(item) for item in sys.argv[3:]]
MARKERS = ('agent_swarm.mcp', 'graphtraj.execution.runner_worker', 'dsh web')
SECRET = re.compile(r'(?i)((?:key|token|=)[^A-Za-z0-9_-]{0,3})[A-Za-z0-9_-]{20,}')
TEXT = {'.json', '.jsonl', '.log', '.yml', '.yaml', '.txt', '.md'}
SKIP_PARTS = {'node_modules', '.git'}
SKIP_NAMES = {'auth.json', '.credentials.yaml'}
MAX_BYTES = 20_000_000
SAMPLE_SECONDS = 30
PROCESS_FIELDS = ('pid', 'ppid', 'pgid', 'etime', 'time', 'pcpu', 'rss')


def masked(text: str) -> str:
    """Hide any long token that follows key, token or =."""
    return SECRET.sub(r'\1[masked]', text)


def summary(line: str) -> None:
    """Add one line to the summary and the terminal."""
    print(line, flush=True)
    with (OUT / 'summary.txt').open('a') as stream:
        stream.write(line + '\n')


def command(*argv: str, limit: int = 45) -> str:
    """Return a read-only command's output, or what stopped it."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=limit, errors='replace')
        return done.stdout + (f'\n[stderr] {done.stderr}' if done.stderr.strip() else '')
    except (OSError, subprocess.TimeoutExpired) as error:
        return f'[{" ".join(argv[:2])} stopped: {type(error).__name__}: {error}]\n'


def processes() -> dict[int, dict]:
    """Return every process by pid. ``time`` is cumulative CPU, which the 30 s sample compares."""
    listing = command('ps', '-axww', '-o', ','.join(f'{name}=' for name in PROCESS_FIELDS) + ',command=')
    found = {}
    for line in listing.splitlines():
        fields = line.split(None, len(PROCESS_FIELDS))
        if len(fields) == len(PROCESS_FIELDS) + 1 and fields[0].isdigit():
            found[int(fields[0])] = {**dict(zip(PROCESS_FIELDS, fields)), 'command': fields[-1]}
    return found


def cpu_seconds(value: str) -> float:
    """Read ps's cumulative time, [dd-]mm:ss.ss or hh:mm:ss."""
    days, _, clock = value.rpartition('-')
    total = 0.0
    for part in clock.split(':'):
        total = total * 60 + float(part)
    return total + int(days or 0) * 86400


def descendants(table: dict[int, dict], roots: set[int]) -> set[int]:
    """Return ``roots`` and everything under them."""
    found, grew = set(roots), True
    while grew:
        grew = False
        for pid, row in table.items():
            if int(row['ppid']) in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def working_directory(pid: int) -> str:
    """Return a process's working directory from lsof, or nothing."""
    for line in command('lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn').splitlines():
        if line.startswith('n'):
            return line[1:]
    return ''


def confirmed(table: dict[int, dict]) -> tuple[set[int], dict[int, str]]:
    """Return the processes that are this run's, and why, from their own command and location."""
    root = str(AG)
    own = {pid for pid, row in table.items() if any(mark in row['command'] for mark in MARKERS) and root in row['command']}
    under = descendants(table, own)
    reasons = {pid: 'its command names a marker and this tree' for pid in own}
    for pid, row in table.items():
        if pid in own or pid == os.getpid() or not any(mark in row['command'] for mark in MARKERS):
            continue
        if pid in under:
            reasons[pid] = 'its command names a marker, and it runs under a confirmed process'
        elif working_directory(pid).startswith(root):
            reasons[pid] = 'its command names a marker, and its working directory is in this tree'
    return set(reasons), reasons


def established(pid: int) -> list[str]:
    """Return a process's established TCP connections, without name lookups."""
    lines = command('lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-sTCP:ESTABLISHED').splitlines()
    return [line for line in lines if 'ESTABLISHED' in line]


def holders(pid: int, lines: list[str], everyone: str) -> list[str]:
    """Return every process line naming the other end of this process's stdin."""
    tokens: set[str] = set()
    for line in lines:
        fields = line.split()
        if len(fields) > 3 and re.fullmatch(r'0[a-z]?', fields[3]):
            tokens.update(re.findall(r'0x[0-9a-f]+', line))
    if not tokens:
        return []
    return [line for line in everyone.splitlines()
            if any(token in line for token in tokens) and not re.match(rf'\S+\s+{pid}\s', line)]


def record_processes(table: dict[int, dict], chosen: set[int], reasons: dict[int, str]) -> dict[int, list[str]]:
    """Save each chosen process's row and descriptors, and who holds an MCP's stdin."""
    with (OUT / 'processes.txt').open('w') as rows:
        rows.write('pid ppid pgid etime time pcpu rss command\n')
        for pid in sorted(chosen):
            row = table.get(pid)
            rows.write(masked(' '.join(row[name] for name in (*PROCESS_FIELDS, 'command'))) + '\n' if row else f'{pid} not running\n')
    everyone = command('lsof', '-nP', '-d', '0-4096', limit=45)
    (OUT / 'lsof').mkdir(exist_ok=True)
    described = {}
    for pid in sorted(pid for pid in chosen if pid in table):
        lines = masked(command('lsof', '-nP', '-a', '-p', str(pid), '-d', '0-4096,cwd')).splitlines()
        network = masked(command('lsof', '-nP', '-a', '-p', str(pid), '-i'))
        held = holders(pid, lines, everyone) if 'agent_swarm.mcp' in table[pid]['command'] else []
        if 'agent_swarm.mcp' in table[pid]['command']:
            described[pid] = held
        (OUT / 'lsof' / f'{pid}.txt').write_text(
            f'why chosen: {reasons.get(pid, "given as an argument, not confirmed by its command")}\n'
            + '\n'.join(lines) + f'\n\n--- network\n{network}\n--- other ends of stdin\n' + masked('\n'.join(held)) + '\n')
    return described


def deepseek_addresses() -> set[str]:
    """Return what api.deepseek.com resolves to now; a CDN may answer from other addresses later."""
    try:
        return set(socket.gethostbyname_ex('api.deepseek.com')[2])
    except OSError:
        return set()


def sample_activity(chosen: set[int], first: dict[int, dict]) -> None:
    """Compare CPU and established connections 30 s apart, and state what that says about model calls."""
    addresses = deepseek_addresses()
    before = {pid: established(pid) for pid in chosen if pid in first}
    print(f'Sampling for {SAMPLE_SECONDS} s; nothing to type.', flush=True)
    time.sleep(SAMPLE_SECONDS)
    second = processes()
    after = {pid: established(pid) for pid in chosen if pid in second}
    with (OUT / 'activity.txt').open('w') as stream:
        stream.write(f'api.deepseek.com now resolves to: {sorted(addresses)}\n')
        for pid in sorted(chosen):
            old, new = first.get(pid), second.get(pid)
            delta = cpu_seconds(new['time']) - cpu_seconds(old['time']) if old and new else None
            stream.write(f'\npid {pid}: cpu seconds used in {SAMPLE_SECONDS} s: {delta}; pcpu {old and old["pcpu"]} then {new and new["pcpu"]}\n')
            stream.write('established first:\n' + masked('\n'.join(before.get(pid, []))) + '\nestablished second:\n'
                         + masked('\n'.join(after.get(pid, []))) + '\n')
    dsh = [pid for pid in chosen if pid in second and 'dsh web' in second[pid]['command']]
    for pid in dsh:
        remote = [line for line in after.get(pid, []) if any(address in line for address in addresses)]
        delta = cpu_seconds(second[pid]['time']) - cpu_seconds(first[pid]['time']) if pid in first else None
        summary(f'note: dsh web {pid}: {len(remote)} established to api.deepseek.com now, of {len(after.get(pid, []))} established; '
                f'cpu seconds used in {SAMPLE_SECONDS} s: {delta}. A model call needs a connection and CPU; a proxy or CDN address would not match, see activity.txt')
    if not dsh:
        summary('note: no running dsh web was among the chosen processes')


def copy_text(source: Path, target: Path) -> int:
    """Copy text records under ``source``; skip packages, login files and links. Return how many."""
    copied = 0
    for path in source.rglob('*') if source.exists() else []:
        if (not path.is_file() or path.is_symlink() or path.name in SKIP_NAMES or SKIP_PARTS & set(path.parts)
                or path.suffix not in TEXT or path.stat().st_size > MAX_BYTES):
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


def clock(seconds: float) -> str:
    """Return a local time for a summary line."""
    return datetime.fromtimestamp(seconds).strftime('%Y-%m-%dT%H:%M:%S')


def session_facts(path: Path) -> tuple[float | None, str, list[dict]]:
    """Return a DSH Session log's last event time and type, and the approvals not decided."""
    last_time, last_type, asked = None, 'none', {}
    for line in path.read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind, data = event.get('type'), event.get('data') or {}
        last_type = kind or last_type
        if isinstance(event.get('time'), (int, float)):
            last_time = event['time'] / 1000
        if kind == 'approval/asked':
            asked[data.get('id')] = {'tool': data.get('toolName'), 'reason': masked(str(data.get('reason')))[:300]}
        elif kind == 'approval/decided':
            asked.pop(data.get('id'), None)
    return last_time, last_type, list(asked.values())


def record_run() -> None:
    """Copy what step 91's member left, and state its last activity, approvals and EMFILE lines."""
    runs = sorted((AG / 'runs').glob('91-residual-420-*'))
    if not runs:
        summary('CANNOT 91 member: no run directory under ' + str(AG / 'runs'))
        return
    run = runs[-1]
    harness = run / 'harness'
    summary(f'note: 91 run read: {run.name}')
    copied = (copy_text(harness / '.graphtraj' / 'runner' / 'sessions', OUT / 'run91' / 'runner-sessions')
              + sum(copy_text(trace, OUT / 'run91' / 'traces' / trace.relative_to(harness / '.graphtraj' / 'state' / 'tasks'))
                    for trace in (harness / '.graphtraj' / 'state' / 'tasks').glob('*/teams/*/traces'))
              + copy_text(harness / '.graphtraj' / 'state' / 'worldline', OUT / 'run91' / 'worldline'))
    summary(f'note: 91 records copied: {copied} text files')
    files = sorted(((path.stat().st_mtime, path) for path in harness.rglob('*')
                    if path.is_file() and not path.is_symlink() and not SKIP_PARTS & set(path.parts)),
                   key=lambda item: item[0], reverse=True)[:20]
    (OUT / 'run91' / 'newest-files.txt').write_text(
        ''.join(f'{clock(when)} {path.relative_to(harness)}\n' for when, path in files))
    logs = [path for path in harness.rglob('session.v4.jsonl') if path.is_file()]
    compressed = [path for path in harness.rglob('session.v4.jsonl.zstd') if path.is_file()]
    if not logs:
        summary(f'CANNOT 91 member last activity: no plain DSH Session log; compressed logs: {len(compressed)}; newest file '
                f'{clock(files[0][0]) if files else "none"}')
    for path in logs:
        when, kind, pending = session_facts(path)
        summary(f'note: 91 member last activity: {clock(when) if when else "no timed event"}, last event {kind}; log modified '
                f'{clock(path.stat().st_mtime)}; {len(path.read_text(errors="replace").splitlines())} events')
        summary(f'note: 91 native approval pending: {"yes" if pending else "no"}: {json.dumps(pending, ensure_ascii=False)[:600]}')
    count, first = 0, None
    for path in harness.rglob('*'):
        if not path.is_file() or path.is_symlink() or SKIP_PARTS & set(path.parts) or path.suffix not in TEXT or path.stat().st_size > MAX_BYTES:
            continue
        lines = path.read_text(errors='replace').splitlines()
        for index, line in enumerate(lines):
            if 'EMFILE' in line:
                count += 1
                if first is None:
                    first = f'{path.relative_to(harness)}:{index + 1}\n' + masked('\n'.join(lines[max(0, index - 2):index + 3]))[:2000]
    (OUT / 'run91' / 'emfile.txt').write_text(f'count {count}\n\n{first or "no line"}\n')
    summary(f'note: 91 EMFILE lines in this run\'s text files: {count}')


def main() -> int:
    """Record processes first, because they may be stopped after this; then the run's files."""
    OUT.mkdir(parents=True, exist_ok=True)
    table = processes()
    confirmed_pids, reasons = confirmed(table)
    chosen = confirmed_pids | set(GIVEN)
    summary(f'note: chosen processes: {sorted(chosen)}; confirmed by command: {sorted(confirmed_pids)}; '
            f'given and not running: {sorted(set(GIVEN) - set(table))}; given and not confirmed: '
            f'{sorted(pid for pid in GIVEN if pid in table and pid not in confirmed_pids)}')
    held = record_processes(table, chosen, reasons)
    for pid, lines in held.items():
        summary(f'note: agent_swarm.mcp {pid} parent {table[pid]["ppid"]}: other ends of its stdin held by {len(lines)} descriptors; see lsof/{pid}.txt')
    sample_activity(chosen, table)
    record_run()
    still = sorted(pid for pid in confirmed_pids if pid in processes())
    (OUT / 'kill-line.txt').write_text(f'kill {" ".join(map(str, still))}\n' if still else '')
    summary('note: this step ran no kill. After it has finished, you run the kill line printed as the next command; '
            f'it names only processes confirmed by their command: {"kill " + " ".join(map(str, still)) if still else "none, nothing to stop"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
