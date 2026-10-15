"""Validate lossless Session v4 values, independently of storage and Runtime I/O.

Based on DeepSeek Harness d743267388641bc76f17c45ce8b4c231aed1d32c;
see DSH-LICENSE and examples/sessions/README.md for provenance and semantics.
Unknown JSON fields are retained, never normalized away. Validation does not
claim an unknown required event can be replayed. GraphTraj extensions have
independent version 1 and use the ``graphtraj`` field/event namespace.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

SESSION_FORMAT_VERSION = 4
EXTENSION_VERSION = 1
INITIAL_COLLECTION_TYPE = 'graphtraj/collection-pending'
MAX_SAFE_INTEGER = 2**53 - 1
SURFACE_TYPES = frozenset({
    'user/message', 'assistant/message', 'system/message',
    'developer/message', 'tool/result',
})
CORE_TYPES = SURFACE_TYPES | {
    'turn/start', 'turn/end', 'step/start', 'step/end', 'assistant/attempt',
    'tool/call', 'request/header', 'request/context', 'session/end-seed',
    'llm/retry', 'llm/retry-started', 'compaction/start', 'compaction/end',
    'compaction/summary',
}
EXTENSION_TYPES = {'graphtraj/native', 'graphtraj/score', 'graphtraj/logprobs',
                   'graphtraj/derived'}


def _require(condition: bool, path: str) -> None:
    """Reject an invalid value without echoing private content."""
    if not condition:
        raise ValueError(f'Invalid Session value: {path}')


def _json(value: Any, path: str = '$') -> None:
    """Require lossless JSON values, rejecting coercions and non-finite numbers."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _require(math.isfinite(value), path)
    elif type(value) is list:
        for item in value:
            _json(item, path)
    elif type(value) is dict:
        for key, item in value.items():
            _require(type(key) is str, path)
            _json(item, f'{path}.{key}')
    else:
        _require(False, path)


def _fields(value: Any, fields: dict[str, type], path: str) -> None:
    """Check required fields while retaining all extension fields."""
    _require(type(value) is dict, path)
    for key, kind in fields.items():
        _require(key in value and type(value[key]) is kind, f'{path}.{key}')


def _integer(value: Any, path: str, minimum: int = 0) -> None:
    """Check a DSH safe integer, excluding Python booleans."""
    _require(type(value) is int and minimum <= value <= MAX_SAFE_INTEGER, path)


def _strings(value: dict, keys: tuple[str, ...], path: str) -> None:
    """Check optional nonempty identities without inventing defaults."""
    for key in keys:
        if key in value:
            _require(type(value[key]) is str and bool(value[key]), f'{path}.{key}')


def validate_header(header: dict) -> None:
    """Validate immutable DSH v4 metadata; callers own snapshots and persistence.

    ``createdAt`` is epoch milliseconds. ``parentSession`` is fork lineage,
    never Agent or Task parentage. Unknown versions are refused, not migrated.
    A GraphTraj header extension binds projectId, agentId and taskIds; native
    identifiers remain evidence, never authorization.
    """
    _json(header)
    _fields(header, {'version': int, 'id': str, 'createdAt': int, 'isSeeded': bool}, 'header')
    _require(header['version'] == SESSION_FORMAT_VERSION, 'header.version')
    _strings(header, ('id', 'parentSession', 'agentPreset', 'cwd'), 'header')
    _integer(header['createdAt'], 'header.createdAt')
    if 'cwd' in header:
        _require(PurePosixPath(header['cwd']).is_absolute() or
                 PureWindowsPath(header['cwd']).is_absolute(), 'header.cwd')
    if 'delegationDepth' in header:
        _integer(header['delegationDepth'], 'header.delegationDepth')
    if 'origin' in header:
        _require(header['origin'] == 'subagent', 'header.origin')
    if 'graphtraj' in header:
        ext = header['graphtraj']
        _provenance(ext)
        _fields(ext, {'version': int, 'projectId': str, 'agentId': str, 'taskIds': list}, 'header.graphtraj')
        _require(ext['version'] == EXTENSION_VERSION, 'header.graphtraj.version')
        _strings(ext, ('projectId', 'agentId'), 'header.graphtraj')
        _require(all(type(item) is str and item for item in ext['taskIds']), 'header.graphtraj.taskIds')


