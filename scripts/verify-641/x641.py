"""641 helper: probe Tasks, the real host's prompts and judge, Issue listings, rehearsal stand-ins.

usage (python -I):
  x641.py task <id> <parent id or -> <out.yml>  one disposable probe Task definition (neutral text only)
  x641.py graph                                  in the project (cwd): the probe Tasks through public task_graph
  x641.py mcpconfig <.mcp.json> <out.json> <home> <PATH>
                                                 Claude's --mcp-config: the project's graphtraj entry plus env HOME
                                                 (isolated) and PATH (ROOT/bin first, whose gh wrapper gives only gh
                                                 the user's HOME; no token)
  x641.py prompt <1|2> <owner/name>              the one-line prompt of real run 1 or 2
  x641.py judge <1|2> <stream.jsonl> <owner/name> <summary.json> [old child number] [--stand-in]
  x641.py ours <listing.json> <since ISO>        numbers of the Issues this verification created (title prefix +
                                                 backup marker, created at or after since)
  x641.py marked <listing.json> <task-backups.yml> <task id>
                                                 how many listed Issues carry that mapping's current marker line
  x641.py numbers <task-backups.yml>             Issue numbers in the isolated mapping file
  x641.py subs <sub_issues.json>                 numbers of the listed Sub-issues
Rehearsal stand-ins (never used by Main):
  x641.py fake-gh <state.json> <login HOME> <gh arguments...>
                                                         a file-backed stand-in for the gh commands used here; like
                                                         gh's stored login it answers only when HOME is <login HOME>
  x641.py fake-claude <claude arguments...>              runs the prompt's calls through the MCP entry's python
Prints facts only; never prints a token, account or the user's paths.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TOOL   = 'mcp__graphtraj__tasks'
PREFIX = 'verify-641 disposable test Task'
MARK   = '<!-- graphtraj-task-backup task='


def task(task_id: str, parent: str, out: str) -> int:
    """Write one probe Task definition; its text names no account, path, machine, provider or model."""
    import yaml

    role = 'parent' if parent == '-' else 'child'
    Path(out).write_text(yaml.safe_dump({
        'task_id': task_id, 'task_name': f'verify-641-{role}', 'source': 'local:verify-641',
        'title': f'{PREFIX} ({role})',
        'body': 'Disposable test Task for checking that a deleted backup Issue is recreated. '
                'Its Issues are deleted after the check.\n',
        'dependencies': [], 'schema_version': 2, 'parent_id': None if parent == '-' else parent,
        'disposition': 'active', 'replaced_by': [], 'retirement_reason': None,
    }, sort_keys=False))
    return 0


def graph() -> int:
    """Print the probe Tasks from the public task_graph; exit 0 when 1 (parent) and 2 (child of 1) are there."""
    from graphtraj.interfaces.gateway import handle_request

    result = handle_request({'action': 'execute', 'feature': 'task_graph', 'arguments': {}}, cwd=Path.cwd())
    tasks  = {item['task_id']: item for item in result.document.get('tasks', [])}
    for key in sorted(tasks):
        item = tasks[key]
        print(f'  task {key}: {item["title"]!r} | parent {item["parent_id"]} | status {item["status"]}')
    ok = (not result.failed and set(tasks) == {'1', '2'} and tasks['2']['parent_id'] == '1'
          and tasks['1']['title'].startswith(PREFIX) and tasks['2']['title'].startswith(PREFIX))
    return 0 if ok else 1


def mcpconfig(source: str, out: str, home: str, search: str) -> int:
    """Write Claude's --mcp-config from the graphtraj entry that configuration --write made."""
    entry = json.loads(Path(source).read_text())['mcpServers']['graphtraj']
    env   = {**entry.get('env', {}), 'HOME': home, 'PATH': search}
    Path(out).write_text(json.dumps({'mcpServers': {'graphtraj': {**entry, 'env': env}}}, indent=2))
    print(f'{out}: graphtraj -> {Path(entry["command"]).name} {" ".join(entry["args"][:4])} ... | env names: {sorted(env)}')
    return 0


