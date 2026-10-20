"""Collect an owned Codex rollout through the optional JSONL archive interface.

Response items keep the rollout's order. Uninterpreted history changes remain
required native records, so messages() refuses incomplete reconstruction.
"""

from copy import deepcopy
import json
import re
from xml.etree import ElementTree
from pathlib import Path
from typing import BinaryIO

from agent_swarm.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from agent_swarm.sessions.protocol import SURFACE_TYPES, native_record, retain_native
from .codex_values import _attachments, _timestamp


class NativeInputError(ValueError):
    """Native hook input or rollout bytes that could not be read or parsed.

    Only this failure class names a missing input rather than an identity
    decision; identity and association refusals remain ordinary errors.
    """


def rollout_record(line: str | bytes, path: Path, offset: int) -> dict:
    """Parse one native rollout line, naming its file and byte offset on failure."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise NativeInputError(f'Codex rollout {path} has no valid JSON record at byte {offset} '
                               f'({len(line)} bytes read): {error}') from error
    if not isinstance(record, dict):
        raise NativeInputError(f'Codex rollout {path} has a non-object record at byte {offset}.')
    return record


def _content(blocks: list[dict]) -> list[dict]:
    """Map native text blocks and retain all other content without guessing."""
    return [{**block, 'type': 'text'} if block.get('type') in {'input_text', 'output_text'}
            else deepcopy(block) for block in blocks]


def _response(record: dict, event: dict, session: str, locator: str) -> dict:
    """Map supported response items; retain unknown items as required evidence."""
    item = record['payload']
    kind = item.get('type')
    role = item.get('role')
    source = {'kind': role}
    content = None
    if kind == 'message' and role in {'user', 'assistant', 'system', 'developer'}:
        if not isinstance(item.get('content'), list):
            return event  # A different native content representation remains explicit evidence.
        content = _content(item['content'])
    elif kind in {'function_call', 'custom_tool_call'}:
        argument_field = 'arguments' if kind == 'function_call' else 'input'
        if not all(isinstance(item.get(key), str) for key in ('call_id', 'name', argument_field)):
            return event
        role = 'assistant'
        content = [{'type': 'tool-call', 'id': item['call_id'], 'name': item['name'],
                    'arguments': item[argument_field]}]
    elif kind in {'function_call_output', 'custom_tool_call_output'}:
        if not isinstance(item.get('call_id'), str):
            # Codex 0.163 also writes host-delivered outputs with only id/name
            # and no originating call; keep them as native evidence.
            return event
        role = 'tool'
        output = item['output']
        if isinstance(output, str):
            content = [{'type': 'text', 'text': output}]
        elif isinstance(output, list):
            content = _content(output)
        else:
            return event  # Preserve a future output envelope as required native evidence.
        source = {'kind': 'tool', 'callId': item['call_id']}
    elif kind in {'reasoning', 'compaction', 'context_compaction'}:
        role = 'assistant'
        content = [{'type': 'reasoning', 'text': block['text']}
                   for block in item.get('summary', []) if isinstance(block.get('text'), str)]
        if item.get('encrypted_content') is not None:
            content.append({'type': 'graphtraj/encrypted', 'value': item['encrypted_content'],
                            'nativePath': 'payload.encrypted_content'})
    elif kind == 'agent_message':
        role = 'assistant'
        content = [{'type': 'codex/agent_message', 'item': deepcopy(item)}]
    if content is None:
        return event
    if kind not in {'reasoning', 'compaction', 'context_compaction'} and item.get('encrypted_content') is not None:
        content.append({'type': 'graphtraj/encrypted', 'value': item['encrypted_content'],
                        'nativePath': 'payload.encrypted_content'})
    if role == 'assistant':
        source = {'kind': 'model', 'model': '', 'provider': ''}
        if kind == 'agent_message':
            source.update(author=item.get('author'), recipient=item.get('recipient'),
                          nativeType='agent_message')
        event['graphtraj']['missing'].extend([
            {'path': 'model', 'reason': 'Response item does not identify the generating model.'},
            {'path': 'provider', 'reason': 'Response item does not identify the generating provider.'},
        ])
    elif role == 'system':
        source = {'kind': 'system-prompt'}
    message = {'id': item.get('id') or f'{session}:{locator}', 'role': role,
               'source': source, 'content': content}
    if role == 'tool':
        message['toolCallId'] = item['call_id']
    data = message if role == 'user' else {'turn': 0, 'step': 0, 'message': message}
    if role == 'assistant':
        data['stream'] = []
    event.update(type='tool/result' if role == 'tool' else role + '/message',
                 surfaceOp='append', data=data)
    event['graphtraj']['native']['record'] = deepcopy(record)
    return event


def _select(events: list[dict], selected: list[int], source: dict) -> None:
    """Keep a native replacement/drop as references, retaining original events."""
    native = source['graphtraj']['native']
    events.append({'type': 'graphtraj/history', 'seq': len(events), 'time': source['time'],
                   'data': {'eventSeqs': selected}, 'graphtraj': {
                       'version': 1, 'native': {
                           'runtime': 'codex', 'sessionId': native['sessionId'],
                           'locator': native['locator'] + '/history',
                       },
                   }})


def _metadata(event: dict, record: dict) -> None:
    """Retain a non-message native record exactly, without putting it in messages."""
    event.update(type='codex/' + record['type'], ignorable=True, data={})
    event['graphtraj']['native']['record'] = deepcopy(record)


def _compaction(events: list[dict], event: dict, store: JsonlSessionStore) -> bool:
    """Apply the native replacement array, including an empty replacement.

    Codex persists ResponseItems and replacement_history_metadata in parallel
    arrays. Old compactions lacking a replacement do not establish exact items.
    """
    record = native_record(event)
    payload = record['payload']
    replacement = payload.get('replacement_history')
    if not isinstance(replacement, list):
        return False
    metadata = payload.get('replacement_history_metadata')
    if metadata is not None and len(metadata) != len(replacement):
        raise ValueError('Native replacement history and metadata lengths differ.')
    _metadata(event, record)
    event['graphtraj']['attachments'] = _attachments(store, record)
    events.append(event)
    selected = []
    for index, item in enumerate(replacement):
        locator = event['graphtraj']['native']['locator'] + f'/replacement_history/{index}'
        source = retain_native('codex', item, session_id=event['graphtraj']['native']['sessionId'],
                               locator=locator, seq=len(events), time=0)
        source['graphtraj']['missing'] = [{
            'path': 'time', 'reason': 'Inherited item creation time is not supplied by compaction.',
        }]
        mapped = _response({'payload': item}, source, event['graphtraj']['native']['sessionId'], locator)
        mapped['graphtraj']['native']['record'] = deepcopy(item)
        if metadata is not None:
            mapped['graphtraj']['native']['metadata'] = deepcopy(metadata[index])
        mapped['graphtraj']['attachments'] = _attachments(store, item)
        if mapped['type'] in SURFACE_TYPES:
            selected.append(mapped['seq'])
        events.append(mapped)
    _select(events, selected, event)
    return True


# Codex 0.163 context fragment boundaries; these are parsing rules, not prompts.
_USER_CONTEXT = (
    ('# AGENTS.md instructions', '</INSTRUCTIONS>'),
    ('<environment_context>', '</environment_context>'),
    ('<user_shell_command>', '</user_shell_command>'),
    ('<turn_aborted>', '</turn_aborted>'),
    ('<subagent_notification>', '</subagent_notification>'),
    ('<recommended_plugins>', '</recommended_plugins>'),
    ('<agent_message_board_notification>', '</agent_message_board_notification>'),
    ('<goal_context>', '</goal_context>'),
    ('<additional_context>', '</additional_context>'),
    ('<skill>', '</skill>'),
)
_DEVELOPER_CONTEXT = (
    '<permissions instructions>', '<model_switch>', '<managed_developer_instructions>',
    '<persistent_mode>', '<apps_instructions>', '<collaboration_mode>', '<multi_agent_role>',
    '<multi_agent_mode>', '<environments_instructions>', '<git_attribution>',
    '<plugins_instructions>', '<realtime_conversation>', '<skills_instructions>', '<tools>',
    '<personality_spec>', '<token_budget>', '<context_window>', '<context_window_guidance>',
    '<rollout_budget>',
)
_SUMMARY_PREFIX = (
    'Another language model started to solve this problem and produced a summary of its thinking process. '
    'You also have access to the state of the tools that were used by that language model. '
    'Use this to build on the work that has already been done and avoid duplicating work. '
    'Here is the summary produced by the other language model, use the information in this summary '
    'to assist with your own analysis:'
)


def _item(event: dict) -> dict:
    """Read the native response item, including one nested in a compaction."""
    native = event.get('graphtraj', {}).get('native', {})
    if 'modelItem' in native:
        return deepcopy(native['modelItem'])
    record = native_record(event)
    return record['payload'] if record.get('type') == 'response_item' else record


def _contextual(item: dict) -> bool:
    """Recognize native contextual user/developer fragments for rollback cuts."""
    for block in item.get('content', []):
        if block.get('type') != 'input_text':
            continue
        text = block['text'].strip()
        if item.get('role') == 'developer':
            if text.lower().startswith(_DEVELOPER_CONTEXT):
                return True
        elif any(text.startswith(start) and text.endswith(end) for start, end in _USER_CONTEXT):
            return True
        elif re.fullmatch(r'<codex_internal_context source="[a-z][a-z0-9_]*">[\s\S]*</codex_internal_context>', text):
            return True
        elif text.startswith(('Warning: The maximum number of unified exec processes you can keep open is',
                              'Warning: Your account was flagged for potentially high-risk cyber activity')):
            return True
        elif text.startswith('Warning: apply_patch was requested via ') and text.endswith(
            'Use the apply_patch tool instead of exec_command.'
        ):
            return True
        elif text.startswith('<hook_prompt'):
            try:
                fragment = ElementTree.fromstring(text)
                if fragment.tag == 'hook_prompt' and fragment.get('hook_run_id', '').strip():
                    return True
            except ElementTree.ParseError:
                pass
    return False


def _boundary(item: dict) -> bool:
    """Recognize a native instruction boundary rather than every user-role item."""
    if item.get('role') == 'assistant' and len(item.get('content', [])) == 1:
        block = item['content'][0]
        if block.get('type') in {'input_text', 'output_text'}:
            try:
                communication = json.loads(block['text'])
            except (ValueError, TypeError):
                communication = None
            if (isinstance(communication, dict)
                    and all(isinstance(communication.get(key), str) for key in ('author', 'recipient', 'content'))
                    and type(communication.get('trigger_turn')) is bool):
                return True
    return item.get('type') == 'agent_message' or (
        item.get('role') == 'user' and not _contextual(item)
        and not any(block.get('text', '').startswith(_SUMMARY_PREFIX + '\n')
                    for block in item.get('content', []))
    )


def _drop_turns(events: list[dict], surface: list[int], count: int, cause: dict) -> list[int]:
    """Replay native rollback by instruction boundaries, keeping pre-turn context.

    The native acceptance order can remove an earlier assistant output generated
    for a removed input; it is not a timestamp and is never used for sorting.
    """
    if type(count) is not int or count < 0:
        raise ValueError('Invalid native rollback count.')
    boundaries = [index for index, ref in enumerate(surface) if _boundary(_item(events[ref]))]
    if count and boundaries:
        cut = boundaries[max(0, len(boundaries) - count)]
        removed = events[surface[cut]]
        native = removed['graphtraj']['native']
        metadata = native.get('metadata', native_record(removed).get('metadata', {})) or {}
        order = metadata.get('user_input_order')
        while cut > boundaries[0] and _contextual(_item(events[surface[cut - 1]])):
            cut -= 1
        surface = surface[:cut]
        if order is not None:
            kept = []
            for ref in surface:
                candidate = events[ref]
                item = _item(candidate)
                native = candidate['graphtraj']['native']
                metadata = native.get('metadata', native_record(candidate).get('metadata', {})) or {}
                candidate_order = metadata.get('user_input_order')
                if (item.get('role') == 'assistant' or item.get('type') == 'function_call') and (
                    candidate_order is not None and candidate_order >= order
                ):
                    continue
                kept.append(ref)
            surface = kept
        passthrough = _item(removed).get('internal_chat_message_metadata_passthrough') or {}
        turn = passthrough.get('turn_id')
        if cut == boundaries[0] and turn is not None:
            kept = []
            for ref in surface:
                item = _item(events[ref])
                passthrough = item.get('internal_chat_message_metadata_passthrough') or {}
                if item.get('role') == 'developer' and passthrough.get('turn_id') == turn:
                    indices = [index for index, block in enumerate(item['content'])
                               if not (block.get('type') == 'input_text' and
                                       block.get('text', '').strip().startswith(('<model_switch>', '<persistent_mode>')))]
                    if not indices:
                        continue
                    if len(indices) != len(item['content']):
                        item['content'] = [item['content'][index] for index in indices]
                        kinds = passthrough.get('content_item_kinds')
                        if isinstance(kinds, list) and len(kinds) > max(indices):
                            passthrough['content_item_kinds'] = [kinds[index] for index in indices]
                        ref = _retained_developer(events, ref, item, cause)
                kept.append(ref)
            surface = kept
    return surface


def _retained_developer(events: list[dict], ref: int, item: dict, cause: dict) -> int:
    """Keep the native rollback's surviving developer fragments with provenance."""
    original = events[ref]
    native = cause['graphtraj']['native']
    locator = native['locator'] + '/retained_developer/' + original['graphtraj']['native']['locator']
    existing = next((event['seq'] for event in events
                     if event.get('graphtraj', {}).get('native', {}).get('locator') == locator
                     and event['graphtraj']['native']['sessionId'] == native['sessionId']), None)
    if existing is not None:
        return existing
    event = retain_native('codex', native_record(original), session_id=native['sessionId'],
                          locator=locator, seq=len(events), time=0)
    event['graphtraj']['missing'] = [{'path': 'time', 'reason': 'Derived retained context has no new creation time.'}]
    event = _response({'payload': item}, event, native['sessionId'], locator)
    event['graphtraj']['native'].update(record=native_record(original), modelItem=item,
                                      derivedFrom=original['graphtraj']['native']['locator'])
    events.append(event)
    return event['seq']


