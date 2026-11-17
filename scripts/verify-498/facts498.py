"""498 F: read-only facts about live executions' Runtimes and their descendants, and retained sidecars.

Usage: python -I facts498.py <worktree src dir> <harness dir> [extra sidecar dirs...]
Never sends a signal, never writes a file (output goes to stdout), never prints an
environment value or a marker value; command lines only through shown_command,
cut to 160 characters. Classes only: env None / empty / readable; marker this
execution's (the Runtime's own value) / other / none.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, sys.argv[1])
from graftling.member_processes import MEMBER_RUN_ENV, _process_view  # noqa: E402
from graftling.tool_descendants import _table, identity, shown_command  # noqa: E402

libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True) if sys.platform == 'darwin' else None
MANAGED = re.compile(r'runner_worker|agent-runner|team_round|graphtraj(-session)? |budget_idle_timer|app-server|'
                     r'--output-format|codex|pi-coding-agent|dsh|graftling')


def flags(pid):
    if libproc is None:
        return None
    buffer = ctypes.create_string_buffer(136)
    if libproc.proc_pidinfo(pid, 3, 0, buffer, 136) < 136:
        return None
    return int.from_bytes(buffer.raw[0:4], sys.byteorder)


def code_signing(pid):
    if libproc is None:
        return None
    value = ctypes.c_uint32(0)
    return value.value if libc.csops(pid, 0, ctypes.byref(value), 4) == 0 else None


def path_of(pid):
    if libproc is None:
        try:
            return os.readlink(f'/proc/{pid}/exe')
        except OSError:
            return None
    buffer = ctypes.create_string_buffer(4096)
    return buffer.value.decode(errors='replace') if libproc.proc_pidpath(pid, buffer, 4096) > 0 else None


def marker_of(view):
    if not view or not view[1]:
        return None
    for item in view[1]:
        if item.startswith(MEMBER_RUN_ENV + '='):
            return item.split('=', 1)[1]
    return ''


def classify(pid, runtime_marker):
    view = _process_view(pid)
    env = 'None' if view is None else ('empty' if not view[1] else 'readable')
    value = marker_of(view)
    marker = ('n/a' if value is None else 'none' if value == '' else
              'this' if runtime_marker and value == runtime_marker else 'other')
    now, f, cs = identity(pid), flags(pid), code_signing(pid)
    try:
        sid = os.getsid(pid)
    except OSError:
        sid = None
    return {'pid': pid, 'ppid': now.ppid if now else None, 'pgid': now.pgid if now else None, 'sid': sid,
            'session_leader': None if f is None else bool(f & 0x20),
            'P_EXEC': None if f is None else bool(f & 0x4000),
            'platform': None if cs is None else bool(cs & 0x4000000),
            'hardened': None if cs is None else bool(cs & 0x10000),
            'exe': path_of(pid), 'env': env, 'marker': marker,
            'argv': shown_command(view[0])[:160] if view and view[0] else ''}


def table():
    """This user's live processes by pid -> ppid (libproc / /proc, as the sampler reads them; no ps)."""
    return {pid: item.ppid for pid, item in _table().items()}


def sidecars(harness, extra):
    found = set()
    roots = [os.environ.get('TMPDIR', '/tmp'), '/tmp', '/private/tmp', *extra]
    try:
        roots.append(subprocess.run(['/usr/bin/getconf', 'DARWIN_USER_TEMP_DIR'], capture_output=True,
                                    text=True).stdout.strip())
    except OSError:
        pass
    for root in filter(None, roots):
        for depth in ('', '*/', '*/*/', '*/*/*/'):
            found.update(glob.glob(os.path.join(root, depth + 'tool-descendants-*.json')))
    # Paths the execution records name (bounded walk of the Harness records).
    deadline, pattern = time.monotonic() + 40, re.compile(rb'"tool_descendants":\s*"([^"]+)"')
    for directory, _, names in os.walk(os.path.join(harness, '.graphtraj')):
        if time.monotonic() > deadline:
            print('note: record walk stopped at 40 s')
            break
        for name in names:
            if name.endswith('.json'):
                path = os.path.join(directory, name)
                try:
                    if os.path.getsize(path) < 4_000_000:
                        with open(path, 'rb') as stream:
                            found.update(match.decode() for match in pattern.findall(stream.read()))
                except OSError:
                    pass
    return sorted({os.path.realpath(path) for path in found})


def main():
    harness = sys.argv[2]
    paths = sidecars(harness, sys.argv[3:])
    rows = table()
    children = {}
    for pid, ppid in rows.items():
        children.setdefault(ppid, []).append(pid)
    print(f'sidecar paths found or named by records: {len(paths)}; existing: {sum(map(os.path.exists, paths))}')
    live = retained = 0
    summary = {'entries': 0, 'alive now': 0, 'alive now, env readable without this marker': 0,
               'recorded argv looks like a managed launch or Runtime': 0, 'recorded argv empty': 0}
    for path in paths:
        try:
            document = json.load(open(path, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        runtime_pid = document.get('runtime_pid')
        entries = document.get('entries') or []
        runtime_live = isinstance(runtime_pid, int) and identity(runtime_pid) is not None
        runtime_view = _process_view(runtime_pid) if runtime_live else None
        runtime_marker = marker_of(runtime_view) or None
        retained += not runtime_live
        if not runtime_live and not entries:
            continue  # counted only
        print(f'\n## sidecar ...{path[-60:]} runtime_pid={runtime_pid} live={runtime_live} entries={len(entries)} '
              f'mtime={time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path)))}')
        for entry in entries:
            summary['entries'] += 1
            argv = str(entry.get('argv', ''))
            summary['recorded argv empty'] += not argv
            if MANAGED.search(argv):
                summary['recorded argv looks like a managed launch or Runtime'] += 1
                print(f'  recorded managed-looking entry pid={entry.get("pid")} argv={argv[:120]!r}')
            now = identity(entry['pid']) if isinstance(entry.get('pid'), int) else None
            if now is not None and now.start == entry.get('start'):
                summary['alive now'] += 1
                fact = classify(entry['pid'], runtime_marker)
                if fact['env'] == 'readable' and fact['marker'] != 'this':
                    summary['alive now, env readable without this marker'] += 1
                print('  recorded and alive:', json.dumps(fact))
        if not runtime_live:
            continue
        live += 1
        print('  runtime:', json.dumps(classify(runtime_pid, runtime_marker)),
              '| runtime marker readable:', runtime_marker is not None)
        pending = list(children.get(runtime_pid, []))
        recorded = {entry.get('pid') for entry in entries}
        while pending:
            pid = pending.pop(0)
            fact = classify(pid, runtime_marker)
            fact['recorded'] = pid in recorded
            print('  descendant:', json.dumps(fact))
            pending.extend(children.get(pid, []))
    print(f'\nlive executions with a sidecar: {live}; sidecars whose Runtime is gone: {retained}')
    print('retained/all sidecar entries:', json.dumps(summary))


if __name__ == '__main__':
    main()
