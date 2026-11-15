"""agents' session_read: slices, views, search, redaction and who may read (466)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import graftling
from graftling import AgentControl, Caller, handle_request
from graftling.sessions import SessionArchive

SECRETS = ('sk-test-secret-value-466', 'ctl-secret-466', 'bearer-secret-466')
ROUNDS = 12
MAIN = 'main-session'


def header(session: str) -> dict:
    """Return a v5 header for one native Claude Session."""
    return {'version': 5, 'id': 'claude:' + session, 'createdAt': 1, 'isSeeded': False,
            'native': {'runtime': 'claude', 'sessionId': session, 'locator': 'test'}}


def message(seq: int, session: str, role: str, blocks: list[dict]) -> dict:
    """Return one archived user or assistant message event."""
    native = {'runtime': 'claude', 'sessionId': session, 'locator': f'message:{seq}'}
    if role == 'user':
        return {'type': 'user/message', 'seq': seq, 'time': 1, 'surfaceOp': 'append', 'native': native,
                'data': {'id': f'm{seq}', 'role': 'user', 'content': blocks, 'source': {'kind': 'user'}}}
    return {'type': 'assistant/message', 'seq': seq, 'time': 1, 'surfaceOp': 'append', 'native': native,
            'data': {'turn': 0, 'step': 0, 'stream': [], 'message': {
                'id': f'm{seq}', 'role': 'assistant', 'content': blocks,
                'source': {'kind': 'model', 'provider': 'test', 'model': 'test'}}}}


def conversation(session: str) -> list[dict]:
    """Return ROUNDS rounds of question, answer with a tool call, tool result and an attached record."""
    events = []
    for number in range(ROUNDS):
        question = f'question {number} of {session}'
        if number == 3:
            question += ' my api_key: ' + SECRETS[0]
        if number == 7:
            question += ' NEEDLE here'
        seq = len(events)
        events += [
            message(seq, session, 'user', [{'type': 'text', 'text': question}]),
            message(seq + 1, session, 'assistant', [
                {'type': 'text', 'text': f'answer {number}'},
                {'type': 'tool-call', 'id': f't{number}', 'name': 'Bash', 'arguments': '{"command": "ls"}'}]),
            message(seq + 2, session, 'user', [{'type': 'tool_result', 'tool_use_id': f't{number}',
                                                'content': f'tool output {number} Bearer {SECRETS[2]}'
                                                           + (' ERROR466 permission denied' if number == 5 else '')}]),
            {'type': 'claude/observation', 'seq': seq + 3, 'time': 0, 'data': {}, 'ignorable': True,
             'native': {'runtime': 'claude', 'sessionId': session, 'locator': f'transcript:{seq + 3}',
                        'record': {'type': 'attachment', 'control_key': SECRETS[1],
                                   'text': f'attached record {number}'}}},
        ]
    return events


def archive(root: Path, *sessions: str) -> None:
    """Archive one conversation per native Session under data root ``root``."""
    store = SessionArchive(root, save_normalized_sessions=True)
    for session in sessions:
        store.map_session(header(session))
        assert store.collect('claude:' + session, conversation(session), source='test', position=1)


def agent(reference: str, parent: str | None, session: str) -> dict:
    """Return a stopped Agent record created by the Main Session."""
    return {'agent': reference, 'name': reference, 'runtime': 'claude', 'host': 'test-host', 'parent': parent,
            'creator': {'host': 'test-host', 'agent': parent, 'session': None if parent else MAIN},
            'session': session, 'sessions': [session], 'settings': {}, 'created_at': 1.0,
            'retired_at': None, 'executions': []}


@pytest.fixture
def control(tmp_path: Path) -> AgentControl:
    """A Main with two top-level Agents; the first has a child, which has a child."""
    root = tmp_path / 'data-root'
    control = AgentControl(root, {})
    for reference, parent in (('agent-p', None), ('agent-c', 'agent-p'), ('agent-g', 'agent-c'),
                              ('agent-s', None)):
        control.import_agent(agent(reference, parent, 's-' + reference[-1]))
    archive(root, MAIN, 's-p', 's-c', 's-g', 's-s')
    return control


def read(control: AgentControl, caller: Caller, **arguments) -> tuple[dict, bool]:
    """Call session_read through the bound agents function."""
    result = graftling.bind(control, caller)({'action': 'session_read', **arguments})
    return result.document, result.failed


def full(control: AgentControl, content: str) -> list[dict]:
    """Return every item of one view of Main's own Session."""
    document, failed = read(control, Caller('test-host', None, MAIN, 'claude'),
                            session=MAIN, content=content, start=0)
    assert not failed, document
    return document['result']['events']