def _rollback(events: list[dict], event: dict) -> None:
    """Select the surviving compaction before replaying native rollback markers.

    The 0.163 paginated/window checkpoint bounds replay unconditionally. Older
    checkpoints are selected from surviving reverse turn segments, so a removed
    turn's compaction cannot erase the earlier user boundary needed by rollback.
    """
    original = []
    for candidate in [*events, event]:
        native = candidate.get('graphtraj', {}).get('native', {})
        if ('/replacement_history/' in native.get('locator', '') or 'derivedFrom' in native
                or candidate['type'] == 'graphtraj/history'):
            continue
        if candidate['type'] != 'graphtraj/native' and 'record' not in native:
            continue
        record = native_record(candidate)
        if record.get('type') in {'session_meta', 'response_item', 'compacted', 'event_msg',
                                  'inter_agent_communication'}:
            original.append((candidate, record))
    latest = next(((candidate, record) for candidate, record in reversed(original)
                   if record['type'] == 'compacted'), None)
    paginated = any(record['type'] == 'session_meta' and record['payload'].get('history_mode') == 'paginated'
                    for _, record in original)
    checkpoint = None
    if latest is not None:
        payload = latest[1]['payload']
        if (isinstance(payload.get('replacement_history'), list) and payload.get('window_number') is not None
                and (paginated or payload.get('resume_metadata') is not None)):
            checkpoint = latest[0]['seq']
    if checkpoint is None:
        pending = 0
        has_input = False
        segment_checkpoint = None
        for candidate, record in reversed(original):
            kind = record['type']
            payload = record.get('payload', {})
            if kind == 'compacted' and isinstance(payload.get('replacement_history'), list):
                if segment_checkpoint is None:
                    segment_checkpoint = candidate['seq']
            elif kind in {'response_item', 'inter_agent_communication'}:
                has_input = has_input or kind == 'inter_agent_communication' or _boundary(payload)
            elif kind == 'event_msg':
                subtype = payload.get('type')
                if subtype == 'thread_rolled_back':
                    pending += payload['num_turns']
                elif subtype == 'user_message':
                    has_input = True
                elif subtype in {'task_started', 'turn_started'}:
                    if pending == 0 and segment_checkpoint is not None:
                        checkpoint = segment_checkpoint
                        break
                    if pending and has_input:
                        pending -= 1
                    has_input = False
                    segment_checkpoint = None
        else:
            if pending == 0:
                checkpoint = segment_checkpoint
    surface = []
    if checkpoint is not None:
        native = events[checkpoint]['graphtraj']['native']
        prefix = native['locator'] + '/replacement_history/'
        surface = [candidate['seq'] for candidate in events
                   if candidate['type'] in SURFACE_TYPES
                   and candidate['graphtraj']['native']['sessionId'] == native['sessionId']
                   and candidate['graphtraj']['native']['locator'].startswith(prefix)]
    for candidate, record in original:
        if checkpoint is not None and candidate['seq'] <= checkpoint:
            continue
        if record['type'] in {'response_item', 'inter_agent_communication'} and candidate['type'] in SURFACE_TYPES:
            surface.append(candidate['seq'])
        elif record['type'] == 'event_msg' and record['payload'].get('type') == 'thread_rolled_back':
            surface = _drop_turns(events, surface, record['payload']['num_turns'], candidate)
    _metadata(event, native_record(event))
    event['seq'] = len(events)
    events.append(event)
    _select(events, surface, event)


