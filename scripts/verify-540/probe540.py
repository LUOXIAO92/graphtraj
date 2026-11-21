"""Task 540 V only: an extra SessionStart hook that records that the hook fired and whether the marker reached it.

usage (as a Codex command hook): python -I probe540.py <output jsonl>

Reads the hook event from stdin; appends one line {at, hook_event_name, source, session_id, marker} where marker is
whether GRAFTLING_MEMBER_RUN is in this hook's environment (its value is never written). Prints {} so Codex adds
nothing. This lets C tell 'the child's hook fired and was skipped' from 'the hook never fired' or 'the marker did not
reach the hook environment'. Writes only <output jsonl>.
"""
import json
import os
import sys
import time

if len(sys.argv) != 2:
    print(__doc__, file=sys.stderr)
    sys.exit(2)
try:
    event = json.loads(sys.stdin.read() or '{}')
except ValueError:
    event = {}
record = {'at': time.time(), 'hook_event_name': event.get('hook_event_name'), 'source': event.get('source'),
          'session_id': event.get('session_id'), 'marker': 'GRAFTLING_MEMBER_RUN' in os.environ}
with open(sys.argv[1], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(record) + '\n')
print('{}')
