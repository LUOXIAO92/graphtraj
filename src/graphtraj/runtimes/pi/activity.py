"""Readable Pi Session message entries and their native per-message usage."""
from graphtraj.runtimes.activity import text_content, tool_content, usage_fact


def project(record: dict, context: dict) -> list[dict]:
    """Project Pi's persisted messages; keep native message IDs as usage identity."""
    if record.get('type') == 'session':
        from graphtraj.runtimes.pi.session_entry import session_source

        context.update(cwd=record.get('cwd'), native_session=record.get('id'),
                       source_kind=session_source(record, [], {}))
    if record.get('type') in {'compaction', 'branch_summary'}:
        return [{'kind': 'work', 'text': record.get('summary', 'Summary content is unavailable.')} ]
    if record.get('type') != 'message':
        return []
    message = record.get('message', {})
    role = message.get('role')
    base = {'cwd': context.get('cwd'), 'native_session': context.get('native_session'),
            'source_kind': context.get('source_kind'), 'model': message.get('model'), 'provider': message.get('provider'), 'phase': 'final'}
    if role == 'toolResult':
        raw = message.get('content')
        return [{**base, 'kind': 'tool', 'phase': 'result', 'call_id': message.get('toolCallId'),
                 'name': message.get('toolName'), 'result': raw, 'content': tool_content(raw),
                 'error': message.get('isError'), 'details': message.get('details')}]
    events = []
    text = text_content(message.get('content'))
    if text:
        events.append({**base, 'kind': 'message', 'role': role, 'text': text})
    for block in message.get('content', []) if isinstance(message.get('content'), list) else []:
        if block.get('type') == 'toolCall':
            events.append({**base, 'kind': 'tool', 'phase': 'call', 'call_id': block.get('id'),
                           'name': block.get('name'), 'arguments': block.get('arguments')})
    if role == 'assistant' and isinstance(message.get('usage'), dict):
        events.append({**base, 'kind': 'usage',
                       'usage': usage_fact(message['usage'], 'pi', record.get('id'), 'final')})
    if message.get('errorMessage'):
        events.append({**base, 'kind': 'work', 'text': message['errorMessage'], 'error': True})
    return events
