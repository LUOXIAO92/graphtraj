"""Display retained receipts through Codex's UI-only hook output.

This optional PostToolUse/Stop hook neither calls a tool nor adds model context.
A Codex Main's own subagents messages and replies are shown by the subagents tool
card itself (544), so this hook shows only receipts no subagents call carries.
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

from graftling import exclusive_lock
from graphtraj.execution.runner_io import write_yaml_durably


def display(event: dict, state_directory: Path) -> dict:
    """Return only new receipts as systemMessage; never return model feedback.

    Any PostToolUse or Stop shows the Session's
    retained ordinary receipts once: completed child executions that this
    Codex Main did not start, kept without a model turn. The project records
    how far each addressed Main's receipts were shown, so no later Main shows
    or is handed them again.
    """
    session = event.get('session_id')
    if event.get('hook_event_name') not in {'PostToolUse', 'Stop'} or not isinstance(session, str) or not session:
        return {}
    facts, settle = _receipt_facts(event, session)
    if not facts:
        return {}
    shown = _show(facts, session, state_directory)
    settle()
    return shown


def _receipt_facts(event: dict, session: str) -> tuple[list[tuple[str, str, str]], Callable[[], None]]:
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
                      f"{notice.get('alias')} · {notice.get('event') or 'completed'}", str(notice.get('message'))))

    def settle() -> None:
        """Record that the receipts read here were shown, per addressed Main."""
        for (runtime, addressed), at in through.items():
            show_receipts(runner, runtime, addressed, at)

    return facts, settle


def _show(facts: list[tuple[str, str, str]], session: str, state_directory: Path) -> dict:
    """Render facts not yet shown in this Session, once each."""
    # Native Session scope prevents another Session's matching IDs suppressing
    # its own display. This cache is optional UI state, not control authority.
    path = state_directory / (hashlib.sha256(session.encode()).hexdigest() + '.yml')
    with exclusive_lock(path.with_suffix('.lock')):
        seen = set(yaml.safe_load(path.read_text()) or []) if path.exists() else set()
        boxes = []
        for identity, header, body in facts:
            if identity in seen:
                continue
            # One header line, then the body verbatim, so its Markdown stays intact (535).
            boxes.append(f'{header}\n\n{body}')
            seen.add(identity)
        if not boxes:
            return {}
        write_yaml_durably(path, sorted(seen))
    return {'systemMessage': '\n\n'.join(boxes)}


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
