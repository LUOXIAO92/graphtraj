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
or replace the marker. A descendant is judged only on a settled read (498),
from kernel facts, never from timing:

- a fork copy that has not executed yet (darwin P_EXEC clear; Linux
  PF_FORKNOEXEC set) whose readable environment lacks the marker, or whose
  read is unreadable: later, neither recorded nor cached; any other fork copy:
  provisional, recorded and judged again at every sample;
- an executed process whose read is unreadable: later (every exec window reads
  unreadable for a moment);
- an executed process with an empty environment: this execution's if it is an
  Apple platform binary (csops), else later;
- an executed process with a readable environment: the marker decides, finally.

A provisional entry that settles foreign is dropped together with every entry
recorded beneath it (by recorded parent pid), and all are cached as foreign.
At stop time the same verdict is taken again, also right before each signal:
this execution's processes and provisional ones (fork copies of ours, such as
a shell subshell, which read their parent's settled view) are signalled; one
whose read is later is never signalled and is listed under ``remaining``.

Known limits: recording can lag one sample (about a second) behind an exec; a
process that never gives a settled read (a same-user setuid program; on Linux a
tool started with ``env -i``) is never recorded; a process started and detached between two samples is reached only
through the marker scan (so not a platform binary); a process whose chain of
ancestors passed through a readable process without the marker is left alone
by design; the Linux rule is not run on a real host; Windows is not covered.
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


def has_exited(pid: int) -> bool:
    """Return whether ``pid`` is exiting or has exited and only waits for its parent to reap it.

    Such a process still answers ``kill(pid, 0)`` but runs nothing. A process
    this user cannot read is not reported as exited.
    """
    try:
        if sys.platform == 'darwin':
            # PROC_PIDT_SHORTBSDINFO=13 (64 bytes) with a nonzero arg includes exiting and zombie
            # processes (XNU findzomb): pbsi_status at 12 (SZOMB), pbsi_flags at 32 (PROC_FLAG_INEXIT 0x4).
            buffer = ctypes.create_string_buffer(64)
            if _proc().proc_pidinfo(pid, 13, 1, buffer, 64) < 64:
                return False
            status = int.from_bytes(buffer.raw[12:16], sys.byteorder)
            flags  = int.from_bytes(buffer.raw[32:36], sys.byteorder)
            return status == _ZOMBIE_DARWIN or bool(flags & 0x4)
        if sys.platform.startswith('linux'):
            stat = Path(f'/proc/{pid}/stat').read_text()
            return stat[stat.rindex(')') + 2:].split()[0] in ('Z', 'X')
    except (OSError, ValueError, IndexError):
        return False
    return False


OURS, FOREIGN, PROVISIONAL, LATER = 'ours', 'foreign', 'provisional', 'later'


def _executed(pid: int) -> bool:
    """Whether ``pid`` has executed an image since its fork (darwin P_EXEC 0x4000; Linux no PF_FORKNOEXEC 0x40)."""
    try:
        if sys.platform == 'darwin':
            buffer = ctypes.create_string_buffer(136)
            if _proc().proc_pidinfo(pid, 3, 0, buffer, 136) < 136:
                return False
            return bool(int.from_bytes(buffer.raw[0:4], sys.byteorder) & 0x4000)  # pbi_flags
        if sys.platform.startswith('linux'):
            stat = Path(f'/proc/{pid}/stat').read_text()
            return not int(stat[stat.rindex(')') + 2:].split()[6]) & 0x40  # flags, field 9
    except (OSError, ValueError, IndexError):
        return False
    return False


def _platform(pid: int) -> bool:
    """Whether ``pid`` runs an Apple platform binary (csops CS_OPS_STATUS, CS_PLATFORM_BINARY 0x4000000)."""
    if sys.platform != 'darwin':
        return False
    try:
        value = ctypes.c_uint32(0)
        return _proc().csops(pid, 0, ctypes.byref(value), 4) == 0 and bool(value.value & 0x4000000)
    except (OSError, AttributeError):
        return False


def _verdict(pid: int, marker: str) -> str:
    """The boundary rule on a settled read (module docstring): OURS, FOREIGN, PROVISIONAL or LATER."""
    executed = _executed(pid)
    view = _process_view(pid)
    if view is None:
        return LATER
    if not executed:
        return LATER if view[1] and f'{MEMBER_RUN_ENV}={marker}' not in view[1] else PROVISIONAL
    if not view[1]:
        return OURS if _platform(pid) else LATER
    return OURS if f'{MEMBER_RUN_ENV}={marker}' in view[1] else FOREIGN


