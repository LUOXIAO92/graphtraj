"""Process-liveness primitives shared by Runner commands."""

from __future__ import annotations

import ctypes
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


OPERATION_TIMEOUT_SECONDS = 10.0

from graftling import process_ancestors, process_executable, process_arguments as _process_arguments

# The Darwin kernel's process information interface (sys/proc_info.h).
_PROC_PIDT_SHORTBSDINFO   = 13
_SHORTBSDINFO_BUFFER_SIZE = 64
_SZOMB                    = 5    # pbsi_status: exited, not yet reaped
_PROC_FLAG_INEXIT         = 0x4  # pbsi_flags: the kernel is tearing it down
# A live process may briefly refuse its argv while it executes a new image.
_ARGUMENT_RETRY_SECONDS   = 0.5
_ARGUMENT_RETRY_INTERVAL  = 0.05


def _libproc() -> ctypes.CDLL | None:
    """Return the loaded libproc, loading and configuring it at most once."""
    if not hasattr(_libproc, 'library'):
        try:
            library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            library.proc_pidinfo.restype = ctypes.c_int
            library.proc_pidinfo.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
            ]
        except (OSError, AttributeError):
            library = None
        _libproc.library = library
    return _libproc.library


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


def unstarted_worker_processes(job_file: Path) -> list[int]:
    """Find exact current Workers for a launch, refusing ambiguous ownership.

    This is an observation, not terminal proof. The caller must hold the
    startup lock and verify pre-Runtime artifacts before stopping a Worker.
    """
    processes = _current_user_processes()
    expected = ['-I', '-m', 'graphtraj.execution.runner_worker', str(job_file)]
    matches = []
    for pid, parent, group in processes:
        arguments = _worker_arguments(pid)
        if arguments is None or str(job_file) not in arguments:
            continue
        executable = process_executable(pid)
        if executable is None and sys.platform == 'darwin' and _process_ended(pid):
            continue  # Exited after its argv was read: it can no longer act.
        if (arguments[1:] != expected
                or executable != Path(sys.executable).resolve()
                or group != pid or any(ppid == pid for _, ppid, _ in processes)):
            raise OSError('Launch process identity or pre-Runtime state is ambiguous')
        matches.append(pid)
    if len(matches) > 1:
        raise OSError('Multiple Workers reference the same launch')
    return matches


def _worker_arguments(pid: int) -> list[str] | None:
    """Read a pid's argv, or None when the kernel shows it has ended.

    An exiting or zombie process can never execute again, so it is no Worker
    and is never signalled. A live, not-exiting process whose argv stays
    unreadable for the bounded retry is refused as before.
    """
    deadline = time.monotonic() + _ARGUMENT_RETRY_SECONDS
    while True:
        try:
            return _process_arguments(pid)
        except OSError:
            if sys.platform != 'darwin':
                if process_is_alive(pid):
                    raise
                return None
            if _process_ended(pid):
                return None
            if time.monotonic() + _ARGUMENT_RETRY_INTERVAL > deadline:
                raise
            time.sleep(_ARGUMENT_RETRY_INTERVAL)


def _short_bsd_info(pid: int) -> tuple[int, int, int, int, int] | None:
    """Darwin pid, parent, group, status and flags, zombies included; None if unreadable."""
    library = _libproc()
    if library is None:
        return None
    record = ctypes.create_string_buffer(_SHORTBSDINFO_BUFFER_SIZE)
    # Nonzero arg includes zombies and exiting processes (XNU findzomb).
    if library.proc_pidinfo(pid, _PROC_PIDT_SHORTBSDINFO, 1, record, len(record)) != len(record):
        return None
    return tuple(int.from_bytes(record.raw[offset:offset + 4], sys.byteorder)
                 for offset in (0, 4, 8, 12, 32))


def _has_ended(info: tuple[int, int, int, int, int]) -> bool:
    return info[3] == _SZOMB or bool(info[4] & _PROC_FLAG_INEXIT)


