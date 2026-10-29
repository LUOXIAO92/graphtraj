"""Main's Claude host keeps serving while a conflict resolver waits for Main (402)."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import yaml

from agent_swarm import AgentsResult
from conftest import InstalledCommands, run_process
from test_task_graph import _task
from test_task_integration import accepted_document  # noqa: F401  (fixture)


def test_host_serves_main_while_the_conflict_resolver_waits_for_its_reply(
    installed_commands: InstalledCommands,
    accepted_document: tuple,
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The reply, a status read and another Task call complete while the resolver waits.

    The resolver blocks after starting until its permission request is
    answered; Main's ``reply`` is the only call that answers it. Before 402
    ``task_integrate`` waited for the resolver's end, so the host never read
    the reply that ends that wait.
    """
    from graphtraj.execution.runner_connection import parent_connection
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request as handle_task
    from graphtraj.runtimes.claude.mcp import serve

    root, worktrees, _, candidate, environment = accepted_document
    dev = worktrees / 'dev'
    (dev / 'article.md').write_text('conflicting integration work\n')
    run_process(['git', 'add', 'article.md'], cwd=dev).check_returncode()
    run_process(['git', 'commit', '-m', 'Existing document requirement'], cwd=dev).check_returncode()
    validator = [sys.executable, '-c', "from pathlib import Path; assert Path('article.md').read_text() "
                 "== 'complete team round\\nconflicting integration work\\n'"]
    failed = run_process([str(installed_commands.product), 'task', 'integrate', '--task-id', '83',
                          '--', *validator], cwd=root)
    assert failed.returncode == 1, failed.stdout

    # The fake resolver stops after its first event until Main answers it.
    answered = tmp_path / 'permission-answered'
    for name, value in {**environment, 'FAKE_CODEX_LIFECYCLE_ACTION': 'resolve-integration',
                        'FAKE_CODEX_RESOLUTION': 'resolved',
                        'FAKE_CODEX_RELEASE_FILE': str(answered)}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(root)
    runner = root / '.graphtraj/runner'
    connection = {'runtime': 'claude', 'session': str(uuid4()), 'runner': str(runner)}

    def native_call(request: dict, tool: str = 'agents') -> AgentsResult:
        """Run Main's calls as the host's main_calls does; reply answers the resolver."""
        if tool == 'agents':
            assert request['feature'] == 'reply'
            answered.touch()
            return AgentsResult({'replied': True})
        with parent_connection(connection), runtime_caller(runner, None):
            return handle_task(request, cwd=root)

    host_in, requests = (os.fdopen(fd, mode, buffering=1) for fd, mode in zip(os.pipe(), 'rw'))
    replies, host_out = (os.fdopen(fd, mode, buffering=1) for fd, mode in zip(os.pipe(), 'rw'))
    host = threading.Thread(target=serve, args=(host_in, host_out, root),
                            kwargs={'native_call': native_call}, daemon=True)
    host.start()
    answers: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [answers.put(json.loads(line)) for line in replies], daemon=True).start()

    def send(identity: int, tool: str, feature: str, arguments: dict) -> None:
        """Write one tools/call; the host reads it only after earlier calls return."""
        requests.write(json.dumps({'jsonrpc': '2.0', 'id': identity, 'method': 'tools/call', 'params': {
            'name': tool, 'arguments': {'action': 'execute', 'feature': feature, 'arguments': arguments}}}) + '\n')

    def collect(identities: set[int], seconds: float) -> dict[int, dict]:
        """Return the replies received for ``identities`` within a bounded wait."""
        received, deadline = {}, time.monotonic() + seconds
        while set(received) != identities:
            try:
                message = answers.get(timeout=max(deadline - time.monotonic(), 0.01))
            except queue.Empty:
                break
            received[message['id']] = message['result']
        return received

    integrate = {'task_id': '83', 'validation_command': validator}
    try:
        send(1, 'tasks', 'task_integrate', {**integrate, 'resolve_conflict': 'Preserve both document requirements',
                                            'role': 'editor'})
        send(2, 'agents', 'reply', {'agent': 'resolver', 'request': 'permission',
                                    'response': {'decision': 'accept'}})
        send(3, 'tasks', 'task_members', {})
        send(4, 'tasks', 'task_register', _task('90', 'unrelated'))
        received = collect({1, 2, 3, 4}, 60)
        assert set(received) == {1, 2, 3, 4}, f'host answered only {sorted(received)} within 60 s'
    finally:
        # A hung resolver is released so it and the host end with this test.
        answered.touch()
        requests.close()
    dispatched = received[1]['structuredContent']
    assert not received[1]['isError'], dispatched
    assert dispatched['status'] == 'resolving-integration'
    assert dispatched['resolution']['launch_status'] == 'launched'
    assert received[2]['structuredContent'] == {'replied': True}
    assert not received[3]['isError'] and not received[4]['isError'], (received[3], received[4])

    # The resolver's later result is adopted through the public operations.
    alias = dispatched['resolution']['alias']
    reports = None
    for _ in range(600):
        reports = handle_task({'action': 'execute', 'feature': 'session_reports', 'arguments': {'alias': alias}},
                              cwd=root).document
        if reports.get('submissions'):
            break
        time.sleep(0.05)
    submission = reports['submissions'][-1]
    decided = handle_task({'action': 'execute', 'feature': 'decide_result', 'arguments': {
        'submission_id': submission['event_id'], 'commit': submission['candidate'], 'decision': 'accepted',
        'reason': 'Both document requirements hold', 'evidence_refs': submission['evidence_refs']}}, cwd=root)
    assert not decided.failed, decided.document
    integrated = handle_task({'action': 'execute', 'feature': 'task_integrate', 'arguments': integrate}, cwd=root)
    assert integrated.document['status'] == 'integrated', integrated.document
    assert run_process(['git', 'merge-base', '--is-ancestor', candidate, 'HEAD'], cwd=dev).returncode == 0
    assert yaml.safe_load((root / '.graphtraj/state/tasks/83-integration/task.yml').read_text())['status'] == 'integrated'
