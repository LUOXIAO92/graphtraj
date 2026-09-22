"""Process-liveness primitives shared by Runner commands."""

from __future__ import annotations

import ctypes
import os
import signal
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
