"""Verify the packaged GUI owning a read-only native pipe; never trust a role claim."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, TextIO

from graphtraj.execution.runner_process import process_executable
from graphtraj.execution.runner_status import process_caller_alias, runtime_caller_is_bound
from graphtraj.runtimes.replacement import caller_runtime
from graphtraj.workspace.runner_project import discover_runner_directory

_WINDOW: ContextVar[tuple[Path, int, Path] | None] = ContextVar('desktop_window', default=None)


def _executable(pid: int) -> Path | None:
    """Read a live executable identity from the OS, including the Windows bridge."""
    if os.name != 'nt':
        return process_executable(pid)
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        return Path(buffer.value) if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None
    finally:
        kernel.CloseHandle(handle)


def _matches_release(executable: Path, release: dict) -> bool:
    """Compare the kernel-selected GUI with provenance shipped in this backend wheel."""
    if executable.name != release.get('executable') or not release.get('files'):
        return False
    files = release['files']
    if executable.name not in files or not any('dist-electron/main.js' in name for name in files):
        return False
    try:
        return all(hashlib.sha256((executable.parent / name).read_bytes()).hexdigest() == digest
                   for name, digest in files.items())
    except OSError:
        return False


@contextmanager
def window_pipe(cwd: Path, input_stream: TextIO, output_stream: TextIO) -> Iterator[None]:
    """Bind only an attested GUI's inherited pipe to its selected project until EOF.

    Provenance is installed package data, not a request, actor field or GUI-supplied
    manifest. Managed/native Agent ancestry is still refused, even for a real GUI.
    Missing proof retains the existing caller checks, including unknown locators.
    """
    binding = None
    try:
        parent = os.getppid()
        executable = _executable(parent)
        # Node uses anonymous socket pairs for Unix stdio and pipes on Windows.
        modes = [os.fstat(stream.fileno()).st_mode for stream in (input_stream, output_stream)]
        pipes = all(stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) for mode in modes)
        release = json.loads(Path(__file__).with_name('desktop-host.json').read_text())
        if (pipes and executable is not None and not runtime_caller_is_bound()
                and caller_runtime() is None
                and process_caller_alias(discover_runner_directory(cwd), os.getpid()) is None
                and not os.environ.get('ELECTRON_RUN_AS_NODE') and not os.environ.get('NODE_OPTIONS')
                and _matches_release(executable, release)):
            binding = (cwd.resolve(), parent, executable)
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    token = _WINDOW.set(binding)
    try:
        yield
    finally:
        _WINDOW.reset(token)


def owns_project(cwd: Path) -> bool:
    """Keep the live GUI/project binding local to the authenticated pipe lifetime."""
    binding = _WINDOW.get()
    return bool(binding and binding[0] == cwd.resolve()
                and binding[1] == os.getppid() and binding[2] == _executable(binding[1]))
