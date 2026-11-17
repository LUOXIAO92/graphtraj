"""Nr, 498 part: the production observation of tool-descendant identification (read only; never signals).

usage: nr498.py <project> <raw dir> <candidate source dir (B's git archive of 871aaaa9)/src> <child name>

Inputs (formats verified from the source at 871aaaa9):
  <raw>/Nw498-samples.jsonl   watch498.py samples: runtime {pid, alive, env, marker}, tree/outside facts
                              {pid, ppid, start, P_EXEC, platform, env, marker, argv}, record = sidecar entries
                              {pid, ppid, pgid, uid, start, argv}.
  child record                <project>/.graphtraj/swarm/control/agents/<agent>.json executions[*].process
                              {runtime_pid, tool_descendants}.
  stop record                 claude-termination-<execution>.yml next to the sidecar (graftling/claude/execution.py:
                              written when the child's execution ends, after _close and stop_tool_processes):
                              {runtime_pid, ..., escaped_processes: {found: [{pid, command}], stopped: [...],
                              remaining: [...], error?}} (tool_descendants.stop_tool_processes). found = every target
                              signalled; remaining = signalled and still alive, plus unsettled (later) reads that were
                              never signalled.
The probe's tool command (N, step 02) starts, detached, a subshell `( sleep 1201; true )` (a fork copy of the tool
shell that never executes: P_EXEC clear), `sleep 1202` (executed) and `sh -c 'sleep 1203; : api_key=<fake>'` (its
recorded command line carries the fake credential). They end by themselves after 1201-1203 s.
Liveness: the candidate's identity() (same pid and start time). Nothing is signalled.
"""
import json, re, sys, time
from pathlib import Path

import yaml

project, raw, source, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, source)
from graftling.tool_descendants import identity  # noqa: E402

DURATIONS = {'sub': 1201, 'bg': 1202, 'sh': 1203}
FAKE = 'sk-probe503fake' + 'value0000'   # never printed; counts only


def check(label, ok, detail=''):
    print(f"CHECK {label}: {ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL')}{(' (' + detail + ')') if detail else ''}")


def exe_sleep(argv, seconds):
    words = str(argv).split()
    return len(words) >= 2 and words[0].rsplit('/', 1)[-1] == 'sleep' and words[1] == str(seconds)


def sh_c(argv):
    words = str(argv).split()
    return len(words) >= 2 and words[0].rsplit('/', 1)[-1] == 'sh' and words[1] == '-c' and f"sleep {DURATIONS['sh']}" in str(argv)


samples_path = raw / 'Nw498-samples.jsonl'
samples = []
if samples_path.is_file():
    for line in samples_path.read_text(errors='replace').splitlines():
        try:
            samples.append(json.loads(line))
        except ValueError:
            pass
agents = project / '.graphtraj/swarm/control/agents'
found = []
for path in agents.glob('*.json') if agents.is_dir() else ():
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        continue
    if record.get('name') == name:
        found.append((path.stat().st_mtime, record))
child = max(found, key=lambda item: item[0])[1] if found else None
print(f"498: samples {len(samples)} in {samples_path}; child {name}: {'agent ' + str(child.get('agent')) if child else 'NOT FOUND'}")
if not samples or child is None:
    for label in ('Runtime environment and marker observed', 'record lists this execution\'s tool commands (subshell, background sleeps)',
                  'record contains no other execution\'s process', 'recorded tool processes stopped at the execution end',
                  'unsettled reads only under remaining, not signalled', 'credential masked in the record and the stop record'):
        check(f'498 {label}', 'BLOCKED', f'not observed - no Nw498 samples or no child record ({samples_path})')
    sys.exit(1)

# Observation: the Runtime's environment class and marker class (classes only).
envs = sorted({str(s['runtime'].get('env')) for s in samples if s['runtime'].get('alive')})
marks = sorted({str(s['runtime'].get('marker')) for s in samples if s['runtime'].get('alive')})
rpids = sorted({s['runtime'].get('pid') for s in samples if s['runtime'].get('pid') is not None})
print(f"498 observation: child Runtime pid(s) {rpids}; environment readable from Main's watcher: {envs or ['never alive in a sample']}; "
      f"carries this execution's marker: {marks or ['n/a']} (classes: env None/empty/readable; marker this/other/none/n/a)")
check('498 Runtime environment and marker observed', 'PASS' if envs else 'BLOCKED',
      f"env {envs} marker {marks}" if envs else 'not observed - the Runtime was never alive in a sample (Nw started after the child ended?)')