def validate_content(content: list) -> None:
    """Validate DSH content, keeping opaque blocks, ciphertext and replay data."""
    _require(type(content) is list, 'content')
    for block in content:
        _fields(block, {'type': str}, 'content.block')
        kind = block['type']
        if kind in {'text', 'reasoning'}:
            _fields(block, {'text': str}, 'content.block')
        elif kind == 'tool-call':
            _fields(block, {'id': str, 'name': str, 'arguments': str}, 'content.tool-call')
        elif kind in {'image', 'file'}:
            _fields(block, {'attachment': dict}, 'content.attachment')
        elif kind in {'tool-addition', 'tool-removal'}:
            _fields(block, {'toolName': str}, 'content.tool-change')
            _require('tool' not in block, 'content.tool-change.tool')
        elif kind == 'graphtraj/encrypted':
            _fields(block, {'value': str, 'nativePath': str}, 'content.encrypted')
        _json(block)


def _message(message: dict, role: str) -> None:
    """Validate the shared identified message and role-specific source."""
    _fields(message, {'id': str, 'role': str, 'content': list, 'source': dict}, 'message')
    _require(message['role'] == role, 'message.role')
    _fields(message['source'], {'kind': str}, 'message.source')
    if role == 'assistant':
        _require(message['source']['kind'] == 'model', 'message.source.kind')
        _fields(message['source'], {'provider': str, 'model': str}, 'message.source')
    elif role == 'tool':
        _require(message['source']['kind'] == 'tool', 'message.source.kind')
        _fields(message['source'], {'callId': str}, 'message.source')
        _fields(message, {'toolCallId': str}, 'message')
        _require(message['toolCallId'] == message['source']['callId'], 'message.toolCallId')
        if 'isError' in message:
            _require(type(message['isError']) is bool, 'message.isError')
    elif role == 'system':
        _require(message['source']['kind'] == 'system-prompt', 'message.source.kind')
    validate_content(message['content'])


def _usage(usage: dict) -> None:
    """Validate disjoint DSH input/cache counts; absence stays absent."""
    _fields(usage, {'inputTokens': int, 'outputTokens': int}, 'usage')
    for key in ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens',
                'totalTokens', 'reasoningTokens'):
        if key in usage:
            _integer(usage[key], f'usage.{key}')


def _failure(value: dict) -> None:
    """Validate provider-neutral failure facts, preserving provider extensions."""
    _fields(value, {'message': str, 'code': str}, 'failure')


def validate_stream(stream: list) -> None:
    """Validate DSH compact runs and GraphTraj semantic text runs.

    DSH dt entries are signed gaps between consecutive epoch-ms timestamps;
    len(dt) == len(texts/args)-1. GraphTraj runs intentionally discard transport
    fragmentation, carry one joined text, and must not be called exact replay.
    Unknown records remain lossless JSON for inspection by their owner.
    """
    _require(type(stream) is list, 'stream')
    for record in stream:
        _fields(record, {'type': str}, 'stream.record')
        _json(record)
        kind = record['type']
        if kind in {'text-chunks', 'reasoning-chunks', 'tool-call-chunks'}:
            member = 'args' if kind == 'tool-call-chunks' else 'texts'
            _fields(record, {'time0': int, 'index': int, 'dt': list, member: list}, 'stream.run')
            _integer(record['index'], 'stream.index')
            _integer(record['time0'], 'stream.time0', -MAX_SAFE_INTEGER)
            _require(len(record[member]) > 0 and len(record['dt']) == len(record[member]) - 1, 'stream.dt')
            _require(all(type(text) is str for text in record[member]), 'stream.members')
            time = record['time0']
            for gap in record['dt']:
                _integer(gap, 'stream.dt', -MAX_SAFE_INTEGER)
                time += gap
                _integer(time, 'stream.time', -MAX_SAFE_INTEGER)
            if kind == 'tool-call-chunks':
                _fields(record, {'id': str}, 'stream.tool-call')
                _strings(record, ('id', 'name'), 'stream.tool-call')
        elif kind == 'chunk':
            _fields(record, {'time': int, 'chunk': dict}, 'stream.chunk')
            _integer(record['time'], 'stream.time', -MAX_SAFE_INTEGER)
            chunk = record['chunk']
            _fields(chunk, {'type': str}, 'stream.chunk')
            if chunk['type'] in {'text-delta', 'reasoning-delta'}:
                _fields(chunk, {'index': int, 'text': str}, 'stream.delta')
            elif chunk['type'] == 'tool-call-delta':
                _fields(chunk, {'index': int, 'id': str, 'argumentsDelta': str}, 'stream.delta')
            elif chunk['type'] == 'block-start':
                _fields(chunk, {'index': int, 'blockType': str}, 'stream.block-start')
            elif chunk['type'] == 'block-end':
                _fields(chunk, {'index': int, 'block': dict}, 'stream.block-end')
                validate_content([chunk['block']])
            elif chunk['type'] == 'usage':
                _usage(chunk.get('usage'))
            elif chunk['type'] == 'finish':
                _fields(chunk.get('reason'), {'kind': str}, 'stream.finish')
                if chunk['reason']['kind'] in {'error', 'aborted'}:
                    _failure(chunk['reason'].get('failure'))
            if 'index' in chunk:
                _integer(chunk['index'], 'stream.index')
        elif kind == 'graphtraj/text-run':
            _fields(record, {'requestId': str, 'attemptId': str, 'messageId': str,
                             'index': int, 'blockType': str, 'text': str}, 'stream.text-run')
            _require(record['blockType'] in {'text', 'reasoning'}, 'stream.blockType')
            _integer(record['index'], 'stream.index')