def _append_record(
    events: list[dict],
    record: dict,
    session: str,
    locator: str,
    store: JsonlSessionStore,
) -> None:
    """Map one native record and its explicit history operation in source order."""
    instant = _timestamp(record.get('timestamp'))
    event = retain_native('codex', record, session_id=session, locator=locator,
                          seq=len(events), time=instant if instant is not None else 0)
    event['graphtraj']['missing'] = [] if instant is not None else [{
        'path': 'time', 'reason': 'Unknown native time; zero is a placeholder.',
    }]
    if instant is not None:
        event['graphtraj']['native']['timeField'] = 'timestamp (rollout record)'
    if type(record.get('ordinal')) is int:
        event['graphtraj']['native']['ordinal'] = record['ordinal']
    kind = record.get('type')
    if kind == 'response_item':
        item = record['payload']
        if (item.get('role') == 'system' or item.get('type') == 'compaction_trigger'
                or (item.get('type') == 'configuration_update'
                    and not (record.get('metadata') or {}).get('harness_authored_configuration'))):
            _metadata(event, record)  # Codex is_api_message excludes raw system items.
        else:
            event = _response(record, event, session, locator)
    elif kind == 'inter_agent_communication':
        communication = record['payload']
        content = [{'type': 'input_text', 'text': communication['content']}]
        if communication.get('encrypted_content') is not None:
            message_type = 'NEW_TASK' if communication['trigger_turn'] else 'MESSAGE'
            content = [
                {'type': 'input_text', 'text':
                    f'Message Type: {message_type}\nTask name: {communication["recipient"]}\n'
                    f'Sender: {communication["author"]}\nPayload:\n'},
                {'type': 'encrypted_content', 'encrypted_content': communication['encrypted_content']},
            ]
        item = {'type': 'agent_message', 'id': communication.get('id'),
                'author': communication['author'], 'recipient': communication['recipient'],
                'content': content, 'internal_chat_message_metadata_passthrough':
                    communication.get('internal_chat_message_metadata_passthrough')}
        event = _response({'payload': item}, event, session, locator)
        event['graphtraj']['native'].update(record=deepcopy(record), modelItem=item)
    elif kind == 'compacted' and _compaction(events, event, store):
        return
    elif kind == 'event_msg' and record.get('payload', {}).get('type') == 'thread_rolled_back':
        _rollback(events, event)
        return
    elif kind in {
        'session_meta', 'turn_context', 'retained_context', 'world_state',
        'token_usage_record', 'security_risk_score', 'inter_agent_communication_metadata',
        'realtime_item', 'event_msg',
    }:
        _metadata(event, record)
    event['graphtraj']['attachments'] = _attachments(store, record)
    events.append(event)


