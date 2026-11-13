"""Record a Runtime's tool descendants while it lives, and stop them afterwards (459).

On macOS the environment of Apple platform binaries (``/bin/zsh``,
``/bin/sleep``) cannot be read, so the ``GRAFTLING_MEMBER_RUN`` marker scan of
:mod:`graftling.member_processes` never finds a Claude Bash tool shell. Their
ancestry and identity can be read. While the Runtime lives, the owner samples
its descendants by parent pid about once a second and keeps each one's pid,
process group, uid and start time in a per-execution sidecar file. After the
execution ends, only processes still alive with the same uid and start time
(so a reused pid is never signalled), plus their current descendants, are
stopped. Names and commands are never matched.

Boundary rule: managed launches (Runner Workers, nested child Runtimes) drop
or replace the marker. A descendant whose environment is readable and does not
hold exactly this execution's marker belongs to another execution or a managed
process; it is neither recorded nor descended into, and the check is repeated
right before each signal.

Known limits: a process started and detached between two samples is reached
only through the marker scan (so not a platform binary); a process whose chain
of ancestors passed through a readable process without the marker is left
alone by design; Windows is not covered.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

from graftling.member_processes import (
    MEMBER_RUN_ENV, _command, _process_view, _user_pids, find_marked_processes,
)

SUPPORTED = sys.platform == 'darwin' or sys.platform.startswith('linux')
SAMPLE_SECONDS = 1.0
_ZOMBIE_DARWIN = 5  # SZOMB in pbi_status
_libproc = None


class Identity(NamedTuple):
    pid: int
    ppid: int
    pgid: int
    uid: int
    start: int


def _proc():
    global _libproc
    if _libproc is None:
        _libproc = ctypes.CDLL(ctypes.util.find_library('proc') or '/usr/lib/libproc.dylib', use_errno=True)
    return _libproc


def identity(pid: int) -> Identity | None:
    """Return a live (non-zombie) process's identity, or None when gone or unreadable."""
    try:
        if sys.platform == 'darwin':
            # PROC_PIDTBSDINFO=3: struct proc_bsdinfo (136 bytes). pbi_status at 4,
            # pbi_ppid 16, pbi_uid 20, pbi_pgid 100, pbi_start_tvsec 120, tvusec 128.
            buffer = ctypes.create_string_buffer(136)
            if _proc().proc_pidinfo(pid, 3, 0, buffer, 136) < 136:
                return None
            raw = buffer.raw
            field = lambda offset, size=4: int.from_bytes(raw[offset:offset + size], sys.byteorder)
            if field(4) == _ZOMBIE_DARWIN or field(12) != pid:
                return None
            return Identity(pid, field(16), field(100), field(20),
                            field(120, 8) * 1_000_000 + field(128, 8))
        if sys.platform.startswith('linux'):
            path = Path(f'/proc/{pid}')
            stat = (path / 'stat').read_text()
            fields = stat[stat.rindex(')') + 2:].split()
            if fields[0] in ('Z', 'X'):
                return None
            return Identity(pid, int(fields[1]), int(fields[2]), path.stat().st_uid, int(fields[19]))
    except (OSError, ValueError, IndexError):
        return None
    return None


def _foreign(pid: int, marker: str) -> bool:
    """Whether ``pid``'s environment is readable and lacks exactly this marker (boundary rule)."""
    view = _process_view(pid)
    if view is None or not view[1]:
        return False
    return f'{MEMBER_RUN_ENV}={marker}' not in view[1]


def _argv(pid: int) -> list[str]:
    view = _process_view(pid)
    return view[0] if view is not None else []


def _table() -> dict[int, Identity]:
    """Return the identities of this user's live processes."""
    uid = os.getuid()
    table = {}
    for pid in _user_pids():
        if pid > 1:
            found = identity(pid)
            if found is not None and found.uid == uid:
                table[pid] = found
    return table


def _descend(table: dict[int, Identity], roots: set[int], marker: str, foreign: set[tuple[int, int]],
             skip: set[int] | frozenset[int] = frozenset()) -> dict[int, Identity]:
    """Return the descendants of ``roots`` in ``table`` that pass the boundary rule."""
    children: dict[int, list[Identity]] = {}
    for item in table.values():
        children.setdefault(item.ppid, []).append(item)
    found: dict[int, Identity] = {}
    pending = list(roots)
    while pending:
        for child in children.get(pending.pop(), ()):
            key = (child.pid, child.start)
            if child.pid in found or child.pid in skip or child.pid in roots or key in foreign:
                continue
            if _foreign(child.pid, marker):
                foreign.add(key)
                continue
            found[child.pid] = child
            pending.append(child.pid)
    return found


def _alive(entry: Identity | dict) -> bool:
    pid, start, uid = ((entry.pid, entry.start, entry.uid) if isinstance(entry, Identity)
                       else (entry['pid'], entry['start'], entry['uid']))
    now = identity(pid)
    return now is not None and now.start == start and now.uid == uid


