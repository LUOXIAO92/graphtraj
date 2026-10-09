"""Shared and exclusive file locks for project state on POSIX and Windows."""

from __future__ import annotations

import os
from typing import IO

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
