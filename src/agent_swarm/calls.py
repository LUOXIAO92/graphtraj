"""One running tool call's stop signal, for a host that serves calls concurrently.

Code that waits calls :func:`pause` or :func:`run_stoppable` at points where
stopping changes nothing already committed. Outside such a host no call is
current and these behave like ``time.sleep`` and ``subprocess.run``.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
import signal
import subprocess
import threading
import time
from typing import Callable, Iterator

from agent_swarm.tool import AgentsError

TERMINATION_SECONDS = 2.0
POLL_SECONDS = 0.02


class CallCancelled(AgentsError):
    """The caller cancelled this call, or its client went away, during a wait."""

    def __init__(self) -> None:
        super().__init__('call-cancelled', 'The caller cancelled this call.')


class Call:
    """Stop signal and undo callbacks of one running call."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        # The caller asked to stop, so no response is sent; input EOF only stops waits.
        self.cancelled = False
        # Run if the caller will never read this call's result.
        self.discards: list[Callable[[], None]] = []


_current: ContextVar[Call | None] = ContextVar('agents_current_call', default=None)


@contextmanager
def current_call(call: Call) -> Iterator[None]:
    """Make ``call`` the one the waits in this context answer to."""
    token = _current.set(call)
    try:
        yield
    finally:
        _current.reset(token)


def running_call() -> Call | None:
    """Return this context's call; ``None`` outside a concurrent host."""
    return _current.get()


def stop_requested() -> bool:
    """Whether this context's call was told to stop."""
    call = _current.get()
    return call is not None and call.stop.is_set()


def pause(seconds: float) -> None:
    """Sleep up to ``seconds``; raise :class:`CallCancelled` at once when told to stop."""
    call = _current.get()
    if call is None:
        time.sleep(seconds)
    elif call.stop.wait(seconds):
        raise CallCancelled()


def on_discard(callback: Callable[[], None]) -> None:
    """Undo a hand-over made for the result if the caller never reads that result."""
    call = _current.get()
    if call is not None:
        call.discards.append(callback)


def run_stoppable(command: tuple[str, ...] | list[str], **options) -> subprocess.CompletedProcess:
    """Run ``command`` to its end, or end its whole process group when told to stop.

    Only for a command whose interruption leaves nothing half-applied.
    """
    call = _current.get()
    if call is None:
        return subprocess.run(command, check=False, **options)
    process = subprocess.Popen(command, start_new_session=True, **options)
    while process.poll() is None:
        if call.stop.wait(POLL_SECONDS):
            _end_group(process)
            raise CallCancelled()
    return subprocess.CompletedProcess(command, process.returncode)


def _end_group(process: subprocess.Popen) -> None:
    """Ask the command's process group to end, then force it after a short bound."""
    for signum, seconds in ((signal.SIGTERM, TERMINATION_SECONDS), (signal.SIGKILL, None)):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        try:
            process.wait(seconds)
            return
        except subprocess.TimeoutExpired:
            continue
