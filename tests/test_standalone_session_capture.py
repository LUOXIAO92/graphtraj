"""Task 384: every agents execution archives a normalized Session when saving is on.

Covers the standalone (agents-only) capture of Claude, Codex, Pi and DSH
executions, create's header ``extra_fields``, saving switched off, GraphTraj's
``extra_fields.graphtraj`` through the same path, and P0 fidelity: messages
rebuilt from the written Session keep the native identity, content and
relative order with nothing missing, repeated or reordered.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from agent_swarm import AgentControl, AgentsError, Caller, bind, read_session, write_config
from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from test_claude_runtime import claude_environment  # noqa: F401 - pytest fixture
from test_codex_independent_control import native_settings  # noqa: F401 - pytest fixture
from test_pi_runtime import context as pi_context, pi_environment  # noqa: F401 - pytest fixture


EXTRA = {'myapp': {'version': 2, 'run': 'r-1'}}


def text(message: dict) -> str:
    """Join a message's text blocks; non-text blocks are compared separately."""
    content = message['content']
    if isinstance(content, str):
        return content
    return ''.join(block.get('text', '') for block in content if isinstance(block, dict))


def claude_native(transcript: Path) -> list[tuple[str, str, str]]:
    """Return the native transcript's conversation as (uuid, role, text), in file order."""
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    return [(row['uuid'], row['type'], text(row['message'])) for row in rows
            if row.get('type') in {'user', 'assistant'}]


def archived(path: Path) -> list[tuple[str, str, str]]:
    """Return the messages rebuilt from the written normalized Session."""
    return [(m['id'], m['role'], text(m)) for m in JsonlSessionStore(path).messages()]


def test_standalone_claude_archives_with_create_fields_and_stops_when_off(
    tmp_path: Path, claude_environment: None,
) -> None:
    """On: one v5 Session per native Session with P0 messages. Off: nothing new, history kept."""
    from agent_swarm.claude.driver import ClaudeDriver

    root = tmp_path / 'agents'
    write_config(root, save_normalized_sessions=True)
    control = AgentControl(root, {'claude': ClaudeDriver(tmp_path, {})})
    call = bind(control, Caller('standalone-host', None, str(uuid4()), 'claude'))

    created = call({'action': 'create', 'runtime': 'claude', 'instruction': 'first', 'extra_fields': EXTRA})
    assert not created.failed, created.document
    agent, session = created.document['agent'], created.document['session']
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    call({'action': 'send', 'agent': agent, 'message': 'second'})
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})

    path = archive_path(root, 'claude:' + session)
    written = read_session(path)
    assert written['header']['version'] == 5
    assert written['header']['extra_fields'] == EXTRA
    assert written['header']['native']['sessionId'] == session
    assert 'graphtraj' not in written['header']

    # P0: identity, content and relative order equal the native transcript.
    native = claude_native(tmp_path / (session + '.jsonl'))
    assert [role for _, role, _ in native] == ['user', 'assistant', 'user', 'assistant']
    assert archived(path) == native

    # Off: later executions write nothing; the existing archive is kept unchanged.
    before = path.read_bytes()
    write_config(root, save_normalized_sessions=False)
    call({'action': 'send', 'agent': agent, 'message': 'third'})
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 20})
    other = call({'action': 'create', 'runtime': 'claude', 'instruction': 'unsaved'})
    call({'action': 'wait', 'agent': other.document['agent'], 'timeout_seconds': 20})
    assert path.read_bytes() == before
    assert not archive_path(root, 'claude:' + other.document['session']).exists()


