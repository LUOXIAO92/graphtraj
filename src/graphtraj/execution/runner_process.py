"""Process-liveness primitives shared by Runner commands."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


OPERATION_TIMEOUT_SECONDS = 10.0

# A control request walks from its own process to the top of the tree. The
# limit only keeps a damaged or cyclic parent chain from looping forever.
ANCESTOR_LIMIT = 64

# On macOS the parent is read through libproc, which needs no helper process
# that a restricted Agent environment might not be able to start. The flavor
# and byte offsets are the documented PROC_PIDT_SHORTBSDINFO record, whose
# first two fields are pbsi_pid and pbsi_ppid.
_LIBPROC_PATH = "/usr/lib/libproc.dylib"
_PROC_PIDT_SHORTBSDINFO = 13
_SHORTBSDINFO_PPID_OFFSET = 4
_SHORTBSDINFO_BUFFER_SIZE = 64


def process_ancestors(pid: int) -> list[int]:
    """Return one process and its ancestors, nearest first.

    Parameters
    ----------
    pid
        Identifier of the process whose tree to walk, usually ``os.getpid()``.

    Returns
    -------
    The supplied identifier followed by its parent, its grandparent and so on
    until the top of the tree, a repeated identifier fails to resolve, or
    ``ANCESTOR_LIMIT`` entries are reached. A platform whose parent record
    cannot be read simply ends the walk there.
    """
    chain: list[int] = []
    seen: set[int] = set()
    while pid and pid not in seen and len(chain) < ANCESTOR_LIMIT:
        seen.add(pid)
        chain.append(pid)
        pid = _process_parent(pid)
    return chain


def _process_parent(pid: int) -> int:
    """Return one process's parent identifier, or 0 when it cannot be read."""

    if sys.platform == "darwin":
        return _darwin_parent(pid)
    if sys.platform.startswith("linux"):
        return _linux_parent(pid)
    return 0


def _darwin_parent(pid: int) -> int:
    """Read one parent identifier through libproc, without spawning a helper."""

    library = _libproc()
    if library is None:
        return 0
    buffer = ctypes.create_string_buffer(_SHORTBSDINFO_BUFFER_SIZE)
    written = library.proc_pidinfo(
        pid, _PROC_PIDT_SHORTBSDINFO, 0, buffer, len(buffer)
    )
    if written < _SHORTBSDINFO_PPID_OFFSET + 4:
        return 0
    return int.from_bytes(
        buffer.raw[_SHORTBSDINFO_PPID_OFFSET:_SHORTBSDINFO_PPID_OFFSET + 4],
        sys.byteorder,
    )


def _libproc() -> ctypes.CDLL | None:
    """Return the loaded libproc, loading and configuring it at most once."""

    if not hasattr(_libproc, "library"):
        try:
            library = ctypes.CDLL(_LIBPROC_PATH, use_errno=True)
            library.proc_pidinfo.restype = ctypes.c_int
            library.proc_pidinfo.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
        except (OSError, AttributeError):
            library = None
        _libproc.library = library
    return _libproc.library


def _linux_parent(pid: int) -> int:
    """Read one parent identifier from the kernel's process record."""

    try:
        record = Path("/proc/{0}/stat".format(pid)).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return 0
    # The second field is the command in parentheses and may contain spaces,
    # so the state and parent are read after the last closing parenthesis.
    fields = record.rpartition(")")[2].split()
    if len(fields) < 2 or not fields[1].isdigit():
        return 0
    return int(fields[1])


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


def process_executable(pid: int) -> Path | None:
    """Read the kernel's executable path for a live process, without argv aliases."""
    if sys.platform.startswith("linux"):
        try:
            return Path(os.readlink(f"/proc/{pid}/exe"))
        except OSError:
            return None
    if sys.platform == "darwin":
        library = _libproc()
        if library is not None:
            buffer = ctypes.create_string_buffer(4096)
            library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            library.proc_pidpath.restype = ctypes.c_int
            if library.proc_pidpath(pid, buffer, len(buffer)) > 0:
                return Path(os.fsdecode(buffer.value))
    return None


def unstarted_worker_processes(job_file: Path) -> list[int]:
    """Find exact current Workers for a launch, refusing ambiguous ownership.

    This is an observation, not terminal proof. The caller must hold the
    startup lock and verify pre-Runtime artifacts before stopping a Worker.
    """
    processes = _current_user_processes()
    expected = ['-I', '-m', 'graphtraj.execution.runner_worker', str(job_file)]
    matches = []
    for pid, parent, group in processes:
        try:
            arguments = _process_arguments(pid)
        except OSError:
            if process_is_alive(pid):
                raise
            continue
        if str(job_file) not in arguments:
            continue
        if (arguments[1:] != expected
                or process_executable(pid) != Path(sys.executable).resolve()
                or group != pid or any(ppid == pid for _, ppid, _ in processes)):
            raise OSError('Launch process identity or pre-Runtime state is ambiguous')
        matches.append(pid)
    if len(matches) > 1:
        raise OSError('Multiple Workers reference the same launch')
    return matches


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
        record = ctypes.create_string_buffer(_SHORTBSDINFO_BUFFER_SIZE)
        count = library.proc_pidinfo(pid, _PROC_PIDT_SHORTBSDINFO, 0, record, len(record))
        if count != len(record):
            if process_is_alive(pid):
                raise OSError('Native process identity is unavailable')
            continue
        values = [int.from_bytes(record.raw[offset:offset + 4], sys.byteorder)
                  for offset in (0, 4, 8, 12)]
        if values[3] != 5:  # SZOMB has exited and cannot execute.
            result.append(tuple(values[:3]))
    return result


def _process_arguments(pid: int) -> list[str]:
    """Read kernel argument boundaries rather than splitting formatted ps text."""
    if sys.platform.startswith('linux'):
        return [os.fsdecode(arg) for arg in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if arg]
    if sys.platform != 'darwin':
        raise OSError('Exact process arguments are unavailable on this platform')
    # Darwin KERN_PROCARGS2 contains argc, executable path, padding, then argv.
    library = ctypes.CDLL(None, use_errno=True)
    query = (ctypes.c_int * 3)(1, 49, pid)
    buffer = ctypes.create_string_buffer(os.sysconf('SC_ARG_MAX'))
    size = ctypes.c_size_t(len(buffer))
    if library.sysctl(query, 3, buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Process arguments are unavailable')
    raw = buffer.raw[:size.value]
    count = int.from_bytes(raw[:4], sys.byteorder)
    start = raw.index(b'\0', 4) + 1
    while start < len(raw) and raw[start] == 0:
        start += 1
    arguments = raw[start:].split(b'\0')[:count]
    if len(arguments) != count or count < 1:
        raise OSError('Process argument record is incomplete')
    return [os.fsdecode(arg) for arg in arguments]