def test_parent_reads_its_range_and_nothing_else(control: AgentControl) -> None:
    """Own, ancestors' and descendants' Sessions are readable; a sibling's is not-found."""
    readable = {
        'agent-p': ({'agent': 'agent-c'}, {'agent': 'agent-g'}, {'session': MAIN}, {'agent': 'agent-p'}),
        'agent-c': ({'agent': 'agent-p'}, {'agent': 'agent-g'}, {'session': 's-c'}, {'session': MAIN}),
        'agent-g': ({'agent': 'agent-c'}, {'session': 'claude:s-p'}),
    }
    for reference, targets in readable.items():
        for target in targets:
            document, failed = read(control, Caller('test-host', reference), **target)
            assert not failed, (reference, target, document)
            assert document['result']['session'].startswith('claude:')
    for reference in ('agent-p', 'agent-c', 'agent-g'):
        for target in ({'agent': 'agent-s'}, {'session': 's-s'}, {'session': 'no-such-session'}):
            document, failed = read(control, Caller('test-host', reference), **target)
            assert failed and document['error']['code'] == 'not-found', (reference, target)
    main = Caller('test-host', None, MAIN, 'claude')
    for target in ({'agent': 'agent-s'}, {'agent': 'agent-g'}, {'session': MAIN}):
        assert not read(control, main, **target)[1]
    other_main = Caller('test-host', None, 'another-main', 'claude')
    document, failed = read(control, other_main, agent='agent-p')
    assert failed and document['error']['code'] == 'not-found'


def test_unknown_callers_are_refused_first(control: AgentControl) -> None:
    """An unrecorded Agent or a caller without Agent or Session is authority-denied, found or not."""
    for caller in (Caller('test-host', 'agent-unknown'), Caller('test-host', None)):
        for target in ({'agent': 'agent-p'}, {'session': 'no-such-session'}):
            document, failed = read(control, caller, **target)
            assert failed and document['error']['code'] == 'authority-denied', (caller, target)


def test_default_is_last_five_and_slices_match_python(control: AgentControl) -> None:
    """No range returns [-5:]; every slice selects exactly what Python list slicing selects."""
    caller = Caller('test-host', 'agent-p')
    for content in ('text', 'tools', 'all'):
        items = full(control, content)
        document, failed = read(control, caller, session=MAIN, content=content)
        assert not failed and document['result']['events'] == items[-5:]
        assert document['result']['total'] == len(items)
        for start, stop in ((-10, -5), (-5, None), (0, 3), (None, -20), (-100, 2), (5, 2), (30, 100),
                            (-1, None), (None, None), (3, -3)):
            arguments = {name: value for name, value in (('start', start), ('stop', stop)) if value is not None}
            if not arguments:
                continue
            document, failed = read(control, caller, session=MAIN, content=content, **arguments)
            result = document['result']
            assert not failed and result['events'] == items[start:stop], (content, start, stop)
            assert [item['index'] for item in result['events']] == list(range(len(items)))[start:stop]
    page = read(control, caller, session=MAIN)[0]['result']
    back = read(control, caller, session=MAIN, start=-10, stop=-5)[0]['result']
    assert page['earlier'] == {'start': back['start'], 'stop': back['stop']} == {'start': 14, 'stop': 19}


