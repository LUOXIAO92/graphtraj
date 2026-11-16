"""Shared isolation of a verify project nested under the Harness from the Harness instruction files (Task 489).

User authorization (Worldline 20261116T180057.272969+0900): verification scripts may disable Claude Code's builtin
plugin cc-plugin-agents-md and exclude the Harness CLAUDE.md/AGENTS.md in an isolated test project's OWN
.claude/settings.local.json under Harness tmp/<task>/ -- never ~/.claude, global plugin settings or the Harness
AGENTS.md. `settings` refuses any project outside <harness>/tmp/.

Cause (489 A/B): the builtin plugin cc-plugin-agents-md walks up from the working directory and gives the model the
Harness AGENTS.md, even when the project has its own git and .graphtraj. Claude Code also loads CLAUDE.md /
CLAUDE.local.md from every parent directory. Existing keys are merged, so rerun `settings` after every
`configuration --write` that rewrites the file.

usage:
  claude_isolation.py prompt <tag>                      (prints PROMPT with TAG filled in)
  claude_isolation.py settings <harness> <project> [--only plugin|excludes]
  claude_isolation.py check <stream.jsonl> <tag> <harness> <project> <prompt file> [--expect clean|loaded]

check reads a real `claude -p --output-format stream-json --verbose` run of PROMPT. A Harness instruction file
counts as LOADED when the init record lists cc-plugin-agents-md, when the FILES line names a file of the Harness
outside the project, or when the answer holds the longest line of the Harness AGENTS.md (compared in memory, never
printed). The answer must not be the prompt echoed. --expect clean (default) exits 0 only when the host answered
with TAG and nothing was loaded; --expect loaded exits 0 only when it answered and something was loaded (the
before-fix demonstration).
"""
import json, sys
from pathlib import Path

PROMPT = ('Reply with exactly two lines. Line 1: TAG followed by the model id you are running as, and say whether '
          'you are logged in. Line 2: FILES: the absolute path of every AGENTS.md or CLAUDE.md whose contents you '
          'were given as instructions, or NONE. Use no tool.')
PLUGIN = 'cc-plugin-agents-md'
EXCLUDES = ('/CLAUDE.md', '/CLAUDE.local.md', '/.claude/CLAUDE.md', '/**/CLAUDE.md', '/**/CLAUDE.local.md',
            '/AGENTS.md', '/**/AGENTS.md')


def settings(harness, project, only=None):
    harness = harness.rstrip('/')
    proj = Path(project).resolve()
    if not proj.is_relative_to(Path(harness).resolve() / 'tmp'):
        print(f'REFUSED: {proj} is not an isolated test project under {harness}/tmp/ (user authorization scope)')
        return 2
    path = proj / '.claude' / 'settings.local.json'
    s = json.loads(path.read_text()) if path.is_file() else {}
    if only in (None, 'excludes'):
        s['claudeMdExcludes'] = sorted({*s.get('claudeMdExcludes', []), *(harness + x for x in EXCLUDES)})
    if only in (None, 'plugin'):
        s['enabledPlugins'] = {**s.get('enabledPlugins', {}), PLUGIN + '@builtin': False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s, indent=2) + '\n')
    print(f'project settings: {path} | claudeMdExcludes {len(s.get("claudeMdExcludes", []))} | '
          f'{PLUGIN}@builtin: {s.get("enabledPlugins", {}).get(PLUGIN + "@builtin", "(not set)")}')
    return 0


def check(stream, tag, harness, project, prompt_file, expect='clean'):
    harness, project = harness.rstrip('/'), project.rstrip('/')
    prompt = Path(prompt_file).read_text().strip()
    agents = Path(harness) / 'AGENTS.md'
    lines = [l.strip() for l in (agents.read_text(errors='replace').splitlines() if agents.is_file() else [])]
    distinct = max((l for l in lines if len(l) >= 30 and not l.startswith('#')), key=len, default='')
    text, is_error, models, plugins, init = None, None, [], [], False
    for line in open(stream, errors='replace'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get('type') == 'system' and d.get('subtype') == 'init':
            init = True
            plugins = [p.get('name') if isinstance(p, dict) else p for p in d.get('plugins') or []]
        if d.get('type') == 'result':
            text, is_error = str(d.get('result') or ''), d.get('is_error')
            models = list((d.get('modelUsage') or {}).keys())
    plugin_loaded = any(PLUGIN in str(p) for p in plugins)
    print(f'init record: {"yes" if init else "NONE"} | plugins: {plugins} | {PLUGIN} loaded: {"YES" if plugin_loaded else "NO"}')
    if text is None:
        print('answer: NONE (no result record)')
        print(f'answer check (expect {expect}): STOP (the host gave no result; see the .err file)')
        return 1
    rows = [l.strip() for l in text.splitlines() if l.strip()]
    files = next((l for l in rows if l.startswith('FILES:')), None)
    answer = next((l for l in reversed(rows) if not l.startswith('FILES:')), '')
    named = (files or '')[6:].split()
    leaked = [w for w in named if (w == harness or w.startswith(harness + '/'))
              and not (w == project or w.startswith(project + '/'))]
    echo = text.strip() == prompt or prompt in text or (len(prompt) > 40 and prompt[:40] in text)
    holds = bool(distinct) and distinct in text
    print(f'answer: {answer[:160]} | is_error: {is_error} | models: {models}')
    print(f'instruction files the model reported: {named or "(no FILES line)"} | Harness files among them: {leaked or "none"}')
    print(f'echo of the prompt: {"YES" if echo else "no"} | distinctive Harness AGENTS.md line in the answer: {"YES" if holds else "no"}')
    answered = not is_error and answer.startswith(tag) and '<' not in answer and files is not None and not echo
    loaded = plugin_loaded or bool(leaked) or holds
    print(f'host answered: {"yes" if answered else "NO"} | Harness instruction file loaded: {"YES" if loaded else "NO"}')
    ok = answered and (loaded if expect == 'loaded' else not loaded)
    print(f'answer check (expect {expect}):', 'OK' if ok else 'STOP')
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ['prompt'] and len(argv) == 2:
        print(PROMPT.replace('TAG', argv[1]))
        return 0
    if argv[:1] == ['settings'] and len(argv) in (3, 5):
        only = argv[4] if len(argv) == 5 and argv[3] == '--only' and argv[4] in ('plugin', 'excludes') else None
        if len(argv) == 5 and only is None:
            print(__doc__); return 2
        return settings(argv[1], argv[2], only)
    if argv[:1] == ['check'] and len(argv) in (6, 8):
        expect = 'clean'
        if len(argv) == 8:
            if argv[6] != '--expect' or argv[7] not in ('clean', 'loaded'):
                print(__doc__); return 2
            expect = argv[7]
        return check(*argv[1:6], expect=expect)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
