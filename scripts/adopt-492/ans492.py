"""492 (Task 489 lesson): judge a real `claude -p --output-format stream-json` answer from the isolated project.

usage: ans492.py <stream.jsonl> <tag> <harness> <project> <prompt file>

PASS (exit 0) only when the result is not an error, its last-but-one non-empty line starts with <tag> and names no
placeholder, the answer neither equals nor contains the prompt (echo), the FILES line names no file of the Harness
outside the project, and the answer holds no distinctive line of the Harness AGENTS.md (its longest line, compared
in memory, never printed). Prints the plugins of the init record and whether cc-plugin-agents-md was loaded.
"""
import json, sys
from pathlib import Path

stream, tag, harness, project, prompt = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], Path(sys.argv[5]).read_text().strip()
agents = Path(harness) / 'AGENTS.md'
lines = [l.strip() for l in (agents.read_text(errors='replace').splitlines() if agents.is_file() else [])]
distinct = max((l for l in lines if len(l) >= 30 and not l.startswith('#')), key=len, default='')
text, is_error, models, plugins = None, None, [], []
for line in open(stream, errors='replace'):
    try:
        d = json.loads(line)
    except ValueError:
        continue
    if d.get('type') == 'system' and d.get('subtype') == 'init':
        plugins = [p.get('name') if isinstance(p, dict) else p for p in d.get('plugins') or []]
    if d.get('type') == 'result':
        text, is_error, models = str(d.get('result') or ''), d.get('is_error'), list((d.get('modelUsage') or {}).keys())
print('plugins in init:', plugins, '| cc-plugin-agents-md loaded:', 'YES' if any('cc-plugin-agents-md' in str(p) for p in plugins) else 'NO')
if text is None:
    print('answer: NONE (no result record)'); print('answer check: STOP'); sys.exit(1)
rows = [l.strip() for l in text.splitlines() if l.strip()]
files = next((l for l in rows if l.startswith('FILES:')), None)
answer = next((l for l in reversed(rows) if not l.startswith('FILES:')), '')
named = (files or '')[6:].split()
leaked = [w for w in named if w.startswith(harness) and not w.startswith(project)]
echo = text.strip() == prompt or prompt in text or (len(prompt) > 40 and prompt[:40] in text)
holds_agents = bool(distinct) and distinct in text
print(f'answer: {answer[:160]} | is_error: {is_error} | models: {models}')
print(f'instruction files reported: {named or "NONE"} | Harness files among them: {leaked or "none"}')
print(f'echo of the prompt: {"YES" if echo else "no"} | distinctive Harness AGENTS.md line in the answer: {"YES" if holds_agents else "no"}')
ok = (not is_error and answer.startswith(tag) and '<' not in answer and files is not None and not leaked
      and not echo and not holds_agents)
print('answer check:', 'OK' if ok else 'STOP')
sys.exit(0 if ok else 1)
