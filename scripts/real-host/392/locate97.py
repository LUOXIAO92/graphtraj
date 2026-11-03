"""Step 97: where the DeepSeek value sits in rerun 89's four flagged session files, masked.

Usage: python -I locate97.py <runs directory> <evidence directory>

Reads only, with locate_key.py's masking: no piece of the value is printed or written. For each finding it
says whether the value is inside a model-produced tool result (a toolResult message or a tool execution
record) or in a record agents wrote (any other record), and writes the masked lines to locations-97.txt.
The last act looks for the value in what was written, and empties that file if it is there.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from locate_key import scan_file  # noqa: E402

RUN = '89-residual-416-20261103T205809'
NAMED = [f'{RUN}/{prefix}/{rest}' for prefix in ('harness/.graphtraj', 'out') for rest in (
    'swarm/native/agent-9695e7c2f39344bb82c3bed11a9a2637/trace.pi/session.jsonl',
    'swarm/sessions/4588fb825e162f2310fdb96ca03bdaeb2200ea568e01a79ead1d0504f3886103/session.jsonl')]


def kind(line: str) -> str:
    """Classify one location line from locate_key.describe."""
    fields = json.loads(line)
    if fields.get('role') == 'toolResult' or str(fields.get('type') or '').startswith('tool_execution') or fields.get('tool_call'):
        return 'model-produced tool result'
    if fields.get('role') in ('assistant', 'user'):
        return f"{fields['role']} message"
    return f"record agents wrote (type {fields.get('type')}, customType {fields.get('customType')})"


def main() -> int:
    """Print one answer line per file; masked locations go to the evidence directory."""
    runs, evidence = Path(sys.argv[1]), Path(sys.argv[2])
    value = os.environ.get('DEEPSEEK_API_KEY', '')
    if not value:
        print('CANNOT no DeepSeek value in this process')
        return 0
    output = []
    for name in NAMED:
        path = runs / name
        if not path.is_file():
            print(f'CANNOT {name}: not found')
            continue
        found, raw_only = scan_file(path, value)
        output += [f'{name}\t{line}' for line in found]
        counts = {}
        for line in found:
            counts[kind(line)] = counts.get(kind(line), 0) + 1
        print(f'PASS {name}: {len(found)} masked locations; by kind {counts}; lines holding it outside parsed JSON {raw_only}')
    target = evidence / 'locations-97.txt'
    target.write_text(''.join(line + '\n' for line in output))
    if value in target.read_text(errors='replace'):
        target.write_text('')
        print('FAIL the output held the value, so it was emptied')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
