"""Rehearsal fixtures for the 498 production observation (watch498.py samples, the stop record), real shapes.

usage: rehearse498.py <raw dir> <sidecar dir> <scenario> [<live pid> <live start>]

Writes <raw>/Nw498-samples.jsonl (watch498.py's line shape) and <sidecar dir>/claude-termination-n1.yml
(graftling/claude/execution.py's termination record with stop_tool_processes's escaped_processes {found, stopped,
remaining}). Pids 70000+ are fake (their identity() start never matches, so they read as gone).
Scenarios:
  positive        Runtime readable with this marker; tool shell, subshell (P_EXEC False, platform), sleep 1201 in it,
                  sleep 1202, sh -c with the redacted credential, sleep 1203; all recorded; all stopped at the end.
  foreign         positive plus a recorded entry that reads readable with another execution's marker.
  alive           positive plus a recorded process still alive after the end, not in found (<live pid> <live start>).
  unsettled       sleep 1202 listed only under remaining (unsettled) but gone long before its own end (signalled).
  unsettled-ok    sleep 1202 (live pid) listed only under remaining and still alive (not signalled).
  unreadable      positive, but the Runtime's environment reads None from the watcher.
"""
import json, sys, time
from pathlib import Path

raw, side, scenario = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
live = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else None
now = time.time()
S = int((now - 60) * 1_000_000)   # identity().start: microseconds
R = 70000
SHELL = "/bin/zsh -c -l source /x/snapshot.sh && eval '( sleep 1201; true ) >/dev/null 2>&1 & sleep 1202 >/dev/null 2>&1 & sh -c ...' && pwd -P"


def fact(pid, ppid, argv, P_EXEC=True, platform=True, env='readable', marker='this', start=S):
    return {'pid': pid, 'ppid': ppid, 'start': start, 'P_EXEC': P_EXEC, 'platform': platform, 'env': env,
            'marker': marker, 'argv': argv}


tree = [fact(R + 5, R, SHELL),
        fact(R + 10, R + 5, SHELL, P_EXEC=False),               # the subshell: a fork copy of the platform zsh
        fact(R + 11, R + 10, 'sleep 1201'),
        fact(R + 12, R + 5, 'sleep 1202'),
        fact(R + 13, R + 5, 'sh -c sleep 1203; : api_key=[redacted]'),
        fact(R + 14, R + 13, 'sleep 1203')]
if scenario == 'unsettled-ok' and live:
    tree[3] = dict(tree[3], pid=live[0], start=live[1])
runtime = {'pid': R, 'alive': True, 'env': 'None' if scenario == 'unreadable' else 'readable',
           'marker': 'n/a' if scenario == 'unreadable' else 'this'}
outside = []
if scenario == 'foreign':
    tree.append(fact(R + 20, R + 5, 'python other_execution_tool.py', marker='other'))
if scenario == 'alive' and live:
    tree.append(fact(live[0], R + 5, 'sleep 30', start=live[1]))
record = [{'pid': f['pid'], 'ppid': f['ppid'], 'pgid': R + 5, 'uid': 501, 'start': f['start'], 'argv': f['argv']} for f in tree]
samples = [{'at': now - 50, 'execution': 'e1', 'state': 'running', 'runtime': runtime, 'tree': tree[:1], 'outside': [],
            'record': record[:1]},
           {'at': now - 40, 'execution': 'e1', 'state': 'running', 'runtime': runtime, 'tree': tree, 'outside': outside,
            'record': record},
           {'at': now - 5, 'execution': 'e1', 'state': 'ended', 'runtime': {'pid': R, 'alive': False}, 'tree': [],
            'outside': [], 'record': record}]
raw.mkdir(parents=True, exist_ok=True)
(raw / 'Nw498-samples.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in samples))
ours = [f for f in tree if f['marker'] == 'this' and f['pid'] != R + 5]
found = [f for f in ours]
remaining = []
if scenario in ('unsettled', 'unsettled-ok'):
    found = [f for f in ours if f['argv'] != 'sleep 1202']
    remaining = [f for f in ours if f['argv'] == 'sleep 1202']
if scenario == 'alive':
    found = [f for f in ours if f['argv'] != 'sleep 30']
side.mkdir(parents=True, exist_ok=True)
import yaml
entry = lambda f: {'pid': f['pid'], 'command': f['argv'][:160]}
(side / 'claude-termination-n1.yml').write_text(yaml.safe_dump(
    {'session': 'sess-c', 'execution_id': 'n1', 'runtime_pid': R, 'worker_pid': 9191, 'process_group_closed': True,
     'runtime_exit_code': 0, 'stdout_eof': True, 'stderr_eof': True, 'pipes_closed': True, 'native_idle': True,
     'escaped_processes': {'found': [entry(f) for f in found], 'stopped': [entry(f) for f in found],
                           'remaining': [entry(f) for f in remaining]}}, sort_keys=False))
print(f'498 fixture {scenario}: {len(samples)} samples, {len(record)} recorded, found {len(found)}, remaining {len(remaining)}')
