"""518 stack sampler and call counter, loaded only into a scratch venv through prof518.pth (never into production).

It does nothing unless this process runs ``-m graphtraj.execution.runner_worker``. Then a daemon thread reads
every thread's Python stack about 50 times a second and, every 10 s, appends one JSON line to ``OUT/<pid>.jsonl``:
the window's wall and process CPU seconds, per thread the count of each stack (innermost frame first,
``file:function:line``, up to DEPTH frames), and the window's call counts of a few whole-record readers
(``_read_shards`` = one whole Worldline read; ``yaml.safe_load`` and ``json.loads`` with the characters parsed;
``_read_alias_record`` = one Runner Session record lookup). Its own cost is in each window's ``sampler_cpu``.
"""
import json
import os
import sys
import threading
import time

OUT = '@OUT@'
PERIOD = 0.02
WINDOW = 10.0
DEPTH = 60
COUNTS: dict[str, list] = {}
_LOCK = threading.Lock()


def _count(name: str, size: int = 0) -> None:
    with _LOCK:
        item = COUNTS.setdefault(name, [0, 0])
        item[0] += 1
        item[1] += size


def _wrap(module, attribute: str, name: str, sized: bool = False) -> None:
    original = getattr(module, attribute)
    if getattr(original, '_prof518', False):
        return

    def counted(*args, **kwargs):
        size = 0
        if sized and args:
            value = args[0]
            size = len(value) if isinstance(value, (str, bytes)) else 0
        _count(name, size)
        return original(*args, **kwargs)

    counted._prof518 = True
    setattr(module, attribute, counted)


def _patch_late() -> None:
    """Wrap module-level helpers that their own module calls by global name, once they are imported."""
    worldline = sys.modules.get('graphtraj.graph.delivery_worldline')
    if worldline is not None:
        _wrap(worldline, '_read_shards', 'worldline._read_shards')
    status = sys.modules.get('graphtraj.execution.runner_status')
    if status is not None:
        _wrap(status, '_read_alias_record', 'runner_status._read_alias_record')


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
        _patch_late()
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
            with _LOCK:
                calls = {name: list(value) for name, value in COUNTS.items()}
                COUNTS.clear()
            line = {'at': wall, 'wall': wall - begin_wall, 'cpu': cpu - begin_cpu, 'sampler_cpu': own - begin_own,
                    'ticks': ticks, 'calls': calls, 'threads': counts}
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(line) + '\n')
            begin_wall, begin_cpu, begin_own, counts, ticks = wall, cpu, own, {}, 0


if 'graphtraj.execution.runner_worker' in getattr(sys, 'orig_argv', ()):
    import yaml

    _wrap(yaml, 'safe_load', 'yaml.safe_load', sized=True)
    _wrap(json, 'loads', 'json.loads', sized=True)
    threading.Thread(target=_run, daemon=True, name='prof518').start()
