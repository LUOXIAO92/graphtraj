"""How a host that owns its children stops them when its native side closes.

The Pi and DSH hosts share ``stop_children``. It finds their children without a
record lock, stops them through the public ``call`` and reads each end through
``status`` of that Agent, never ``wait``: ``wait`` returns at once while a request
is unanswered, and an interrupted execution keeps counting its request until it
ends. Every call runs on its Agent's own daemon thread, so a call that blocks,
on a record lock or inside a driver, costs that Agent alone: the whole-hierarchy
``status`` would wait for every record's lock in turn, so one held lock would hide
every child. ``CLOSE_SECONDS`` bounds what these hosts wait for before the stop,
which keeps their process inside 20 seconds. The Claude and Codex hosts
use ``stop_owned``: they stop whatever this process runs, which no caller's
``status`` scope covers.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .control import AgentControl

# One deadline for the whole stop, however many children there are.
STOP_SECONDS = 10.0
PAUSE_SECONDS = 0.05
# How long one Agent's calls may hold up the next Agent's, which keeps descendants
# first unless a call is blocked. A pass begun just before the deadline may run this
# far past it, so that a read that is merely in progress is not reported as unanswered.
TURN_SECONDS = 0.5
# Each of the two waits a closing Pi or DSH host makes before the stop: for requests
# in flight on its connection, and for its notice flusher. Both share this number so
# that 2 * CLOSE_SECONDS + STOP_SECONDS stays inside the 20 seconds a host may take.
CLOSE_SECONDS = 3.0
# Stands for what no status answered: alone, every Agent; after names, any other Agent.
STATUS_UNREADABLE = '(status unreadable)'


def stop_children(call: Callable, agents: Callable[[], list[str]]) -> list[str]:
    """Interrupt every active child, descendants first, and return those not confirmed stopped.

    ``agents`` names the children, deepest first, without taking a record lock
    (:meth:`AgentControl.visible_agents`); it says who exists, never their state.
    Only the latest ``status`` of an Agent showing it out of ``active`` confirms it.
    Every pass reads each Agent again and interrupts what is not confirmed: that is
    idempotent, and it reaches an Agent that was still starting, or that a stopping
    parent has just created. An Agent has one thread at a time, so a blocked call
    neither delays the others nor piles up; this returns within ``STOP_SECONDS``
    plus ``TURN_SECONDS`` whatever is blocked, and that thread is left to the
    process's end.

    The result ends in ``STATUS_UNREADABLE`` when the Agents could not be listed, or
    when a read went unanswered and no Agent was seen stopped: then nothing was seen
    that could speak for an Agent not named.
    """
    deadline = time.monotonic() + STOP_SECONDS
    latest: dict[str, str | None] = {}
    threads: dict[str, threading.Thread] = {}
    names: list[str] = []

    def attempt(agent: str) -> None:
        """Read one Agent and interrupt it unless it answered as out of ``active``."""
        latest[agent] = None
        try:
            status = call({'action': 'status', 'agent': agent})
            if not status.failed:
                latest[agent] = status.document['result']['state']
        except Exception:
            pass  # Unanswered, so it is still unconfirmed; the interrupt is still worth trying.
        if latest[agent] in (None, 'active'):
            try:
                call({'action': 'interrupt', 'agent': agent})
            except Exception:
                pass  # Still unconfirmed at the deadline, so it is reported then.

    while True:
        try:
            names, listed = agents(), True
        except Exception:
            listed = False
        for agent in names:
            if agent not in threads or not threads[agent].is_alive():
                threads[agent] = threading.Thread(target=attempt, args=(agent,), daemon=True)
                threads[agent].start()
                threads[agent].join(max(0.0, min(TURN_SECONDS, deadline + TURN_SECONDS - time.monotonic())))
        unconfirmed = [agent for agent in names if latest.get(agent) in (None, 'active')]
        remaining = deadline - time.monotonic()
        if listed and not unconfirmed:
            return []
        if remaining <= 0:
            silent = any(latest.get(agent) is None for agent in names) and len(unconfirmed) == len(names)
            return unconfirmed + [STATUS_UNREADABLE] if silent or not listed else unconfirmed
        time.sleep(min(PAUSE_SECONDS, remaining))


def stop_owned(control: AgentControl) -> list[str]:
    """Interrupt what this process owns and return the Agents still owned at the deadline.

    Every pass interrupts again, which reaches an Agent still starting or one
    whose interrupt failed. It does not call ``owns_running``: that takes the
    record lock, which a blocked interrupt holds until the process ends.
    """
    deadline = time.monotonic() + STOP_SECONDS
    while True:
        owned     = control.interrupt_owned()
        remaining = deadline - time.monotonic()
        if not owned or remaining <= 0:
            return owned
        time.sleep(min(PAUSE_SECONDS, remaining))


def exit_if_owned_unconfirmed(unconfirmed: list[str]) -> None:
    """``exit_if_unconfirmed`` for ``stop_owned``, which leaves other processes' Agents alone."""
    exit_if_unconfirmed(unconfirmed, 'Every other Agent this process ran stopped.')


def exit_if_unconfirmed(unconfirmed: list[str], others: str = 'Every other Agent stopped.') -> None:
    """Report what was not confirmed stopped and end this process; nothing to report returns.

    Its owning thread can keep a stuck child's process alive, and the native
    Session's shutdown waits for this process, so this path alone uses
    ``os._exit``. An error already unwinding is written first, or it would be lost.
    ``others`` is the sentence about the Agents that are not named.
    """
    if not unconfirmed:
        return
    named = ', '.join(agent for agent in unconfirmed if agent != STATUS_UNREADABLE)
    if not named:
        what = 'Host shutdown could not read status, so no Agent is confirmed stopped.'
    elif STATUS_UNREADABLE in unconfirmed:
        what = (f'Host shutdown could not confirm the stop of: {named}. '
                'Status did not answer for all of them, so no other Agent is confirmed stopped either.')
    else:
        what = f'Host shutdown could not confirm the stop of: {named}. {others}'
    try:
        if sys.exc_info()[1] is not None:
            traceback.print_exc(file=sys.stderr)
        print(json.dumps({'error': {'code': 'stop-unconfirmed',
                                    'message': f'{what} The next host for this Session shows the state through status.'}}),
              file=sys.stderr, flush=True)
    finally:
        os._exit(1)
