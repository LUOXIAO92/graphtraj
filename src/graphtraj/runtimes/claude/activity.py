"""Project Claude's native stream records through the existing activity reader."""
from graphtraj.runtimes.activity import text_content, tool_content, usage_fact


def project(record: dict, context: dict) -> list[dict]:
    """Expose final messages, tools and per-invocation usage without double counting."""
    kind = record.get('type')
    if kind == 'system' and record.get('subtype') == 'init':
        context['model'] = record.get('model')
        context['provider'] = record.get('apiProvider')
        return []
    base = {'model': context.get('model'), 'provider': context.get('provider')}
    if kind in {'assistant', 'user'}:
        message = record.get('message', {})
        events = []
        for block in message.get('content', []):
            if block.get('type') == 'tool_use':
                events.append({**base, 'kind': 'tool', 'phase': 'call', 'call_id': block.get('id'),
                               'name': block.get('name'), 'arguments': block.get('input')})
            elif block.get('type') == 'tool_result':
                events.append({**base, 'kind': 'tool', 'phase': 'result',
                               'call_id': block.get('tool_use_id'), 'result': block.get('content'),
                               'content': tool_content(block.get('content')), 'error': block.get('is_error')})
            else:
                events.append({**base, 'kind': 'message', 'role': kind,
                               'text': text_content([block]), 'phase': 'final'})
        return events
    if kind == 'stream_event':
        event = record.get('event', {})
        delta = event.get('delta', {})
        if event.get('type') == 'content_block_delta' and isinstance(delta.get('text'), str):
            return [{**base, 'kind': 'message', 'role': 'assistant', 'phase': 'stream', 'text': delta['text']}]
        return []
    if kind == 'result':
        events = []
        if isinstance(record.get('usage'), dict):
            events.append({**base, 'kind': 'usage', 'usage': usage_fact(
                record['usage'], 'claude', record.get('uuid'), 'final')})
        if record.get('is_error'):
            events.append({**base, 'kind': 'notice', 'text': str(record.get('errors') or record.get('result'))})
        return events
    return []