def shown_command(argv: list[str] | str) -> str:
    """A command line as recorded: recognizable credentials redacted first, then cut to 300 characters.

    Tool shells carry whatever the model typed. Redaction covers only credentials it
    can recognize (Bearer tokens, ``*_KEY=``/``*TOKEN=``-style assignments, URL
    passwords, known key shapes and this process's own secret variables).
    """
    from graftling.codex.diagnostics import redact  # late: keeps ``import graftling`` light

    text = argv if isinstance(argv, str) else ' '.join(argv)
    return _command([redact(text)])


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
             skip: set[int] | frozenset[int] = frozenset(),
             verdicts: dict[int, str] | None = None) -> dict[int, Identity]:
    """Return the descendants of ``roots`` in ``table`` that are ours or provisional.

    A foreign one is cached in ``foreign``; a later one is neither returned nor
    cached. ``verdicts`` (when given) receives every judged pid's verdict.
    """
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
            verdict = _verdict(child.pid, marker)
            if verdicts is not None:
                verdicts[child.pid] = verdict
            if verdict == FOREIGN:
                foreign.add(key)
            if verdict in (FOREIGN, LATER):
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
        self._provisional: set[tuple[int, int]] = set()
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
        """Add current descendants; drop recorded ones that are gone; refresh command lines; write on change."""
        if not SUPPORTED or self.runtime_pid is None:
            return
        with self._lock:
            try:
                table = _table()
                live = {key: entry for key, entry in self.entries.items()
                        if (now := table.get(entry['pid'])) is not None and now.start == entry['start']}
                self._settle(live)
                # A first read may come between fork and exec or find argv unreadable: re-read
                # each recorded command line; an unreadable read keeps the earlier one.
                for key, entry in list(live.items()):
                    if argv := _argv(entry['pid']):
                        live[key] = {**entry, 'argv': shown_command(argv)}
                # The Runtime is a root only while its pid still has its start time.
                runtime = table.get(self.runtime_pid)
                roots = {entry['pid'] for entry in live.values()}
                if runtime is not None and runtime.start == self._runtime_start:
                    roots.add(self.runtime_pid)
                verdicts: dict[int, str] = {}
                for item in _descend(table, roots, self.marker, self._foreign, verdicts=verdicts).values():
                    key = (item.pid, item.start)
                    if verdicts.get(item.pid) == PROVISIONAL:
                        self._provisional.add(key)
                    if key not in live:
                        live[key] = {'pid': item.pid, 'ppid': item.ppid, 'pgid': item.pgid, 'uid': item.uid,
                                     'start': item.start, 'argv': shown_command(_argv(item.pid))}
                if live != self.entries:
                    self.entries = live
                    write_sidecar(self.path, self.runtime_pid, list(live.values()))
                self.error = None
            except Exception as error:  # a sampling failure must never break the owner
                self.error = f'descendant sampling: {type(error).__name__}: {error}'

    def _settle(self, live: dict[tuple[int, int], dict]) -> None:
        """Judge provisional entries again; a foreign one is dropped with every entry recorded beneath it.

        An unsettled read (later, or still a fork copy) keeps the entry provisional.
        """
        self._provisional &= set(live)
        dropped: set[tuple[int, int]] = set()
        for key in list(self._provisional):
            verdict = _verdict(live[key]['pid'], self.marker)
            if verdict == FOREIGN:
                dropped.add(key)
            elif verdict == OURS:
                self._provisional.discard(key)
        # Beneath by the recorded parent pid, transitively, even when reparented since.
        parents = {key[0] for key in dropped}
        while parents:
            below = {key for key, entry in live.items() if key not in dropped and entry.get('ppid') in parents}
            dropped |= below
            parents = {key[0] for key in below}
        for key in dropped:
            live.pop(key, None)
            self._provisional.discard(key)
            self._foreign.add(key)

    def finish(self) -> list[dict]:
        """Stop sampling after one final sample; return the recorded entries."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.sample()
        return list(self.entries.values())


def _targets(entries: list[dict], marker: str, exclude: set[int],
             unsettled: dict[int, Identity] | None = None) -> dict[int, Identity]:
    """Recorded processes still alive and their descendants that are ours or provisional; ``unsettled`` gets the later ones.

    A provisional process is a fork copy (a subshell) reading its parent's settled view, not an unsettled read.
    """
    unsettled = {} if unsettled is None else unsettled
    table = _table()
    recorded = {}
    for entry in entries:
        now = table.get(entry['pid'])
        if (now is not None and now.start == entry['start'] and now.uid == entry['uid']
                and now.pid not in exclude):
            verdict = _verdict(now.pid, marker)
            if verdict in (OURS, PROVISIONAL):
                recorded[now.pid] = now
            elif verdict == LATER:
                unsettled[now.pid] = now
    verdicts: dict[int, str] = {}
    recorded.update(_descend(table, set(recorded), marker, set(), exclude, verdicts))
    for pid, verdict in verdicts.items():
        if verdict == LATER and pid in table:
            unsettled[pid] = table[pid]
    return recorded


def _signal(targets: dict[int, Identity], marker: str, sig: int) -> None:
    for item in targets.values():
        # Re-verify identity and the boundary right before the signal: ours, or a fork copy of ours
        # (provisional); one that executed meanwhile is judged on its settled read, a later one never.
        if _alive(item) and _verdict(item.pid, marker) in (OURS, PROVISIONAL):
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
    unsettled: dict[int, Identity] = {}
    commands: dict[int, str] = {}
    if entries and SUPPORTED:
        try:
            targets.update(_targets(entries, marker or '', skipped, unsettled))
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
    # Unsettled processes (later) are never signalled; they are reported under remaining.
    unsettled = {pid: item for pid, item in unsettled.items() if pid not in targets}
    for pid in [*targets, *unsettled]:
        argv = _argv(pid)
        commands[pid] = shown_command(argv) if argv else shown_command(commands.get(pid, ''))
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
              'remaining': [entry(pid) for pid in sorted({*alive, *unsettled})]}
    if errors:
        report['error'] = '; '.join(errors)
    return report