def test_standalone_codex_execution_writes_its_rollout_in_native_order(
    tmp_path: Path, native_settings: dict,
) -> None:
    """The Codex execution archives the rollout it owns; saving off writes nothing."""
    from agent_swarm.codex.driver import CodexDriver
    from agent_swarm.sessions.protocol import native_record

    root = tmp_path / 'agents'
    write_config(root, save_normalized_sessions=True)
    control = AgentControl(root, {'codex': CodexDriver(native_settings)})
    call = bind(control, Caller('standalone-host', 'parent', 'parent-session', 'codex'))
    created = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hello', 'extra_fields': EXTRA})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    assert done.document['result']['last_result']['outcome'] == 'completed', done.document

    session = created.document['session']
    written = read_session(archive_path(root, 'codex:' + session))
    assert written['header']['version'] == 5 and written['header']['extra_fields'] == EXTRA
    rollout = tmp_path / 'native' / f'rollout-{session}.jsonl'
    assert written['header']['native']['locator'] == str(rollout)
    # P0 at the record level: every complete native line once, in file order.
    lines = [json.loads(line) for line in rollout.read_text().splitlines()]
    assert [native_record(event) for event in written['events']] == lines

    write_config(root, save_normalized_sessions=False)
    other = call({'action': 'create', 'runtime': 'codex', 'instruction': 'hello'})
    call({'action': 'wait', 'agent': other.document['agent'], 'timeout_seconds': 10})
    assert sorted(p.parent.name for p in (root / 'sessions').glob('*/session.jsonl')) == [
        archive_path(root, 'codex:' + session).parent.name]


def codex_rollout(path: Path, session: str) -> list[tuple[str, str]]:
    """Write a native rollout with two exchanges and return its (role, text) order."""
    exchange = [('user', 'question one'), ('assistant', 'answer one'),
                ('user', 'question two'), ('assistant', 'answer two')]
    rows = [{'timestamp': '2026-10-29T00:00:00.000Z', 'type': 'session_meta',
             'payload': {'id': session, 'cwd': str(path.parent)}}]
    for index, (role, body) in enumerate(exchange):
        kind = 'input_text' if role == 'user' else 'output_text'
        rows.append({'timestamp': f'2026-10-29T00:00:0{index + 1}.000Z', 'type': 'response_item',
                     'payload': {'type': 'message', 'role': role, 'content': [{'type': kind, 'text': body}]}})
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return exchange


@pytest.mark.parametrize('usage', ['standalone', 'graphtraj'])
def test_codex_capture_hook_rebuilds_native_messages(tmp_path: Path, usage: str) -> None:
    """The execution's archive hook (no consumer override) keeps P0 in both usages."""
    from agent_swarm.codex.managed_session import CodexManagedExecution
    from graphtraj.interfaces.agents import graphtraj_fields

    archive = SessionArchive(tmp_path / 'agents', save_normalized_sessions=True)
    fields = EXTRA if usage == 'standalone' else graphtraj_fields('/project', 'agent-1', ['384'], EXTRA)
    rollout = tmp_path / 'rollout.jsonl'
    expected = codex_rollout(rollout, 'thread-p0')
    owner = SimpleNamespace(archive=archive, extra_fields=fields, expected_session=None)
    collector = CodexManagedExecution._archive(owner, SimpleNamespace(thread_id='thread-p0', rollout_path=rollout))
    collector.collect(rollout)
    collector.collect(rollout)  # A repeated notification adds nothing.

    path = archive_path(archive.root, 'codex:thread-p0')
    assert [(m['role'], text(m)) for m in JsonlSessionStore(path).messages()] == expected
    header = read_session(path)['header']
    assert header['extra_fields'] == fields
    if usage == 'graphtraj':
        assert header['extra_fields']['graphtraj']['taskIds'] == ['384']
    # Saving off: the hook binds nothing for a new execution.
    assert CodexManagedExecution._archive(SimpleNamespace(archive=None), None) is None


def pi_native(root: Path, agent: str) -> list[tuple[str, str]]:
    """Return the native Pi Session file's conversation as (role, text), in entry order."""
    [path] = (root / 'native' / agent).glob('**/session.jsonl')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [(row['message']['role'], text(row['message'])) for row in rows
            if row.get('type') == 'message' and row['message'].get('role') in {'user', 'assistant'}]


