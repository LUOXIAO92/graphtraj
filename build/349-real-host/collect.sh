#!/bin/sh
# Task 349 real-host kit: snapshot the isolated project's Main records after a step.
#   /bin/bash build/349-real-host/collect.sh <step-label>
# Reads only GraphTraj records under the isolated project and Pi Session files in
# the kit's own session directory; prints no environment and copies no credentials.
set -eu

T=${T:-/private/tmp/graphtraj-349}
P=$T/project
# The Runner follows the project's selected layout (legacy .graphtraj/runner or core/runner).
R=$("$T/venv/bin/python" -c 'import sys; from pathlib import Path; from graphtraj.configuration.project_configuration import runner_directory; print(runner_directory(Path(sys.argv[1])))' "$P")
LABEL=${1:?step label required}
OUT=$T/evidence/$LABEL
mkdir -p "$OUT"

cp "$R/main-sessions/continuity.jsonl" "$OUT/continuity.jsonl" 2>/dev/null || echo "(no continuity.jsonl)" > "$OUT/continuity.jsonl"
if [ -d "$R/main-sessions/inbox" ]; then
  mkdir -p "$OUT/inbox"
  cp "$R/main-sessions/inbox/"*.jsonl "$R/main-sessions/inbox/"*.cursor "$OUT/inbox/" 2>/dev/null || true
fi
for directory in "$R"/sessions/*/; do
  [ -f "$directory/parent-notices.jsonl" ] || continue
  cp "$directory/parent-notices.jsonl" "$OUT/parent-notices-$(basename "$directory").jsonl"
done
ps -Ao pid,ppid,command | grep -E 'graphtraj-(mcp|session)|/bin/(pi|dsh)|claude' | grep -v grep > "$OUT/processes.txt" || true

"$T/venv/bin/python" - "$T" "$OUT" "$R" <<'PY' | tee "$OUT/summary.txt"
"""Print claims, queues, members and executions; check the claim record is append-only."""
import hashlib
import json
import sys
from pathlib import Path

T, OUT = Path(sys.argv[1]), Path(sys.argv[2])
runner = Path(sys.argv[3])
claims_path = runner / 'main-sessions/continuity.jsonl'
lines = claims_path.read_text().splitlines() if claims_path.exists() else []

print('== claims (continuity.jsonl, oldest first)')
for line in lines:
    claim = json.loads(line)
    previous = claim['previous'] and f"{claim['previous']['runtime']}:{claim['previous']['session']}"
    print(f"  {claim['entry']:<32} {claim['runtime']}:{claim['session']}  previous={previous}")

# Every earlier snapshot must be a prefix of the current record.
prefix_ok = True
for earlier in sorted((T / 'evidence').glob('*/continuity.jsonl')):
    if earlier.parent == OUT or earlier.read_text().startswith('(no'):
        continue
    if lines[:len(earlier.read_text().splitlines())] != earlier.read_text().splitlines():
        prefix_ok = False
        print(f'  NOT APPEND-ONLY versus {earlier.parent.name}')
print(f'== append-only versus earlier snapshots: {prefix_ok}')

print('== Main notice queues (runtime:session lines/acknowledged)')
for claim in {(json.loads(l)['runtime'], json.loads(l)['session']) for l in lines}:
    key = hashlib.sha256(':'.join(claim).encode()).hexdigest()
    queue = runner / 'main-sessions/inbox' / (key + '.jsonl')
    cursor = queue.with_suffix('.cursor')
    total = len(queue.read_text().splitlines()) if queue.exists() else 0
    acknowledged = int(cursor.read_text()) if cursor.exists() else 0
    print(f'  {claim[0]}:{claim[1]}  queued={total} acknowledged={acknowledged}')
    if queue.exists():
        for row in queue.read_text().splitlines():
            event = json.loads(row)['event']
            print(f"    - {event.get('alias')} {event.get('event')}: {str(event.get('message'))[:120]!r}")

print('== Task-free Agents (executions: operation/outcome/last message)')
for path in sorted((T / 'project/.graphtraj/swarm/control/agents').glob('*.json')):
    record = json.loads(path.read_text())
    creator = record.get('creator') or {}
    print(f"  {record['agent']} name={record.get('name')} creator={creator.get('host')}:{creator.get('session')}")
    for execution in record.get('executions', []):
        print(f"    - {execution.get('operation')}/{execution.get('outcome') or execution.get('state')}: "
              f"{str(execution.get('last_message'))[:80]!r}")

print('== Task member Sessions (alias, owner, delivered notices)')
for directory in sorted((runner / 'sessions').glob('*')):
    notices = directory / 'parent-notices.jsonl'
    mapping = directory / 'mapping.yml'
    owner = ''
    if mapping.exists():
        import yaml
        data = yaml.safe_load(mapping.read_text()) or {}
        connection = data.get('parent_connection') or {}
        owner = f"parent={data.get('parent')} owner={connection.get('runtime')}:{connection.get('session')}"
    print(f'  {directory.name} {owner}')
    if notices.exists():
        for row in notices.read_text().splitlines():
            record = json.loads(row)
            address = record.get('parent_connection') or {}
            print(f"    - {record.get('identity', {}).get('type')} delivery={record.get('delivery')} "
                  f"to={address.get('runtime')}:{address.get('session')}")
PY
echo "saved: $OUT"
