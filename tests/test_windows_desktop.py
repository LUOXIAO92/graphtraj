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
