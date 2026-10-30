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

from agent_swarm.sessions import SESSION_FORMAT_VERSION, retain_native
from graphtraj.sessions.storage import SessionStore, StreamWriter, session_path


from agent_swarm.claude import collect_hook_event, hook_source
from graphtraj.interfaces.agents import graphtraj_fields


def timestamp(record: dict) -> tuple[int, list[dict]]:
    """Read native ISO time; zero is an explicitly missing protocol placeholder."""
    value = record.get('timestamp')
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return int(parsed.timestamp() * 1000), []
        except ValueError:
            pass
    return 0, [{
        'path': 'time', 'reason': 'Native timestamp unavailable; zero is a protocol placeholder.'}]


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
    project_identity: str | None = None,
) -> SessionStore:
    """Open a stable archive without changing its original collection metadata."""
    identity = 'claude:' + native_id + (':agent:' + child_id if child_id else '')
    path = session_path(state, identity)
    if path.exists():
        return SessionStore(path)
    origin = project_identity if project_identity is not None else str(project.resolve())
    header = {'version': SESSION_FORMAT_VERSION, 'id': identity, 'createdAt': int(time.time() * 1000),
              'isSeeded': False, 'cwd': origin,
              'native': {'runtime': 'claude', 'sessionId': native_id,
                         'locator': 'collection', 'source': source},
              'missing': [{'path': 'createdAt', 'reason': 'Collection creation time; native creation time unavailable.'},
                          {'path': 'taskIds', 'reason': 'No Task association supplied by native source.'}],
              'extra_fields': graphtraj_fields(origin, agent_id, task_ids or [])}
    if task_ids:
        header['missing'] = header['missing'][:1]
    if fork_parent and not child_id:
        header.update(parentSession='claude:' + fork_parent, isSeeded=True)
    if child_id:
        header['origin'] = 'subagent'
        header['native']['agentId'] = child_id
        header['native']['parentNativeSessionId'] = native_id
    return SessionStore.create(path, header)


def has_logprobs(value: object) -> bool:
    """Distinguish native probability fields from ordinary text mentioning them."""
    if isinstance(value, dict):
        return 'logprobs' in value or any(has_logprobs(item) for item in value.values())
    return isinstance(value, list) and any(has_logprobs(item) for item in value)


