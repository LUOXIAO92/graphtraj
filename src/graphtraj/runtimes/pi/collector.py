"""Archive Pi native entries and compact live output without a raw RPC copy.

Native JSONL offsets are replayable. RPC coordinates belong to one connection;
its last committed draft survives disconnect, but Pi cannot replay an unsaved
transport tail. Native messages subsequently supply the durable final content.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
import uuid

from graphtraj.sessions.protocol import retain_native
from graphtraj.sessions.storage import SessionStore, StreamWriter, session_path


def timestamp(record: dict) -> tuple[int, list[dict]]:
    """Use native epoch milliseconds or ISO time, explicitly marking receipt time."""
    value = record.get('timestamp')
    if type(value) is int:
        return value, []
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000), []
        except ValueError:
            pass
    return int(time.time() * 1000), [{'path': 'timestamp', 'reason': 'Native time unavailable; receipt time used.'}]


def has_probabilities(value: object) -> bool:
    """Distinguish actual probability fields from text merely mentioning them."""
    if isinstance(value, dict):
        return any('logprob' in key.lower().replace('_', '') or key.lower() == 'probabilities'
                   or has_probabilities(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_probabilities(item) for item in value)
    return False


def map_message(event: dict) -> dict:
    """Project understood Pi messages while retaining the complete original record.

    Branch and compaction entries remain opaque: their native parent IDs must
    not be guessed into DSH surface replacement ranges. Local turn/step values
    identify the mapping only, not provider requests or active branch position.
    """
    record = event['data']['record']
    native = record.get('message', {})
    if not isinstance(native, dict):
        return event
    role = native.get('role') if record.get('type') == 'message' else None
    if role not in {'user', 'assistant', 'toolResult'}:
        return event
    if role == 'assistant' and not all(isinstance(native.get(key), str) for key in ('model', 'provider')):
        return event
    if role == 'toolResult' and not isinstance(native.get('toolCallId'), str):
        return event
    blocks = native.get('content')
    if isinstance(blocks, str):
        blocks = [{'type': 'text', 'text': blocks}]
    if not isinstance(blocks, list):
        return event
    content = []
    for block in blocks:
        if not isinstance(block, dict):
            return event
        kind = block.get('type')
        if kind == 'text' and isinstance(block.get('text'), str):
            content.append({'type': 'text', 'text': block['text']})
        elif kind == 'thinking' and isinstance(block.get('thinking'), str):
            content.append({'type': 'reasoning', 'text': block['thinking']})
        elif kind == 'toolCall' and all(isinstance(block.get(key), str) for key in ('id', 'name')):
            arguments = block.get('arguments')
            content.append({'type': 'tool-call', 'id': block['id'], 'name': block['name'],
                            'arguments': arguments if isinstance(arguments, str) else json.dumps(arguments)})
            if not isinstance(arguments, str):
                event['graphtraj']['missing'].append({'path': 'toolArgumentsText',
                    'reason': 'Pi supplied parsed arguments; JSON text is mapped, original lexical spelling unavailable.'})
        else:
            content.append({'type': 'pi/content', 'record': block})
    message = {'id': record.get('id') or event['graphtraj']['native']['locator'],
               'role': 'tool' if role == 'toolResult' else role, 'content': content,
               'source': {'kind': 'user'}}
    data = {'turn': event['seq'], 'step': 0, 'message': message}
    if role == 'assistant':
        message['source'] = {'kind': 'model', 'provider': native['provider'], 'model': native['model']}
        data['stream'] = []
        if native.get('stopReason') in {'error', 'aborted'}:
            data['interrupted'] = True
        usage = native.get('usage', {})
        if all(type(usage.get(key)) is int and usage[key] >= 0 for key in ('input', 'output')):
            # Pi input is uncached; cache counts are disjoint (Pi Usage contract).
            data['usage'] = {target: usage[source] for source, target in (
                ('input', 'inputTokens'), ('output', 'outputTokens'), ('cacheRead', 'cacheReadTokens'),
                ('cacheWrite', 'cacheWriteTokens'), ('totalTokens', 'totalTokens')) if source in usage}
        event['graphtraj']['missing'].append({'path': '/data/stream',
            'reason': 'Persisted Pi message has no transport stream; live attempts are retained separately when observed.'})
    elif role == 'toolResult':
        message.update(source={'kind': 'tool', 'callId': native['toolCallId']}, toolCallId=native['toolCallId'])
        if isinstance(native.get('isError'), bool):
            message['isError'] = native['isError']
    event['type'] = 'tool/result' if role == 'toolResult' else role + '/message'
    event['data'] = message if role == 'user' else data
    event['surfaceOp'] = 'append'
    event['graphtraj']['native']['record'] = record
    event['graphtraj']['missing'].append({'path': 'coordinates',
        'reason': 'Turn/step and fallback message IDs are collector coordinates; native parentId retains branch topology.'})
    return event


def inherited_prefix(native: Path, parent: Path) -> tuple[str, int]:
    """Locate copied branch entries by native identity/content, not Agent parentage.

    Pi copies entries without changing their IDs. Compare record hashes while
    scanning bounded individual lines; never import the parent's unrelated
    branches into the child or retain a second array of full messages.
    """
    def fingerprint(record: dict) -> bytes:
        """Identify an unchanged native entry independently of JSON whitespace."""
        return sha256(json.dumps(record, sort_keys=True).encode()).digest()

    with parent.open('rb') as stream:
        parent_id = json.loads(stream.readline())['id']
        entries = {fingerprint(json.loads(line)) for line in stream if line.endswith(b'\n')}
    with native.open('rb') as stream:
        stream.readline()
        end = stream.tell()
        while line := stream.readline():
            if not line.endswith(b'\n') or fingerprint(json.loads(line)) not in entries:
                break
            end = stream.tell()
    return 'pi:' + parent_id, end


class PiCollector:
    """Collect one verified Pi Session into a project-owned, portable archive."""

    def __init__(
        self,
        state: Path,
        native: Path,
        session: str,
        *,
        project: str,
        agent: str,
        source: str,
        tasks: list[str] | None = None,
        execution: str | None = None,
        header: dict | None = None,
        parent_sources: set[Path] | None = None,
        attachment_root: Path | None = None,
        source_paths: dict[str, Path] | None = None,
    ) -> None:
        """Open an owned archive, optionally limiting offline source acquisition.

        Migration supplies its associated parent files and project attachment
        root; native paths in content cannot broaden that acquisition scope.
        """
        self.native = native
        self.source_paths = source_paths
        self.attachment_root = (Path(os.path.abspath(attachment_root)) if attachment_root else None)
        self.session = session
        self.state = state.resolve()
        self.project = Path(os.path.abspath(project)) if source_paths is not None else Path(project).resolve()
        self.source = 'rpc:' + (execution or uuid.uuid4().hex)
        self.position = 0
        self.writer: StreamWriter | None = None
        self.snapshots: dict = {}
        if native.is_file():
            with native.open('rb') as stream:
                header = json.loads(stream.readline())
        header = header or {'id': session}
        if header.get('id') != session:
            raise ValueError('Pi collection source belongs to another Session.')
        path = session_path(state, 'pi:' + session)
        if path.exists():
            self.store = SessionStore(path)
            if self.store.header['graphtraj']['native']['sessionId'] != session:
                raise ValueError('Pi archive identity does not match its source.')
        else:
            created, missing = timestamp(header)
            if header.get('type') != 'session':
                missing.append({'path': 'nativeHeader', 'reason': 'Only verified RPC Session identity available; Pi has not persisted its header yet.'})
            metadata = {'version': 1, 'projectId': project, 'agentId': agent,
                        'taskIds': tasks or [], 'source': source,
                        'native': {'runtime': 'pi', 'sessionId': session,
                                   'locator': 'header', 'record': header}, 'missing': missing}
            canonical = {'version': 4, 'id': 'pi:' + session, 'createdAt': created,
                         'isSeeded': False, 'graphtraj': metadata}
            if header.get('cwd'):
                canonical['cwd'] = header['cwd']
            if source in {'child', 'member'}:
                canonical['origin'] = 'subagent'
            if header.get('parentSession'):
                try:
                    parent_path = (Path(os.path.abspath(header['parentSession'])) if source_paths is not None
                                   else Path(header['parentSession']).resolve())
                    if parent_sources is not None and parent_path not in parent_sources:
                        raise ValueError('Native parent is not an associated project source.')
                    captured_parent = source_paths.get(str(parent_path)) if source_paths is not None else parent_path
                    if captured_parent is None:
                        raise ValueError('Native parent source was not captured.')
                    parent, end = inherited_prefix(native, captured_parent)
                    canonical.update(parentSession=parent, isSeeded=True)
                    metadata['native']['inheritedPrefixEnd'] = end
                except (OSError, ValueError, KeyError):
                    missing.append({'path': 'parentSession', 'reason': 'Native parent path retained; inherited prefix unavailable. Canonical log is unseeded, not a claim of no native fork.'})
            self.store = SessionStore.create(path, canonical)
        pending = self.store.pending()
        if pending:
            # A new transport cannot replay the old pipe. Preserve its durable
            # partial attempt before importing native final messages on resume.
            previous = StreamWriter(self.store, pending['source'])
            previous.event['graphtraj']['missing'].append({
                'path': 'transportTail', 'reason': 'Connection ended; bytes after its last checkpoint cannot be replayed by Pi RPC.'})
            self.writer = previous
            self._finish(True)
        self.sync_native()

    def _event(self, record: dict, locator: str) -> dict:
        """Retain native topology and unknown fields without guessing branch surfaces."""
        observed, missing = timestamp(record)
        event = retain_native('pi', record, session_id=self.session, locator=locator,
                              seq=self.store.next_seq, time=observed)
        if not has_probabilities(record):
            missing.append({'path': 'logprobs', 'reason': 'Not exposed in this native record; no probabilities inferred.'})
        attachments = []
        message = record.get('message', {})
        content = message.get('content', []) if isinstance(message, dict) else []
        if isinstance(content, list):
            for index, block in enumerate(content):
                if not isinstance(block, dict) or block.get('type') not in {'file', 'image'}:
                    continue
                path = block.get('path')
                if isinstance(path, str):
                    candidate = Path(path)
                    root = Path(self.store.header.get('cwd') or self.project)
                    root = Path(os.path.abspath(root)) if self.source_paths is not None else root.resolve()
                    if not candidate.is_absolute():
                        candidate = root / candidate
                    candidate = (Path(os.path.abspath(candidate)) if self.source_paths is not None
                                 else candidate.resolve())
                    private = (self.state, self.project / '.graphtraj', self.project / '.codex')
                    # Model-authored paths must not extend a managed Runtime's
                    # filesystem grants through the host-side archive writer.
                    in_scope = self.attachment_root is None or candidate.is_relative_to(self.attachment_root)
                    if in_scope and candidate.is_relative_to(root) and not any(candidate.is_relative_to(p) for p in private):
                        acquired = self.source_paths.get(str(candidate)) if self.source_paths is not None else candidate
                        reference = (self.store.copy_attachment(acquired) if acquired is not None else
                                     {'missing': {'path': str(candidate), 'reason': 'Attachment was not captured.'}})
                    else:
                        reference = {'missing': {'path': path, 'reason': 'Outside the captured Session directories; not acquired.'}}
                    location = f'/message/content/{index}/path'
                    attachments.append({'nativePath': location, **reference})
                    if 'missing' in reference:
                        missing.append({'path': location, 'reason': reference['missing']['reason']})
        if attachments:
            event['graphtraj']['attachments'] = attachments
        event['graphtraj']['missing'] = missing
        return map_message(event)

    def sync_native(self) -> None:
        """Read only complete appended source records and atomically advance offsets."""
        if self.writer is not None or not self.native.is_file():
            return
        source = 'native:' + self.session
        with self.native.open('rb') as stream:
            stream.seek(max(0, self.store.position(source)))
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line or not line.endswith(b'\n'):
                    break
                record = json.loads(line)
                if start == 0 and record.get('id') != self.session:
                    raise ValueError('Pi collection source belongs to another Session.')
                metadata = self.store.header['graphtraj']['native']
                # A known header already lives in the immutable archive header.
                # Deferred native headers still need a log event when they arrive.
                events = [] if start == 0 and metadata['record'].get('type') == 'session' else [
                    self._event(record, 'byte:' + str(start))]
                if stream.tell() == metadata.get('inheritedPrefixEnd'):
                    events.append({'type': 'session/end-seed', 'seq': self.store.next_seq + len(events),
                                   'time': self.store.header['createdAt'], 'data': {'inherited': True}})
                if events:
                    self.store.append_many(events, source=source, position=stream.tell())

    def _start(self) -> None:
        """Start a log-only attempt with explicit local mapping coordinates."""
        if self.writer is not None:
            return
        self.sync_native()
        seq = self.store.next_seq
        event = {'type': 'assistant/attempt', 'seq': seq, 'time': int(time.time() * 1000),
                 'data': {'turn': seq, 'step': 0, 'stream': []},
                 'graphtraj': {'version': 1, 'native': {'runtime': 'pi', 'sessionId': self.session,
                              'locator': self.source + ':attempt:' + str(seq)}, 'missing': [
                     {'path': 'coordinates', 'reason': 'Turn, step, request and message IDs are collector-local, not provider IDs.'},
                     {'path': 'timestamp', 'reason': 'Attempt time is receipt time; native message times remain in retained records.'},
                     {'path': 'transportTail', 'reason': 'Pi RPC has no replay cursor; a hard crash may lose bytes after the last checkpoint.'},
                 ]}}
        # Checkpoint only after all records mapped from one input have been
        # fed. A raw source record must never commit only its metadata prefix.
        self.writer = StreamWriter(self.store, self.source, event, checkpoint_bytes=sys.maxsize)
        self.snapshots = {}

    def _feed(self, record: dict) -> None:
        """Assign ordered compact source coordinates to one semantic stream record."""
        assert self.writer is not None
        self.position += 1
        self.writer.feed(record, self.position)

    def _snapshot(self, message: dict, slot: str) -> None:
        """Retain changed metadata, stripping only known cumulative content fields.

        Authoritative complete blocks remain in message_end/native entries.
        Signatures, ciphertext, usage, probabilities and unknown fields survive
        even if they first appear on an intermediate cumulative snapshot.
        """
        if not isinstance(message, dict):
            return
        metadata = deepcopy(message)
        content = metadata.pop('content', None)
        if isinstance(content, list):
            blocks = []
            for block in content:
                value = deepcopy(block)
                if isinstance(value, dict):
                    removed = {'text': ('text',), 'thinking': ('thinking',),
                               'toolCall': ('arguments', 'partialJson')}.get(value.get('type'), ())
                    for field in removed:
                        value.pop(field, None)
                blocks.append(value)
            metadata['contentMetadata'] = blocks
        elif content is not None:
            metadata['content'] = content
        previous = self.snapshots.get(slot, {})
        changes = {key: value for key, value in metadata.items() if key not in previous or previous[key] != value}
        removed = sorted(set(previous) - set(metadata))
        if changes or removed:
            self._feed({'type': 'pi/snapshot-metadata', 'slot': slot, 'fields': changes, 'removed': removed})
        self.snapshots[slot] = metadata

    def receive(self, event: dict) -> None:
        """Consume actual Pi events; fragments are never copied to an RPC JSONL."""
        kind = event.get('type')
        if kind == 'response':
            return  # Command receipts are retained by Runner, not conversation content.
        if kind == 'message_update':
            self._start()
            update = deepcopy(event.get('assistantMessageEvent', {}))
            self._snapshot(event.get('message', {}), 'message')
            self._snapshot(update.pop('partial', {}), 'partial')
            part = update.get('type')
            extras = {k: v for k, v in event.items() if k not in {'type', 'message', 'assistantMessageEvent'}}
            if extras:
                self._feed({'type': 'pi/update-fields', 'fields': extras})
            if part in {'text_delta', 'thinking_delta', 'toolcall_delta'} and isinstance(update.get('delta'), str):
                index = update['contentIndex']
                extra = {k: v for k, v in update.items() if k not in {'type', 'contentIndex', 'delta'}}
                if extra:
                    self._feed({'type': 'pi/delta-fields', 'fields': extra})
                # Tool argument strings have their own message coordinate and a
                # native toolcall_start/end boundary, never assistant prose.
                message = str(self.writer.event['seq']) + (':tool-arguments' if part == 'toolcall_delta' else '')
                self._feed({'type': 'graphtraj/text-run', 'requestId': self.source,
                            'attemptId': str(self.writer.event['seq']), 'messageId': message,
                            'index': index, 'blockType': 'reasoning' if part == 'thinking_delta' else 'text',
                            'text': update['delta']})
            else:
                if part in {'text_start', 'thinking_start', 'toolcall_start'}:
                    content = event.get('assistantMessageEvent', {}).get('partial', {}).get('content', [])
                    index = update.get('contentIndex')
                    if isinstance(index, int) and 0 <= index < len(content):
                        update['initialBlock'] = content[index]
                # End snapshots repeat the block body; keep an explicit boundary
                # and retain a replacement only if the authoritative text differs.
                if part in {'text_end', 'thinking_end'}:
                    text = ''.join(r['text'] for r in self.writer.event['data']['stream']
                                   if r.get('type') == 'graphtraj/text-run'
                                   and r['index'] == update.get('contentIndex')
                                   and r['blockType'] == ('reasoning' if part == 'thinking_end' else 'text'))
                    if update.get('content') == text:
                        update.pop('content')
                self._feed({'type': 'pi/assistant-event', 'event': update})
            if self.writer.buffered >= 65536 or part not in {'text_delta', 'thinking_delta', 'toolcall_delta'}:
                self.writer.checkpoint()
            return
        if kind == 'message_start' and event.get('message', {}).get('role') == 'assistant':
            if self.writer is not None:
                self._finish(True)
            self._start()
            self._feed({'type': 'pi/message-start', 'event': event})
            self._snapshot(event['message'], 'message')
            self.writer.checkpoint()
            return
        if self.writer is not None:
            self._feed({'type': 'pi/event', 'event': event})
            if kind == 'message_end':
                interrupted = event.get('message', {}).get('stopReason') in {'error', 'aborted'}
                self._finish(interrupted)
                self.sync_native()
            elif kind in {'auto_retry_start', 'agent_end', 'agent_settled', 'turn_end'}:
                self._finish(True)
                self.sync_native()
            else:
                # Semantic boundaries make received partial output durable.
                self.writer.checkpoint()
        else:
            self.position += 1
            self.store.append(self._event(event, self.source + ':' + str(self.position)),
                              source=self.source, position=self.position)
            self.sync_native()

    def _finish(self, interrupted: bool) -> None:
        """Finalize one attempt with explicit probability availability and semantics."""
        assert self.writer is not None
        if has_probabilities(self.writer.event['data']['stream']):
            missing = {'path': 'probabilitySemantics',
                       'reason': 'Native probability fields retained; no raw/sampled distribution or tokenizer alignment inferred.'}
        else:
            missing = {'path': 'logprobs', 'reason': 'Not exposed in the observed Pi stream.'}
        self.writer.event['graphtraj']['missing'].append(missing)
        self.writer.finish(interrupted=interrupted)
        self.writer = None

    def close(self) -> None:
        """Preserve partial output on transport closure and collect final native entries."""
        try:
            if self.writer is not None:
                self._finish(True)
            self.sync_native()
        finally:
            self.store.close()


def collect_stdio() -> None:
    """Collect a verified extension's pipe without registering or replacing Main."""
    from graphtraj.configuration.project_configuration import load_project_configuration
    from graphtraj.execution.runner_status import process_caller_alias
    from graphtraj.runtimes.pi.session_entry import current_connection, session_record, session_source
    from graphtraj.workspace.runner_project import discover_runner_directory
    import os

    cwd = Path.cwd()
    runner = discover_runner_directory(cwd)
    # Managed children are collected host-side, outside their filesystem sandbox.
    if process_caller_alias(runner, os.getpid()) is not None:
        return
    connection = current_connection()
    if connection is None:
        raise ValueError('Pi native Session association is unavailable.')
    initial = json.loads(sys.stdin.readline())
    header, entries = initial.get('header'), initial.get('entries', [])
    if header is None:
        header, entries = session_record(Path(connection['session_file']), connection['session'])
    if header.get('id') != connection['session']:
        raise ValueError('Pi collection source belongs to another Session.')
    source = session_source(header, entries, os.environ)
    if source == 'main':
        from graphtraj.execution.main_finalize import session_binding
        import yaml

        binding = yaml.safe_load(session_binding(cwd, 'pi', connection['session']).read_text())
        if binding['connection'] != connection:
            raise ValueError('Pi SessionStart binding is stale.')
    elif source != 'child':
        raise ValueError('Unknown Pi collection source.')
    configuration = load_project_configuration(cwd)
    collector = PiCollector(configuration.state, Path(connection['session_file']), connection['session'],
                            project=str(configuration.harness_root), agent='pi:' + connection['session'], source=source, header=header)
    print(json.dumps({'ready': True}), flush=True)
    try:
        for line in sys.stdin:
            collector.receive(json.loads(line))
    finally:
        collector.close()
