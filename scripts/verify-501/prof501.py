"""501 stack sampler, loaded only into a scratch venv through prof501.pth (never into production).

It does nothing unless this process runs ``-m graphtraj.execution.runner_worker``. Then a daemon
thread reads every thread's Python stack about 50 times a second and, every 10 s, appends one JSON
line to ``OUT/<pid>.jsonl``: the window's wall and process CPU seconds and, per thread, the count of
each stack (innermost frame first, ``file:function:line``). A thread blocked in C (a lock, a read,
``time.sleep``) shows the Python line that called it, so the report sorts stacks against the
window's CPU. Its own cost is in each window's ``sampler_cpu`` (thread CPU of the sampler itself).
"""
import json
import os
import sys
import threading
import time

OUT = '@OUT@'
PERIOD = 0.02
WINDOW = 10.0
DEPTH = 14


def _stack(frame) -> str:
    parts = []
    while frame is not None and len(parts) < DEPTH:
        code = frame.f_code
        parts.append(f'{os.path.basename(code.co_filename)}:{code.co_name}:{frame.f_lineno}')
        frame = frame.f_back
    return ' < '.join(parts)


def _run() -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{os.getpid()}.jsonl')
    me = threading.get_ident()
    begin_wall, begin_cpu, begin_own = time.time(), time.process_time(), time.thread_time()
    counts: dict[str, dict[str, int]] = {}
    ticks = 0
    while True:
        time.sleep(PERIOD)
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            if ident == me:
                continue
            per = counts.setdefault(names.get(ident, str(ident)), {})
            key = _stack(frame)
            per[key] = per.get(key, 0) + 1
        ticks += 1
        wall = time.time()
        if wall - begin_wall >= WINDOW:
            cpu, own = time.process_time(), time.thread_time()
            line = {'at': wall, 'wall': wall - begin_wall, 'cpu': cpu - begin_cpu, 'sampler_cpu': own - begin_own,
                    'ticks': ticks, 'threads': counts}
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(line) + '\n')
            begin_wall, begin_cpu, begin_own, counts, ticks = wall, cpu, own, {}, 0


if 'graphtraj.execution.runner_worker' in getattr(sys, 'orig_argv', ()):
    threading.Thread(target=_run, daemon=True, name='prof501').start()
