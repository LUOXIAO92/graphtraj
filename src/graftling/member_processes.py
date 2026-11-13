"""Find and stop processes a member left behind after its Runtime exited.

Runtimes such as Claude Code start each tool command in its own session, so a
command like ``(nohup job &)`` leaves the Runtime's process group and is
re-parented to PID 1. Neither the group nor ancestry can find it afterwards.
Each member launch therefore carries a random per-execution value in
``MEMBER_RUN_ENV``; children inherit it through shells, ``setsid`` and
``nohup``. Only same-user processes whose environment holds exactly that value
are signalled. Names and command patterns are never matched.

The same scanner serves any such marker variable: ``variable`` names it (the
test suite uses its own per-run variable), and ``prefix=True`` matches every
value that starts with ``marker`` instead of exactly it.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

# The name avoids KEY, SECRET and TOKEN: Codex's default shell environment
# policy drops such variables from tool shells.
MEMBER_RUN_ENV = 'GRAFTLING_MEMBER_RUN'
_COMMAND_LIMIT = 300


def new_marker() -> str:
    """Return a fresh per-execution marker value."""
    return uuid.uuid4().hex


def _environment_darwin(pid: int) -> tuple[list[str], list[str]] | None:
    libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
    size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
    argmax = ctypes.c_int(0)
    if libc.sysctl((ctypes.c_int * 2)(1, 8), 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        return None
    size = ctypes.c_size_t(argmax.value)
    buffer = ctypes.create_string_buffer(argmax.value)
    # CTL_KERN=1, KERN_PROCARGS2=49
    if libc.sysctl((ctypes.c_int * 3)(1, 49, pid), 3, buffer, ctypes.byref(size), None, 0) != 0:
        return None
    raw = buffer.raw[:size.value]
    if len(raw) < 4:
        return None
    argc = int.from_bytes(raw[:4], sys.byteorder)
    position = raw.find(b'\0', 4)
    if position < 0:
        return None
    while position < len(raw) and raw[position] == 0:
        position += 1
    argv: list[str] = []
    for _ in range(argc):
        end = raw.find(b'\0', position)
        if end < 0:
            return None
        argv.append(raw[position:end].decode(errors='replace'))
        position = end + 1
    environment: list[str] = []
    while position < len(raw):
        end = raw.find(b'\0', position)
        if end <= position:
            break
        environment.append(raw[position:end].decode(errors='replace'))
        position = end + 1
    return argv, environment


def _environment_linux(pid: int) -> tuple[list[str], list[str]] | None:
    try:
        environ = Path(f'/proc/{pid}/environ').read_bytes()
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes()
    except OSError:
        return None
    split = lambda data: [item.decode(errors='replace') for item in data.split(b'\0') if item]
    return split(cmdline), split(environ)


def _process_view(pid: int) -> tuple[list[str], list[str]] | None:
    """Return (argv, environment) of a same-user process, or None if unreadable or gone."""
    try:
        if sys.platform == 'darwin':
            return _environment_darwin(pid)
        return _environment_linux(pid)
    except (OSError, ValueError):
        return None


def parent_pid(pid: int) -> int | None:
    """Return the parent of a process, or None when it is gone or unreadable."""
    try:
        if sys.platform.startswith('linux'):
            stat = Path(f'/proc/{pid}/stat').read_text()
            return int(stat[stat.rindex(')') + 2:].split()[1])
        libproc = ctypes.CDLL(ctypes.util.find_library('proc') or '/usr/lib/libproc.dylib', use_errno=True)
        # PROC_PIDTBSDINFO=3: struct proc_bsdinfo, whose pbi_ppid is the fifth uint32.
        buffer = ctypes.create_string_buffer(136)
        if libproc.proc_pidinfo(pid, 3, 0, buffer, 136) < 20:
            return None
        return int.from_bytes(buffer.raw[16:20], sys.byteorder)
    except (OSError, ValueError, IndexError):
        return None


def ancestor_pids(pid: int | None = None) -> set[int]:
    """Return ``pid`` (default: this process) and all its ancestors."""
    current = os.getpid() if pid is None else pid
    found = set()
    while current and current > 1 and current not in found:
        found.add(current)
        current = parent_pid(current)
    return found


def _user_pids() -> list[int]:
    if sys.platform.startswith('linux'):
        uid = os.getuid()
        pids = []
        for entry in Path('/proc').iterdir():
            if entry.name.isdigit():
                try:
                    if entry.stat().st_uid == uid:
                        pids.append(int(entry.name))
                except OSError:
                    continue
        return pids
    # macOS: libproc lists every pid; KERN_PROCARGS2 later reads only same-user ones.
    libproc = ctypes.CDLL(ctypes.util.find_library('proc') or '/usr/lib/libproc.dylib', use_errno=True)
    count = libproc.proc_listallpids(None, 0)
    if count <= 0:
        raise OSError(ctypes.get_errno(), 'proc_listallpids failed')
    # A full buffer may have been cut short by processes started between the
    # two calls; retry with more room until the list fits (459).
    for _ in range(8):
        capacity = count * 2 + 64
        buffer = (ctypes.c_int * capacity)()
        count = libproc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        if count <= 0:
            raise OSError(ctypes.get_errno(), 'proc_listallpids failed')
        if count < capacity:
            return [pid for pid in buffer[:count] if pid > 0]
    raise OSError(0, 'proc_listallpids kept filling its buffer')


def _carries(pid: int, marker: str, variable: str = MEMBER_RUN_ENV, prefix: bool = False) -> list[str] | None:
    """Return the argv when ``pid`` holds this marker (exactly, or as a prefix), else None."""
    view = _process_view(pid)
    if view is None:
        return None
    argv, environment = view
    entry = f'{variable}={marker}'
    if prefix:
        return argv if any(item.startswith(entry) for item in environment) else None
    return argv if entry in environment else None


def _command(argv: list[str]) -> str:
    text = ' '.join(argv)
    return text if len(text) <= _COMMAND_LIMIT else text[:_COMMAND_LIMIT] + '...'


def find_marked_processes(marker: str, exclude: set[int] | frozenset[int] = frozenset(), *,
                          variable: str = MEMBER_RUN_ENV, prefix: bool = False) -> dict[int, str]:
    """Map pid to command for same-user processes carrying ``marker`` in ``variable``."""
    if not marker:
        return {}
    skipped = {os.getpid(), *exclude}
    found = {}
    for pid in _user_pids():
        if pid in skipped or pid <= 1:
            continue
        argv = _carries(pid, marker, variable, prefix)
        if argv is not None:
            found[pid] = _command(argv)
    return found


def _signal_marked(pids: dict[int, str], marker: str, sig: int, variable: str, prefix: bool) -> None:
    for pid in pids:
        # Re-check right before signalling: the pid may have been reused.
        if _carries(pid, marker, variable, prefix) is not None:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass


def _wait_gone(pids: dict[int, str], marker: str, seconds: float, variable: str,
               prefix: bool) -> dict[int, str]:
    deadline = time.monotonic() + seconds
    alive = dict(pids)
    while alive:
        for pid in list(alive):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if _carries(pid, marker, variable, prefix) is None:
                alive.pop(pid)
        if not alive or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    return alive


def stop_marked_processes(marker: str, exclude: set[int] | frozenset[int] = frozenset(),
                          grace: float = 3.0, *, variable: str = MEMBER_RUN_ENV,
                          prefix: bool = False) -> dict:
    """Stop processes left with this execution's marker; report what was found.

    SIGTERM first, SIGKILL after ``grace`` seconds. A process counts as stopped
    once it no longer exists with the marker (exited, zombie or pid reused).
    """
    try:
        found = find_marked_processes(marker, exclude, variable=variable, prefix=prefix)
    except (OSError, subprocess.SubprocessError) as error:
        return {'found': [], 'stopped': [], 'remaining': [], 'error': str(error)}
    alive = found
    if found:
        _signal_marked(found, marker, signal.SIGTERM, variable, prefix)
        alive = _wait_gone(found, marker, grace, variable, prefix)
        if alive:
            _signal_marked(alive, marker, signal.SIGKILL, variable, prefix)
            alive = _wait_gone(alive, marker, 2.0, variable, prefix)
    entry = lambda pid: {'pid': pid, 'command': found[pid]}
    return {'found': [entry(pid) for pid in sorted(found)],
            'stopped': [entry(pid) for pid in sorted(found) if pid not in alive],
            'remaining': [entry(pid) for pid in sorted(alive)]}
