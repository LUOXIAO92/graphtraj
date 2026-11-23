"""Task 581: which Python ran graftling during one host Session, read from the process table (never from canned text).

usage:
  procs.py watch <pid> <out>              until <pid> exits, every 0.3 s: each descendant of <pid> whose command line
                                          names graftling, one line per new (pid, command) to <out>
  procs.py judge <out> <prefix> <label>   PASS when at least one Python process ran graftling and every such
                                          process's interpreter (argv[0]) lies under <prefix> (the uv install)
Only descendants of the Session are kept, so other graftling processes on the machine (another Harness, an IDE)
never count. A Python process is one whose argv[0] file name starts with 'python'.
"""
import os, subprocess, sys, time


def table():
    out = subprocess.run(['ps', '-axww', '-o', 'pid=,ppid=,command='], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2])
    return rows


def descendants(rows, root):
    children = {}
    for pid, (ppid, _) in rows.items():
        children.setdefault(ppid, []).append(pid)
    found, todo = set(), [root]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def watch(pid, out):
    seen = set()
    with open(out, 'a') as sink:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                return 0
            rows = table()
            for child in sorted(descendants(rows, pid)):
                command = rows[child][1]
                if 'graftling' in command and (child, command) not in seen:
                    seen.add((child, command))
                    sink.write(f'{child} {command}\n')
                    sink.flush()
            time.sleep(0.3)


def judge(out, prefix, label):
    prefix = prefix.rstrip('/') + '/'
    lines = [l.rstrip('\n') for l in open(out, errors='replace')] if os.path.exists(out) else []
    pythons = []
    for line in lines:
        command = line.split(' ', 1)[1] if ' ' in line else ''
        argv0 = command.split(' ', 1)[0]
        if os.path.basename(argv0).startswith('python'):
            pythons.append((argv0, command))
    for argv0, command in sorted(set(pythons)):
        print(f'  {label} graftling process: {command[:220]}')
    outside = sorted({a for a, _ in pythons if not a.startswith(prefix)})
    ok = bool(pythons) and not outside
    if not pythons:
        print(f'FAIL: {label}: no Python process running graftling was seen under the Session ({len(lines)} graftling '
              f'command line(s) sampled in {out})')
    elif outside:
        print(f'FAIL: {label}: graftling ran from an interpreter outside the uv install {prefix}: {outside}')
    else:
        print(f'PASS: {label}: every Python process running graftling ({len(set(pythons))}) started from the uv '
              f'install: {sorted({a for a, _ in pythons})}')
    return 0 if ok else 1


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['watch'] and len(a) == 3:
        sys.exit(watch(int(a[1]), a[2]))
    if a[:1] == ['judge'] and len(a) == 4:
        sys.exit(judge(a[1], a[2], a[3]))
    print(__doc__)
    sys.exit(2)
