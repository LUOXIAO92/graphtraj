"""Archive Claude native records without using activity projections as evidence.

Hook callers supply the native event, not a model-authored collection request.
Collection grants no Agent authority. Native child identity is scoped to its
parent Session; it never becomes a fork relationship or a Main association.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import time

from graphtraj.sessions.protocol import retain_native
from graphtraj.sessions.storage import SessionStore, StreamWriter, session_path


def timestamp(record: dict) -> tuple[int, list[dict]]:
    """Read native ISO time or explicitly identify the local receipt clock."""
    value = record.get('timestamp')
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return int(parsed.timestamp() * 1000), []
        except ValueError:
            pass
    return int(time.time() * 1000), [{
        'path': 'time', 'reason': 'Native timestamp unavailable; local collection receipt time.'}]


def open_archive(
    state: Path,
    project: Path,
    native_id: str,
    agent_id: str,
    *,
    source: str,
    child_id: str | None = None,
    fork_parent: str | None = None,
    task_ids: list[str] | None = None,
) -> SessionStore:
    """Open a stable archive without changing its original collection metadata."""
    identity = 'claude:' + native_id + (':agent:' + child_id if child_id else '')
    path = session_path(state, identity)
    if path.exists():
        return SessionStore(path)
    header = {'version': 4, 'id': identity, 'createdAt': int(time.time() * 1000),
              'isSeeded': False, 'cwd': str(project.resolve()), 'graphtraj': {
                  'version': 1, 'projectId': str(project.resolve()), 'agentId': agent_id,
                  'taskIds': task_ids or [], 'native': {'runtime': 'claude', 'sessionId': native_id,
                                           'locator': 'collection', 'source': source},
                  'missing': [{'path': 'createdAt', 'reason': 'Collection creation time; native creation time unavailable.'},
                              {'path': 'taskIds', 'reason': 'No Task association supplied by native source.'}]}}
    if task_ids:
        header['graphtraj']['missing'] = header['graphtraj']['missing'][:1]
    if fork_parent and not child_id:
        header.update(parentSession='claude:' + fork_parent, isSeeded=True)
    if child_id:
        header['origin'] = 'subagent'
        header['graphtraj']['native']['agentId'] = child_id
        header['graphtraj']['native']['parentNativeSessionId'] = native_id
    return SessionStore.create(path, header)


def has_logprobs(value: object) -> bool:
    """Distinguish native probability fields from ordinary text mentioning them."""
    if isinstance(value, dict):
        return 'logprobs' in value or any(has_logprobs(item) for item in value.values())
    return isinstance(value, list) and any(has_logprobs(item) for item in value)


def native_event(store: SessionStore, record: dict, locator: str) -> dict:
    """Retain every JSON field, with missing capabilities scoped to this record."""
    when, missing = timestamp(record)
    event = retain_native('claude', record, session_id=store.header['graphtraj']['native']['sessionId'],
                          locator=locator, seq=store.next_seq, time=when)
    event['graphtraj']['missing'] = missing + [
        {'path': 'hiddenReasoning', 'reason': 'Only native exposed thinking/signatures are available; no decryption.'},
    ]
    if not has_logprobs(record):
        event['graphtraj']['missing'].append({
            'path': 'logprobs', 'reason': 'Not exposed in this record; no probabilities inferred.'})
    message = record.get('message')
    content = message.get('content', []) if isinstance(message, dict) else []
    for index, block in enumerate(content if isinstance(content, list) else []):
        if not isinstance(block, dict) or block.get('type') not in {'image', 'document'}:
            continue
        source = block.get('source')
        if not isinstance(source, dict):
            continue
        location = f'/message/content/{index}/source'
        if source.get('type') == 'base64':
            try:
                reference = store.put_attachment(base64.b64decode(source['data'], validate=True))
                event['graphtraj'].setdefault('attachments', []).append({'nativePath': location, **reference})
            except (ValueError, KeyError, TypeError):
                event['graphtraj']['missing'].append({'path': location, 'reason': 'Native base64 bytes could not be decoded; original value retained.'})
        elif source.get('type') == 'url':
            event['graphtraj']['missing'].append({'path': location, 'reason': 'External URL content not supplied by Runtime; URL retained without fetching.'})
    return event


def seed_pending(store: SessionStore) -> bool:
    """Determine whether this fork still needs its inherited-prefix boundary."""
    if not store.header.get('isSeeded'):
        return False
    after = -1
    while True:
        page = store.page(after)
        if any(e['type'] == 'session/end-seed' for e in page['events']):
            return False
        if not page['has_more']:
            return True
        after = page['after']


def collect_transcript(store: SessionStore, path: Path, *, child_id: str | None = None) -> int:
    """Read complete JSONL records once, committing each record and byte cursor.

    An incomplete trailing line is replayed on the next hook. No directory scan
    or unrelated Session import is performed. Source paths are retained solely
    as provenance; the archive contains the actual record values.
    """
    source = 'transcript:' + str(path.resolve())
    count = 0
    inherited = seed_pending(store)
    with path.open('rb') as stream:
        stream.seek(max(0, store.position(source)))
        while line := stream.readline():
            if not line.endswith(b'\n'):
                break
            position = stream.tell()
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('Claude transcript records must be objects.')
            provenance = store.header['graphtraj']['native']
            native = provenance.get('parentNativeSessionId', provenance['sessionId'])
            if record.get('sessionId', native) != native:
                raise ValueError('Transcript belongs to another native Session.')
            if child_id:
                if record.get('agentId', child_id) != child_id:
                    raise ValueError('Transcript belongs to another native Agent.')
            elif record.get('isSidechain') or record.get('agentId'):
                raise ValueError('A native child transcript cannot be collected as Main.')
            event = native_event(store, record, source + ':' + str(position))
            if inherited and not record.get('forkedFrom'):
                marker = {'type': 'session/end-seed', 'seq': store.next_seq,
                          'time': event['time'], 'data': {'inherited': True}}
                event['seq'] += 1
                store.append_many([marker, event], source=source, position=position)
                inherited = False
            else:
                store.append(event, source=source, position=position)
            count += 1
    return count


def collect_hook(event: dict, cwd: Path) -> dict:
    """Collect exactly the transcript identified by an official native hook.

    SubagentStop's transcript_path is the parent's file. Only its separate
    agent_transcript_path may supply the child. agent_type alone is not a child
    marker because Claude also supplies it for a top-level --agent invocation.
    This entry never registers Main, a checker, or a plugin as a control owner.
    """
    from graphtraj.configuration.project_configuration import load_project_configuration

    kind = event.get('hook_event_name')
    if kind not in {'SessionStart', 'Stop', 'StopFailure', 'SessionEnd', 'SubagentStop'}:
        raise ValueError('Unsupported Claude collection hook.')
    native_id = event.get('session_id')
    if not isinstance(native_id, str) or not native_id:
        raise ValueError('Native Session identity is required.')
    child = event.get('agent_id')
    if child is not None and (not isinstance(child, str) or not child):
        raise ValueError('Native child identity must be a nonempty string.')
    if kind == 'SubagentStop' and not child:
        raise ValueError('Native child identity is required.')
    path = event.get('agent_transcript_path' if child else 'transcript_path')
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('The native source must supply its own absolute transcript path.')
    if child and event.get('transcript_path') and Path(path).resolve() == Path(event['transcript_path']).resolve():
        raise ValueError('The parent transcript is not the child transcript.')
    if event.get('cwd') and Path(event['cwd']).resolve() != cwd.resolve():
        raise ValueError('Hook working directory differs from collection entry.')
    from graphtraj.workspace.runner_project import discover_project_root

    configuration = load_project_configuration(discover_project_root(cwd))
    source = 'child' if child else 'native-session'
    fork_parent = None
    if not child and Path(path).exists():
        # Official SDK fork transcripts annotate copied messages with forkedFrom.
        # Read only this supplied file; never search the Runtime's Session store.
        with Path(path).open('rb') as transcript:
            for line in transcript:
                if not line.endswith(b'\n'):
                    break
                record = json.loads(line)
                if record.get('forkedFrom'):
                    fork_parent = record['forkedFrom'].get('sessionId')
                    break
                if record.get('type') in {'user', 'assistant'}:
                    break
    with open_archive(configuration.state, configuration.harness_root, native_id,
                      'claude-native:' + (child or native_id), source=source, child_id=child, fork_parent=fork_parent) as store:
        try:
            count = collect_transcript(store, Path(path), child_id=child)
            unavailable = None
        except OSError as error:
            count = 0
            unavailable = {'path': path, 'reason': type(error).__name__ + ': native transcript unavailable.'}
        # Hook records are observations; repeated hooks are not repeated messages.
        hook_source = 'hooks'
        position = store.position(hook_source) + 1
        retained = native_event(store, event, f'hook:{position}')
        if unavailable:
            retained['graphtraj']['missing'].append(unavailable)
        if kind == 'SessionStart' and event.get('source') == 'fork' and not fork_parent:
            retained['graphtraj']['missing'].append({
                'path': 'parentSession', 'reason': 'SessionStart reports fork but supplies no parent identity or inherited cut.'})
        if count and seed_pending(store):
            marker = {'type': 'session/end-seed', 'seq': store.next_seq,
                      'time': retained['time'], 'data': {'inherited': True}}
            retained['seq'] += 1
            store.append_many([marker, retained], source=hook_source, position=position)
        else:
            store.append(retained, source=hook_source, position=position)
        return {'session_id': store.header['id'], 'source': source, 'records': count,
                'missing': unavailable}


class StreamCollector:
    """Compact managed stdout while retaining non-text semantics and boundaries."""

    def __init__(self, store: SessionStore, source: str, model: str, provider: str) -> None:
        """Use an execution-scoped ordered source; resume its durable draft if any."""
        self.store = store
        self.source = source
        self.model = model
        self.provider = provider
        self.writer = StreamWriter(store, source, checkpoint_bytes=1) if store.pending() else None
        self.message_id = source
        if self.writer:
            self.message_id = next((item['messageId'] for item in self.writer.event['data']['stream']
                                    if item['type'] == 'graphtraj/text-run'), source)

    def accept(self, record: dict, position: int) -> None:
        """Commit opaque facts or checkpoint compact text with its source position."""
        if position <= self.store.position(self.source):
            return
        event = record.get('event', {}) if record.get('type') == 'stream_event' else {}
        delta = event.get('delta', {})
        plain = (set(record) <= {'type', 'event', 'session_id', 'parent_tool_use_id', 'uuid'}
                 and record.get('parent_tool_use_id') is None
                 and set(event) == {'type', 'index', 'delta'}
                 and event.get('type') == 'content_block_delta'
                 and (set(delta) == {'type', 'text'} and delta['type'] == 'text_delta'
                      or set(delta) == {'type', 'thinking'} and delta['type'] == 'thinking_delta'))
        if plain:
            if self.writer is None:
                template = {'type': 'assistant/message', 'seq': self.store.next_seq,
                            'time': int(time.time() * 1000), 'surfaceOp': 'append',
                            'data': {'turn': 0, 'step': 0, 'stream': [], 'message': {
                                'id': self.message_id + ':' + str(position), 'role': 'assistant',
                                'source': {'kind': 'model', 'provider': self.provider, 'model': self.model},
                                'content': []}}, 'graphtraj': {'version': 1, 'missing': [
                                    {'path': 'turn/step', 'reason': 'Local collection coordinates, not native turn numbers.'},
                                    {'path': 'requestId/attemptId', 'reason': 'Collection message/execution coordinates; native request identity unavailable.'},
                                    {'path': 'time', 'reason': 'Local collection receipt time.'}]}}
                # ponytail: stdout cannot replay after a Worker crash, so commit
                # each received fragment to the replaceable SQLite draft. Batch
                # checkpoints only if the native transport gains durable replay.
                self.writer = StreamWriter(self.store, self.source, template, checkpoint_bytes=1)
            self.writer.feed({'type': 'graphtraj/text-run', 'requestId': self.message_id,
                              'attemptId': self.source, 'messageId': self.message_id,
                              'index': event['index'], 'blockType': 'text' if 'text' in delta else 'reasoning',
                              'text': delta.get('text', delta.get('thinking'))}, position)
            return
        if self.writer and record.get('type') == 'stream_event':
            self.writer.feed({'type': 'claude/native', 'record': record}, position)
            return
        retained = native_event(self.store, record, self.source + ':' + str(position))
        if self.writer:
            self.writer.position = position
            message = record.get('message', {})
            if record.get('type') == 'assistant' and record.get('parent_tool_use_id') is None:
                content = []
                for block in message.get('content', []):
                    if block.get('type') == 'thinking':
                        content.append({**block, 'type': 'reasoning', 'text': block['thinking']})
                    else:
                        content.append(block)
                retained['graphtraj']['missing'].extend(self.writer.event['graphtraj']['missing'])
                self.writer.event['graphtraj'] = retained['graphtraj']
                self.writer.event['graphtraj']['native']['record'] = record
                self.writer.finish(content=content)
            else:
                # Permission, error, cancellation and tool boundaries cannot be
                # merged through. Keep the received partial message explicitly.
                retained['seq'] += 1
                self.writer.finish(content=[], interrupted=True, following=[retained])
            self.writer = None
        else:
            self.store.append(retained, source=self.source, position=position)
        if event.get('type') == 'message_start':
            self.message_id = event.get('message', {}).get('id') or self.source + ':' + str(position)

    def close(self) -> None:
        """Keep received partial text after interruption rather than lose the draft."""
        if self.writer:
            self.writer.finish(content=[], interrupted=True)
            self.writer = None