def _provenance(ext: dict) -> None:
    """Validate source identity and explicit unavailable-field explanations."""
    _fields(ext, {'version': int}, 'graphtraj')
    _require(ext['version'] == EXTENSION_VERSION, 'graphtraj.version')
    if 'native' in ext:
        native = ext['native']
        _fields(native, {'runtime': str, 'sessionId': str, 'locator': str}, 'graphtraj.native')
        _strings(native, ('runtime', 'sessionId', 'locator'), 'graphtraj.native')
    if 'missing' in ext:
        _fields(ext, {'missing': list}, 'graphtraj')
        for item in ext['missing']:
            _fields(item, {'path': str, 'reason': str}, 'graphtraj.missing')
            _strings(item, ('path', 'reason'), 'graphtraj.missing')


def _observation(data: dict, kind: str, seq: int) -> None:
    """Validate append-only RL/derived observations and their explicit alignment.

    Token position is zero-based in this attempt's specified tokenizer, never
    a transport chunk index. Output spans use UTF-8 byte offsets [start, end).
    Null identities need a missing explanation. Probability arrays may be
    sparse; no API name alone proves raw versus sampled semantics.
    """
    _fields(data, {'target': dict, 'source': dict}, kind)

    target = data['target']
    _fields(target, {'eventSeq': int}, 'observation.target')
    _integer(target['eventSeq'], 'observation.target.eventSeq')
    _require(target['eventSeq'] < seq, 'observation.target.eventSeq')

    for key in ('tokenPosition', 'blockIndex'):
        if key in target:
            _integer(target[key], f'target.{key}')

    for key in ('requestId', 'attemptId', 'model', 'tokenizer'):
        _require(key in target and (target[key] is None or
                 (type(target[key]) is str and bool(target[key]))), f'target.{key}')
        if target[key] is None:
            _require(
                type(target.get('missing')) is dict
                and type(target['missing'].get(key)) is str
                and bool(target['missing'][key]),
                f'target.missing.{key}',
            )

    source = data['source']
    _fields(source, {'kind': str, 'producer': str, 'evidence': str}, 'observation.source')
    _require(source['kind'] in {'native', 'recomputed', 'supplemented'}, 'observation.source.kind')
    _strings(source, ('producer', 'evidence'), 'observation.source')
    if source['kind'] != 'native':
        _fields(source, {'context': list}, 'observation.source')
        _require(bool(source['context']), 'observation.source.context')
        for context in source['context']:
            _fields(context, {'sessionId': str, 'eventSeq': int}, 'observation.source.context')
            _integer(context['eventSeq'], 'observation.source.context.eventSeq')

    if kind == 'graphtraj/score':
        _fields(data, {'name': str, 'rule': str}, 'score')
        _require(type(data.get('value')) in (int, float), 'score.value')
    elif kind == 'graphtraj/derived':
        _require(source['kind'] == 'supplemented', 'derived.source')
        validate_content(data.get('content'))
    else:
        _fields(data, {'distribution': str, 'semantics': str, 'tokens': list}, 'logprobs')
        _require(data['distribution'] in {'raw', 'sampled', 'unspecified'}, 'logprobs.distribution')
        _strings(data, ('semantics',), 'logprobs')

        if data['distribution'] == 'sampled':
            _fields(data, {'sampling': dict}, 'logprobs')
            for key in ('temperature', 'topP', 'topK'):
                _require(key in data['sampling'], f'logprobs.sampling.{key}')
                if data['sampling'][key] is None:
                    missing = data['sampling'].get('missing')
                    _require(
                        type(missing) is dict
                        and type(missing.get(key)) is str
                        and bool(missing[key]),
                        f'logprobs.sampling.missing.{key}',
                    )
                else:
                    _require(type(data['sampling'][key]) in (int, float), f'logprobs.sampling.{key}')

        positions = set()
        for token in data['tokens']:
            _fields(token, {'position': int}, 'token')
            _integer(token['position'], 'token.position')
            _require(token['position'] not in positions, 'token.position.duplicate')
            positions.add(token['position'])

            _require('logprob' in token, 'token.logprob')
            probability = token['logprob']
            # JSON cannot encode -infinity: preserve its native spelling separately.
            if probability is None:
                _require(type(token.get('missing')) is str and bool(token['missing']), 'token.missing')
            else:
                _require(type(probability) in (float, int) and probability <= 0, 'token.logprob')

            if 'tokenId' in token:
                _integer(token['tokenId'], 'token.tokenId')
            if 'text' in token:
                _require(type(token['text']) is str, 'token.text')

            if 'span' in token:
                span = token['span']
                _fields(span, {'blockIndex': int, 'start': int, 'end': int}, 'token.span')
                for key in ('blockIndex', 'start', 'end'):
                    _integer(span[key], f'token.span.{key}')
                _require(span['start'] <= span['end'], 'token.span')


