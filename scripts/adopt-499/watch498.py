"""Nw (498 part): read-only watcher of the n499 child's Runtime, its tool processes and its descendants record.

usage: watch498.py <project> <raw dir> <candidate source dir (B's git archive of 871aaaa9)/src> <child name>
                   <seconds> [<after-end seconds>]

Never writes production, never sends a signal, never prints or writes an environment value or the marker value.
Every 0.5 s while the child runs it reads (code at 871aaaa9):
  child record   <project>/.graphtraj/swarm/control/agents/<agent>.json, executions[*].process:
                 runtime_pid, tool_marker (only compared, never written), tool_descendants (the sidecar path)
                 (graphtraj/execution/agent_driver.py, run.events.process).
  sidecar        {'version': 1, 'runtime_pid': <pid|null>, 'entries': [{pid, ppid, pgid, uid, start, argv}]}
                 (graftling/tool_descendants.py write_sidecar; argv already through shown_command, redacted).
  processes      the candidate's own readers: _table (pid, ppid, start), _process_view (argv, environment),
                 _executed (darwin P_EXEC), _platform (csops CS_PLATFORM_BINARY), shown_command.
Each changed sample is one JSON line in <raw>/Nw498-samples.jsonl:
  {at, execution, runtime: {pid, alive, env, marker}, tree: [facts], outside: [facts], record: [entries]}
  facts = {pid, ppid, start, P_EXEC, platform, env: None|empty|readable, marker: this|other|none|n/a, argv}
  tree    = the Runtime's descendants now (by ppid); outside = recorded entries alive now but not under the Runtime.
After every execution ended (or the child is retired) it keeps sampling the processes it saw for <after-end seconds>
(default 15; the owner's stop takes up to 3 + 2 s), then writes '== END'. Hard limit <seconds>.
"""
import json, signal, sys, time
from pathlib import Path

signal.signal(signal.SIGHUP, signal.SIG_IGN)

project, raw, source, name, limit = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], float(sys.argv[5])
after = float(sys.argv[6]) if len(sys.argv) > 6 else 15.0
sys.path.insert(0, source)
from graftling.member_processes import MEMBER_RUN_ENV, _process_view  # noqa: E402
from graftling.tool_descendants import _executed, _platform, _table, shown_command  # noqa: E402

agents = project / '.graphtraj/swarm/control/agents'
out, log = raw / 'Nw498-samples.jsonl', raw / 'Nw498.txt'


def note(text):
    with log.open('a') as stream:
        stream.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def child():
    best = None
    for path in agents.glob('*.json') if agents.is_dir() else ():
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if record.get('name') == name and (best is None or path.stat().st_mtime > best[0]):
            best = (path.stat().st_mtime, record)
    return best[1] if best else None


def classes(pid, marker):
    view = _process_view(pid)
    env = 'None' if view is None else ('empty' if not view[1] else 'readable')
    if view is None or not view[1]:
        mark = 'n/a'
    else:
        values = [item.split('=', 1)[1] for item in view[1] if item.startswith(MEMBER_RUN_ENV + '=')]
        mark = 'none' if not values else ('this' if marker and values[0] == marker else 'other')
    return env, mark, view


def facts(item, marker):
    env, mark, view = classes(item.pid, marker)
    return {'pid': item.pid, 'ppid': item.ppid, 'start': item.start, 'P_EXEC': _executed(item.pid),
            'platform': _platform(item.pid), 'env': env, 'marker': mark,
            'argv': shown_command(view[0])[:200] if view and view[0] else ''}


note(f"start: watching {agents} for {name} (read only; at most {limit:.0f} s; {after:.0f} s after the end)")
began, ended_at, last, reason = time.time(), None, {}, f'time limit {limit:.0f} s'
while time.time() - began < limit:
    record = child()
    if record is not None:
        executions = record.get('executions') or []
        table = _table()
        children = {}
        for item in table.values():
            children.setdefault(item.ppid, []).append(item)
        for execution in executions:
            process = execution.get('process') or {}
            marker = process.get('tool_marker') if isinstance(process.get('tool_marker'), str) else None
            sidecar = process.get('tool_descendants')
            entries, side_pid = [], None
            if isinstance(sidecar, str):
                try:
                    document = json.loads(Path(sidecar).read_text())
                    entries, side_pid = document.get('entries') or [], document.get('runtime_pid')
                except (OSError, ValueError):
                    pass
            rpid = process.get('runtime_pid') if isinstance(process.get('runtime_pid'), int) else side_pid
            runtime = {'pid': rpid, 'alive': isinstance(rpid, int) and rpid in table}
            if runtime['alive']:
                runtime['env'], runtime['marker'], _ = classes(rpid, marker)
            tree, pending, seen = [], list(children.get(rpid, [])) if runtime['alive'] else [], set()
            while pending:
                item = pending.pop(0)
                if item.pid in seen:
                    continue
                seen.add(item.pid)
                tree.append(facts(item, marker))
                pending.extend(children.get(item.pid, []))
            outside = [facts(table[e['pid']], marker) for e in entries
                       if isinstance(e.get('pid'), int) and e['pid'] not in seen and e['pid'] in table
                       and table[e['pid']].start == e.get('start')]
            sample = {'execution': execution.get('id'), 'state': execution.get('state'), 'runtime': runtime,
                      'tree': tree, 'outside': outside, 'record': entries}
            key = json.dumps(sample, sort_keys=True)
            if last.get(execution.get('id')) != key:
                last[execution.get('id')] = key
                with out.open('a') as stream:
                    stream.write(json.dumps({'at': time.time(), **sample}) + '\n')
                note(f"execution {execution.get('id')}: runtime alive={runtime['alive']} tree={len(tree)} "
                     f"recorded={len(entries)} outside={len(outside)}")
        done = record.get('retired_at') is not None or (executions and all(e.get('state') == 'ended' for e in executions))
        if done and ended_at is None:
            ended_at = time.time()
            note(f"every execution ended or the child is retired; sampling {after:.0f} s more")
        if ended_at is not None and time.time() - ended_at >= after:
            reason = 'every execution ended'
            break
    time.sleep(0.5)
note(f"== END ({reason}); samples: {sum(1 for _ in out.open()) if out.exists() else 0}")
