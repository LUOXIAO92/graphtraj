"""Cross-platform native entries used by the installed Windows desktop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from conftest import PROJECT_ROOT


def operation(root: Path, feature: str, arguments: dict) -> dict:
    """Invoke the same public stdio entry used by the packaged desktop."""
    environment = {**os.environ, 'PYTHONPATH': str(PROJECT_ROOT / 'src')}
    reply = subprocess.run(
        [sys.executable, '-c', 'from graphtraj.interfaces.local_tool import main; main()'],
        input=json.dumps({'action': 'execute', 'feature': feature, 'arguments': arguments}) + '\n',
        cwd=root, env=environment, text=True, capture_output=True, timeout=30, check=True,
    )
    value = json.loads(reply.stdout)
    assert not value.get('failed'), value
    return value['result']


def test_public_setup_and_concurrent_registration(temporary_git_repository: Path) -> None:
    """Separate writers retain all graph nodes and native dependency edges."""
    root = temporary_git_repository
    operation(root, 'project_setup', {'source_repository': str(root), 'apply': True, 'create_dev': True})

    def register(number: int) -> None:
        """Register one controlled ticket through the public entry."""
        operation(root, 'ticket_register', {
            'ticket_id': str(number), 'ticket_name': f'controlled-{number}',
            'title': f'Controlled {number}', 'body': 'No Agent or model execution.',
            'source': f'https://github.com/example/controlled/issues/{number}',
            'dependencies': [] if number == 1 else ['1'],
        })

    register(1)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(register, range(2, 6)))
    graph = operation(root, 'ticket_graph', {})
    assert {ticket['ticket_id'] for ticket in graph['tickets']} == {'1', '2', '3', '4', '5'}
    assert all(ticket['dependencies'] == ['1'] for ticket in graph['tickets'] if ticket['ticket_id'] != '1')


def test_public_settings_processes_keep_one_approved_winner(temporary_git_repository: Path) -> None:
    """Two independent desktop pipes review one revision without losing a save."""
    root = temporary_git_repository
    operation(root, 'project_setup', {'source_repository': str(root), 'apply': True, 'create_dev': True})
    (root / '.graphtraj/roles.yml').write_text(
        'roles:\n  reader:\n    runtime: codex\n    model: original\nrole_tree: {}\n', encoding='utf-8',
    )
    command = [sys.executable, '-c', 'from graphtraj.interfaces.local_tool import main; main()', '--desktop-settings']
    environment = {**os.environ, 'PYTHONPATH': str(PROJECT_ROOT / 'src')}
    initial = subprocess.run(command, input='{"action":"read"}\n', cwd=root, env=environment,
                             text=True, capture_output=True, timeout=15, check=True)
    revision = json.loads(initial.stdout)['result']['revision']
    processes = []
    try:
        for model in ('first', 'second'):
            child = subprocess.Popen(command, cwd=root, env=environment, text=True,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes.append(child)
            child.stdin.write(json.dumps({'action': 'save', 'revision': revision,
                                          'edits': {'reader': {'model': model}}}) + '\n')
            child.stdin.flush()
        for child in processes:
            proposal = json.loads(child.stdout.readline())
            assert 'review' in proposal, proposal
        # Release both real native save pipes after both have reviewed the same revision.
        for child in processes:
            child.stdin.write('{"decision":"accept"}\n')
            child.stdin.flush()
        replies = [json.loads(child.communicate(timeout=15)[0]) for child in processes]
        assert sorted(reply['failed'] for reply in replies) == [False, True], replies
        winner = next(reply['result'] for reply in replies if not reply['failed'])
        final = subprocess.run(command, input='{"action":"read"}\n', cwd=root, env=environment,
                               text=True, capture_output=True, timeout=15, check=True)
        assert json.loads(final.stdout)['result']['roles'] == winner['roles']
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=15)