def pi_archived(path: Path) -> list[tuple[str, str]]:
    """Rebuild Pi messages from the written Session with Pi's own native rules."""
    from agent_swarm.sessions.pi import archive_messages

    return [(m['role'], text(m)) for m in archive_messages(JsonlSessionStore(path))
            if m['role'] in {'user', 'assistant'}]


def pi_request(tmp_path: Path, pi_environment: dict) -> dict:
    """Prepare a standalone Pi request the way the Pi host does."""
    _, prepared = pi_context(tmp_path, pi_environment)
    project = tmp_path / 'standalone'
    (project / 'docs').mkdir(parents=True)
    return {**prepared.launch_document()['adapter_request'],
            'worktree_path': str(project), 'harness_root': str(project),
            'git_common_directory': str(project / '.git'), 'docs_directory': str(project / 'docs'),
            'worktree_access': 'read', 'reports': [], 'resources': []}


def test_standalone_pi_archives_when_on_and_not_when_off(tmp_path: Path, pi_environment: dict) -> None:
    """The Pi execution builds its own collector from the bound archive."""
    from agent_swarm.pi import PiDriver

    root = tmp_path / 'data'
    write_config(root, save_normalized_sessions=True)
    call = bind(AgentControl(root, {'pi': PiDriver(pi_request(tmp_path, pi_environment))}),
                Caller('standalone-host', None))
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'remember-384', 'extra_fields': EXTRA})
    assert not created.failed, created.document
    done = call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    assert not done.failed, done.document

    path = archive_path(root, 'pi:' + created.document['session'])
    written = read_session(path)
    assert written['header']['version'] == 5 and written['header']['extra_fields'] == EXTRA
    assert written['header']['source'] == 'child'
    # P0: the rebuilt conversation equals the native Session file's entries.
    native = pi_native(root, created.document['agent'])
    assert native[0] == ('user', 'remember-384')
    assert pi_archived(path) == native

    write_config(root, save_normalized_sessions=False)
    other = call({'action': 'create', 'runtime': 'pi', 'instruction': 'unsaved'})
    call({'action': 'wait', 'agent': other.document['agent'], 'timeout_seconds': 10})
    assert not archive_path(root, 'pi:' + other.document['session']).exists()
    assert read_session(path) == written


def test_graphtraj_pi_writes_graphtraj_fields_and_native_message_order(
    tmp_path: Path, pi_environment: dict,
) -> None:
    """GraphTraj's Pi children carry extra_fields.graphtraj; messages follow the native entries."""
    from graphtraj.configuration.project_configuration import default_configuration_content
    from graphtraj.interfaces.agents import agents_callback, swarm_root

    project = tmp_path / 'project'
    (project / '.graphtraj').mkdir(parents=True)
    (project / '.graphtraj/config.yml').write_text(default_configuration_content(project, project))
    (project / '.graphtraj/roles.yml').write_text(yaml.safe_dump({'roles': {'team': {'worker': {
        'runtime': 'pi', 'model': 'deepseek/deepseek-flash', 'pi': pi_environment}}}}))
    cwd = project / 'worktrees/research'
    cwd.mkdir(parents=True)
    call = agents_callback(project, Caller('controlled-host', 'parent'), cwd)
    created = call({'action': 'create', 'runtime': 'pi', 'instruction': 'remember-384'})
    assert not created.failed, created.document
    agent = created.document['agent']
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})
    call({'action': 'resume', 'agent': agent, 'message': 'continue'})
    call({'action': 'wait', 'agent': agent, 'timeout_seconds': 10})

    path = archive_path(swarm_root(project), 'pi:' + created.document['session'])
    header = read_session(path)['header']
    assert header['extra_fields']['graphtraj'] == {
        'version': 1, 'projectId': str(project), 'agentId': agent, 'taskIds': []}
    native = pi_native(swarm_root(project), agent)
    assert [role for role, _ in native] == ['user', 'assistant', 'user', 'assistant']
    assert pi_archived(path) == native