class CodexJsonlArchive:
    """Read only the Runtime-owned path supplied for this Agent's Session.

    The activation byte boundary distinguishes old history from new records.
    Saving/backfill choices are owned by the supplied archive. Notifications
    may wake collection, but never supply canonical ordering or timestamps.
    """

    def __init__(
        self,
        archive: SessionArchive,
        agent: str,
        session: str,
        rollout: Path | None,
        *,
        new_session: bool = False,
        task_ids: tuple[str, ...] = (),
    ) -> None:
        """Capture the source boundary without reading any other native Session."""
        self.archive = archive
        self.agent = agent
        self.session = session
        self.id = archive.native_id('codex', session)
        self.task_ids = task_ids
        self.parent_archive: Path | None = None
        try:
            self.activation = rollout.stat().st_size if rollout is not None else 0
        except FileNotFoundError:
            self.activation = 0
        if new_session:
            self.activation = 0
        self.header: dict | None = None

    def collection_key(self) -> tuple:
        """Notice policy changes even while the native file itself is unchanged."""
        try:
            configuration = (self.archive.root / 'config.yml').stat()
            revision = (configuration.st_size, configuration.st_mtime_ns)
        except FileNotFoundError:
            revision = None
        try:
            parent_revision = self.parent_archive.stat().st_mtime_ns if self.parent_archive else None
        except FileNotFoundError:
            parent_revision = None
        return (revision, parent_revision, self.archive.save_normalized_sessions, self.archive.backfill_history)

    def _seed(self, store: JsonlSessionStore, stream: BinaryIO, metadata: dict) -> tuple[list[dict], int] | None:
        """Resolve the native exclusive inheritance cut without scanning Runtime Home."""
        if self.activation and not self.archive.backfill_history:
            return None
        base = metadata.get('history_base')
        events = []
        position = 0
        if isinstance(base, dict):
            self.parent_archive = archive_path(self.archive.root, self.archive.native_id('codex', base['thread_id']))
            if not self.parent_archive.is_file():
                return None
            parent = JsonlSessionStore(self.parent_archive)
            if max(parent.position('rollout'), parent.position('rollout:history')) < base['end_byte_offset']:
                return None
            after = -1
            ordinals = set()
            finished = False
            while not finished:
                page = parent.page(after)
                for original in page['events']:
                    native = original['graphtraj']['native']
                    ordinal = native.get('ordinal') if native['sessionId'] == base['thread_id'] else None
                    if ordinal is not None and ordinal >= base['end_ordinal_exclusive']:
                        finished = True
                        break
                    if ordinal is not None:
                        ordinals.add(ordinal)
                    events.append(deepcopy(original))
                    for attachment in original.get('graphtraj', {}).get('attachments', []):
                        if attachment.get('storage') == 'session':
                            store.put_attachment(parent.attachment(attachment['sha256']))
                if not page['has_more']:
                    break
                after = page['after']
            if ordinals != set(range(base['end_ordinal_exclusive'])):
                return None
        else:
            stream.seek(0)
            first = stream.readline()
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line.endswith(b'\n'):
                    return None
                record = rollout_record(line, Path(stream.name), start)
                payload = record.get('payload', {})
                if (record.get('type') == 'event_msg' and payload.get('type') == 'thread_settings_applied'
                        and payload.get('thread_id') == self.session):
                    position = start
                    break
                _append_record(events, record, self.session, f'byte:{start}', store)
        events.append({'type': 'session/end-seed', 'seq': len(events), 'time': 0,
                       'data': {'inherited': True}, 'graphtraj': {
                           'version': 1, 'native': {'runtime': 'codex', 'sessionId': self.session,
                                                  'locator': 'fork/end-seed'},
                       }})
        if base is None:
            _append_record(events, rollout_record(first, Path(stream.name), 0), self.session, 'byte:0', store)
        return events, position

    def collect(self, rollout: Path) -> None:
        """Publish complete records in native order, retaining unsupported history."""
        # Mapping requires the metadata, even when saving is currently off.
        # The shared archive checks the current policy before every write.
        with rollout.open('rb') as stream:
            first = stream.readline()
            if not first.endswith(b'\n'):
                return
            metadata_record = rollout_record(first, rollout, 0)
            metadata = metadata_record.get('payload', {})
            if metadata_record.get('type') != 'session_meta' or metadata.get('id') != self.session:
                raise ValueError('Codex rollout does not match the owned Session.')
            if self.header is None:
                created = _timestamp(metadata.get('timestamp') or metadata_record.get('timestamp'))
                self.header = {
                    'version': 4, 'id': self.id, 'createdAt': created if created is not None else 0,
                    'isSeeded': bool(metadata.get('forked_from_id')), 'graphtraj': {
                        'version': 1, 'projectId': str(self.archive.root), 'agentId': self.agent,
                        'taskIds': list(self.task_ids), 'native': {'runtime': 'codex', 'sessionId': self.session,
                            'locator': str(rollout), 'source': metadata.get('source')},
                        'missing': [] if created is not None else [{
                            'path': 'createdAt', 'reason': 'Unknown native time; zero is a placeholder.',
                        }],
                    },
                }
                if metadata.get('forked_from_id'):
                    self.header['parentSession'] = self.archive.native_id('codex', metadata['forked_from_id'])
                self.header = self.archive.native_header('codex', self.session) or self.header
                self.id = self.header['id']
                self.archive.map_session(self.header)
            store = self.archive.store(self.id)
            if store is None:
                self.activation = rollout.stat().st_size
                return

            # Byte cursors and locators belong to one physical rollout file.
            # Codex can continue the same Session in a new file (for example
            # after "Conversation reverted"); that file keeps its own cursor
            # and file-qualified locators instead of the first file's offsets.
            first_file = store.header['graphtraj']['native']['locator']
            prefix     = '' if first_file == str(rollout) else f'{rollout.name}:'

            # The shared writer needs the retained projection, but only unseen
            # native bytes need parsing unless an excluded prefix is requested.
            events = []
            after = -1
            while True:
                page = store.page(after)
                events.extend(page['events'])
                if not page['has_more']:
                    break
                after = page['after']
            position = max(store.position(f'{prefix}rollout'), store.position(f'{prefix}rollout:history'), 0)
            if rollout.stat().st_size < position:
                raise ValueError('Codex rollout was truncated before its committed cursor.')
            if self.archive.backfill_history and store.pending():
                events = []
                position = 0
            if metadata.get('forked_from_id') and not events:
                seeded = self._seed(store, stream, metadata)
                if seeded is None:
                    gap = retain_native('codex', metadata_record, session_id=self.session,
                                        locator='byte:0', seq=0, time=0)
                    gap['graphtraj']['missing'] = [{
                        'path': 'inheritedPrefix', 'reason': 'Native inherited prefix is not yet collected.',
                    }]
                    store.checkpoint(gap, source='fork-prefix', position=rollout.stat().st_size)
                    start = max(len(first), store.position('fork-records'))
                    if self.activation > start:
                        # The activation is a file size observed while Codex may
                        # be appending; the record it splits is earlier history.
                        stream.seek(self.activation - 1)
                        if stream.read(1) != b'\n':
                            stream.readline()
                    else:
                        stream.seek(start)
                    while True:
                        start = stream.tell()
                        line = stream.readline()
                        if not line.endswith(b'\n'):
                            break
                        observed = retain_native('codex', rollout_record(line, rollout, start), session_id=self.session,
                            locator=f'byte:{start}', seq=0, time=0)
                        store.checkpoint(observed, source='fork-records', position=stream.tell())
                    return
                events, position = seeded
            excluded = None
            stream.seek(position)
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line.endswith(b'\n'):
                    break
                locator = f'{prefix}byte:{start}'
                if start < self.activation and not self.archive.backfill_history:
                    if excluded is None:
                        excluded = locator
                    continue
                record = rollout_record(line, rollout, start)
                _append_record(events, record, self.session, locator, store)
            if excluded is not None:
                # Keep an unresolved observation, not a fabricated native event.
                # Later backfill resolves it by the first omitted record's
                # source coordinate. messages() refuses the partial history.
                gap = retain_native('codex', {}, session_id=self.session, locator=excluded,
                                    seq=0, time=0)
                gap['graphtraj']['missing'] = [{
                    'path': 'history', 'reason': 'Historical content excluded by collection policy.',
                }]
                gap['graphtraj']['collectionBoundary'] = self.activation
                store.checkpoint(gap, source=f'{prefix}history-excluded', position=self.activation)
            source = f'{prefix}rollout:history' if self.archive.backfill_history else f'{prefix}rollout'
            store.publish(events, source=source, position=stream.tell() - len(line))