def calls(phase: str, repository: str) -> list[dict]:
    """Run 1 backs up parent 1 then child 2; run 2 backs up child 2 twice."""
    def backup(task_id: str) -> dict:
        return {'action': 'execute', 'feature': 'task_backup',
                'arguments': {'task_id': task_id, 'repository': repository}}
    return [backup('1'), backup('2')] if phase == '1' else [backup('2'), backup('2')]


def prompt(phase: str, repository: str) -> str:
    """The one-line prompt: inline calls in order, nothing else."""
    listed = '; '.join(f'call {n} = {json.dumps(call, separators=(",", ":"))}'
                       for n, call in enumerate(calls(phase, repository), 1))
    return (f'Use only the {TOOL} tool, inline arguments, one call at a time in this order: {listed}. '
            f'Make no other call. Then reply with exactly one line: DONE-641-{phase}.')


def payload(text: str) -> object:
    """Decode one tool result text; a wrapped ``result`` is unwrapped."""
    try:
        document = json.loads(text)
    except ValueError:
        return text
    if isinstance(document, dict) and 'outcome' not in document and isinstance(document.get('result'), dict):
        return document['result']
    return document


def stream_calls(stream: str) -> tuple[list, dict | None, list]:
    """Return the init record, the final record and each tool call with its answer."""
    init, final, uses, answers = None, None, [], {}
    for line in Path(stream).read_text().splitlines() if Path(stream).is_file() else []:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get('type') == 'system' and record.get('subtype') == 'init':
            init = record
        if record.get('type') == 'result':
            final = record
        for item in (record.get('message') or {}).get('content') or []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use':
                uses.append((item.get('id'), item.get('name'), item.get('input')))
            if item.get('type') == 'tool_result':
                content = item.get('content')
                body    = (' '.join(part.get('text', '') for part in content if isinstance(part, dict))
                           if isinstance(content, list) else str(content))
                answers[item.get('tool_use_id')] = (bool(item.get('is_error')), payload(body))
    made = [(name, arguments, *answers.get(use, (True, 'no result'))) for use, name, arguments in uses]
    return made, init, [final]