# The tool processes, by (pid, start), from every sample (tree and outside).
procs = {}
in_tree = set()
for s in samples:
    for f in s.get('tree') or []:
        procs.setdefault((f['pid'], f['start']), dict(f, first=s['at']))
        in_tree.add((f['pid'], f['start']))
    for f in s.get('outside') or []:
        procs.setdefault((f['pid'], f['start']), dict(f, first=s['at']))
recorded = {}
for s in samples:
    for e in s.get('record') or []:
        if isinstance(e.get('pid'), int) and isinstance(e.get('start'), int):
            recorded.setdefault((e['pid'], e['start']), e)
mine = {}
for key, f in procs.items():
    for kind in ('sub', 'bg'):
        if exe_sleep(f['argv'], DURATIONS[kind]):
            mine.setdefault(kind if kind == 'bg' else 'sub-sleep', key)
    if sh_c(f['argv']):
        mine.setdefault('sh', key)
    if exe_sleep(f['argv'], DURATIONS['sh']):
        mine.setdefault('sh-sleep', key)
if 'sub-sleep' in mine:
    parent = procs[mine['sub-sleep']]['ppid']
    sub = [k for k in procs if k[0] == parent]
    if sub:
        mine['subshell'] = sub[0]
for kind, key in sorted(mine.items()):
    f = procs[key]
    print(f"498 tool process {kind}: pid {f['pid']} ppid {f['ppid']} P_EXEC {f['P_EXEC']} platform {f['platform']} env {f['env']} "
          f"marker {f['marker']} recorded {key in recorded} seen under the Runtime {key in in_tree} argv {f['argv'][:120]!r}")
need = ['subshell', 'sub-sleep', 'bg', 'sh']
missing = [k for k in need if k not in mine or mine[k] not in recorded]
check("498 record lists this execution's tool commands (subshell, background sleeps)", not missing,
      f"missing or not recorded: {missing}" if missing else f"recorded: {', '.join(need)}")

# No other execution's process: every recorded entry was seen under the Runtime (pid and start), or is recorded
# beneath one that was (recorded ppid chain); none read readable without this marker while recorded.
ok_keys, unseen, foreign = set(), [], []
by_pid = {k[0]: k for k in recorded}
for key in recorded:
    chain, k = [], key
    while k is not None and k not in in_tree and k not in chain:
        chain.append(k)
        k = by_pid.get(recorded[k].get('ppid'))
    if k is None or k not in in_tree:
        if recorded[key].get('ppid') not in rpids:
            unseen.append(key[0])
for s in samples:
    keys = {(e.get('pid'), e.get('start')) for e in s.get('record') or []}
    for f in (s.get('tree') or []) + (s.get('outside') or []):
        if (f['pid'], f['start']) in keys and f['env'] == 'readable' and f['marker'] != 'this':
            foreign.append(f"{f['pid']} marker {f['marker']}")
detail = f"recorded entries {len(recorded)}; not seen under the Runtime {sorted(unseen)}; readable without this marker {sorted(set(foreign))}"
check("498 record contains no other execution's process", 'FAIL' if foreign else ('BLOCKED' if unseen else 'PASS'),
      detail + ('' if foreign or not unseen else ' - not observed for those entries (watcher missed them)'))

# After the end: the stop record.
execution = (child.get('executions') or [{}])[0]
sidecar = (execution.get('process') or {}).get('tool_descendants')
term, tpath = None, None
if execution.get('state') == 'ended' and isinstance(sidecar, str):
    for path in sorted(Path(sidecar).parent.glob('claude-termination-*.yml')):
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if document.get('runtime_pid') in rpids or path.stem.endswith(Path(sidecar).stem.replace('tool-descendants-', '')):
            term, tpath = document, path
if term is None:
    why = 'the child execution has not ended yet: rerun Nr later' if execution.get('state') != 'ended' else f'no claude-termination-*.yml for the Runtime next to {sidecar}'
    for label in ('recorded tool processes stopped at the execution end', 'unsettled reads only under remaining, not signalled'):
        check(f'498 {label}', 'PENDING' if execution.get('state') != 'ended' else 'BLOCKED', why)
