"""Process-liveness primitives shared by Runner commands."""

from __future__ import annotations

import os
import signal
import time


OPERATION_TIMEOUT_SECONDS = 10.0


def process_is_alive(pid: int) -> bool:
    """Return whether a process identifier still resolves for this user."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def stop_worker(pid: int) -> bool:
    """Stop and reap one Runner-owned worker process group."""

    if _reap_worker(pid):
        return True
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _reap_worker(pid):
            return True
        time.sleep(0.01)
    return False


def _reap_worker(pid: int) -> bool:
    try:
        waited_pid, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return not process_is_alive(pid)
    except OSError:
        return False
    return waited_pid == pid
