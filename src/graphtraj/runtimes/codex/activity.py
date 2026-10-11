"""Readable Codex rollout messages, calls, results and token-count observations."""
from graphtraj.runtimes.activity import fingerprint, text_content, usage_fact


def project(record: dict, context: dict) -> list[dict]:
    """Interpret recorded rollout items without exposing encrypted reasoning or metadata."""
    payload = record.get('payload', {})
    kind = payload.get('type')
    if record.get('type') == 'session_meta':
        from graphtraj.runtimes.codex.session_entry import session_source

        context.update(native_session=payload.get('id'), source_kind=session_source(payload))
        return []
    if record.get('type') == 'turn_context':
        context.update(model=payload.get('model'), turn_id=payload.get('turn_id'), cwd=payload.get('cwd'))
        return []
    if record.get('type') == 'event_msg' and kind == 'task_started':
        if payload.get('turn_id') != context.get('turn_id'):
            # A new turn must supply its own project; the previous cwd is not evidence.
            context.update(cwd=None, model=None)
        context['turn_id'] = payload.get('turn_id')
    base = {'model': context.get('model'), 'turn_id': context.get('turn_id'), 'cwd': context.get('cwd'),
            'native_session': context.get('native_session'), 'source_kind': context.get('source_kind')}
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
        total = info.get('total_token_usage')
        previous = context.get('total')
        if isinstance(total, dict):
            # Even an incomplete observation is the native baseline for later records.
            context['total'] = total
        raw = info.get('last_token_usage')
        if not isinstance(raw, dict):
            return []
        # Codex exposes a cumulative counter rather than a provider request ID.
        # A changed counter identifies a usage observation; identical replayed
        # counters must never be charged twice. Do not invent a provider ID.
        observation = fingerprint(total) if total else None
        usage = usage_fact(raw, 'codex', f'counter:{observation}' if observation else None, 'snapshot')
        usage.update(cumulative=total, previous_cumulative=previous, observation_id=observation,
                     identity_basis='native-cumulative-counter',
                     coverage='Call identity uses the native cumulative counter; provider request ID is not recorded.')
        return [{**base, 'kind': 'usage', 'usage': usage}]
    if record.get('type') == 'event_msg' and kind in {'task_started', 'task_complete', 'turn_aborted', 'error'}:
        return [{**base, 'kind': 'work', 'text': kind, 'details': payload}]
    return []
