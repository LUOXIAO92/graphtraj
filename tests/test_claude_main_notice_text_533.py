"""533: a GraphTraj Claude Main gets the shared notice text on both of its notice paths.

GraphTraj queues Main notices itself (main_continuity.queue_notice). The mod submits and draws ``text``;
without it the Main sees the old title and the end record as escaped JSON.
"""
import json
from pathlib import Path
from uuid import uuid4

from graftling.calls import Call, current_call

from graphtraj.configuration.project_configuration import runner_directory
from graphtraj.execution.main_continuity import queue_notice
from graphtraj.runtimes.claude.host import NativeCalls, main_calls

REPLY = '## Reply from n533\n\n- one `agents`\n- two\n\n> quoted "line"'


def queue_three(runner: Path, session: str) -> None:
    """An end, a native permission request and a report, as GraphTraj's notify_direct_parent queues them."""
    connection = {'runtime': 'claude', 'session': session}
    end = {'session': 's1', 'execution_id': 'exec-1', 'outcome': 'completed', 'terminal_confirmed': True,
           'session_id': 's1', 'permissions': {'requested': 'auto', 'matches_request': True},
           'last_agent_message': REPLY}
    queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'n533@advisor', 'event': 'completed',
                                      'message': 'Session execution ended:\n' + json.dumps(end, ensure_ascii=False),
                                      'execution': 'exec-1'})
    request = {'session': 's2', 'execution_id': 'exec-2', 'request_id': 'req-9', 'request_token': 'tok-7',
               'method': 'claude/can_use_tool', 'params': {'tool_name': 'Bash', 'input': {'command': 'ls'}}}
    queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'w@engineer', 'event': 'claude/can_use_tool',
                                      'message': 'Claude requires a native permission reply:\n' + json.dumps(request),
                                      'execution': 'exec-2', 'request_id': 'req-9'})
    queue_notice(runner, connection, {'source': 'graphtraj', 'alias': 'e@engineer', 'event': 'report-submitted',
                                      'message': 'Submitted report engineer.md for its direct parent to handle; '
                                                 'read it through session_reports: /h/.state/engineer.md'})


def assert_texts(notices: list[dict]) -> None:
    texts = {notice['event']['event']: notice['text'] for notice in notices}
    assert set(texts) == {'completed', 'claude/can_use_tool', 'report-submitted'}
    end = texts['completed']
    assert end.startswith('[Graftling notice from n533@advisor · completed · execution exec-1]\n')
    assert REPLY in end
    assert end.splitlines()[-1] == 'Facts: execution_id `exec-1` · outcome `completed`'
    request = texts['claude/can_use_tool']
    assert request.startswith('[Graftling notice from w@engineer · claude/can_use_tool · execution exec-2]\n')
    assert request.splitlines()[-1] == ('Facts: execution_id `exec-2` · request_id `req-9` · '
                                        'request_token `tok-7` · method `claude/can_use_tool`')
    assert '"command": "ls"' in request
    assert texts['report-submitted'].endswith('session_reports: /h/.state/engineer.md')
    for text in texts.values():
        for dropped in ('permissions', 'terminal_confirmed', 'session_id', '\\n', '\\"'):
            assert dropped not in text
    # The stored event stays what was queued.
    assert all('text' not in notice['event'] for notice in notices)


def project(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / 'project'
    (root / '.graphtraj').mkdir(parents=True)
    return root, runner_directory(root), str(uuid4())


def test_pushed_notices_carry_the_shared_text(tmp_path: Path) -> None:
    root, runner, session = project(tmp_path)
    queue_three(runner, session)
    claimed = NativeCalls(lambda *a: None, root, runner).notices({'operation': 'notices', 'session': session})
    assert_texts(claimed['notices'])
    stored = (runner / 'main-sessions').rglob('*.jsonl')
    assert all('"text"' not in path.read_text() for path in stored)


def test_notices_on_a_result_carry_the_shared_text(tmp_path: Path) -> None:
    root, runner, session = project(tmp_path)
    queue_three(runner, session)
    run = main_calls(root, lambda *a, **k: None, None)(session, root)
    with current_call(Call()):
        document = run('tasks', {'action': 'discover'}).document
    assert_texts(document['main_notices'])