def native_event(store: SessionStore, record: dict, locator: str) -> dict:
    """Retain every JSON field, with missing capabilities scoped to this record."""
    when, missing = timestamp(record)
    event = retain_native('claude', record, session_id=store.header['native']['sessionId'],
                          locator=locator, seq=store.next_seq, time=when)
    event['receivedAtMs'] = int(time.time() * 1000)
    event['missing'] = missing + [
        {'path': 'hiddenReasoning', 'reason': 'Only native exposed thinking/signatures are available; no decryption.'},
    ]
    if not has_logprobs(record):
        event['missing'].append({
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
                event.setdefault('attachments', []).append({'nativePath': location, **reference})
            except (ValueError, KeyError, TypeError):
                event['missing'].append({'path': location, 'reason': 'Native base64 bytes could not be decoded; original value retained.'})
        elif source.get('type') == 'url':
            event['missing'].append({'path': location, 'reason': 'External URL content not supplied by Runtime; URL retained without fetching.'})
    return event


def fork_source(record: dict, native_id: str) -> dict | None:
    """Recognize an explicitly identified inherited message, never a parent guess."""
    fork = record.get('forkedFrom')
    if (isinstance(fork, dict) and isinstance(fork.get('sessionId'), str)
            and fork['sessionId'] and fork['sessionId'] != native_id
            and isinstance(fork.get('messageUuid'), str) and fork['messageUuid']):
        return fork
    return None


def collect_transcript(
    store: SessionStore,
    path: Path,
    *,
    child_id: str | None = None,
    source_path: Path | None = None,
) -> int:
    """Read complete JSONL records once with durable event and byte cursors.

    An incomplete trailing line is replayed on the next hook. No directory scan
    or unrelated Session import is performed. Source paths are retained solely
    as provenance; the archive contains the actual record values.
    """
    source = 'transcript:' + (str(source_path) if source_path is not None else str(path.resolve()))
    count = 0
    observations = []
    with path.open('rb') as stream:
        stream.seek(max(0, store.position(source)))
        while line := stream.readline():
            if not line.endswith(b'\n'):
                break
            position = stream.tell()
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('Claude transcript records must be objects.')
            provenance = store.header['native']
            native = provenance.get('parentNativeSessionId', provenance['sessionId'])
            if record.get('sessionId', native) != native:
                raise ValueError('Transcript belongs to another native Session.')
            if child_id:
                if record.get('agentId', child_id) != child_id:
                    raise ValueError('Transcript belongs to another native Agent.')
            elif record.get('isSidechain') or record.get('agentId'):
                raise ValueError('A native child transcript cannot be collected as Main.')
            event = native_event(store, record, source + ':' + str(position))
            fork = fork_source(record, native) if not child_id else None
            if store.next_seq == 0:
                observations.append({'event': event, 'source': source, 'position': position})
                if source_path is None or len(observations) >= 256:
                    store.stage_initial_observations(observations)
                    observations.clear()
            elif fork:
                raise ValueError('Late inherited history after canonical publication requires unresolved ancestry handling.')
            else:
                store.append(event, source=source, position=position)
            count += 1
    if observations:
        store.stage_initial_observations(observations)
    return count


def finish_transcript_collection(
    store: SessionStore,
    native_id: str,
    *,
    child: bool = False,
    terminal: bool = False,
) -> None:
    """Publish a collected native prefix only when its ancestry is established.

    Offline migration may supply a stopped transcript, but does not synthesize
    a native hook. Recorded hooks still participate in fork classification.
    """
    if store.next_seq or not store.pending():
        return
    observations = store.pending()['event']['data']['observations']
    inherited = []
    parents = set()
    local_message = False
    fork_expected = False
    for observation in observations:
        record = observation['event']['data']['record']
        if observation['source'] == 'hooks':
            fork_expected |= record.get('source') == 'fork'
            continue
        fork = fork_source(record, native_id) if not child else None
        if fork:
            if local_message:
                raise ValueError('Inherited records follow child-local messages; ancestry remains pending.')
            parents.add('claude:' + fork['sessionId'])
            inherited.append((observation['source'], observation['position']))
        elif record.get('type') in {'user', 'assistant'}:
            local_message = True
    if len(parents) > 1:
        raise ValueError('Conflicting native fork parents; ancestry remains pending.')
    if (local_message or (terminal and inherited)) and (not fork_expected or inherited or child):
        store.finish_initial_collection(parent_session=next(iter(parents), None),
                                        inherited=inherited)


def collect_jsonl_hook(event: dict, cwd: Path) -> dict:
    """Collect the native hook's associated transcript into the project's tool-owned archive.

    GraphTraj only chooses the archive and its ``extra_fields.graphtraj``; the
    collection itself is the agents package's.
    """
    from graphtraj.interfaces.agents import configured_archive, graphtraj_fields
    from graphtraj.workspace.runner_project import discover_project_root

    _kind, native_id, child, _path = hook_source(event, cwd)
    return collect_hook_event(configured_archive(discover_project_root(cwd)), event, cwd,
                              extra_fields=graphtraj_fields(str(cwd), 'claude-native:' + (child or native_id)))


def collect_hook(event: dict, cwd: Path) -> dict:
    """Collect exactly the transcript identified by an official native hook.

    SubagentStop's transcript_path is the parent's file. Only its separate
    agent_transcript_path may supply the child. agent_type alone is not a child
    marker because Claude also supplies it for a top-level --agent invocation.
    This entry never registers Main, a checker, or a plugin as a control owner.
    """
    from graphtraj.configuration.project_configuration import load_project_configuration

    kind, native_id, child, path = hook_source(event, cwd)
    from graphtraj.workspace.runner_project import discover_project_root

    configuration = load_project_configuration(discover_project_root(cwd))
    source = 'child' if child else 'native-session'
    with open_archive(configuration.state, configuration.harness_root, native_id,
                      'claude-native:' + (child or native_id), source=source, child_id=child) as store:
        try:
            count = collect_transcript(store, Path(path), child_id=child)
            unavailable = None
        except OSError as error:
            count = 0
            unavailable = {'path': path, 'reason': type(error).__name__ + ': native transcript unavailable.'}
        # Hook records are observations; repeated hooks are not repeated messages.
        hook_channel = 'hooks'
        position = store.position(hook_channel) + 1
        retained = native_event(store, event, f'hook:{position}')
        if unavailable:
            retained['missing'].append(unavailable)
        if kind == 'SessionStart' and event.get('source') == 'fork':
            retained['missing'].append({
                'path': 'parentSession', 'reason': 'SessionStart reports fork but supplies no parent identity or inherited cut.'})
        if store.next_seq:
            store.append(retained, source=hook_channel, position=position)
        else:
            store.stage_initial_observation(retained, source=hook_channel, position=position)
            finish_transcript_collection(
                store, native_id, child=bool(child),
                terminal=kind in {'Stop', 'StopFailure', 'SessionEnd', 'SubagentStop'})
        return {'session_id': store.header['id'], 'source': source, 'records': count,
                'missing': unavailable}


class StreamCollector:
    """Compact managed stdout while retaining non-text semantics and boundaries."""

    def __init__(self, store: SessionStore, source: str, model: str, provider: str) -> None:
        """Use an execution-scoped ordered source; resume its durable draft if any."""
        self.store = store
        self.source = source
        self.requested_model = model
        self.observed_model = None
        self.provider = provider
        self.writer = StreamWriter(store, source, checkpoint_bytes=1) if store.pending() else None
        self.message_id = source
        if self.writer:
            message = self.writer.event['data'].get('message', {})
            self.observed_model = message.get('source', {}).get('model')
            self.message_id = next((item['messageId'] for item in self.writer.event['data']['stream']
                                    if item['type'] == 'text-run'), source)

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
                template = {'type': 'assistant/attempt', 'seq': self.store.next_seq,
                            'time': 0,
                            'data': {'turn': 0, 'step': 0, 'stream': []},
                            'requestedModel': self.requested_model,
                            'receivedAtMs': int(time.time() * 1000),
                            'missing': [
                                {'path': 'turn/step', 'reason': 'Local collection coordinates, not native turn numbers.'},
                                {'path': 'requestId/attemptId', 'reason': 'Collection message/execution coordinates; native request identity unavailable.'},
                                {'path': 'time', 'reason': 'Native timestamp unavailable; zero is a protocol placeholder.'}]}
                if self.observed_model:
                    template.update(type='assistant/message', surfaceOp='append')
                    template['data']['message'] = self.message(self.observed_model)
                else:
                    template['missing'].append({
                        'path': 'model', 'reason': 'Native model not observed; configured model is only a request.'})
                # ponytail: stdout cannot replay after a Worker crash, so commit
                # each received fragment to the replaceable SQLite draft. Batch
                # checkpoints only if the native transport gains durable replay.
                self.writer = StreamWriter(self.store, self.source, template, checkpoint_bytes=1)
            self.writer.feed({'type': 'text-run', 'requestId': self.message_id,
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
                returned_model = message.get('model')
                if 'model' in message:
                    self.observed_model = (returned_model if isinstance(returned_model, str)
                                           and returned_model and returned_model != '<synthetic>' else None)
                if self.observed_model:
                    self.writer.event.update(type='assistant/message', surfaceOp='append')
                    self.writer.event['data']['message'] = self.message(self.observed_model)
                    self.writer.event['missing'] = [
                        item for item in self.writer.event['missing'] if item['path'] != 'model']
                else:
                    self.writer.event['type'] = 'assistant/attempt'
                    self.writer.event.pop('surfaceOp', None)
                    self.writer.event['data'].pop('message', None)
                content = []
                for block in message.get('content', []):
                    if block.get('type') == 'thinking':
                        content.append({**block, 'type': 'reasoning', 'text': block['thinking']})
                    else:
                        content.append(block)
                retained['missing'].extend(
                    item for item in self.writer.event['missing'] if item['path'] != 'time')
                retained['firstReceivedAtMs'] = self.writer.event.get('receivedAtMs')
                # Final native time describes the completed record. The first
                # fragment's observation clock is separate provenance only.
                self.writer.event['time'] = retained['time']
                # The completed record's archive facts replace the draft's.
                for key in ('requestedModel', 'receivedAtMs', 'missing'):
                    self.writer.event.pop(key, None)
                self.writer.event.update({key: value for key, value in retained.items()
                                          if key not in ('type', 'seq', 'time', 'data')})
                self.writer.event['native']['record'] = record
                self.writer.finish(content=content)
            else:
                # Permission, error, cancellation and tool boundaries cannot be
                # merged through. Keep the received partial message explicitly.
                retained['seq'] += 1
                self.writer.finish(content=[], interrupted=True, following=[retained])
            self.writer = None
        else:
            self.store.append(retained, source=self.source, position=position)
        if event.get('type') == 'message_start' and record.get('parent_tool_use_id') is None:
            message = event.get('message', {})
            self.message_id = message.get('id') or self.source + ':' + str(position)
            model = message.get('model')
            self.observed_model = model if isinstance(model, str) and model and model != '<synthetic>' else None
        elif record.get('type') in {'assistant', 'result'} and record.get('parent_tool_use_id') is None:
            self.observed_model = None

    def message(self, model: str) -> dict:
        """Build a projection only for a model observed on the native channel."""
        return {'id': self.message_id, 'role': 'assistant', 'content': [],
                'source': {'kind': 'model', 'provider': self.provider, 'model': model}}

    def close(self) -> None:
        """Keep received partial text after interruption rather than lose the draft."""
        if self.writer:
            self.writer.finish(content=[], interrupted=True)
            self.writer = None
