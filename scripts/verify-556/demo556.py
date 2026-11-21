"""Task 556 demonstration through the real ``graphtraj-mcp`` entry (one process per call).

Usage: python -I demo556.py <graphtraj-mcp executable> <new scratch project directory>

Creates a scratch GraphTraj project, then calls the ``tasks`` tool's
``worldline_append`` with an ``arguments_file`` holding several problems,
fixes only the file and calls again, and shows three refused files (GraphTraj
private state, a link escaping the workspace, a path outside it). Starts no
Runtime and raises no approval dialog.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from graphtraj.configuration.project_configuration import default_configuration_content


def call(entry: str, project: Path, name: str, arguments: dict) -> dict:
    """Send one ``tools/call`` to a new ``graphtraj-mcp`` process in ``project``; return its result."""
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
               'params': {'name': name, 'arguments': arguments}}
    print(f'>>> {name} {json.dumps(arguments)}')
    completed = subprocess.run([entry], input=json.dumps(request) + '\n', capture_output=True,
                               text=True, cwd=project, timeout=120, check=False)
    result = json.loads(completed.stdout.splitlines()[0])['result']
    print('<<< isError =', result['isError'])
    print(json.dumps(result.get('structuredContent', result['content']), indent=2, ensure_ascii=False))
    return result


def main(entry: str, project: Path) -> int:
    """Run the demonstration; return 0 when every expectation holds."""
    project.mkdir(parents=True)
    (project / '.graphtraj').mkdir()
    (project / '.graphtraj/config.yml').write_text(default_configuration_content(project, project))
    arguments = project / 'event.json'
    ok = True

    print('== 1. one call with several problems (schema and worldline_append checks together)')
    arguments.write_text(json.dumps({
        'event': {'event': 'Not plain!', 'caused_by_event_ids': 'not-a-list', 'evidence_refs': ['', '']},
        'note': 'unexpected',
    }, indent=2))
    print(arguments.read_text())
    failed = call(entry, project, 'tasks', {'action': 'execute', 'feature': 'worldline_append',
                                            'arguments_file': 'event.json'})
    errors = failed['structuredContent']['error']['errors']
    ok &= failed['isError'] and len(errors) == 4

    print('== 2. the same call after fixing only the file')
    arguments.write_text(json.dumps({
        'event': {'event': 'demo-556-arguments-file', 'caused_by_event_ids': [], 'evidence_refs': []},
    }, indent=2))
    print(arguments.read_text())
    done = call(entry, project, 'tasks', {'action': 'execute', 'feature': 'worldline_append',
                                          'arguments_file': 'event.json'})
    ok &= not done['isError']
    event_id = done['structuredContent'].get('event_id')

    print('== 3. refused files (only the path is named, never the content)')
    outside = project.parent / f'{project.name}-outside.json'
    outside.write_text('{"secret": "outside-content"}')
    (project / 'escape.json').symlink_to(outside)
    for named in ('.graphtraj/config.yml', 'escape.json', str(outside)):
        refused = call(entry, project, 'tasks', {'action': 'execute', 'feature': 'task_graph',
                                                 'arguments_file': named})
        ok &= refused['isError'] and 'outside-content' not in json.dumps(refused)
    refused = call(entry, project, 'agents', {'action': 'execute', 'feature': 'status',
                                              'arguments_file': '.graphtraj/config.yml'})
    ok &= refused['isError']

    print('== follow-ups (ready to paste)')
    print(f'cd {project} && {Path(entry).parent}/graphtraj worldline read | grep -n {event_id}')
    print(f'cat {arguments}')
    print('RESULT:', 'all expectations held' if ok else 'an expectation FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
