"""Shared and exclusive file locks for project state on POSIX and Windows."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

if os.name != 'nt':
    from fcntl import LOCK_EX, LOCK_NB, LOCK_SH, LOCK_UN, flock
else:
    import ctypes
    import errno
    import msvcrt
    from ctypes import wintypes

    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    class _Overlapped(ctypes.Structure):
        """Windows OVERLAPPED with zero offset and no asynchronous event."""

        _fields_ = [
            ('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
            ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
            ('hEvent', wintypes.HANDLE),
        ]

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _lock = _kernel.LockFileEx
    _lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                      wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped)]
    _lock.restype = wintypes.BOOL
    _unlock = _kernel.UnlockFileEx
    _unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                        wintypes.DWORD, ctypes.POINTER(_Overlapped)]
    _unlock.restype = wintypes.BOOL

    def flock(file: int | IO, operation: int) -> None:
        """Lock a file's common first byte, blocking unless LOCK_NB is supplied.

        All GraphTraj callers coordinate on this range. Windows permits locking
        beyond EOF, shared readers, and releases locks when the handle closes.
        The descriptor position is unchanged. This does not implement the POSIX
        process-owner authentication used by the separate Runner control pipe.
        """
        descriptor = file if isinstance(file, int) else file.fileno()
        handle = msvcrt.get_osfhandle(descriptor)
        overlap = _Overlapped()
        if operation == LOCK_UN:
            success = _unlock(handle, 0, 1, 0, ctypes.byref(overlap))
        else:
            if (operation & ~LOCK_NB) not in (LOCK_SH, LOCK_EX):
                raise ValueError('Expected a shared or exclusive file lock.')
            flags = (2 if operation & LOCK_EX else 0) | (1 if operation & LOCK_NB else 0)
            success = _lock(handle, flags, 0, 1, 0, ctypes.byref(overlap))
        if not success:
            error = ctypes.get_last_error()
            if error == 33:  # ERROR_LOCK_VIOLATION
                raise BlockingIOError(errno.EAGAIN, 'The file is locked by another handle.')
            raise ctypes.WinError(error)


@contextmanager
def replacement_lock(path: Path) -> Iterator[None]:
    """Serialize a compare-and-replace without holding a Windows data handle.

    Windows byte locks block reads from other handles, and ordinary open files
    cannot be replaced. A kernel mutex uses the canonical destination name and
    leaves the target available for validation and atomic replacement. Its
    default security descriptor is retained; access errors fail closed.
    """
    if os.name != 'nt':
        with path.open('rb') as stream:
            flock(stream, LOCK_EX)
            yield
        return

    name = 'Global\\GraphTraj-replace-' + hashlib.sha256(
        os.path.normcase(str(path.resolve())).encode('utf-8')
    ).hexdigest()
    create = _kernel.CreateMutexW
    create.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    wait = _kernel.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    release = _kernel.ReleaseMutex
    release.argtypes = [wintypes.HANDLE]
    release.restype = wintypes.BOOL
    close = _kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = wait(handle, 0xFFFFFFFF)
        if result not in (0, 0x80):  # Acquired or abandoned by a terminated owner.
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not release(handle):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close(handle)