def validate_event(event: dict) -> None:
    """Validate one event without mutating it or discarding unknown payloads.

    Unknown event types are admitted for archival inspection. Use
    ``validate_session(..., reconstruct=True)`` before interpreting a log.
    This validates protocol values, not a live Agent's execution lifecycle.
    """
    _json(event)
    _fields(event, {'type': str, 'seq': int, 'time': int}, 'event')
    _require('data' in event, 'event.data')
    _integer(event['seq'], 'event.seq')
    _integer(event['time'], 'event.time', -MAX_SAFE_INTEGER)
    _require(bool(event['type']), 'event.type')
    if 'ignorable' in event:
        _require(event['ignorable'] is True, 'event.ignorable')
    if 'graphtraj' in event:
        _provenance(event['graphtraj'])
    kind, data = event['type'], event['data']
    if kind in CORE_TYPES | EXTENSION_TYPES:
        _fields(data, {}, 'event.data')
    if kind in SURFACE_TYPES:
        op = event.get('surfaceOp')
        if op != 'append':
            _fields(op, {'op': str, 'startSeq': int, 'endSeq': int}, 'surfaceOp')
            _require(op['op'] == 'replace', 'surfaceOp.op')
            _require(0 <= op['startSeq'] <= op['endSeq'] < event['seq'], 'surfaceOp.range')
        if 'sourceEventSeqs' in event:
            refs = event['sourceEventSeqs']
            _require(kind != 'assistant/message' and type(refs) is list and bool(refs), 'sourceEventSeqs')
            for ref in refs:
                _integer(ref, 'sourceEventSeqs')
                _require(ref < event['seq'], 'sourceEventSeqs')
            _require(len(refs) == len(set(refs)), 'sourceEventSeqs.duplicate')
        role = 'tool' if kind == 'tool/result' else kind.split('/')[0]
        _message(data if kind == 'user/message' else data.get('message'), role)
    elif kind in CORE_TYPES | EXTENSION_TYPES:
        _require('surfaceOp' not in event and 'sourceEventSeqs' not in event, 'event.surface')

    if kind in {'turn/start', 'turn/end', 'step/start', 'step/end',
                'system/message', 'developer/message', 'assistant/message',
                'assistant/attempt', 'tool/call', 'tool/result', 'llm/retry', 'llm/retry-started'}:
        _integer(data.get('turn'), 'data.turn')
        if kind not in {'turn/start', 'turn/end'}:
            _integer(data.get('step'), 'data.step')
    if kind in {'assistant/message', 'assistant/attempt'}:
        validate_stream(data.get('stream'))
        if 'interrupted' in data:
            _require(data['interrupted'] is True, 'data.interrupted')
    elif kind == 'turn/end':
        _fields(data.get('reason'), {'kind': str}, 'turn.reason')
        if data['reason']['kind'] == 'error':
            _failure(data['reason'].get('error'))
        if data['reason']['kind'] == 'aborted':
            _fields(data['reason'].get('reason'), {'kind': str}, 'turn.cancel')
    elif kind == 'tool/call':
        _fields(data, {'callId': str, 'name': str, 'arguments': str}, 'tool.call')
    elif kind == 'tool/result' and 'error' in data:
        _require(data['message'].get('isError') is True, 'tool.result.error')
        _fields(data['error'], {'name': str, 'code': str}, 'tool.result.error')
    elif kind == 'request/header':
        _fields(data, {'header': dict, 'reason': str}, 'request')
        _require(data['reason'] in {'initial', 'resume', 'change', 'series'}, 'request.reason')
        header = data['header']
        _fields(header, {'config': dict}, 'request.header')
        _fields(header['config'], {'provider': str, 'model': str}, 'request.config')
        _require('system' not in header, 'request.header.system')
        if 'tools' in header:
            _require(type(header['tools']) is list and bool(header['tools']), 'request.tools')
            for tool in header['tools']:
                _fields(tool, {'name': str, 'description': str, 'parameters': dict}, 'request.tool')
        config = header['config']
        for key in ('temperature', 'maxTokens'):
            if key in config:
                _require(type(config[key]) in (int, float), f'request.config.{key}')
        if 'reasoningEffort' in config:
            _require(type(config['reasoningEffort']) is str, 'request.config.reasoningEffort')
        if 'stop' in config:
            _require(type(config['stop']) is list and all(type(item) is str for item in config['stop']), 'request.config.stop')
        if 'adapterDefaults' in header:
            _require(type(header['adapterDefaults']) is dict and bool(header['adapterDefaults']), 'request.adapterDefaults')
            for key in ('maxTokens', 'reasoningEffort'):
                if key in header['adapterDefaults']:
                    _require(header['adapterDefaults'][key] is True, f'request.adapterDefaults.{key}')
        if 'startsSeries' in data:
            _require(data['startsSeries'] is True, 'request.startsSeries')
    elif kind == 'request/context':
        _fields(data, {'provider': str, 'model': str}, 'request.context')
        if 'contextWindow' in data:
            _integer(data['contextWindow'], 'request.contextWindow')
    elif kind == 'session/end-seed':
        if 'inherited' in data:
            _require(data['inherited'] is True, 'session.inherited')
    elif kind in {'llm/retry', 'llm/retry-started'}:
        _fields(data, {'retryId': str, 'retry': int}, 'retry')
        _integer(data['retry'], 'retry.retry')
        if kind == 'llm/retry':
            _fields(data, {'provider': str, 'mode': str, 'policyKey': str}, 'retry')
            _require(data['mode'] in {'normal', 'always'}, 'retry.mode')
            # Native retry jitter retains fractional milliseconds without rounding.
            delay = data.get('delayMs')
            _require(type(delay) in (int, float) and delay >= 0, 'retry.delayMs')
            if data['mode'] == 'normal':
                _integer(data.get('maxRetries'), 'retry.maxRetries')
            _failure(data.get('failure'))
    elif kind in {'compaction/start', 'compaction/end', 'compaction/summary'}:
        _fields(data, {'compactionId': str}, 'compaction')
        if kind != 'compaction/summary':
            _require('turn' in data, 'compaction.turn')
            if data['turn'] is not None:
                _integer(data['turn'], 'compaction.turn')
        else:
            _fields(data, {'summary': list, 'shadowedRange': dict, 'shadowedSeqs': list,
                           'shadowedTokenCount': int, 'provider': str, 'model': str}, 'compaction')
            validate_content(data['summary'])
            _fields(data['shadowedRange'], {'start': int, 'end': int}, 'compaction.range')
            _require(0 <= data['shadowedRange']['start'] <= data['shadowedRange']['end'] < event['seq'], 'compaction.range')
            _integer(data['shadowedTokenCount'], 'compaction.shadowedTokenCount')
            for ref in data['shadowedSeqs']:
                _integer(ref, 'compaction.shadowedSeqs')
                _require(ref < event['seq'], 'compaction.shadowedSeqs')
            if 'rawOutput' in data:
                validate_content(data['rawOutput'])
            if 'llmStreamCall' in data:
                _require(data['llmStreamCall'] is True and 'rawOutput' in data, 'compaction.llmStreamCall')
    elif kind == 'graphtraj/native':
        _require('record' in data, 'native.record')
        _require('native' in event.get('graphtraj', {}), 'native.provenance')
    elif kind in EXTENSION_TYPES:
        _observation(data, kind, event['seq'])
    if kind in {'assistant/message', 'compaction/summary'} and 'usage' in data:
        _usage(data['usage'])


