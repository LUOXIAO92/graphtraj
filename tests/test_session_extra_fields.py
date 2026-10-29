"""Archive v5: extra_fields container, redaction, v4 reading and v5-only writing (no Runtime I/O)."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path, read_session
from agent_swarm.sessions.claude import ClaudeJsonlCollector
from agent_swarm.sessions.protocol import (
    ARCHIVE_TYPES, native_record, upgrade_event, upgrade_header, validate_event, validate_header,
)
from test_claude_jsonl import message, write

EXAMPLES = Path(__file__).parents[1] / 'examples' / 'sessions'
V4_EXAMPLES = Path(__file__).parent / 'fixtures' / 'sessions_v4'
GRAPHTRAJ = {'graphtraj': {'version': 1, 'projectId': '/project', 'agentId': 'agent', 'taskIds': ['384']}}
# Keys the v4 ``graphtraj`` object carried for core archive facts.
CORE_KEYS = ('native', 'missing', 'previousSession', 'boundary', 'attachments', 'source',
             'contextReplay', 'receivedAtMs', 'lastReceivedAtMs', 'collectionBoundary',
             'usage', 'usageSource')


def header(**fields: object) -> dict:
    """Return explicit v5 test metadata."""
    return {'version': 5, 'id': 'test', 'createdAt': 1, 'isSeeded': False, **fields}


def user(seq: int, text: str, **fields: object) -> dict:
    """Return a v5 user message with native provenance."""
    return {'type': 'user/message', 'seq': seq, 'time': 1, 'surfaceOp': 'append',
            'data': {'id': f'm{seq}', 'role': 'user', 'source': {'kind': 'user'},
                     'content': [{'type': 'text', 'text': text}]},
            'native': {'runtime': 'fixture', 'sessionId': 'native', 'locator': f'line:{seq}'}, **fields}


def downgrade(value: dict, *, is_header: bool) -> dict:
    """Spell a v5 value the way a v4 writer did; inverse of the documented mapping."""
    value = deepcopy(value)
    ext = {'version': 1, **value.pop('extra_fields', {}).pop('graphtraj', {})}
    for key in CORE_KEYS:
        if key in value:
            ext[key] = value.pop(key)
    value['graphtraj'] = ext
    if is_header:
        value['version'] = 4
        return value
    if value['type'] in ARCHIVE_TYPES | {'collection-pending'}:
        value['type'] = 'graphtraj/' + value['type']
    message = value['data'].get('message', value['data'])
    for block in [*message.get('content', []), *value['data'].get('stream', [])]:
        if block.get('type') in {'encrypted', 'text-run'}:
            block['type'] = 'graphtraj/' + block['type']
    return value


@pytest.mark.parametrize('runtime', ['codex', 'pi', 'dsh', 'claude'])
def test_accepted_v4_examples_read_as_the_v5_examples(runtime: str) -> None:
    """The accepted P0 fixtures map one-to-one; native records stay byte-identical JSON."""
    old = json.loads((V4_EXAMPLES / f'{runtime}.json').read_text())
    new = json.loads((EXAMPLES / f'{runtime}.json').read_text())
    assert len(old['cases']) == len(new['cases'])
    for before, after in zip(old['cases'], new['cases']):
        assert upgrade_event(before['event']) == after['event']
        assert 'graphtraj' not in after['event'] and not after['event']['type'].startswith('graphtraj/')
        assert native_record(after['event']) == before['native'] == after['native']


def test_v4_header_and_event_mapping() -> None:
    """Core facts become core fields; only product associations become extra_fields.graphtraj."""
    native = {'runtime': 'codex', 'sessionId': 's', 'locator': '/rollout.jsonl', 'source': 'cli'}
    old = {'version': 4, 'id': 'codex:s:boundary:x', 'createdAt': 1, 'isSeeded': False, 'cwd': '/w',
           'graphtraj': {'version': 1, 'projectId': '/p', 'agentId': 'a', 'taskIds': ['1'],
                         'native': native, 'missing': [{'path': 'createdAt', 'reason': 'unknown'}],
                         'previousSession': 'codex:s', 'boundary': {'kind': 'rollout', 'offset': 0},
                         'source': 'member'}}
    assert upgrade_header(old) == {
        'version': 5, 'id': 'codex:s:boundary:x', 'createdAt': 1, 'isSeeded': False, 'cwd': '/w',
        'extra_fields': {'graphtraj': {'version': 1, 'projectId': '/p', 'agentId': 'a', 'taskIds': ['1']}},
        'native': native, 'missing': [{'path': 'createdAt', 'reason': 'unknown'}],
        'previousSession': 'codex:s', 'boundary': {'kind': 'rollout', 'offset': 0}, 'source': 'member'}
    assert upgrade_header(header()) == header()
    stream = [{'type': 'graphtraj/text-run', 'requestId': 'r', 'attemptId': 'a', 'messageId': 'm',
               'index': 0, 'blockType': 'text', 'text': 'hi'},
              {'type': 'chunk', 'time': 1, 'chunk': {'type': 'block-end', 'index': 1,
               'block': {'type': 'graphtraj/encrypted', 'value': 'c', 'nativePath': '/x'}}}]
    event = {'type': 'assistant/message', 'seq': 0, 'time': 1, 'surfaceOp': 'append',
             'data': {'turn': 0, 'step': 0, 'stream': stream, 'message': {
                 'id': 'm', 'role': 'assistant', 'source': {'kind': 'model', 'provider': 'p', 'model': 'm'},
                 'content': [{'type': 'text', 'text': 'hi'},
                             {'type': 'graphtraj/encrypted', 'value': 'c', 'nativePath': '/x'}]}},
             'graphtraj': {'version': 1, 'native': {**native, 'record': {'type': 'graphtraj/native'}},
                           'attachments': [], 'contextReplay': True}}
    upgraded = upgrade_event(event)
    validate_event(upgraded)
    assert set(upgraded) == {'type', 'seq', 'time', 'surfaceOp', 'data', 'native', 'attachments', 'contextReplay'}
    assert upgraded['native']['record'] == {'type': 'graphtraj/native'}  # native data is never renamed
    assert [b['type'] for b in upgraded['data']['message']['content']] == ['text', 'encrypted']
    assert upgraded['data']['stream'][0]['type'] == 'text-run'
    assert upgraded['data']['stream'][1]['chunk']['block']['type'] == 'encrypted'
    opaque = {'type': 'graphtraj/native', 'seq': 0, 'time': 1, 'data': {'record': {'type': 'graphtraj/encrypted'}},
              'graphtraj': {'version': 1, 'native': native}}
    assert upgrade_event(opaque) == {'type': 'native', 'seq': 0, 'time': 1,
                                     'data': {'record': {'type': 'graphtraj/encrypted'}}, 'native': native}
    for kind in ('history', 'score', 'logprobs', 'derived', 'collection-pending'):
        assert upgrade_event({**opaque, 'type': 'graphtraj/' + kind})['type'] == kind
    with pytest.raises(ValueError, match='collision'):
        upgrade_event({**event, 'native': native})
    with pytest.raises(ValueError, match='header.version'):
        upgrade_header({**old, 'version': 3})


@pytest.mark.parametrize('value', [[], 'graphtraj', None, {'': {}}, {1: 'x'},
                                   {'ns': float('nan')}, {'ns': (1, 2)}, {'ns': {'x': {1, 2}}}])
def test_extra_fields_container_is_validated(value: object) -> None:
    """Core checks only object, nonempty string keys and lossless JSON values."""
    with pytest.raises(ValueError, match='extra_fields'):
        validate_header(header(extra_fields=value))
    with pytest.raises(ValueError, match='extra_fields'):
        validate_event(user(0, 'x', extra_fields=value))
    if value is not None:  # None means "no extra fields" for a writer
        with pytest.raises(ValueError):
            ClaudeJsonlCollector(None, 's', Path('/w'), 'e', extra_fields=value)


def test_v4_spelling_is_refused_for_writing(tmp_path: Path) -> None:
    """A leftover v4 writer fails loudly instead of producing a mixed file."""
    with pytest.raises(ValueError, match='header.version'):
        JsonlSessionStore.create(tmp_path / 'a.jsonl', downgrade(header(), is_header=True))
    store = JsonlSessionStore.create(tmp_path / 'a.jsonl', header())
    with pytest.raises(ValueError, match='graphtraj is version 4'):
        store.publish([downgrade(user(0, 'x'), is_header=False)], source='s', position=0)
    with pytest.raises(ValueError, match='graphtraj is version 4'):
        validate_header({**header(), 'graphtraj': GRAPHTRAJ['graphtraj']})


def test_unknown_namespaces_are_kept_and_ignored(tmp_path: Path) -> None:
    """Namespaces never change messages, order or identity; they survive reopening."""
    unknown = {'someone.else': {'v': 7, 'any': [None, {'x': 1.5}]}, 'graphtraj': GRAPHTRAJ['graphtraj']}
    plain = JsonlSessionStore.create(tmp_path / 'plain.jsonl', header())
    plain.publish([user(0, 'a'), user(1, 'b')], source='s', position=0)
    tagged = JsonlSessionStore.create(tmp_path / 'tagged.jsonl', header(extra_fields=unknown))
    tagged.publish([user(0, 'a', extra_fields=unknown), user(1, 'b')], source='s', position=0)
    reopened = JsonlSessionStore(tagged.path)
    assert reopened.messages() == plain.messages()
    assert reopened.header['extra_fields'] == unknown
    assert reopened.page()['events'][0]['extra_fields'] == unknown


def test_redaction_applies_to_header_and_event_extra_fields(tmp_path: Path) -> None:
    """Credential-named keys and recognizable secrets never reach the file; native content stays exact."""
    secret = 'sk-' + 'A1b2C3d4E5f6G7h8'
    supplied = {'acme': {'api_key': 'plain-value-1', 'note': 'Bearer opaque-value-2', 'id': secret}}
    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=True,
                             event_fields=lambda event: {'probe': {'password': 'plain-value-3',
                                                                   'seen': event['type'], 'text': secret}})
    path = tmp_path / 'native.jsonl'
    write(path, [message('q', None, 'native text keeps ' + secret)])
    collector = ClaudeJsonlCollector(archive, 's', tmp_path, 'e', extra_fields=supplied)
    collector.bind(path)
    stored = archive_path(archive.root, 'claude:s')
    text = stored.read_text()
    for value in ('plain-value-1', 'opaque-value-2', 'plain-value-3'):
        assert value not in text
    result = JsonlSessionStore(stored)
    assert result.header['extra_fields'] == {'acme': {'api_key': '[redacted]', 'note': 'Bearer [redacted]',
                                                      'id': '[redacted]'}}
    events = result.page()['events']
    assert {event['extra_fields']['probe']['password'] for event in events} == {'[redacted]'}
    assert {event['extra_fields']['probe']['text'] for event in events} == {'[redacted]'}
    assert result.messages()[0]['content'][0]['text'] == 'native text keeps ' + secret
    assert supplied['acme']['api_key'] == 'plain-value-1'  # the caller's value is not mutated


def test_event_fields_attach_once_to_new_events(tmp_path: Path) -> None:
    """Published events keep their first fields; replays and None add nothing; bad output writes nothing."""
    calls = []

    def fields(event: dict) -> dict | None:
        calls.append(event['native']['locator'])
        return None if event['type'] != 'user/message' else {'probe': {'n': len(calls)}}

    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True,
                             backfill_history=True, event_fields=fields)
    path = tmp_path / 'native.jsonl'
    first = [message('q', None, 'one'), message('a', 'q', 'two', role='assistant')]
    write(path, first)
    collector = ClaudeJsonlCollector(archive, 's', tmp_path, 'e')
    collector.bind(path)
    stored = JsonlSessionStore(archive_path(archive.root, 'claude:s')).page()['events']
    assert [event.get('extra_fields') for event in stored] == [{'probe': {'n': 1}}, None]
    write(path, [*first, message('b', 'a', 'three')])
    collector.collect()
    again = JsonlSessionStore(archive_path(archive.root, 'claude:s')).page()['events']
    assert again[:2] == stored
    assert again[2]['extra_fields']['probe']['n'] > 1
    with pytest.raises(ValueError):
        SessionArchive(tmp_path, event_fields='not callable')
    bad = JsonlSessionStore(archive_path(archive.root, 'claude:s'), event_fields=lambda event: {'': 1})
    before = bad.path.read_bytes()
    with pytest.raises(ValueError, match='extra_fields'):
        bad.publish([*again, {**user(3, 'four'), 'native': {**user(3, 'x')['native'], 'runtime': 'claude'}}],
                    source='extra', position=0)
    assert bad.path.read_bytes() == before


def _identity(messages: list[dict]) -> list[tuple]:
    """Identity, content and relative order of reconstructed messages."""
    return [(item['id'], item['role'], json.dumps(item['content'], sort_keys=True)) for item in messages]


def test_v4_file_and_v5_file_reconstruct_the_same_messages_and_resume_as_v5(tmp_path: Path) -> None:
    """P0 across versions: same native Session read from v4 and v5, then resumed into the v4 file."""
    original = [message('q', None, 'old'), message('a', 'q', 'one', role='assistant'),
                message('b', 'a', 'two')]
    boundary = {'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'boundary',
                'parentUuid': None, 'sessionId': 's', 'logicalParentUuid': 'b',
                'compactMetadata': {'preservedMessages': {'anchorUuid': 'summary', 'uuids': ['b', 'a']}}}
    compacted = [*original, boundary, message('summary', 'boundary', 'summary', isCompactSummary=True)]
    full = [*compacted, message('end', 'summary', 'new question')]

    def collect(root: Path, records: list[dict]) -> Path:
        path = root / 'native.jsonl'
        root.mkdir(exist_ok=True)
        write(path, records)
        archive = SessionArchive(root / 'swarm', save_normalized_sessions=True, backfill_history=True)
        ClaudeJsonlCollector(archive, 's', root, 'e', extra_fields=GRAPHTRAJ).bind(path)
        return archive_path(archive.root, 'claude:s')

    v5 = collect(tmp_path / 'v5', compacted)
    lines = [json.loads(line) for line in v5.read_text().splitlines()]
    metadata, events = lines[0], lines[1:]
    assert metadata['pending'] == [] and events
    old_metadata = {**metadata, 'header': downgrade(metadata['header'], is_header=True)}
    old_events = [downgrade(event, is_header=False) for event in events]
    assert upgrade_header(old_metadata['header']) == metadata['header']
    assert [upgrade_event(event) for event in old_events] == events

    resumed_root = tmp_path / 'v4'
    v4 = collect(resumed_root, [])  # same layout; then replace its content by the v4 spelling
    v4.write_text(''.join(json.dumps(value) + '\n' for value in [old_metadata, *old_events]))
    v4_bytes = v4.read_bytes()
    assert _identity(JsonlSessionStore(v4).messages()) == _identity(JsonlSessionStore(v5).messages())
    assert read_session(v4) == read_session(v5) == {'header': metadata['header'], 'events': events}
    assert v4.read_bytes() == v4_bytes  # reading never rewrites

    def resume(root: Path) -> None:
        write(root / 'native.jsonl', full)
        archive = SessionArchive(root / 'swarm', save_normalized_sessions=True, backfill_history=True)
        ClaudeJsonlCollector(archive, 's', root, 'e', extra_fields=GRAPHTRAJ).bind(root / 'native.jsonl')

    resume(resumed_root)
    resume(tmp_path / 'v5')  # control: the same resume into the v5 file
    rewritten = [json.loads(line) for line in v4.read_text().splitlines()]
    assert rewritten[0]['header']['version'] == 5
    assert not any('graphtraj' in value for value in [rewritten[0]['header'], *rewritten[1:]])
    assert rewritten[1:len(events) + 1] == events  # prefix kept exactly: no loss, duplication or reordering
    assert read_session(v4)['events'] == read_session(v5)['events']
    assert read_session(v4)['header']['extra_fields'] == GRAPHTRAJ
    assert _identity(JsonlSessionStore(v4).messages()) == _identity(JsonlSessionStore(v5).messages())
    assert [m['id'] for m in JsonlSessionStore(v4).messages()] == ['summary', 'b', 'a', 'end']
