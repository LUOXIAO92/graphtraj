"""Readable DSH v4 Session records; embedded stream usage is never added twice."""
from graphtraj.runtimes.activity import text_content, usage_fact


def project(record: dict, context: dict) -> list[dict]:
    """Interpret native event coordinates, preserving stream/final distinctions."""
    kind = record.get('type')
    data = record.get('data', {})
    if kind == 'model/selection':
        context.update(model=data.get('model'), provider=data.get('provider'))
        return []
    coordinate = (data.get('turn'), data.get('step'))
    if all(value is not None for value in coordinate):
        if coordinate != context.get('coordinate'):
            context.update(coordinate=coordinate, attempt=0)
        if kind == 'llm/retry-started':
            context['attempt'] = data.get('retry', 0)
    call = (f"{data['turn']}:{data['step']}:{context.get('attempt', 0)}"
            if 'turn' in data and 'step' in data else None)
    base = {'model': context.get('model'), 'provider': context.get('provider'),
            'turn_id': data.get('turn'), 'step': data.get('step'), 'native_sequence': record.get('seq')}
    if kind in {'assistant/message', 'assistant/attempt', 'user/message'}:
        message = data if kind == 'user/message' else data.get('message', {})
        source = message.get('source', {})
        base.update(model=source.get('model', base['model']), provider=source.get('provider', base['provider']))
        events = [{**base, 'kind': 'message', 'role': message.get('role'),
                   'text': text_content(message.get('content')), 'phase': 'final'}]
        if isinstance(data.get('usage'), dict):
            events.append({**base, 'kind': 'usage', 'usage': usage_fact(data['usage'], 'dsh', call, 'final')})
        return events
    if kind == 'assistant/chunk':
        chunk = data.get('chunk', {})
        if isinstance(chunk.get('usage'), dict):
            return [{**base, 'kind': 'usage', 'usage': usage_fact(chunk['usage'], 'dsh', call, 'stream')}]
        if isinstance(chunk.get('text'), str):
            return [{**base, 'kind': 'message', 'role': 'assistant', 'text': chunk['text'], 'phase': 'stream'}]
    if kind == 'tool/call':
        return [{**base, 'kind': 'tool', 'phase': 'call', 'call_id': data.get('callId'),
                 'name': data.get('name'), 'arguments': data.get('arguments')}]
    if kind == 'tool/result':
        message = data.get('message', {})
        return [{**base, 'kind': 'tool', 'phase': 'result',
                 'call_id': message.get('source', {}).get('callId', data.get('callId')),
                 'result': message.get('content', data.get('content')), 'error': data.get('error', data.get('isError')) or any(
                     block.get('isError') for block in message.get('content', []) if isinstance(block, dict))}]
    if kind in {'tool/code-dispatch', 'tool/code-dispatch-start'}:
        return [{**base, 'kind': 'tool', 'phase': 'result' if kind == 'tool/code-dispatch' else 'call',
                 'call_id': data.get('subCallId'), 'name': data.get('name'),
                 'result': data.get('content'), 'error': data.get('isError'),
                 'details': {key: data[key] for key in ('rootCallId', 'parentCallId') if key in data}}]
    if kind in {'turn/start', 'turn/end', 'llm/retry', 'llm/retry-started', 'command/done'}:
        return [{**base, 'kind': 'work', 'text': kind, 'details': data}]
    return []
