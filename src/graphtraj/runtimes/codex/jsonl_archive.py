"""Collect an owned Codex rollout through the optional JSONL archive interface.

Response items keep the rollout's order. Uninterpreted history changes remain
required native records, so messages() refuses incomplete reconstruction.
"""

from copy import deepcopy
import json
from pathlib import Path

from graphtraj.sessions.archive import SessionArchive
from graphtraj.sessions.protocol import retain_native
from graphtraj.runtimes.codex.session_archive import _attachments, _timestamp


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
        content = _content(item['content'])
    elif kind in {'function_call', 'custom_tool_call'}:
        argument_field = 'arguments' if kind == 'function_call' else 'input'
        if not all(isinstance(item.get(key), str) for key in ('call_id', 'name', argument_field)):
            return event
        role = 'assistant'
        content = [{'type': 'tool-call', 'id': item['call_id'], 'name': item['name'],
                    'arguments': item[argument_field]}]
    elif kind in {'function_call_output', 'custom_tool_call_output'}:
        role = 'tool'
        output = item['output']
        content = [{'type': 'text', 'text': output}] if isinstance(output, str) else _content(output)
        source = {'kind': 'tool', 'callId': item['call_id']}
    elif kind == 'reasoning':
        role = 'assistant'
        content = [{'type': 'reasoning', 'text': block['text']}
                   for block in item.get('summary', []) if isinstance(block.get('text'), str)]
        if item.get('encrypted_content') is not None:
            content.append({'type': 'graphtraj/encrypted', 'value': item['encrypted_content'],
                            'nativePath': 'payload.encrypted_content'})
    if content is None:
        return event
    if role == 'assistant':
        source = {'kind': 'model', 'model': '', 'provider': ''}
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
    ) -> None:
        """Capture the source boundary without reading any other native Session."""
        self.archive = archive
        self.agent = agent
        self.session = session
        self.id = 'codex:' + session
        try:
            self.activation = rollout.stat().st_size if rollout is not None else 0
        except FileNotFoundError:
            self.activation = 0
        self.header: dict | None = None

    def collect(self, rollout: Path) -> None:
        """Publish complete records in native order, retaining unsupported history."""
        # Mapping requires the metadata, even when saving is currently off.
        # The shared archive checks the current policy before every write.
        with rollout.open('rb') as stream:
            first = stream.readline()
            if not first.endswith(b'\n'):
                return
            metadata_record = json.loads(first)
            metadata = metadata_record.get('payload', {})
            if metadata_record.get('type') != 'session_meta' or metadata.get('id') != self.session:
                raise ValueError('Codex rollout does not match the owned Session.')
            if self.header is None:
                created = _timestamp(metadata.get('timestamp') or metadata_record.get('timestamp'))
                self.header = {
                    'version': 4, 'id': self.id, 'createdAt': created if created is not None else 0,
                    'isSeeded': False, 'graphtraj': {
                        'version': 1, 'projectId': str(self.archive.root), 'agentId': self.agent,
                        'taskIds': [], 'native': {'runtime': 'codex', 'sessionId': self.session,
                            'locator': str(rollout), 'source': metadata.get('source')},
                        'missing': [] if created is not None else [{
                            'path': 'createdAt', 'reason': 'Unknown native time; zero is a placeholder.',
                        }],
                    },
                }
                if metadata.get('forked_from_id'):
                    self.header['parentSession'] = 'codex:' + metadata['forked_from_id']
                    self.header['graphtraj']['missing'].append({
                        'path': 'inheritedPrefix', 'reason': 'Native fork prefix has not been resolved.',
                    })
                self.archive.map_session(self.header)
            store = self.archive.store(self.id)
            if store is None:
                self.activation = rollout.stat().st_size
                return
            # Keep records collected on earlier activations even without backfill.
            existing = set()
            after = -1
            while True:
                page = store.page(after)
                existing.update(event['graphtraj']['native']['locator'] for event in page['events'])
                if not page['has_more']:
                    break
                after = page['after']
            events = []
            excluded = None
            stream.seek(0)
            while True:
                start = stream.tell()
                line = stream.readline()
                if not line.endswith(b'\n'):
                    break
                locator = f'byte:{start}'
                if start < self.activation and not self.archive.backfill_history and locator not in existing:
                    if excluded is None:
                        excluded = locator
                    continue
                record = json.loads(line)
                instant = _timestamp(record.get('timestamp'))
                event = retain_native('codex', record, session_id=self.session, locator=locator,
                    seq=len(events), time=instant if instant is not None else 0)
                event['graphtraj']['missing'] = [] if instant is not None else [{
                    'path': 'time', 'reason': 'Unknown native time; zero is a placeholder.',
                }]
                if record.get('type') == 'response_item':
                    event = _response(record, event, self.session, locator)
                elif record.get('type') in {'session_meta', 'turn_context'} or (
                    record.get('type') == 'event_msg' and record.get('payload', {}).get('type') in {
                        'token_count', 'task_started', 'task_complete', 'thread_settings_applied',
                        'user_message', 'agent_message', 'agent_reasoning',
                    }
                ):
                    event['type'] = 'codex/' + record['type']
                    event['ignorable'] = True
                    event['graphtraj']['native']['record'] = deepcopy(record)
                event['graphtraj']['attachments'] = _attachments(store, record)
                events.append(event)
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
                store.checkpoint(gap, source='history-excluded', position=self.activation)
            source = 'rollout:history' if self.archive.backfill_history else 'rollout'
            store.publish(events, source=source, position=stream.tell() - len(line))
