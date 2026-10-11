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
            call_id = payload.get('call_id', payload.get('id'))
            name = payload.get('name')
            if call_id and name:
                # Copy on write keeps earlier pagination checkpoints unchanged.
                context['tools'] = {**context.get('tools', {}), call_id: name}
            return [{**base, 'kind': 'tool', 'call_id': call_id,
                     'name': name, 'tool_type': kind, 'phase': 'call',
                     'arguments': payload.get('arguments', payload.get('input', payload.get('action')))}]
        if kind in {'function_call_output', 'custom_tool_call_output', 'local_shell_call_output'}:
            return [{**base, 'kind': 'tool', 'call_id': payload.get('call_id'),
                     'name': context.get('tools', {}).get(payload.get('call_id')),
                     'phase': 'result', 'result': payload.get('output')}]
        if kind == 'reasoning':
            summary = text_content(payload.get('summary'))
            blocks = payload.get('content') or []
            content = text_content([block for block in blocks if isinstance(block, dict)
                                    and block.get('type') in {'reasoning_text', 'text'}])
            readable = '\n\n'.join(part for part in (summary, content) if part.strip())
            availability = 'available' if readable else 'unavailable' if payload.get('encrypted_content') else 'missing'
            return [{**base, 'kind': 'message', 'role': 'reasoning',
                     'availability': availability,
                     'text': readable or ('Reasoning is inaccessible; only encrypted content is recorded.'
                                          if availability == 'unavailable' else 'No reasoning text was recorded.')}]
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
                     scope='latest-response', cumulative_scope='native-session-counter',
                     coverage='Native usage observation: last_token_usage describes the latest response; '
                              'total_token_usage is the cumulative Session counter. Provider request ID is not recorded.')
        return [{**base, 'kind': 'usage', 'usage': usage}]
    if record.get('type') == 'event_msg' and kind in {'task_started', 'task_complete', 'turn_aborted', 'error'}:
        return [{**base, 'kind': 'work', 'text': kind, 'details': payload}]
    return []
