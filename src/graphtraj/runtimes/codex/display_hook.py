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
from typing import Callable

import yaml

from agent_swarm import exclusive_lock
from graphtraj.execution.runner_io import write_yaml_durably


def display(event: dict, state_directory: Path) -> dict:
    """Return only new communication as systemMessage; never return model feedback.

    Besides the agents call itself, any PostToolUse or Stop shows the Session's
    retained ordinary receipts once: completed child executions that this
    Codex Main did not start, kept without a model turn. The project records
    how far each addressed Main's receipts were shown, so no later Main shows
    or is handed them again.
    """
    session = event.get('session_id')
    if event.get('hook_event_name') not in {'PostToolUse', 'Stop'} or not isinstance(session, str) or not session:
        return {}
    receipts, settle = _receipt_facts(event, session)
    facts = _agents_facts(event, session) + receipts
    if not facts:
        return {}
    shown = _show(facts, session, state_directory)
    settle()
    return shown


def _receipt_facts(event: dict, session: str) -> tuple[list[tuple[str, str, str, str]], Callable[[], None]]:
    """Read retained ordinary receipts addressed to this Codex Session's host.

    Also returns how to record, once they are shown, how far each addressed
    Main's receipts were shown.
    """
    from graphtraj.execution.main_continuity import owns_main_root, receipts_shown, retained_receipts, show_receipts
    from graphtraj.execution.runner_models import RunnerError
    from graphtraj.workspace.runner_project import discover_runner_directory

    # The native event names the Main's own working directory; without it there is no project.
    cwd = event.get('cwd')
    if not isinstance(cwd, str) or not cwd:
        return [], lambda: None
    try:
        runner = discover_runner_directory(Path(cwd))
        receipts = retained_receipts(runner)
    except (RunnerError, OSError, ValueError):
        return [], lambda: None
    facts, shown, through = [], {}, {}
    for record, notice in receipts:
        connection = record['parent_connection']
        # A continuing Main also shows receipts retained for an earlier Main,
        # except those already shown to or handed over from that Main.
        if (connection.get('session') != session
                and not owns_main_root(runner, connection, {'runtime': 'codex', 'session': session})):
            continue
        addressee = (connection.get('runtime'), connection.get('session'))
        if addressee not in shown:
            shown[addressee] = receipts_shown(runner, *addressee)
        if record['at'] <= shown[addressee]:
            continue
        through[addressee] = max(through.get(addressee, 0.0), record['at'])
        identity = record.get('identity', {})
        facts.append((f"receipt:{notice.get('alias')}:{identity.get('execution_id')}",
                      str(notice.get('alias')), f'Codex session {session}', str(notice.get('message'))))

    def settle() -> None:
        """Record that the receipts read here were shown, per addressed Main."""
        for (runtime, addressed), at in through.items():
            show_receipts(runner, runtime, addressed, at)

    return facts, settle


def _agents_facts(event: dict, session: str) -> list[tuple[str, str, str, str]]:
    """Return the request and reply facts of one successful agents call."""
    if (event.get('hook_event_name') != 'PostToolUse'
            or event.get('tool_name') not in {'mcp__graphtraj__agents', 'mcp__agents__agents'}):
        return []
    request = event.get('tool_input', {})
    response = event.get('tool_response', {})
    if (not isinstance(request, dict) or request.get('action') != 'execute'
            or not isinstance(response, dict) or response.get('isError')):
        return []
    document = response.get('structuredContent', {})
    if not isinstance(document, dict) or document.get('error'):
        return []
    record = document.get('result', {})
    agent = document.get('agent')
    call_id = event.get('tool_use_id')
    if (not isinstance(record, dict)
            or not all(isinstance(value, str) and value for value in (agent, session, call_id))):
        return []
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
    return facts


def _show(facts: list[tuple[str, str, str, str]], session: str, state_directory: Path) -> dict:
    """Render facts not yet shown in this Session, once each."""
    # Native Session scope prevents another Session's matching IDs suppressing
    # its own display. This cache is optional UI state, not control authority.
    path = state_directory / (hashlib.sha256(session.encode()).hexdigest() + '.yml')
    with exclusive_lock(path.with_suffix('.lock')):
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
