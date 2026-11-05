#!/bin/zsh
# Step 03 (Main, no dialog): claude -p in the scratch project creates a Claude
# child through the plugin's agents tool and waits for it.
source ${0:A:h}/env.zsh
rm -rf "$PROJECT/.agents-control"
export GRAFTLING_PYTHON=$VENV/bin/python
{
  cd "$PROJECT"
  print "== claude mcp list"; "$CLAUDE" mcp list
  print "== claude -p (stream in $OUT/03-stream.jsonl)"
  print -r -- "Use the $TOOL tool, not your own subagents. Discover its features, create a Claude child that answers exactly one word, then wait for it and print the wait result." \
    | "$CLAUDE" -p --verbose --output-format stream-json --allowedTools "$TOOL" \
    > "$OUT/03-stream.jsonl"
  print "exit $?"
  print "== agents results"
  "$VENV/bin/python" - "$OUT/03-stream.jsonl" "$TOOL" <<'PY'
import json, sys
calls, found = set(), []
for line in open(sys.argv[1], encoding='utf-8', errors='replace'):
    try: message = (json.loads(line).get('message') or {})
    except ValueError: continue
    for item in message.get('content') if isinstance(message.get('content'), list) else []:
        if item.get('type') == 'tool_use' and item.get('name') == sys.argv[2]: calls.add(item['id'])
        if item.get('type') == 'tool_result' and item.get('tool_use_id') in calls:
            content = item.get('content')
            text = content if isinstance(content, str) else ' '.join(b.get('text', '') for b in content or [])
            found.append(text); print('result:', text[:800])
ok = any('"standby"' in t and '"completed"' in t for t in found)
print('standby+completed:', ok)
PY
  print "== configuration the host wrote"; cat "$PROJECT/.agents-control/claude-host.json"
  print "\n== host.log"; cat "$PROJECT/.agents-control/host.log"
} 2>&1 | tee "$OUT/03-create-child.txt"
cat <<NEXT

Success: 'standby+completed: True' (a wait result with state standby and
last_result.outcome completed), claude-host.json with cwd $PROJECT, and host.log
ending 'agents host recorded its children stopped.'
If a result says 'must be launched directly by the selected Claude CLI', copy it:
the claude on PATH differs from the running one.
Next: zsh $STEPS/04-both.zsh
NEXT
