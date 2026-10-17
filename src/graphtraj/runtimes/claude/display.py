"""Human-only agents communication through Claude's synchronous native hook.

Return systemMessage, never additionalContext, updatedMCPToolOutput or a user
message. The owning CLI renders this in its native informational container.
This hook must not be configured async: async systemMessage has different,
model-directed semantics in Claude Code.
"""
from __future__ import annotations

import json
import sys


def _frame(sender: str, recipient: str, body: str) -> str:
    """Format readable content with explicit direction, without model markup."""
    return f'┌ agents · {sender} → {recipient}\n' + '\n'.join('│ ' + line for line in body.splitlines()) + '\n└'


def display_response(event: dict, seen: set[tuple[str, str]] | None = None) -> dict:
    """Render the successful native exchange, retaining original tool contents.

    ``seen`` belongs to the owning execution, so repeated native hook callbacks
    and repeated observations of its same child result do not draw twice. A
    command-hook caller relies on Claude's native per-tool hook invocation.
    """
    if event.get('hook_event_name') != 'PostToolUse' or event.get('tool_name') != 'mcp__agents__agents':
        return {}
    request = event.get('tool_input')
    response = event.get('tool_response')
    if not isinstance(request, dict) or not isinstance(response, dict) or response.get('isError'):
        return {}
    document = response.get('structuredContent')
    if not isinstance(document, dict) or document.get('error'):
        return {}
    result = document.get('result', {})
    agent = document.get('agent')
    caller = event.get('session_id')
    if not isinstance(agent, str) or not isinstance(caller, str):
        return {}
    seen = seen if seen is not None else set()
    frames = []
    action = request.get('action')
    outgoing = request.get('instruction') if action == 'create' else request.get('message')
    key = ('sent', str(event.get('tool_use_id')))
    if (action in {'create', 'send', 'resume'} and isinstance(outgoing, str)
            and result.get('resumed') is not False and key not in seen):
        frames.append(_frame(caller, agent, outgoing))
        seen.add(key)
    last = result.get('last_result') or {}
    key = (agent, str(last.get('id')))
    if last.get('id') and key not in seen:
        incoming = last.get('last_message')
        if not incoming and last.get('error'):
            incoming = last['error'].get('message')
        if isinstance(incoming, str) and incoming:
            frames.append(_frame(agent, caller, incoming))
            seen.add(key)
    if not frames:
        return {}
    text = '\n\n'.join(frames)
    # Claude caps hook strings at 10,000 characters. Name the display-only cut;
    # the original tool input/result and native archive retain complete content.
    if len(text) > 10000:
        text = text[:9800] + '\n… Display truncated; full text remains in the tool input/result.'
    return {'systemMessage': text}


def main() -> None:
    """Serve one synchronous command hook, without reading or changing config."""
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise ValueError('A native hook object is required.')
    print(json.dumps(display_response(event), ensure_ascii=False))


if __name__ == '__main__':
    main()