def test_default_omits_tool_results_and_records(control: AgentControl) -> None:
    """text keeps conversation text; tools adds calls and results; all adds attached records."""
    text = full(control, 'text')
    assert len(text) == 2 * ROUNDS and all(set(item) == {'index', 'seq', 'type', 'text'} for item in text)
    serialized = json.dumps(text)
    assert 'tool output' not in serialized and 'attached record' not in serialized and 'Bash' not in serialized
    assert 'omitted' in read(control, Caller('test-host', 'agent-p'), session=MAIN)[0]['result']
    tools = json.dumps(full(control, 'tools'))
    assert 'tool output 0' in tools and '"name": "Bash"' in tools and 'attached record' not in tools
    everything = full(control, 'all')
    assert len(everything) == 4 * ROUNDS and 'attached record 0' in json.dumps(everything)
    document = read(control, Caller('test-host', 'agent-p'), session=MAIN, content='all')[0]['result']
    assert 'omitted' not in document and document['header']['id'] == 'claude:' + MAIN


def test_search_returns_positions_to_slice_around(control: AgentControl) -> None:
    """Hits carry the view index; a slice around one reads the hit; long hit lists stay bounded."""
    caller = Caller('test-host', 'agent-c')
    found = read(control, caller, session=MAIN, search='needle')[0]['result']
    assert found['hits_total'] == 1 and 'NEEDLE here' in found['hits'][0]['snippet']
    index = found['hits'][0]['index']
    around = read(control, caller, session=MAIN, start=index - 1, stop=index + 2)[0]['result']['events']
    assert 'NEEDLE' in around[1]['text'] and around[1]['seq'] == found['hits'][0]['seq']
    assert read(control, caller, session=MAIN, search='tool output')[0]['result']['hits_total'] == 0
    tools = read(control, caller, session=MAIN, search='tool output', content='tools')[0]['result']
    assert tools['hits_total'] == ROUNDS
    many = read(control, caller, session=MAIN, search='attached record', content='all')[0]['result']
    assert many['hits_total'] == ROUNDS and len(many['hits']) == ROUNDS
    questions = read(control, caller, session=MAIN, search='e', content='all')[0]['result']
    assert questions['hits_total'] == 4 * ROUNDS and len(questions['hits']) == 20
    assert questions['earlier_hits'] == {'count': 4 * ROUNDS - 20, 'stop': questions['hits'][0]['index']}
    narrowed = read(control, caller, session=MAIN, search='question', start=0, stop=8)[0]['result']
    assert narrowed['hits_total'] == 4


def test_no_credential_value_is_returned_or_searchable(control: AgentControl) -> None:
    """Credentials and control material are redacted in every view and before searching."""
    caller = Caller('test-host', 'agent-p')
    for content in ('text', 'tools', 'all'):
        serialized = json.dumps(read(control, caller, session=MAIN, content=content, start=0)[0])
        assert not any(secret in serialized for secret in SECRETS), content
        for secret in SECRETS:
            found = read(control, caller, session=MAIN, content=content, search=secret)[0]['result']
            assert found['hits_total'] == 0 and not any(found['outside_view'].values())


def test_search_names_matches_outside_the_view(control: AgentControl) -> None:
    """An error only in a Bash result: 0 text hits, an outside count naming tools, then found and sliced."""
    caller = Caller('test-host', 'agent-p')
    found = read(control, caller, session=MAIN, search='error466')[0]['result']
    assert found['hits_total'] == 0 and found['outside_view'] == {'tools': 1, 'all': 1}
    assert "content 'tools' (1 of them)" in found['repeat']
    tools = read(control, caller, session=MAIN, search='error466', content='tools')[0]['result']
    assert tools['hits_total'] == 1 and tools['outside_view'] == {'all': 0}
    index = tools['hits'][0]['index']
    item = read(control, caller, session=MAIN, content='tools', start=index, stop=index + 1)[0]['result']['events']
    assert item[0]['content'][0]['type'] == 'tool-result' and 'ERROR466' in item[0]['content'][0]['content']
    records = read(control, caller, session=MAIN, search='attached record 3')[0]['result']
    assert records['outside_view'] == {'tools': 0, 'all': 1} and "content 'all'" in records['repeat']
    everything = read(control, caller, session=MAIN, search='attached record 3', content='all')[0]['result']
    assert everything['outside_view'] == {} and 'every archived event' in everything['repeat']
    assert 'No archived event' in read(control, caller, session=MAIN, search='question 1')[0]['result']['repeat']


