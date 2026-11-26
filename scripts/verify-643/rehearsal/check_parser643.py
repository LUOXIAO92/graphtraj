"""Task 643 rehearsal: the rollout parser on REAL rollouts (Task 640's R-unelevated evidence, Codex 0.172.0 on Windows
Server 2022). For every rollout: the exec_command calls, the exit code drive643.tool_calls reads for each (fixed), and
what drive640.tool_calls read (the defect: None). Prints counts and codes only, never a command or a value.
Usage: python3 -I check_parser643.py <verify-643/vm> <verify-640/vm> <rollout dir>..."""
import json, pathlib, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import drive643, drive640
total, good = 0, 0
for directory in sys.argv[3:]:
    for path in sorted(pathlib.Path(directory).glob('*.jsonl')):
        records = [json.loads(line) for line in path.read_text(encoding='utf-8', errors='replace').splitlines() if line.strip()]
        raw = sum(1 for r in records if r.get('type') == 'response_item' and (r.get('payload') or {}).get('type') == 'function_call'
                  and (r['payload'].get('name') == 'exec_command'))
        new = [c for c in drive643.tool_calls(records) if c['tool'] == 'exec_command']
        old = [c for c in drive640.tool_calls(records) if c['tool'] == 'exec_command']
        total += raw
        good += sum(1 for c in new if c['exit_code'] == -1073741502)
        print(f'{pathlib.Path(directory).name}/{path.name[:40]}...: exec_command function_calls {raw}; '
              f'643 parser {len(new)} call(s), exit codes {sorted({c["exit_code"] for c in new}, key=str)}; '
              f'640 parser exit codes {sorted({str(c["exit_code"]) for c in old})}')
print(f'PARSER {"PASS" if total and good == total else "FAIL"}: {good} of {total} exec_command calls read as -1073741502')
