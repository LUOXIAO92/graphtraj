"""500: 459's ``stop_own`` cleanup tolerates a process that exits between its identity check and the kill.

Seen under the loaded repetition (R new): test_tool_descendants_496 failed with ProcessLookupError at
test_tool_descendants_459.py ``stop_own``. Deterministic here: the identity check says alive, then the
kill finds the pid gone. No real process is signalled (``os.kill`` is replaced for this test).
"""
from __future__ import annotations

import os
import signal

import test_tool_descendants_459 as helpers
from graftling.tool_descendants import Identity


def test_stop_own_returns_when_the_process_exits_between_the_check_and_the_kill(monkeypatch) -> None:
    gone = Identity(pid=4_000_000, ppid=1, pgid=4_000_000, uid=os.getuid(), start=1)
    checks, sent = [], []

    def is_alive(item):
        checks.append(item.pid)
        return len(checks) == 1  # alive at the check, gone afterwards

    def kill(pid, sig):
        sent.append((pid, sig))
        raise ProcessLookupError(3, 'No such process')

    monkeypatch.setattr(helpers, 'is_alive', is_alive)
    monkeypatch.setattr(os, 'kill', kill)
    helpers.stop_own([gone])
    assert sent == [(gone.pid, signal.SIGKILL)]
