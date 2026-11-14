"""Nw: read-only watcher of the n475 child's 459 descendants records while N runs.

usage: watch459.py <project> <raw dir> <child name> <seconds>

The owner's sampler drops a recorded process once it has ended, so after a normal end
the record file no longer lists the Bash tool command. This watcher reads (never
writes, never signals) the child record under <project>/.graphtraj/swarm/control/agents
every 0.2 s, follows each execution's ``process.tool_descendants`` file and appends
every distinct content of it to <raw>/Nw-snapshots.jsonl (argv as the owner recorded
it: already redacted and cut by 459). It stops by itself when the child has two
executions that both ended, when the child is retired, or after <seconds>.
"""
import json, signal, sys, time
from pathlib import Path

signal.signal(signal.SIGHUP, signal.SIG_IGN)   # as nohup does; nohup itself cannot detach in every sandbox

project, raw, name, limit = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])
agents = project / '.graphtraj/swarm/control/agents'
out, log = raw / 'Nw-snapshots.jsonl', raw / 'Nw.txt'
start = time.time()
seen: dict[str, str] = {}
child_agent = None


def note(text: str) -> None:
    with log.open('a') as stream:
        stream.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def child() -> dict | None:
    """The live (not retired) record named ``name``; the newest if there are several."""
    best = None
    for path in agents.glob('*.json') if agents.is_dir() else ():
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('name') == name and record.get('retired_at') is None:
            if best is None or path.stat().st_mtime > best[0]:
                best = (path.stat().st_mtime, record)
    return best[1] if best else None


note(f"start: watching {agents} for {name} (read only; at most {limit:.0f} s)")
reason = f'time limit {limit:.0f} s'
while time.time() - start < limit:
    record = child()
    if record is None and child_agent is not None:
        reason = 'child retired or gone'
        break
    if record is not None:
        if child_agent is None:
            child_agent = record.get('agent')
            note(f"child {name} found: agent {child_agent}")
        executions = record.get('executions') or []
        for execution in executions:
            sidecar = (execution.get('process') or {}).get('tool_descendants')
            if not isinstance(sidecar, str):
                continue
            try:
                text = Path(sidecar).read_text()
            except OSError:
                continue
            if seen.get(sidecar) != text:
                seen[sidecar] = text
                try:
                    document = json.loads(text)
                except ValueError:
                    continue
                with out.open('a') as stream:
                    stream.write(json.dumps({'at': time.time(), 'agent': child_agent, 'execution': execution.get('id'),
                                             'sidecar': sidecar, 'record': document}) + '\n')
                note(f"execution {execution.get('id')}: record changed, {len(document.get('entries') or [])} entries")
        if len(executions) >= 2 and all(e.get('state') == 'ended' for e in executions):
            reason = 'both executions ended'
            break
    time.sleep(0.2)
note(f"== END ({reason}); snapshots: {sum(1 for _ in out.open()) if out.exists() else 0}")
