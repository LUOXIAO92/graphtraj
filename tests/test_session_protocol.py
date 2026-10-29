"""Behavior of the public Runtime-facing Session value protocol (no Runtime I/O)."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agent_swarm.sessions.protocol import (
    native_record, retain_native, snapshot_event, validate_content, validate_event,
    validate_header, validate_session, validate_stream,
)

EXAMPLES = Path(__file__).parents[1] / 'examples' / 'sessions'


def header(*, seeded: bool = False) -> dict:
    """Return explicit test Session metadata, not a captured Runtime identity."""
    return {'version': 5, 'id': 'test-session', 'createdAt': 1, 'isSeeded': seeded,
            'extra_fields': {'graphtraj': {'version': 1, 'projectId': 'test-project',
                         'agentId': 'test-agent', 'taskIds': ['311']}}}


def event(kind: str, data: dict, seq: int = 0, **fields: object) -> dict:
    """Build a test event with deterministic non-native coordinates."""
    return {'type': kind, 'seq': seq, 'time': 1, 'data': data, **fields}


def user(text: str, seq: int = 0, **fields: object) -> dict:
    """Build an identified DSH user message."""
    return event('user/message', {'id': f'm{seq}', 'role': 'user',
                 'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': text}]},
                 seq, surfaceOp='append', **fields)


def observation(kind: str = 'logprobs', *, source: str = 'native') -> dict:
    """Supply explicitly synthetic probabilities, never claimed as observed data."""
    data = {'target': {'eventSeq': 0, 'requestId': 'request-1', 'attemptId': 'attempt-2',
                       'model': 'test-model', 'tokenizer': 'test-tokenizer'},
            'source': {'kind': source, 'producer': 'test-producer', 'evidence': 'test-fixture'},
            'distribution': 'raw', 'semantics': 'Synthetic pre-sampling natural log probability',
            'tokens': [{'position': 0, 'tokenId': 42, 'text': 'é', 'logprob': -0.7,
                        'span': {'blockIndex': 0, 'start': 0, 'end': 2}},
                       {'position': 2, 'logprob': None, 'missing': 'Provider withheld probability'}]}
    if source != 'native':
        data['source']['context'] = [{'sessionId': 'test-session', 'eventSeq': 0}]
    if kind == 'score':
        data = {key: data[key] for key in ('target', 'source')}
        data.update(name='test-score', rule='Synthetic rubric v1', value=0.75)
        data['target'].update(tokenPosition=3, blockIndex=0)
    elif kind == 'derived':
        data = {key: data[key] for key in ('target', 'source')}
        data['content'] = [{'type': 'reasoning', 'text': 'A later model hypothesis'}]
    return event(kind, data, 1)


@pytest.mark.parametrize('runtime', ['codex', 'pi', 'dsh', 'claude'])
def test_runtime_mapping_examples_preserve_native_records(runtime: str) -> None:
    """Every source-backed mapping survives JSON and preserves the entire native value."""
    fixture = json.loads((EXAMPLES / f'{runtime}.json').read_text())
    assert fixture['sources']
    for case in fixture['cases']:
        mapped = snapshot_event(case['event'])
        assert native_record(json.loads(json.dumps(mapped))) == case['native']
        # Detached snapshots cannot rewrite the caller's original evidence.
        recovered = native_record(mapped)
        recovered['new-field'] = 'local edit'
        assert native_record(mapped) == case['native']
        if runtime == 'dsh':
            assert {k: v for k, v in mapped.items() if k not in {'native', 'missing'}} == case['native']
    if runtime == 'codex':
        assert fixture['cases'][0]['event']['data']['content'][0]['text'] == fixture['cases'][0]['native']['payload']['content'][0]['text']
        assert fixture['cases'][2]['event']['data']['arguments'] == fixture['cases'][2]['native']['payload']['arguments']
    elif runtime == 'pi':
        mapped = fixture['cases'][0]['event']
        assert mapped['data']['usage']['inputTokens'] == fixture['cases'][0]['native']['message']['usage']['input']
        assert mapped['data']['usage']['cacheReadTokens'] == 3
        assert mapped['data']['message']['content'][0]['text'] == 'Hello'
    elif runtime == 'claude':
        assert fixture['cases'][1]['event']['data']['message']['toolCallId'] == fixture['cases'][1]['native']['message']['content'][0]['tool_use_id']


def test_unknown_fields_ciphertext_and_missing_values_survive() -> None:
    """Native opaque retention never projects private content away or fills missing values."""
    record = {'type': 'future', 'encrypted_content': 'ciphertext', 'new': [None, {'x': 3}]}
    mapped = retain_native('codex', record, session_id='native', locator='line:3', seq=0, time=1)
    mapped['missing'] = [{'path': '/reasoning', 'reason': 'Not exposed'}]
    record['encrypted_content'] = 'caller mutation'
    assert native_record(mapped)['encrypted_content'] == 'ciphertext'
    assert native_record(mapped)['new'][0] is None
    validate_session(header(), [mapped])
    with pytest.raises(ValueError, match='opaque-native'):
        validate_session(header(), [mapped], reconstruct=True)
    unknown = event('future/event', {'x': 3})
    validate_session(header(), [unknown])
    with pytest.raises(ValueError, match='unknown-required'):
        validate_session(header(), [unknown], reconstruct=True)
    unknown['ignorable'] = True
    validate_session(header(), [unknown], reconstruct=True)
    assert snapshot_event(unknown) == unknown


@pytest.mark.parametrize('value', [float('nan'), float('inf'), (1, 2), {1: 'coerced'}])
def test_non_json_values_are_rejected(value: object) -> None:
    """Snapshots must not silently coerce or lose native data."""
    with pytest.raises(ValueError):
        snapshot_event(event('unknown', {'value': value}))


@pytest.mark.parametrize('field,value', [('version', 3), ('version', 4), ('version', 6), ('createdAt', True),
                                        ('createdAt', -1), ('createdAt', 2**53), ('isSeeded', 0)])
def test_header_versions_and_safe_integers(field: str, value: object) -> None:
    """No automatic old-format fallback and no boolean/integer coercion."""
    candidate = header()
    candidate[field] = value
    with pytest.raises(ValueError):
        validate_header(candidate)


def test_fork_and_compaction_preserve_original_history() -> None:
    """A tagged fork cut and surface replacement never erase source events."""
    first, second = user('original', 0), user('second', 1)
    marker = event('session/end-seed', {'inherited': True}, 2)
    summary = user('summary', 3, sourceEventSeqs=[0, 1])
    summary['surfaceOp'] = {'op': 'replace', 'startSeq': 0, 'endSeq': 1}
    events = [first, second, marker, summary]
    original = deepcopy(events)
    child = header(seeded=True)
    child['parentSession'] = 'parent-session'
    validate_session(child, events, reconstruct=True)
    assert events == original
    assert events[0]['data']['content'][0]['text'] == 'original'
    with pytest.raises(ValueError, match='isSeeded'):
        validate_session(header(), events)
    summary['sourceEventSeqs'] = [0]
    with pytest.raises(ValueError, match='surfaceOp.sources'):
        validate_session(child, events)


def test_failed_attempt_retry_and_interrupted_message_are_distinct() -> None:
    """Failure streams remain off the message surface; interruptions preserve delivered text."""
    failure = {'message': 'test failure', 'code': 'RATE_LIMIT', 'status': 429}
    attempt = event('assistant/attempt', {'turn': 1, 'step': 1, 'stream': [
        {'type': 'chunk', 'time': 1, 'chunk': {'type': 'finish', 'reason': {'kind': 'error', 'failure': failure}}}]})
    retry = event('llm/retry', {'turn': 1, 'step': 1, 'retryId': 'retry-1', 'provider': 'test',
                              'mode': 'normal', 'policyKey': 'test', 'retry': 1, 'maxRetries': 2,
                              'delayMs': 100, 'failure': failure}, 1)
    retry_start = event('llm/retry-started', {'turn': 1, 'step': 1, 'retryId': 'retry-1', 'retry': 1}, 2)
    message = event('assistant/message', {'turn': 1, 'step': 1, 'interrupted': True,
        'message': {'id': 'm', 'role': 'assistant', 'source': {'kind': 'model', 'provider': 'test', 'model': 'test'},
                    'content': [{'type': 'text', 'text': 'part'}]},
        'stream': [{'type': 'text-chunks', 'time0': 2, 'index': 0, 'dt': [1], 'texts': ['pa', 'rt']}]},
        3, surfaceOp='append')
    validate_session(header(), [attempt, retry, retry_start, message], reconstruct=True)
    assert 'usage' not in message['data']
    attempt['surfaceOp'] = 'append'
    with pytest.raises(ValueError, match='surface'):
        validate_event(attempt)


def test_request_header_and_tool_pair_keep_raw_arguments() -> None:
    """Request snapshots and tool/result identities stay distinct from message content."""
    request = event('request/header', {'reason': 'initial', 'header': {
        'config': {'provider': 'test', 'model': 'test', 'temperature': 0.7, 'topP': 0.9},
        'tools': [{'name': 'read', 'description': 'Read', 'parameters': {'type': 'object'}}]}})
    call = event('tool/call', {'turn': 1, 'step': 1, 'callId': 'call', 'name': 'read',
                             'arguments': '{ "x": 1 }'}, 1)
    result = event('tool/result', {'turn': 1, 'step': 1, 'message': {
        'role': 'tool', 'id': 'result', 'source': {'kind': 'tool', 'callId': 'call'},
        'toolCallId': 'call', 'isError': True, 'content': [{'type': 'text', 'text': 'failed'}]},
        'error': {'name': 'ReadError', 'code': 'MISSING'}, 'meta': {'future': ['retained']}},
        2, surfaceOp='append')
    validate_session(header(), [request, call, result])
    assert snapshot_event(call)['data']['arguments'] == '{ "x": 1 }'
    request['data']['header']['system'] = 'retired field'
    with pytest.raises(ValueError, match='system'):
        validate_event(request)


def test_dsh_stream_timing_and_unknown_extensions_are_preserved() -> None:
    """DSH signed timestamp gaps retain exact chunk boundaries, including tool arguments."""
    stream = [{'type': 'tool-call-chunks', 'index': 1, 'time0': 10, 'dt': [-1, 3],
               'id': 'call', 'name': 'read', 'args': ['{', '"x":1', '}']},
              {'type': 'future-record', 'private': {'value': 'keep'}}]
    before = deepcopy(stream)
    validate_stream(stream)
    assert stream == before
    stream[0]['dt'].pop()
    with pytest.raises(ValueError, match='stream.dt'):
        validate_stream(stream)


@pytest.mark.parametrize('kind,source', [('logprobs', 'native'),
                                       ('logprobs', 'recomputed'),
                                       ('score', 'native'),
                                       ('derived', 'supplemented')])
def test_append_only_rl_sources_and_alignment(kind: str, source: str) -> None:
    """Native, recomputed and supplemented records target history without replacing it."""
    encrypted = user('visible prefix')
    encrypted['data']['content'].append({'type': 'encrypted', 'value': 'opaque',
                                        'nativePath': '/payload/encrypted_content'})
    saved = deepcopy(encrypted)
    value = observation(kind, source=source)
    validate_session(header(), [encrypted, value])
    assert encrypted == saved
    assert value['data']['target']['attemptId'] == 'attempt-2'
    if kind == 'logprobs':
        assert value['data']['tokens'][1]['logprob'] is None
        assert value['data']['distribution'] == 'raw'
        assert 'sampled' not in value['data']


def test_sampled_distribution_and_unknown_tokenizer_are_explicit() -> None:
    """Missing sampling controls and tokenizer identity need reasons, not fabricated values."""
    value = observation()
    value['data'].update(distribution='sampled', sampling={
        'temperature': 0.8, 'topP': None, 'topK': None,
        'missing': {'topP': 'Not returned', 'topK': 'Not returned'}})
    value['data']['target'].update(tokenizer=None, missing={'tokenizer': 'Not exposed'})
    validate_event(value)
    del value['data']['target']['missing']
    with pytest.raises(ValueError, match='missing.tokenizer'):
        validate_event(value)


@pytest.mark.parametrize('mutation', ['future-target', 'duplicate-position', 'positive-logprob', 'missing-provenance'])
def test_invalid_rl_observations_are_rejected(mutation: str) -> None:
    """Reject observations that cannot be attributed or aligned safely."""
    value = observation()
    if mutation == 'future-target':
        value['data']['target']['eventSeq'] = 1
    elif mutation == 'duplicate-position':
        value['data']['tokens'][1]['position'] = 0
    elif mutation == 'positive-logprob':
        value['data']['tokens'][0]['logprob'] = 0.1
    else:
        del value['data']['source']['evidence']
    with pytest.raises(ValueError):
        validate_event(value)


def test_semantic_run_is_independent_of_transport_chunk_size() -> None:
    """The protocol accepts joined text and token spans without per-character records.

    Assembly here is a mapping example; production accumulation, flush and crash
    recovery are Task 312. No claim about persistent file size is made here.
    """
    text = 'é' * 1024
    records = []
    for fragments in ([text], list(text)):
        run = {'type': 'text-run', 'requestId': 'r', 'attemptId': 'a',
               'messageId': 'm', 'index': 0, 'blockType': 'text', 'text': ''.join(fragments)}
        validate_stream([run])
        records.append(json.dumps(run))
    assert records[0] == records[1]
    probability = observation()
    validate_event(probability)
    assert probability['data']['tokens'][0]['span'] == {'blockIndex': 0, 'start': 0, 'end': 2}


def test_unknown_event_payload_can_be_any_lossless_json() -> None:
    """Unknown plugin payloads need not be objects to survive archival reading."""
    for payload in (None, ['future', {'opaque': 2}], 'opaque'):
        value = event('future/event', payload)
        assert snapshot_event(value)['data'] == payload


def test_token_spans_cannot_claim_ciphertext_or_unreceived_output() -> None:
    """Explicit token offsets must refer to available text, not opaque positions."""
    target = user('é')
    value = observation()
    validate_session(header(), [target, value])
    value['data']['tokens'][0]['span']['end'] = 3
    with pytest.raises(ValueError, match='span.end'):
        validate_session(header(), [target, value])
    value['data']['tokens'][0]['span']['end'] = 2
    target['data']['content'] = [{'type': 'encrypted', 'value': 'opaque', 'nativePath': '/ciphertext'}]
    with pytest.raises(ValueError, match='opaque-content'):
        validate_session(header(), [target, value])


def test_compaction_summary_and_developer_tool_updates() -> None:
    """Compaction metering stays log-only; dynamic tool additions cite their request."""
    request = event('request/header', {'reason': 'change', 'header': {
        'config': {'provider': 'test', 'model': 'test'},
        'tools': [{'name': 'read', 'description': 'Read', 'parameters': {}}]}})
    update = event('developer/message', {'turn': 1, 'step': 1, 'headerSeq': 0,
        'message': {'id': 'update', 'role': 'developer', 'source': {'kind': 'test-plugin'},
                    'content': [{'type': 'tool-addition', 'toolName': 'read'}]}},
        1, surfaceOp='append')
    start = event('compaction/start', {'compactionId': 'c', 'turn': None}, 2)
    summary = event('compaction/summary', {'compactionId': 'c',
        'summary': [{'type': 'text', 'text': 'summary'}],
        'shadowedRange': {'start': 1, 'end': 1}, 'shadowedSeqs': [1],
        'shadowedTokenCount': 10, 'provider': 'test', 'model': 'test',
        'usage': {'inputTokens': 10, 'outputTokens': 2}}, 3)
    replacement = user('summary', 4, sourceEventSeqs=[1, 3])
    replacement['surfaceOp'] = {'op': 'replace', 'startSeq': 1, 'endSeq': 1}
    end = event('compaction/end', {'compactionId': 'c', 'turn': None}, 5)
    validate_session(header(), [request, update, start, summary, replacement, end], reconstruct=True)
    assert 'surfaceOp' not in summary
    update['data']['headerSeq'] = 1
    with pytest.raises(ValueError, match='headerSeq'):
        validate_session(header(), [request, update])


@pytest.mark.parametrize('delay', [0, 1, 488.02348886860193])
def test_retry_preserves_native_numeric_milliseconds(delay: float) -> None:
    """Jitter is a duration, not an integer sequence or counter."""
    retry = event('llm/retry', {'turn': 0, 'step': 0, 'retryId': 'r', 'retry': 1, 'provider': 'dsh',
                              'mode': 'always', 'policyKey': 'default',
                              'delayMs': delay, 'failure': {'message': 'retry', 'code': 'RATE_LIMIT'}})
    validate_event(retry)
    assert retry['data']['delayMs'] == delay
    for invalid in (-1, True, '1', None, float('inf'), float('nan')):
        retry['data']['delayMs'] = invalid
        with pytest.raises(ValueError):
            validate_event(retry)


@pytest.mark.parametrize('fault', [
    None, 'append', 'missing', 'empty', 'duplicate', 'future', 'incomplete',
    'range', 'non-surface', 'shadowed',
])
def test_assistant_replacement_requires_current_surface_coverage(fault: str | None) -> None:
    """Allow assistant replacements without relaxing source or surface checks."""
    first, second = user('old', 0), user('second', 1)
    marker = event('turn/start', {'turn': 0}, 2)
    replacement = event('assistant/message', {
        'turn': 0, 'step': 0, 'stream': [],
        'message': {'id': 'native-assistant', 'role': 'assistant',
                    'source': {'kind': 'model', 'provider': 'native', 'model': 'native'},
                    'content': [{'type': 'text', 'text': 'new context'}]},
    }, 3, surfaceOp={'op': 'replace', 'startSeq': 0, 'endSeq': 1},
        sourceEventSeqs=[0, 1])
    events = [first, second, marker, replacement]
    if fault == 'append':
        replacement['surfaceOp'] = 'append'
    elif fault == 'missing':
        del replacement['sourceEventSeqs']
    elif fault in {'empty', 'duplicate', 'future', 'incomplete'}:
        replacement['sourceEventSeqs'] = {
            'empty': [], 'duplicate': [0, 1, 1], 'future': [0, 1, 3],
            'incomplete': [0],
        }[fault]
    elif fault == 'range':
        replacement['surfaceOp']['endSeq'] = 3
    elif fault == 'non-surface':
        replacement['surfaceOp']['endSeq'] = 2
        replacement['sourceEventSeqs'] = [0, 1, 2]
    elif fault == 'shadowed':
        repeated = deepcopy(replacement)
        repeated['seq'] = 4
        events.append(repeated)

    original = deepcopy(events)
    if fault:
        with pytest.raises(ValueError, match='sourceEventSeqs|surfaceOp'):
            validate_session(header(), events, reconstruct=True)
    else:
        validate_session(header(), events, reconstruct=True)
    assert events == original


def test_jsonl_messages_consume_assistant_replacement(tmp_path: Path) -> None:
    """The archive consumer applies the shared validator's replacement contract."""
    from agent_swarm.sessions.archive import JsonlSessionStore

    replacement = event('assistant/message', {
        'turn': 0, 'step': 0, 'stream': [],
        'message': {'id': 'replacement', 'role': 'assistant',
                    'source': {'kind': 'model', 'provider': 'native', 'model': 'native'},
                    'content': [{'type': 'text', 'text': 'retained context'}]},
    }, 2, surfaceOp={'op': 'replace', 'startSeq': 0, 'endSeq': 1}, sourceEventSeqs=[0, 1])
    store = JsonlSessionStore.create(tmp_path / 'session.jsonl', header())
    events = [user('first', 0), user('second', 1), replacement]
    for item in events:
        item['native'] = {
            'runtime': 'codex', 'sessionId': 'test-session', 'locator': f"fixture:{item['seq']}",
        }
    store.publish(events, source='test', position=3)
    assert JsonlSessionStore(store.path).messages() == [replacement['data']['message']]