def validate_session(header: dict, events: list[dict], *, reconstruct: bool = False) -> None:
    """Validate a complete contiguous log, fork cut and surface references.

    Archival validation retains unknown required events; reconstruction refuses
    them. Neither mode executes tools, resumes a Runtime, or migrates versions.
    A fork's last inherited marker identifies its exact prefix length. Surface
    replacements must cite every currently shadowed node, not every log event.
    """
    validate_header(header)
    _require(type(events) is list, 'events')

    surface: list[int] = []
    inherited = []

    for seq, event in enumerate(events):
        validate_event(event)
        _require(event['seq'] == seq, 'event.contiguous-seq')
        kind = event['type']
        _require(kind != INITIAL_COLLECTION_TYPE, 'event.pending-collection is not canonical history')

        if kind in EXTENSION_TYPES:
            _require('graphtraj' in header, 'header.graphtraj required for extensions')
        if reconstruct and kind == 'graphtraj/native':
            _require(False, 'event.opaque-native requires Runtime interpretation')
        if reconstruct and kind not in CORE_TYPES | EXTENSION_TYPES:
            _require(event.get('ignorable') is True, 'event.unknown-required')

        if kind == 'session/end-seed' and event['data'].get('inherited') is True:
            inherited.append(seq)

        if kind == 'developer/message':
            additions = any(
                block['type'] == 'tool-addition'
                for block in event['data']['message']['content']
            )
            ref = event['data'].get('headerSeq')
            _require(additions == (ref is not None), 'developer.headerSeq')
            if ref is not None:
                _integer(ref, 'developer.headerSeq')
                _require(ref < seq and events[ref]['type'] == 'request/header', 'developer.headerSeq')

        if kind == 'graphtraj/logprobs':
            target = events[event['data']['target']['eventSeq']]
            for token in event['data']['tokens']:
                if 'span' not in token:
                    continue
                span = token['span']
                _require(target['type'] in SURFACE_TYPES, 'token.span.target-message')
                message = (
                    target['data'] if target['type'] == 'user/message'
                    else target['data'].get('message', {})
                )
                blocks = message.get('content', [])
                _require(span['blockIndex'] < len(blocks), 'token.span.blockIndex')
                block = blocks[span['blockIndex']]
                _require(block.get('type') in {'text', 'reasoning'}, 'token.span.opaque-content')
                _require(span['end'] <= len(block['text'].encode('utf-8')), 'token.span.end')

        if kind not in SURFACE_TYPES:
            continue
        op = event['surfaceOp']
        if op == 'append':
            surface.append(seq)
        else:
            _require(op['startSeq'] in surface and op['endSeq'] in surface, 'surfaceOp.nodes')
            start, end = surface.index(op['startSeq']), surface.index(op['endSeq'])
            _require(start <= end, 'surfaceOp.order')
            _require(
                set(surface[start:end + 1]) <= set(event.get('sourceEventSeqs', [])),
                'surfaceOp.sources',
            )
            surface[start:end + 1] = [seq]

    _require(bool(inherited) == header['isSeeded'], 'header.isSeeded')


