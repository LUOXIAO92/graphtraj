"""Stop one ``dsh web`` process group if the process that started it dies.

``DshService.start`` runs this script as ``python -I -S watcher.py <pid>``. Its
stdin is a pipe whose write end only the service holds. One byte means the service
stopped the group itself, so there is nothing to do. The end of the pipe with
nothing written means the owner died, or never closed the service: nothing else
would stop the group, since the owner's own stop was a thread in that process.

Standard library only, no inherited environment, and stderr is the owner's. In a
Claude host that is ``host.log``, so these lines are the record a killed host
cannot write.
"""
from __future__ import annotations

import os
import signal
import sys
import time

# As DshService.close: each signal gets this long before the next one.
STEP_SECONDS = 5.0
POLL_SECONDS = 0.05


def report(text: str, pid: int) -> None:
    """Write one line to the owner's stderr; a stderr nobody reads must not end the stop."""
    try:
        os.write(2, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} agents DSH watcher: {text} pid={pid}\n".encode())
    except OSError:
        pass


def group_exists(pid: int) -> bool:
    """Return whether the group led by ``pid`` still answers.

    On darwin a group holding only zombies answers EPERM. The owner is gone, so
    launchd reaps them and the answer soon becomes ESRCH. Until then the group
    counts as present, so a real refusal can never be reported as a stop.
    """
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_group(pid: int) -> bool:
    """Send SIGINT, SIGTERM and SIGKILL in turn; return whether the group ended."""
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass

        deadline = time.monotonic() + STEP_SECONDS
        while time.monotonic() < deadline:
            if not group_exists(pid):
                return True
            time.sleep(POLL_SECONDS)
    return not group_exists(pid)


def main() -> None:
    """Wait for the owner's word or its death, and exit 1 only if the group could not be stopped."""
    pid = int(sys.argv[1])
    if os.read(0, 1) or not group_exists(pid):
        return

    report('the owner of this DSH service ended without closing it, stopping the DSH process group', pid)
    if stop_group(pid):
        report('stopped the DSH process group', pid)
        return
    report('could not stop the DSH process group', pid)
    sys.exit(1)


if __name__ == '__main__':
    main()