def judge(phase: str, stream: str, repository: str, summary: str, *rest: str) -> int:
    """Judge one real run from its stream and write the Issue numbers it reported to ``summary``."""
    stand_in = '--stand-in' in rest
    old      = next((int(item) for item in rest if item.isdigit()), None)
    made, init, (final,) = stream_calls(stream)
    failed = 0

    def ck(name: str, ok: bool, detail: str = '') -> None:
        nonlocal failed
        failed += not ok
        print(f'CHECK 641 run {phase} {name}: {"PASS" if ok else "FAIL"}{f" ({detail})" if detail else ""}')

    if init is not None:
        plugins = [plugin.get('name') for plugin in init.get('plugins', [])]
        servers = [(server.get('name'), server.get('status')) for server in init.get('mcp_servers', [])]
        print(f'init: model {init.get("model")} | apiKeySource {init.get("apiKeySource")} | plugins {plugins} '
              f'| mcp servers {servers}')
        native = 'graphtraj-claude-host' in plugins
        print('serving path: ' + ('STAND-IN (rehearsal; no Claude host)' if stand_in else
                                  'native graphtraj-claude-host association' if native else
                                  'graphtraj-claude-host NOT loaded (run the trust step)'))
        if stand_in:
            print(f'CHECK 641 run {phase} serving path is the native association: SKIPPED (stand-in, not evidence)')
        else:
            ck('serving path is the native association', native)
    else:
        ck('stream has an init record', False)
    for number, (name, arguments, error, answer) in enumerate(made, 1):
        print(f'call {number}: {name} {json.dumps(arguments)[:160]} -> {"ERROR " if error else ""}'
              f'{json.dumps(answer)[:400]}')
    expected = calls(phase, repository)
    ck('exactly the expected task_backup calls, inline, in order',
       [(name, arguments) for name, arguments, _, _ in made] == [(TOOL, call) for call in expected],
       f'{len(made)} calls')
    answers = [answer if isinstance(answer, dict) and not error else {} for _, _, error, answer in made]
    answers += [{}] * (2 - len(answers))
    first, second = answers[:2]

    def issue(answer: dict) -> int | None:
        return ((answer.get('backup') or {}).get('issue') or {}).get('number')

    if phase == '1':
        ck('parent 1 created', first.get('outcome') == 'created' and issue(first) is not None,
           f'outcome {first.get("outcome")}, Issue #{issue(first)}')
        ck('child 2 created and linked under the parent',
           second.get('outcome') == 'created' and issue(second) is not None
           and second.get('hierarchy') == [{'parent': '1', 'child': '2', 'outcome': 'linked'}],
           f'outcome {second.get("outcome")}, Issue #{issue(second)}, hierarchy {second.get("hierarchy")}')
        found = {'parent': issue(first), 'child': issue(second)}
    else:
        replaced = first.get('replaced_issue') or {}
        ck('child 2 recreated: outcome recreated naming the deleted Issue',
           first.get('outcome') == 'recreated' and replaced.get('number') == old
           and issue(first) not in (None, old),
           f'outcome {first.get("outcome")}, replaced_issue {replaced}, new Issue #{issue(first)}, deleted #{old}')
        ck('the recreated Issue is linked under the parent',
           first.get('hierarchy') == [{'parent': '1', 'child': '2', 'outcome': 'linked'}],
           f'hierarchy {first.get("hierarchy")}')
        ck('repeating the backup is unchanged on the same Issue',
           second.get('outcome') == 'unchanged' and issue(second) == issue(first) and 'replaced_issue' not in second
           and second.get('hierarchy') == [{'parent': '1', 'child': '2', 'outcome': 'unchanged'}],
           f'outcome {second.get("outcome")}, Issue #{issue(second)}, hierarchy {second.get("hierarchy")}')
        found = {'recreated': issue(first)}
    if final is not None:
        print(f'final: {str(final.get("result"))[:80]!r} | is_error {final.get("is_error")}')
    Path(summary).write_text(json.dumps(found))
    print(f'RESULT 641 judge run {phase}: {"PASS" if not failed else f"FAIL ({failed})"} | Issues {found}')
    return 1 if failed else 0


def listed(listing: str) -> list[dict]:
    """Read a saved Issue listing (one JSON array, or several from gh --paginate)."""
    text = Path(listing).read_text().strip()
    try:
        return json.loads(text)
    except ValueError:
        return [item for part in text.replace('][', ']\n[').splitlines() for item in json.loads(part)]


def ours(listing: str, since: str) -> int:
    """Print the numbers of Issues this verification created: neutral title prefix and a backup marker."""
    start = datetime.fromisoformat(since.replace('Z', '+00:00')) - timedelta(minutes=2)
    print(' '.join(str(item['number']) for item in listed(listing)
                   if 'pull_request' not in item and str(item.get('title', '')).startswith(PREFIX)
                   and MARK in (item.get('body') or '')
                   and datetime.fromisoformat(item['created_at'].replace('Z', '+00:00')) >= start))
    return 0


def mapping(backups: str, task_id: str) -> dict:
    """Return the isolated mapping of ``task_id``."""
    import yaml

    return next(item for item in yaml.safe_load(Path(backups).read_text())['backups'] if item['task_id'] == task_id)


def marked(listing: str, backups: str, task_id: str) -> int:
    """Print how many listed Issues carry the mapping's current marker line (GraphTraj's own adoption test)."""
    item = mapping(backups, task_id)
    line = '<!-- graphtraj-task-backup task={0} marker={1} -->'.format(task_id, item['marker'])
    print(sum(line in (issue.get('body') or '').splitlines() for issue in listed(listing)))
    return 0


def numbers(backups: str) -> int:
    """Print the Issue numbers recorded in the isolated mapping file (none when it is absent)."""
    import yaml

    path = Path(backups)
    items = yaml.safe_load(path.read_text())['backups'] if path.is_file() else []
    print(' '.join(str(item['issue']['number']) for item in items if item.get('issue')))
    return 0