def test_dsh_driver_binds_the_archive_with_create_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSH executions archive their native log; off binds no collector."""
    import agent_swarm.dsh.driver as dsh_driver

    header = {'version': 4, 'id': 'dsh-native', 'createdAt': 1, 'isSeeded': False}
    native = [{'type': 'user/message', 'seq': 0, 'time': 1, 'surfaceOp': 'append',
               'data': {'id': 'u1', 'role': 'user', 'source': {'kind': 'user'},
                        'content': [{'type': 'text', 'text': 'hello'}]}},
              {'type': 'assistant/message', 'seq': 1, 'time': 2, 'surfaceOp': 'append',
               'data': {'turn': 0, 'step': 0, 'stream': [], 'message': {
                   'id': 'a1', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'hi'}],
                   'source': {'kind': 'model', 'provider': 'deepseek', 'model': 'native'}}}}]
    bound = []

    class Execution:
        """Replay one recorded native DSH Session through the bound collector."""

        archive = None

        def __init__(self, settings, message, directory, started, created, trace, session) -> None:
            self.started, self.created, self.trace = started, created, trace

        def run(self) -> dict:
            bound.append(self.archive)
            self.created('dsh-native', 1)
            self.started('dsh-native', 1)
            if self.archive is not None:
                self.archive.start({'header': header, 'cursor': -1}, [])
                for event in native:
                    self.archive.event(event)
                self.trace.write_text(''.join(json.dumps(row) + '\n' for row in [header, *native]))
                self.archive.finish(self.trace)
            return {'outcome': 'completed', 'last_agent_message': 'hi'}

    monkeypatch.setattr(dsh_driver, 'DshExecution', Execution)
    monkeypatch.setattr(dsh_driver, 'prepare', lambda configuration, cwd: {})
    monkeypatch.setattr('agent_swarm.dsh.binding.bind_run', lambda turn, run: None)
    root = tmp_path / 'agents'
    write_config(root, save_normalized_sessions=True)
    call = bind(AgentControl(root, {'dsh': dsh_driver.DshDriver(tmp_path, {})}), Caller('host', None))
    created = call({'action': 'create', 'runtime': 'dsh', 'instruction': 'hello', 'extra_fields': EXTRA})
    assert not created.failed, created.document
    call({'action': 'wait', 'agent': created.document['agent'], 'timeout_seconds': 10})
    path = archive_path(root, 'dsh:dsh-native')
    assert read_session(path)['header']['extra_fields'] == EXTRA
    assert [(m['id'], m['role'], text(m)) for m in JsonlSessionStore(path).messages()] == [
        ('u1', 'user', 'hello'), ('a1', 'assistant', 'hi')]

    write_config(root, save_normalized_sessions=False)
    call({'action': 'create', 'runtime': 'dsh', 'instruction': 'unsaved'})
    assert bound[-1] is None


@pytest.mark.parametrize('value', [[], {'': {}}, {'ns': float('nan')}, 'text'])
def test_create_refuses_an_invalid_extra_fields_container(tmp_path: Path, value: object) -> None:
    """Only a JSON object keyed by nonempty namespace names is accepted, before any start."""
    class Driver:
        def prepare(self, runtime, caller):
            raise AssertionError('validation precedes preparation')

    control = AgentControl(tmp_path / 'agents', {'codex': Driver()})
    with pytest.raises(AgentsError) as refused:
        control.create('codex', 'hi', _binding(), extra_fields=value)
    assert refused.value.code == 'invalid-input'
    assert not (tmp_path / 'agents' / 'control').exists()


def _binding():
    """Return a root caller binding for direct backend calls."""
    from agent_swarm import Binding

    return Binding(Caller('host', None))


def test_claude_native_helper_is_collected_into_the_bound_archive(tmp_path: Path) -> None:
    """A finished native helper keeps its own transcript, scoped beside its parent Session."""
    from agent_swarm.claude.collection import collect_hook_event

    archive = SessionArchive(tmp_path / 'agents', save_normalized_sessions=True, backfill_history=True)
    child = tmp_path / 'child.jsonl'
    rows = [{'type': 'user', 'uuid': 'c1', 'sessionId': 'parent', 'agentId': 'helper', 'isSidechain': True,
             'timestamp': '2026-10-29T00:00:00Z', 'message': {'role': 'user', 'content': 'look up'}},
            {'type': 'assistant', 'uuid': 'c2', 'parentUuid': 'c1', 'sessionId': 'parent', 'agentId': 'helper',
             'isSidechain': True, 'timestamp': '2026-10-29T00:00:01Z',
             'message': {'id': 'm2', 'role': 'assistant', 'model': 'claude-opus-5-5',
                         'content': [{'type': 'text', 'text': 'found'}]}}]
    child.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = collect_hook_event(archive, {
        'hook_event_name': 'SubagentStop', 'session_id': 'parent', 'agent_id': 'helper',
        'agent_transcript_path': str(child), 'transcript_path': str(tmp_path / 'parent.jsonl'),
        'cwd': str(tmp_path)}, tmp_path, extra_fields=EXTRA)
    assert result['saved'] and result['source'] == 'child'
    path = archive_path(archive.root, result['session_id'])
    header = read_session(path)['header']
    assert header['extra_fields'] == EXTRA and header['native']['agentId'] == 'helper'
    # P0 at the record level: each helper transcript row once, in file order.
    from agent_swarm.sessions.protocol import native_record

    records = [native_record(event) for event in read_session(path)['events']]
    assert [record for record in records if record.get('uuid')] == rows


def test_graphtraj_sqlite_archive_written_before_v5_reads_as_v5(tmp_path: Path) -> None:
    """Legacy SQLite bytes stay as written; GraphTraj readers see the v5 form."""
    from graphtraj.sessions.storage import SessionStore, archive_owner

    path = tmp_path / 'session.sqlite3'
    header = {'version': 4, 'id': 'codex:old', 'createdAt': 1, 'isSeeded': False,
              'graphtraj': {'version': 1, 'projectId': '/p', 'agentId': 'a', 'taskIds': ['7'],
                            'native': {'runtime': 'codex', 'sessionId': 'old', 'locator': 'byte:0'}}}
    event = {'type': 'graphtraj/native', 'seq': 0, 'time': 1, 'data': {'record': {'type': 'x'}},
             'graphtraj': {'version': 1, 'native': {'runtime': 'codex', 'sessionId': 'old', 'locator': 'byte:1'},
                           'missing': [{'path': 'time', 'reason': 'test'}]}}
    db = sqlite3.connect(path)
    for statement in ('CREATE TABLE header (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)',
                      'CREATE TABLE events (seq INTEGER PRIMARY KEY, value TEXT NOT NULL, native TEXT UNIQUE)',
                      'CREATE TABLE checkpoints (source TEXT PRIMARY KEY, position INTEGER NOT NULL)',
                      'CREATE TABLE draft (id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL, value TEXT NOT NULL)',
                      'CREATE TABLE attachments (digest TEXT PRIMARY KEY, content BLOB NOT NULL)'):
        db.execute(statement)
    db.execute('INSERT INTO header VALUES (1, ?)', (json.dumps(header),))
    db.execute('INSERT INTO events VALUES (0, ?, NULL)', (json.dumps(event),))
    db.execute('PRAGMA user_version = 1')
    db.commit()
    db.close()
    before = path.read_bytes()

    with SessionStore(path, readonly=True) as store:
        assert store.header['version'] == 5 and 'graphtraj' not in store.header
        assert archive_owner(store.header) == {'version': 1, 'projectId': '/p', 'agentId': 'a', 'taskIds': ['7'],
                                               'native': header['graphtraj']['native']}
        [read] = store.page()['events']
        assert read['type'] == 'native' and read['native']['locator'] == 'byte:1'
        assert read['missing'] == [{'path': 'time', 'reason': 'test'}] and 'graphtraj' not in read
        store.validate()
    assert path.read_bytes() == before