def test_unrecognized_caller_is_refused_before_a_broken_lookup(control: AgentControl) -> None:
    """A corrupt archive raises on lookup: unknown callers still get authority-denied, known ones not-found."""
    from graftling.sessions import archive_path

    broken = archive_path(control.root, 'corrupt')
    broken.parent.mkdir(parents=True)
    broken.write_text('not json\n')
    document, failed = read(control, Caller('test-host', 'agent-unknown'), session='corrupt')
    assert failed and document['error']['code'] == 'authority-denied'
    document, failed = read(control, Caller('test-host', 'agent-p'), session='corrupt')
    assert failed and document['error']['code'] == 'not-found'


def test_unfinished_output_is_read_redacted(control: AgentControl) -> None:
    """A pending draft appears in the result's pending, in the chosen view, without the credential."""
    archive = SessionArchive(control.root, save_normalized_sessions=True)
    archive.map_session(header('s-c'))
    draft = message(4 * ROUNDS, 's-c', 'assistant', [{'type': 'text', 'text': 'partial answer api_key: ' + SECRETS[0]}])
    assert archive.checkpoint('claude:s-c', draft, source='live', position=1)
    document, failed = read(control, Caller('test-host', 'agent-p'), agent='agent-c')
    assert not failed
    pending = document['result']['pending']
    assert len(pending) == 1 and pending[0]['text'].startswith('partial answer') and pending[0]['seq'] == 4 * ROUNDS
    assert SECRETS[0] not in json.dumps(document) and '[redacted]' in pending[0]['text']


def test_legacy_evidence_is_bounded_in_a_search(control: AgentControl) -> None:
    """content all: a read slices legacy events; a search returns only their total."""
    from graftling.sessions import JsonlSessionStore, archive_path

    JsonlSessionStore(archive_path(control.root, 'claude:' + MAIN)).retain_legacy(
        {'header': header(MAIN), 'events': [{'seq': seq, 'type': 'old'} for seq in range(30)]})
    caller = Caller('test-host', None, MAIN, 'claude')
    searched = read(control, caller, session=MAIN, content='all', search='old')[0]['result']
    assert searched['legacy'] == {'total': 30}
    page = read(control, caller, session=MAIN, content='all', start=-10, stop=-5)[0]['result']['legacy']
    assert [event['seq'] for event in page['events']] == list(range(30))[-10:-5] and page['total'] == 30


def test_feature_is_discoverable_and_validated(control: AgentControl) -> None:
    """The MCP/CLI envelope lists session_read; exactly one target and integer slices are required."""
    call = graftling.bind(control, Caller('test-host', 'agent-p'))
    names = [item['feature'] for item in handle_request({'action': 'discover', 'query': 'search history'}, call)
             .document['features']]
    assert names == ['session_read']
    result = handle_request({'action': 'execute', 'feature': 'session_read',
                             'arguments': {'agent': 'agent-c', 'start': -2}}, call)
    assert not result.failed and len(result.document['result']['events']) == 2
    for arguments in ({}, {'agent': 'agent-c', 'session': MAIN}, {'agent': 'agent-c', 'start': 'x'},
                      {'agent': 'agent-c', 'content': 'raw'}, {'agent': 'agent-c', 'path': '/tmp/x'}):
        result = handle_request({'action': 'execute', 'feature': 'session_read', 'arguments': arguments}, call)
        assert result.failed and result.document['error']['code'] == 'invalid-input', arguments


