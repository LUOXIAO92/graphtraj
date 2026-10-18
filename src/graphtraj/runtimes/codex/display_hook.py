"""Display observed agents communication through Codex's UI-only hook output.

This optional PostToolUse hook neither calls a tool nor adds model context.
Its per-Session cache contains displayed fact identifiers, never message bodies.
The native host owns hook installation, trust and invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import yaml

from agent_swarm.locks import exclusive
from graphtraj.execution.runner_io import write_yaml_durably


def display(event: dict, state_directory: Path) -> dict:
    """Return only new communication as systemMessage; never return model feedback."""
    if (event.get('hook_event_name') != 'PostToolUse'
            or event.get('tool_name') not in {'mcp__graphtraj__agents', 'mcp__agents__agents'}):
        return {}
    request = event.get('tool_input', {})
    response = event.get('tool_response', {})
    if (not isinstance(request, dict) or request.get('action') != 'execute'
            or not isinstance(response, dict) or response.get('isError')):
        return {}
    document = response.get('structuredContent', {})
    if not isinstance(document, dict) or document.get('error'):
        return {}
    record = document.get('result', {})
    agent = document.get('agent')
    session = event.get('session_id')
    call_id = event.get('tool_use_id')
    if (not isinstance(record, dict)
            or not all(isinstance(value, str) and value for value in (agent, session, call_id))):
        return {}
    caller = f'Codex session {session}'
    child = f"{record.get('name') or agent} [{agent}]"
    facts = []
    arguments = request.get('arguments', {})
    if (request.get('feature') in {'create', 'send', 'resume'}
            and document.get('action') == request['feature']
            and record.get('resumed') is not False and isinstance(arguments, dict)):
        body = arguments.get('instruction', arguments.get('message'))
        if isinstance(body, str) and body:
            facts.append((f'send:{call_id}', caller, child, body))
    reply = record.get('last_result')
    if isinstance(reply, dict) and reply.get('id'):
        body = reply.get('last_message')
        if isinstance(body, str) and body:
            facts.append((f"reply:{agent}:{reply['id']}", child, caller, body))
    if not facts:
        return {}

    # Native Session scope prevents another Session's matching IDs suppressing
    # its own display. This cache is optional UI state, not control authority.
    path = state_directory / (hashlib.sha256(session.encode()).hexdigest() + '.yml')
    with exclusive(path.with_suffix('.lock')):
        seen = set(yaml.safe_load(path.read_text()) or []) if path.exists() else set()
        boxes = []
        for identity, sender, recipient, body in facts:
            if identity in seen:
                continue
            boxes.append(f'╭─ agents/MCP · {sender} → {recipient}\n'
                         + '\n'.join('│ ' + line for line in body.splitlines()) + '\n╰─')
            seen.add(identity)
        if not boxes:
            return {}
        write_yaml_durably(path, sorted(seen))
    return {'systemMessage': '\n'.join(boxes)}


def main() -> None:
    """Read one native hook event and emit only the supported UI-warning field."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory', required=True, type=Path)
    options = parser.parse_args()
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError('A native hook event must be an object.')
        result = display(event, options.state_directory)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
        # Exit 1 reports a genuine hook error; unlike exit 2 it does not replace
        # a completed tool result with model feedback in Codex PostToolUse.
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