def write_sidecar(path: Path, runtime_pid: int | None, entries: list[dict]) -> None:
    """Write the record atomically; it is never under the Agent lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump({'version': 1, 'runtime_pid': runtime_pid, 'entries': entries}, stream)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_sidecar(path: str | Path) -> list[dict]:
    """Return the recorded entries; raise OSError or ValueError when unreadable."""
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    entries = document.get('entries') if isinstance(document, dict) else None
    if not isinstance(entries, list) or not all(
            isinstance(item, dict) and all(isinstance(item.get(key), int) for key in ('pid', 'uid', 'start'))
            for item in entries):
        raise ValueError('malformed tool descendants record')
    return entries


class DescendantSampler:
    """Sample a Runtime's descendants about once a second into ``path``."""

    def __init__(self, path: Path, marker: str) -> None:
        self.path = Path(path)
        self.marker = marker
        self.runtime_pid: int | None = None
        self._runtime_start: int | None = None
        self.entries: dict[tuple[int, int], dict] = {}
        self.error: str | None = None
        self._foreign: set[tuple[int, int]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def prepare(self) -> None:
        """Write the empty record before the Runtime starts, so a missing file means a failure."""
        write_sidecar(self.path, None, [])

    def start(self, runtime_pid: int) -> None:
        self.runtime_pid = runtime_pid
        if not SUPPORTED:
            return
        runtime = identity(runtime_pid)
        self._runtime_start = runtime.start if runtime is not None else None
        self._thread = threading.Thread(target=self._loop, daemon=True, name='tool-descendants')
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(SAMPLE_SECONDS):
            self.sample()

    def sample(self) -> None:
        """Add current descendants; drop recorded ones that are gone; write on change."""
        if not SUPPORTED or self.runtime_pid is None:
            return
        with self._lock:
            try:
                table = _table()
                live = {key: entry for key, entry in self.entries.items()
                        if (now := table.get(entry['pid'])) is not None and now.start == entry['start']}
                # The Runtime is a root only while its pid still has its start time.
                runtime = table.get(self.runtime_pid)
                roots = {entry['pid'] for entry in live.values()}
                if runtime is not None and runtime.start == self._runtime_start:
                    roots.add(self.runtime_pid)
                for item in _descend(table, roots, self.marker, self._foreign).values():
                    key = (item.pid, item.start)
                    if key not in live:
                        live[key] = {'pid': item.pid, 'ppid': item.ppid, 'pgid': item.pgid, 'uid': item.uid,
                                     'start': item.start, 'argv': _command(_argv(item.pid))}
                if live.keys() != self.entries.keys():
                    self.entries = live
                    write_sidecar(self.path, self.runtime_pid, list(live.values()))
                self.error = None
            except Exception as error:  # a sampling failure must never break the owner
                self.error = f'descendant sampling: {type(error).__name__}: {error}'

    def finish(self) -> list[dict]:
        """Stop sampling after one final sample; return the recorded entries."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.sample()
        return list(self.entries.values())


def _targets(entries: list[dict], marker: str, exclude: set[int]) -> dict[int, Identity]:
    table = _table()
    recorded = {}
    for entry in entries:
        now = table.get(entry['pid'])
        if (now is not None and now.start == entry['start'] and now.uid == entry['uid']
                and now.pid not in exclude and not _foreign(now.pid, marker)):
            recorded[now.pid] = now
    recorded.update(_descend(table, set(recorded), marker, set(), exclude))
    return recorded


def _signal(targets: dict[int, Identity], marker: str, sig: int) -> None:
    for item in targets.values():
        # Re-verify identity and the boundary right before the signal.
        if _alive(item) and not _foreign(item.pid, marker):
            try:
                os.kill(item.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass


def _wait(targets: dict[int, Identity], seconds: float) -> dict[int, Identity]:
    deadline = time.monotonic() + seconds
    alive = dict(targets)
    while alive:
        for pid in list(alive):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not _alive(alive[pid]):
                alive.pop(pid)
        if not alive or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    return alive


def stop_tool_processes(entries: list[dict] | None, marker: str | None,
                        exclude: set[int] | frozenset[int] = frozenset(), *, grace: float = 3.0,
                        error: str | None = None) -> dict:
    """Stop recorded descendants still alive (same uid and start), their descendants, and marked processes.

    One SIGTERM, up to ``grace`` seconds, one SIGKILL, up to 2 s for all of
    them together. ``error`` (for example an unreadable record) is reported
    with any scan failure; it never turns into a silent empty result.
    """
    skipped = {os.getpid(), *exclude}
    errors = [error] if error else []
    targets: dict[int, Identity] = {}
    commands: dict[int, str] = {}
    if entries and SUPPORTED:
        try:
            targets.update(_targets(entries, marker or '', skipped))
        except (OSError, ValueError) as failure:
            errors.append(f'descendant scan: {type(failure).__name__}: {failure}')
    if marker:
        try:
            for pid, command in find_marked_processes(marker, skipped).items():
                found = identity(pid)
                if found is not None and pid not in targets:
                    targets[pid] = found
                    commands[pid] = command
        except OSError as failure:
            errors.append(f'marker scan: {type(failure).__name__}: {failure}')
    for pid in targets:
        commands.setdefault(pid, _command(_argv(pid)))
    alive = targets
    if targets:
        _signal(targets, marker or '', signal.SIGTERM)
        alive = _wait(targets, grace)
        if alive:
            _signal(alive, marker or '', signal.SIGKILL)
            alive = _wait(alive, 2.0)
    entry = lambda pid: {'pid': pid, 'command': commands[pid]}
    report = {'found': [entry(pid) for pid in sorted(targets)],
              'stopped': [entry(pid) for pid in sorted(targets) if pid not in alive],
              'remaining': [entry(pid) for pid in sorted(alive)]}
    if errors:
        report['error'] = '; '.join(errors)
    return report