def snapshot_event(event: dict) -> dict:
    """Return a validated detached JSON snapshot, including every unknown field."""
    validate_event(event)
    return deepcopy(event)


def retain_native(
    runtime: str,
    record: dict,
    *,
    session_id: str,
    locator: str,
    seq: int,
    time: int,
) -> dict:
    """Retain an uninterpreted native semantic record with reversible provenance.

    This is an archival mapping seam, not a transport collector. Pi RPC text
    deltas must be assembled before calling it; blindly retaining all RPC
    snapshots would preserve the known amplification bug. ``time`` is an
    observed receipt timestamp if native time is unavailable; record that fact
    in graphtraj.missing rather than inventing a native timestamp.
    """
    event = {'type': 'graphtraj/native', 'seq': seq, 'time': time,
             'data': {'record': record}, 'graphtraj': {'version': EXTENSION_VERSION,
             'native': {'runtime': runtime, 'sessionId': session_id, 'locator': locator}}}
    return snapshot_event(event)


def native_record(event: dict) -> dict:
    """Recover a detached original JSON record, without reversing lossy projections."""
    validate_event(event)
    if event['type'] == 'graphtraj/native':
        return deepcopy(event['data']['record'])
    native = event.get('graphtraj', {}).get('native', {})
    _require('record' in native, 'native.record unavailable')
    return deepcopy(native['record'])