def subs(listing: str) -> int:
    """Print the numbers of the listed Sub-issues."""
    print(' '.join(str(item['number']) for item in listed(listing)))
    return 0


def fake_gh(state_file: str, login_home: str, args: list[str]) -> int:
    """Rehearsal stand-in for ``gh``: auth status, api (REST used here) and issue delete, kept in a JSON file.

    Like gh's stored login (found through HOME), every request except ``--version`` answers only when HOME is
    ``login_home``; otherwise it fails as the real gh did with an isolated HOME.
    """
    if args[:1] != ['--version'] and os.environ.get('HOME') != login_home:
        sys.stderr.write('github.com\n  X Failed to log in to github.com account (default)\n'
                         '  - The token in default is invalid. (stand-in: HOME is not the login HOME)\n')
        return 1
    path  = Path(state_file)
    state = json.loads(path.read_text()) if path.is_file() else {'issues': [], 'parents': {}, 'serial': 900}

    def finish(document: object, code: int = 0) -> int:
        path.write_text(json.dumps(state))
        if code:
            sys.stderr.write(f'gh: {document}\n')
        elif document is not None:
            sys.stdout.write(json.dumps(document))
        return code

    def find(repository: str, number: int) -> dict | None:
        return next((item for item in state['issues']
                     if (item['repository'], item['number']) == (repository, number)), None)

    def delete(item: dict) -> None:
        item['deleted'] = True
        key = str(item['id'])
        state['parents'] = {child: parent for child, parent in state['parents'].items()
                            if key not in (child, str(parent))}

    if args[:1] == ['--version']:
        print('gh stand-in (rehearsal)')
        return 0
    if '--jq' in args:
        # Only the field paths this script asks for (``.a.b``).
        at = args.index('--jq')
        expression, args = args[at + 1], args[:at] + args[at + 2:]
        output = subprocess.run([sys.executable, '-I', __file__, 'fake-gh', state_file, login_home, *args],
                                capture_output=True, text=True, check=False)
        if output.returncode:
            sys.stderr.write(output.stderr)
            return output.returncode
        value = json.loads(output.stdout)
        for key in expression.strip('.').split('.'):
            value = value[key]
        print(json.dumps(value) if not isinstance(value, str) else value)
        return 0
    if args[:2] == ['auth', 'status']:
        print('github.com\n  Logged in to github.com (stand-in)')
        return 0
    if args[:2] == ['issue', 'delete']:
        item = find(args[args.index('--repo') + 1], int(args[2]))
        if item is None or item.get('deleted'):
            return finish('Could not resolve to an issue', 1)
        delete(item)
        return finish(None)
    if args[0] != 'api':
        return finish(f'stand-in does not implement {args[:2]}', 1)
    method = args[args.index('--method') + 1] if '--method' in args else 'GET'
    target = next(item for item in args[1:] if item.startswith('repos/'))
    data   = json.load(sys.stdin) if '--input' in args else None
    url    = urlsplit(target)
    parts  = url.path.split('/')
    repo   = '/'.join(parts[1:3])
    if len(parts) == 3:
        return finish({'full_name': repo, 'permissions': {'admin': True}})
    if len(parts) == 4 and method == 'POST':
        state['serial'] += 1
        number = max([item['number'] for item in state['issues'] if item['repository'] == repo] + [900]) + 1
        item = {'repository': repo, 'number': number, 'id': 70000 + state['serial'],
                'node_id': f'I_stand_in_{state["serial"]}', 'html_url': f'https://github.com/{repo}/issues/{number}',
                'title': data['title'], 'body': data['body'], 'state': 'open',
                'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
        state['issues'].append(item)
        return finish(item)
    if len(parts) == 4:
        assert parse_qs(url.query)['state'] == ['all']
        return finish(sorted([item for item in state['issues'] if item['repository'] == repo
                              and not item.get('deleted')], key=lambda item: -item['number']))
    item = find(repo, int(parts[4]))
    if item is None:
        return finish('Not Found (HTTP 404)', 1)
    if item.get('deleted'):
        return finish('This issue was deleted (HTTP 410)', 1)
    if len(parts) == 6 and parts[5] == 'parent':
        parent = state['parents'].get(str(item['id']))
        found  = next((other for other in state['issues'] if other['id'] == parent), None)
        return finish(found) if found else finish('Not Found (HTTP 404)', 1)
    if len(parts) == 6 and parts[5] == 'sub_issues' and method == 'GET':
        return finish([other for other in state['issues']
                       if state['parents'].get(str(other['id'])) == item['id'] and not other.get('deleted')])
    if len(parts) == 6 and parts[5] == 'sub_issues':
        if str(data['sub_issue_id']) in state['parents'] and not data.get('replace_parent'):
            return finish('a Sub-issue has one parent (HTTP 422)', 1)
        state['parents'][str(data['sub_issue_id'])] = item['id']
        return finish(item)
    if len(parts) == 6 and parts[5] == 'sub_issue':
        state['parents'].pop(str(data['sub_issue_id']), None)
        return finish(item)
    if method == 'PATCH':
        item.update(data)
    return finish(item)


def fake_claude(args: list[str]) -> int:
    """Rehearsal stand-in for ``claude``: runs the prompt's tasks calls through the MCP entry's python and env.

    It is not a Claude host and has no native association; the judge prints STAND-IN for it.
    """
    if '--version' in args:
        print('stand-in (rehearsal; not Claude Code)')
        return 0
    text  = sys.stdin.read()
    lines = [{'type': 'system', 'subtype': 'init', 'model': 'STAND-IN', 'apiKeySource': 'none',
              'plugins': [], 'mcp_servers': [], 'tools': []}]
    found = [json.loads(item) for item in re.findall(r'call \d+ = (\{.*?\})(?=; call|\. Make)', text)]
    # Rehearsal of a midway failure: the named run makes no call, so its judge fails.
    if '--rehearsal-break-run' in args and f'DONE-641-{args[args.index("--rehearsal-break-run") + 1]}.' in text:
        found = []
    if found:
        entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['graphtraj']
        env   = {**os.environ, **entry.get('env', {})}
        code  = ('import json, sys\nfrom pathlib import Path\n'
                 'from graphtraj.interfaces.gateway import handle_request\n'
                 'for request in json.loads(sys.stdin.read()):\n'
                 '    result = handle_request(request, cwd=Path.cwd())\n'
                 '    print(json.dumps([result.failed, result.document]))\n')
        ran = subprocess.run([entry['command'], '-I', '-c', code], input=json.dumps(found), env=env,
                             capture_output=True, text=True, check=False)
        sys.stderr.write(ran.stderr)
        for number, (request, answer) in enumerate(zip(found, ran.stdout.splitlines()), 1):
            error, document = json.loads(answer)
            lines.append({'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': f'use-{number}', 'name': TOOL, 'input': request}]}})
            lines.append({'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': f'use-{number}', 'is_error': error,
                 'content': [{'type': 'text', 'text': json.dumps(document)}]}]}})
    lines.append({'type': 'result', 'result': 'stand-in', 'is_error': False})
    sys.stdout.write(''.join(json.dumps(line) + '\n' for line in lines))
    return 0


if __name__ == '__main__':
    operation, rest = sys.argv[1], sys.argv[2:]
    handlers = {'task': task, 'graph': graph, 'mcpconfig': mcpconfig, 'judge': judge, 'ours': ours,
                'marked': marked, 'numbers': numbers, 'subs': subs}
    if operation == 'prompt':
        print(prompt(*rest))
        sys.exit(0)
    if operation == 'fake-gh':
        sys.exit(fake_gh(rest[0], rest[1], rest[2:]))
    if operation == 'fake-claude':
        sys.exit(fake_claude(rest))
    if operation not in handlers:
        sys.exit(f'unknown operation {operation}')
    sys.exit(handlers[operation](*rest))
