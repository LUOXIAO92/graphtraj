"""How a host that owns its children stops them when its native side closes.

The Pi and DSH hosts share this. It stops through the public ``call`` and reads
the end through ``status``, never ``wait``: ``wait`` returns at once while a
request is unanswered, and an interrupted execution keeps counting its request
until it ends.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import Callable

# One deadline for the whole stop, however many children there are.
STOP_SECONDS = 10.0
PAUSE_SECONDS = 0.05
# Stands for the Agents themselves when no status could be read at all.
STATUS_UNREADABLE = '(status unreadable)'


def _active(call: Callable) -> list[str] | None:
    """Return the active Agents, descendants first, or ``None`` if status cannot be read."""
    try:
        status = call({'action': 'status'})
        if status.failed:
            return None
        pending = list(status.document['result']['agents'])
        owned = []
        while pending:
            agent = pending.pop()
            owned.append(agent)
            pending.extend(agent['children'])
        return [agent['agent'] for agent in reversed(owned) if agent['state'] == 'active']
    except Exception:
        return None


def stop_children(call: Callable) -> list[str]:
    """Interrupt every active child, descendants first, and return those not confirmed stopped.

    Only a status showing an Agent out of ``active`` confirms it. Every pass
    interrupts what is still active: it is idempotent, and it reaches an Agent
    that was still starting, or that a stopping parent has just created. One
    failed interrupt never stops the others. Nothing is confirmed when no
    status could be read, which returns ``[STATUS_UNREADABLE]``.
    """
    deadline = time.monotonic() + STOP_SECONDS
    unconfirmed = [STATUS_UNREADABLE]
    while True:
        active = _active(call)
        if active is not None:
            unconfirmed = active
        for agent in active or ():
            try:
                call({'action': 'interrupt', 'agent': agent})
            except Exception:
                pass  # Still active at the deadline, so it is reported then.
        remaining = deadline - time.monotonic()
        if active == [] or remaining <= 0:
            return unconfirmed
        time.sleep(min(PAUSE_SECONDS, remaining))


def exit_if_unconfirmed(unconfirmed: list[str]) -> None:
    """Report what was not confirmed stopped and end this process; nothing to report returns.

    Its owning thread can keep a stuck child's process alive, and the native
    Session's shutdown waits for this process, so this path alone uses
    ``os._exit``. An error already unwinding is written first, or it would be lost.
    """
    if not unconfirmed:
        return
    what = ('Host shutdown could not read status, so no Agent is confirmed stopped.'
            if unconfirmed == [STATUS_UNREADABLE] else
            f"Host shutdown could not confirm the stop of: {', '.join(unconfirmed)}. Every other Agent stopped.")
    try:
        if sys.exc_info()[1] is not None:
            traceback.print_exc(file=sys.stderr)
        print(json.dumps({'error': {'code': 'stop-unconfirmed',
                                    'message': f'{what} The next host for this Session shows the state through status.'}}),
              file=sys.stderr, flush=True)
    finally:
        os._exit(1)
