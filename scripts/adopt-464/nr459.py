"""Nr, 459 part: the normal-end observations of the n464 child (read only; never signals).

usage: nr459.py <project> <raw dir> <candidate source dir (B's git archive of the target)/src> <host config> <child name>

Where the facts are (code at b3d522ad):
  child record   <project>/.graphtraj/swarm/control/agents/<agent>.json, executions[*].process:
                 tool_marker (457; the GRAFTLING_MEMBER_RUN value, never printed here) and
                 tool_descendants (459; absolute path of the owner's descendants record),
                 written by graphtraj/execution/agent_driver.py through ExecutionEvents.process.
  run directory  the record file's directory, <project>/.graphtraj/swarm/native/<agent>/ (control.py Run.directory):
                 tool-descendants-<native id>.json   the sampler's record (graftling/tool_descendants.py);
                 claude-termination-<native id>.yml  the owner's end facts (graftling/claude/execution.py), whose
                                                     escaped_processes is the owner's normal-end reclaim result.
                 The execution record itself gets escaped_processes only from an owner-exited reconcile
                 (control.py _stop_escaped), so at a normal end it is absent there.
  Nw snapshots   <raw>/Nw-snapshots.jsonl (watch459.py): the record files as they were while the child ran. The
                 sampler drops a recorded process once it has ended, so after a normal end only these show the
                 Bash tool command.
Liveness uses the target's own rule (graftling.tool_descendants._alive: same pid, uid and start time), imported
from the candidate source, not from production.
"""
import json, re, subprocess, sys
from pathlib import Path

import yaml

project, raw, source, hostcfg, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
sys.path.insert(0, source)
from graftling.tool_descendants import _alive, identity, read_sidecar  # noqa: E402

TOOL = re.compile(r'n464-tool|(^|[^0-9A-Za-z])sleep 3([^0-9]|$)')


def check(label, ok, detail=''):
    print(f"CHECK {label}: {ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')}{(' (' + detail + ')') if detail else ''}")


agents = project / '.graphtraj/swarm/control/agents'
found = []
for path in agents.glob('*.json') if agents.is_dir() else ():
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        continue
    if record.get('name') == name:
        found.append((path.stat().st_mtime, path, record))
if not found:
    print(f'459: NO {name} child record under {agents}')
    sys.exit(1)
_, path, child = max(found, key=lambda item: item[0])
exs = child.get('executions') or []
print(f"459: child {name} record {path} (run directory {project / '.graphtraj/swarm/native' / str(child.get('agent'))})")

# 1. facts recorded (booleans only; the marker value is never printed)
for index, ex in enumerate(exs):
    process = ex.get('process') or {}
    sidecar = process.get('tool_descendants')
    print(f"  execution {ex.get('id')} ({'create' if index == 0 else 'send'}): tool_marker recorded={bool(process.get('tool_marker'))} "
          f"tool_descendants recorded={isinstance(sidecar, str) and bool(sidecar)} record file exists={isinstance(sidecar, str) and Path(sidecar).is_file()}")
create = exs[0] if exs else {}
cp = create.get('process') or {}
check('459 create execution recorded tool_marker and tool_descendants',
      bool(cp.get('tool_marker')) and isinstance(cp.get('tool_descendants'), str) and bool(cp.get('tool_descendants')),
      f"tool_marker={bool(cp.get('tool_marker'))} tool_descendants={bool(cp.get('tool_descendants'))}")

# 2. the records now and while the child ran
now: dict[str, list] = {}
for ex in exs:
    sidecar = (ex.get('process') or {}).get('tool_descendants')
    if isinstance(sidecar, str):
        try:
            now[ex.get('id')] = read_sidecar(sidecar)
            print(f"  record now, execution {ex.get('id')}: {len(now[ex.get('id')])} entries")
        except (OSError, ValueError) as error:
            print(f"  record now, execution {ex.get('id')}: unreadable ({type(error).__name__}: {error})")
snapshots_file = raw / 'Nw-snapshots.jsonl'
snapshots = []
if snapshots_file.is_file():
    for line in snapshots_file.read_text().splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get('agent') == child.get('agent'):
            snapshots.append(item)