def project_with_two_tasks(tmp_path: Path) -> Path:
    """A GraphTraj project whose Task 148 and Task 149 members have archived Sessions."""
    from graphtraj.interfaces.agents import swarm_root
    from test_result_submission import result_project

    runner, _, _ = result_project(tmp_path)
    other = runner / 'sessions' / 'review@e1'
    other.mkdir(parents=True)
    mapping = yaml.safe_load((runner / 'sessions' / 'research@x1' / 'mapping.yml').read_text())
    mapping.update(alias='review@e1', session='native-review@e1', task_id='149', role='reviewer')
    (other / 'mapping.yml').write_text(yaml.safe_dump(mapping))
    archive(swarm_root(tmp_path), 'native-review@e1', 'native-research@x1', MAIN)
    return runner


def test_graphtraj_project_members_and_main_read_every_project_session(tmp_path: Path) -> None:
    """Any verified project caller reads another Task's member Session; unknown callers are refused."""
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.agents import agents_callback, run_agents_feature

    runner = project_with_two_tasks(tmp_path)
    request = {'action': 'session_read', 'agent': 'review@e1'}
    with runtime_caller(runner, 'research@x1'):
        result = run_agents_feature(request, cwd=tmp_path)
    assert not result.failed, result.document
    assert result.document['result']['session'] == 'claude:native-review@e1'
    assert [item['index'] for item in result.document['result']['events']] == list(range(2 * ROUNDS))[-5:]
    for caller in (Caller('graphtraj-gateway', 'review@e1'), Caller('graphtraj-gateway', None, MAIN, 'codex')):
        call = agents_callback(tmp_path, caller, tmp_path)
        for target in ({'agent': 'research@x1'}, {'session': 'native-review@e1'}, {'session': MAIN}):
            document = call({'action': 'session_read', **target}).document
            assert 'error' not in document, (caller, target, document)
            assert not any(secret in json.dumps(document) for secret in SECRETS)
    for caller in (Caller('graphtraj-gateway', 'native-helper-thread'), Caller('graphtraj-gateway', 'agent-none')):
        document = agents_callback(tmp_path, caller, tmp_path)({'action': 'session_read',
                                                                 'session': 'native-review@e1'}).document
        assert document['error']['code'] == 'authority-denied', caller
    missing = agents_callback(tmp_path, Caller('graphtraj-gateway', 'review@e1'), tmp_path)(
        {'action': 'session_read', 'session': 'no-such-session'}).document
    assert missing['error']['code'] == 'not-found'


def test_tasks_session_read_forwards_with_the_old_page(tmp_path: Path) -> None:
    """after/limit keep their meaning: every archived event after ``after``, at most ``limit``."""
    from graphtraj.execution.runner_status import runtime_caller
    from graphtraj.interfaces.gateway import handle_request as tasks_request

    runner = project_with_two_tasks(tmp_path)
    events = conversation('native-review@e1')
    request = {'action': 'execute', 'feature': 'session_read', 'arguments': {'session_id': 'native-review@e1'}}
    with runtime_caller(runner, 'research@x1'):
        first = tasks_request(request, cwd=tmp_path).document
        second = tasks_request({**request, 'arguments': {'session_id': 'claude:native-review@e1',
                                                         'after': 9, 'limit': 7}}, cwd=tmp_path).document
    assert first['header']['id'] == 'claude:native-review@e1' and first['pending'] == []
    assert len(first['events']) == len(events) and not first['has_more'] and first['after'] == len(events) - 1
    assert [event['seq'] for event in second['events']] == list(range(10, 17))
    assert second['after'] == 16 and second['has_more'] and isinstance(second['revision'], int)
    assert not any(secret in json.dumps([first, second]) for secret in SECRETS)
    assert first['events'][0]['data'] == events[0]['data']
