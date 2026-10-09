"""Readable Codex rollout messages, calls, results and token-count observations."""
from graphtraj.runtimes.activity import fingerprint, text_content, usage_fact


def project(record: dict, context: dict) -> list[dict]:
    """Interpret recorded rollout items without exposing encrypted reasoning or metadata."""
    payload = record.get('payload', {})
    kind = payload.get('type')
    if record.get('type') == 'turn_context':
        context.update(model=payload.get('model'), turn_id=payload.get('turn_id'))
        return []
    if record.get('type') == 'event_msg' and kind == 'task_started':
        context['turn_id'] = payload.get('turn_id')
    base = {'model': context.get('model'), 'turn_id': context.get('turn_id')}
    if record.get('type') == 'response_item':
        if kind == 'message':
            return [{**base, 'kind': 'message', 'role': payload.get('role'),
                     'text': text_content(payload.get('content')), 'phase': 'final'}]
        if kind in {'function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call', 'tool_search_call'}:
            return [{**base, 'kind': 'tool', 'call_id': payload.get('call_id', payload.get('id')),
                     'name': payload.get('name', kind), 'phase': 'call',
                     'arguments': payload.get('arguments', payload.get('input', payload.get('action')))}]
        if kind in {'function_call_output', 'custom_tool_call_output', 'local_shell_call_output'}:
            return [{**base, 'kind': 'tool', 'call_id': payload.get('call_id'),
                     'phase': 'result', 'result': payload.get('output')}]
        if kind == 'reasoning':
            summary = text_content(payload.get('summary'))
            return [{**base, 'kind': 'message', 'role': 'work',
                     'text': summary or 'Reasoning content is not readable in this record.'}]
    if record.get('type') == 'event_msg' and kind == 'token_count':
        info = payload.get('info') or {}
        raw = info.get('last_token_usage')
        if not isinstance(raw, dict):
            return []
        # Codex exposes a cumulative counter rather than a provider request ID.
        # A changed counter identifies a usage observation; identical replayed
        # counters must never be charged twice. Do not invent a provider ID.
        total = info.get('total_token_usage')
        observation = fingerprint(total) if total else None
        usage = usage_fact(raw, 'codex', f'counter:{observation}' if observation else None, 'snapshot')
        usage.update(cumulative=total, observation_id=observation,
                     identity_basis='native-cumulative-counter',
                     coverage='Call identity uses the native cumulative counter; provider request ID is not recorded.')
        return [{**base, 'kind': 'usage', 'usage': usage}]
    if record.get('type') == 'event_msg' and kind in {'task_started', 'task_complete', 'turn_aborted', 'error'}:
        return [{**base, 'kind': 'work', 'text': kind, 'details': payload}]
    return []