def _process_ended(pid: int) -> bool:
    """Darwin: whether the kernel shows pid as exiting, a zombie, or reaped."""
    info = _short_bsd_info(pid)
    if info is not None:
        return _has_ended(info)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _current_user_processes() -> list[tuple[int, int, int]]:
    """Read current-user PID, parent and group identities from the platform."""
    if sys.platform != 'darwin':
        rows = subprocess.check_output(
            ['/bin/ps', '-U', str(os.getuid()), '-o', 'pid=,ppid=,pgid='], text=True,
        )
        return [tuple(map(int, row.split())) for row in rows.splitlines()]
    library = _libproc()
    if library is None:
        raise OSError('Native process enumeration is unavailable')
    # PROC_UID_ONLY and proc_bsdshortinfo are the same libproc interface used
    # for ancestry above. No helper executable or formatted argv is needed.
    size = library.proc_listpids(4, os.getuid(), None, 0)
    if size <= 0:
        raise OSError('Native process enumeration failed')
    pids = (ctypes.c_int * (size // 4 + 128))()
    written = library.proc_listpids(4, os.getuid(), pids, ctypes.sizeof(pids))
    if written <= 0 or written >= ctypes.sizeof(pids):
        raise OSError('Native process enumeration is incomplete')
    result = []
    for pid in pids[:written // 4]:
        info = _short_bsd_info(pid)
        if info is None:
            if process_is_alive(pid):
                raise OSError('Native process identity is unavailable')
            continue
        if not _has_ended(info):  # Exiting or zombie processes cannot execute.
            result.append(info[:3])
    return result


def process_started_at(pid: int) -> float:
    """Read process creation time from the kernel, refusing unavailable identity."""
    if sys.platform == 'darwin':
        library = _libproc()
        record = ctypes.create_string_buffer(136)
        # PROC_PIDTBSDINFO: pbi_start_tvsec/usec follow the 120-byte BSD prefix.
        if library is None or library.proc_pidinfo(pid, 3, 0, record, len(record)) != len(record):
            raise OSError('Process creation time is unavailable')
        seconds = int.from_bytes(record.raw[120:128], sys.byteorder)
        micros = int.from_bytes(record.raw[128:136], sys.byteorder)
        return seconds + micros / 1_000_000
    if sys.platform.startswith('linux'):
        fields = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
        if len(fields) <= 19:
            raise OSError('Process creation record is incomplete')
        boot = next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines()
                    if line.startswith('btime '))
        return int(boot) + int(fields[19]) / os.sysconf('SC_CLK_TCK')
    raise OSError('Process creation time is unsupported')


def _runtime_group(group: int) -> list[tuple[int, int, int]]:
    """Read only the retained group; unrelated processes grant no authority."""
    if sys.platform != 'darwin':
        rows = subprocess.check_output(
            ['/bin/ps', '-e', '-o', 'pid=,ppid=,pgid=,stat='], text=True,
        )
        return [tuple(map(int, fields[:3])) for row in rows.splitlines()
                if (fields := row.split()) and int(fields[2]) == group
                and not fields[3].startswith('Z')]
    library = _libproc()
    if library is None:
        raise OSError('Native process group enumeration is unavailable')
    # PROC_PGRP_ONLY avoids querying identities of other Agents or OS services.
    ctypes.set_errno(0)
    size = library.proc_listpids(2, group, None, 0)
    if size < 0 or (size == 0 and ctypes.get_errno()):
        raise OSError('Native process group enumeration failed')
    pids = (ctypes.c_int * (size // 4 + 128))()
    ctypes.set_errno(0)
    written = library.proc_listpids(2, group, pids, ctypes.sizeof(pids))
    if written < 0 or written >= ctypes.sizeof(pids) or (written == 0 and ctypes.get_errno()):
        raise OSError('Native process group enumeration is incomplete')
    result = []
    for pid in pids[:written // 4]:
        record = ctypes.create_string_buffer(_SHORTBSDINFO_BUFFER_SIZE)
        # Nonzero arg explicitly includes zombies (XNU proc_pidinfo findzomb).
        # An ESRCH from the live-only query is not a termination observation.
        count = library.proc_pidinfo(pid, _PROC_PIDT_SHORTBSDINFO, 1, record, len(record))
        if count != len(record):
            if process_is_alive(pid):
                raise OSError('Owned process group identity is unavailable')
            continue
        values = [int.from_bytes(record.raw[offset:offset + 4], sys.byteorder)
                  for offset in (0, 4, 8, 12)]
        if values[2] == group and values[3] != 5:
            result.append(tuple(values[:3]))
    return result


def settle_runtime_group(
    pid: int, executable: Path, session: str, owned_at: float | None,
) -> dict:
    """Observe or stop an exactly identified Runtime group, never a guessed PID.

    The Adapter must have created the retained leader with start_new_session.
    Its Worker must have released ownership and the caller must hold the Runner
    startup lock. An orphaned nonempty group has no verifiable leader and is
    refused. A live leader must predate this execution's retained heartbeat;
    its kernel start time is rechecked before signalling to detect PID reuse.
    """
    if type(pid) is not int or pid <= 1 or not session:
        raise OSError('Runtime group identity is unavailable')
    if type(owned_at) not in (int, float) or not math.isfinite(owned_at):
        owned_at = None
    signals = []
    for sig in (signal.SIGTERM, signal.SIGKILL, None):
        members = _runtime_group(pid)
        if not members:
            return {'method': 'current-process-group', 'process_group': pid,
                    'running_members': [], 'signals': signals, 'observed_at': time.time()}
        if sig is None:
            raise OSError('The owned Runtime group still has running members')
        arguments = _process_arguments(pid)
        started = process_started_at(pid)
        if (not any(row[0] == pid for row in members)
                or owned_at is None or started <= 0 or started > owned_at
                or process_executable(pid) != executable.resolve()
                or not any(arguments[index:index + 2] == [flag, session]
                           for index in range(len(arguments))
                           for flag in ('--session-id', '--resume'))
                or not any(arguments[index:index + 2] == ['--input-format', 'stream-json']
                           for index in range(len(arguments)))
                or '--print' not in arguments):
            raise OSError('Current Runtime group leader does not match the retained Claude invocation')
        # Check again immediately before signalling, as for pre-Runtime stop.
        if (os.getpgid(pid) != pid or _process_arguments(pid) != arguments
                or process_started_at(pid) != started
                or process_executable(pid) != executable.resolve()):
            raise OSError('Runtime process identity changed during stop')
        os.killpg(pid, sig)
        signals.append(sig.name)
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not _runtime_group(pid):
                break
            time.sleep(0.05)
    raise OSError('Runtime group stopping could not be confirmed')