print(f"  Nw snapshots for this child: {len(snapshots)} ({snapshots_file}{'' if snapshots_file.is_file() else ': not present, Nw did not run'})")
listed = []
for item in snapshots:
    for entry in (item.get('record') or {}).get('entries') or []:
        if item.get('execution') == create.get('id') and TOOL.search(str(entry.get('argv', ''))):
            listed.append(f"Nw snapshot: pid {entry.get('pid')} argv {str(entry.get('argv'))[:160]!r}")
for entry in now.get(create.get('id'), []):
    if TOOL.search(str(entry.get('argv', ''))):
        listed.append(f"record now: pid {entry.get('pid')} argv {str(entry.get('argv'))[:160]!r}")
for line in listed[:6]:
    print('  ' + line)
if listed:
    check('459 descendants record lists the Bash tool command', True, f'{len(listed)} entries name n464-tool or sleep 3')
elif snapshots_file.is_file():
    check('459 descendants record lists the Bash tool command', False,
          f'no record of the create execution named n464-tool or sleep 3 ({len(snapshots)} snapshots)')
else:
    check('459 descendants record lists the Bash tool command',
          'NOT OBSERVED (Nw did not run; after a normal end the sampler has already dropped the ended command)')

# 3. nothing recorded is still alive, and no process names the command (read only)
running = [ex.get('id') for ex in exs if ex.get('state') != 'ended']
entries = {}
for item in snapshots:
    for entry in (item.get('record') or {}).get('entries') or []:
        entries[(entry.get('pid'), entry.get('start'))] = entry
for listing in now.values():
    for entry in listing:
        entries[(entry.get('pid'), entry.get('start'))] = entry
try:
    ps = subprocess.run(['ps', '-axww', '-o', 'pid=,command='], capture_output=True, text=True, timeout=60).stdout
except (OSError, subprocess.SubprocessError) as error:
    ps = ''
    print(f'  ps failed: {error}')
host = next((line for line in ps.splitlines() if hostcfg in line and ' serve ' in line), None)
host_pid = int(host.split()[0]) if host else None
visible = host_pid is not None and identity(host_pid) is not None
named = [line for line in ps.splitlines() if 'n464-tool' in line and not any(word in line for word in ('grep', 'nr459.py', 'watch459.py'))]
alive = [entry for entry in entries.values() if isinstance(entry.get('pid'), int) and _alive(entry)]
print(f"  recorded identities checked: {len(entries)}; alive with the recorded start time: {len(alive)}; "
      f"processes naming n464-tool: {len(named)}; Main's host visible to ps and libproc: {visible}")
for entry in alive:
    print(f"    ALIVE pid {entry.get('pid')} argv {str(entry.get('argv'))[:160]!r}")
for line in named:
    print(f"    NAMED {line[:200]}")
if running:
    check('459 no recorded tool process alive after the end', 'PENDING', f'executions still running: {running}; rerun Nr after they end')
elif not visible:
    check('459 no recorded tool process alive after the end',
          'CHECK BY HAND (ps or libproc cannot see Main\'s host here; run Nr in a normal Terminal)')
else:
    check('459 no recorded tool process alive after the end', not alive and not named,
          f'{len(alive)} alive, {len(named)} named; never signalled')

# 4. what is kept about escaped_processes at the normal end
for ex in exs:
    print(f"  execution {ex.get('id')}: record escaped_processes = "
          f"{json.dumps(ex['escaped_processes']) if 'escaped_processes' in ex else 'absent (only an owner-exited reconcile writes it)'}")
    sidecar = (ex.get('process') or {}).get('tool_descendants')
    if isinstance(sidecar, str):
        native = Path(sidecar).stem.removeprefix('tool-descendants-')
        termination = Path(sidecar).parent / f'claude-termination-{native}.yml'
        if termination.is_file():
            data = yaml.safe_load(termination.read_text()) or {}
            escaped = data.get('escaped_processes')
            summary = ('null (the Runtime had not exited when the owner checked)' if escaped is None else
                       f"found={len(escaped.get('found') or [])} stopped={len(escaped.get('stopped') or [])} "
                       f"remaining={len(escaped.get('remaining') or [])} error={escaped.get('error')!r} {json.dumps(escaped)[:300]}")
            print(f"    owner's normal-end reclaim ({termination}): escaped_processes {summary}")
        else:
            print(f"    owner's normal-end reclaim: {termination} not found")