else:
    escaped = term.get('escaped_processes') or {}
    pids = {part: {e.get('pid') for e in escaped.get(part) or [] if isinstance(e, dict)} for part in ('found', 'stopped', 'remaining')}
    print(f"498 stop record {tpath}: found {sorted(pids['found'])} stopped {sorted(pids['stopped'])} remaining {sorted(pids['remaining'])}"
          f"{' error ' + str(escaped.get('error')) if escaped.get('error') else ''}")
    now = time.time()
    bad, rows, gaps = [], [], []
    unsettled = pids['remaining'] - pids['found']
    long_lived = {key for kind, key in mine.items() if kind in ('subshell', 'sub-sleep', 'bg', 'sh', 'sh-sleep')}

    def why_gone(key):
        """Correction 1: from the watcher's samples, why a gone probe process is not listed under stopped."""
        present = [i for i, s in enumerate(samples)
                   if any((f['pid'], f['start']) == key for f in (s.get('tree') or []) + (s.get('outside') or []))]
        if not present:
            return 'unknown (never seen alive in a sample)'
        later = samples[present[-1] + 1:]
        if any(s.get('state') != 'ended' for s in later):
            return 'ended before the execution end, not by this execution\'s stop (absent in a later running sample)'
        if later:
            return (f"ended at the end without the tool-process stop (process-group close?); "
                    f"process_group_closed={term.get('process_group_closed')}")
        return 'unknown (no sample after it was last seen)'

    for key in sorted(recorded):
        pid, start = key
        alive = (lambda i: i is not None and i.start == start)(identity(pid))
        argv = str(recorded[key].get('argv', ''))
        # identity().start is microseconds on darwin (pbi_start_tvsec * 1e6 + usec).
        ends = next((start / 1e6 + d for d in DURATIONS.values() if f'sleep {d}' in argv), None)
        when = time.strftime('%H:%M:%S', time.localtime(ends)) if ends else 'unknown'
        state = 'alive' if alive else 'gone'
        rows.append(f"  recorded pid {pid}: {state}; found {pid in pids['found']} stopped {pid in pids['stopped']} "
                    f"remaining {pid in pids['remaining']}{'; ends by itself at ' + when + ' (never signalled here)' if alive else ''}"
                    f"{' (unsettled read: only reported)' if pid in unsettled else ''}")
        if pid in unsettled:
            continue
        # Alive after the end and not an unsettled read: not stopped (FAIL). A long-lived probe process that is gone
        # but not listed under stopped is an observation gap, not evidence of a defect (Correction 1): Claude Code may
        # end it at the Bash tool's end, or _close()'s process-group close (before stop_tool_processes) may end it.
        if alive:
            bad.append(pid)
        elif key in long_lived and pid not in pids['stopped']:
            reason = why_gone(key)
            gaps.append(f'{pid}: {reason}')
            rows.append(f"    pid {pid} gone, not listed under stopped: {reason}")
    print('\n'.join(rows) or '  (no recorded entry)')
    both = sorted(pids['found'] & pids['remaining'])
    if not recorded or bad or both:
        verdict = 'FAIL'
    elif gaps:
        verdict = 'NOT OBSERVED'
    else:
        verdict = 'PASS'
    check('498 recorded tool processes stopped at the execution end (gone; listed under found and stopped)', verdict,
          f"alive after the end, not stopped: {bad}; signalled but still alive: {both}"
          + (f"; gone without the stop listing them: {'; '.join(gaps)}" if gaps else ''))
    wrong = []
    for pid in sorted(unsettled):
        key = next((k for k in procs if k[0] == pid), None)
        alive = key is not None and (lambda i: i is not None and i.start == key[1])(identity(pid))
        argv = procs[key]['argv'] if key else ''
        ends = next((key[1] / 1e6 + d for d in DURATIONS.values() if f'sleep {d}' in argv), None) if key else None
        print(f"  unsettled (remaining, not found) pid {pid}: {'alive (not signalled)' if alive else 'gone'}"
              f"{'; ends by itself at ' + time.strftime('%H:%M:%S', time.localtime(ends)) if alive and ends else ''}")
        if not alive and ends is not None and now < ends:
            wrong.append(pid)
    check('498 unsettled reads only under remaining, not signalled',
          not wrong,
          f"unsettled {sorted(unsettled)}; gone before their own end (signalled): {wrong}" if unsettled else 'none unsettled')

# Credential masking in the record (keeps 495 (466); the results are counted by nr499.py).
texts = [samples_path.read_text(errors='replace') if samples_path.is_file() else '']
if term is not None:
    texts.append(tpath.read_text(errors='replace'))
if isinstance(sidecar, str) and Path(sidecar).is_file():
    texts.append(Path(sidecar).read_text(errors='replace'))
values = sum(t.count(FAKE) for t in texts)
sh_entry = recorded.get(mine.get('sh')) if mine.get('sh') else None
red = sh_entry is not None and '[redacted]' in str(sh_entry.get('argv', ''))
check('498 credential masked in the record and the stop record (value 0; the sh -c entry shows [redacted])', values == 0 and red,
      f"value occurrences {values}; recorded sh -c entry {'has' if red else 'lacks'} [redacted]")
