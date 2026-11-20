"""531 profiler: prof518's stack sampler plus per-call CPU of named functions. Loaded only into a scratch venv
through prof531.pth (never into production).

It does nothing unless this process runs ``-m graphtraj.execution.runner_worker``. Then:
- a daemon thread samples every thread's Python stack about 50 times a second (as prof518);
- each function in TIMED is wrapped once its module is imported: the wrapper adds the calling thread's own CPU
  (``time.thread_time``, so other threads and waiting are not counted) of the outermost call per thread, keyed by
  the function and its nearest GraphTraj/graftling callers; ``yaml.safe_load`` and ``json.loads`` also add the
  characters parsed. Module functions are replaced in every loaded graphtraj/graftling module that holds them
  (``from x import f`` too); methods on their class.
Every 10 s one JSON line goes to ``OUT/<pid>.jsonl``: wall, process CPU, the sampler's own CPU, stacks per thread
and ``timed`` = {"function <- callers": [calls, thread CPU s, chars]}.
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
CALLERS = 6
# module, attribute (Class.method for methods)
TIMED = (
    ('yaml', 'safe_load'),
    ('json', 'loads'),
    ('graphtraj.graph.delivery_worldline', '_read_shards'),
    ('graphtraj.execution.runner_status', '_read_alias_record'),
    ('graphtraj.execution.runner_status', 'retained_session_directories'),
    ('graphtraj.runtimes.codex.access', 'project_history_files'),
    ('graphtraj.runtimes.claude.adapter', '_validated_resources'),
    ('graphtraj.runtimes.claude.adapter', 'ClaudeRuntimeAdapter.preflight_runtime_context'),
    ('graftling.sessions.archive', 'native_session_files'),
    ('graftling.control', 'AgentControl.create'),
    ('graftling.control', 'AgentControl.registration'),
    ('graftling.control', 'AgentControl._load'),
    ('graphtraj.execution.agent_driver', 'AdapterDriver.prepare'),
    ('graphtraj.interfaces.agents', 'GraphTrajAgents.reconcile_children'),
)
STATS: dict[str, list] = {}
_LOCK = threading.Lock()
_LOCAL = threading.local()
_DONE: set = set()


def _callers(frame) -> str:
    names = []
    while frame is not None and len(names) < CALLERS:
        name = frame.f_code.co_filename
        if '/graphtraj/' in name or '/graftling/' in name:
            names.append(f'{os.path.basename(name)}:{frame.f_code.co_name}')
        frame = frame.f_back
    return ' < '.join(names) or '-'


def _timed(original, name: str, sized: bool):
    def timed(*args, **kwargs):
        active = getattr(_LOCAL, 'active', None)
        if active is None:
            active = _LOCAL.active = set()
        if name in active:  # recursion: only the outermost call is timed
            return original(*args, **kwargs)
        active.add(name)
        size = 0
        if sized and args and isinstance(args[0], (str, bytes)):
            size = len(args[0])
        key = f'{name} <- {_callers(sys._getframe(1))}'
        begin = time.thread_time()
        try:
            return original(*args, **kwargs)
        finally:
            spent = time.thread_time() - begin
            active.discard(name)
            with _LOCK:
                item = STATS.setdefault(key, [0, 0.0, 0])
                item[0] += 1
                item[1] += spent
                item[2] += size

    timed._prof531 = original
    timed.__name__ = getattr(original, '__name__', name)
    timed.__qualname__ = getattr(original, '__qualname__', name)
    timed.__doc__ = getattr(original, '__doc__', None)
    timed.__wrapped__ = original
    return timed


def _patch() -> None:
    """Wrap every TIMED function whose module is imported now (once each)."""
    for module_name, attribute in TIMED:
        if (module_name, attribute) in _DONE:
            continue
        module = sys.modules.get(module_name)
        if module is None:
            continue
        owner, _, method = attribute.rpartition('.')
        target = getattr(module, owner, None) if owner else module
        if target is None or not hasattr(target, method):
            continue
        original = target.__dict__.get(method) if isinstance(target, type) else getattr(target, method)
        if original is None or getattr(original, '_prof531', None) is not None:
            _DONE.add((module_name, attribute))
            continue
        name = f'{module_name.rsplit(".", 1)[-1]}.{attribute}'
        wrapper = _timed(original, name, module_name in ('yaml', 'json'))
        if isinstance(target, type):
            setattr(target, method, wrapper)
        else:
            for other in list(sys.modules.values()):
                other_name = getattr(other, '__name__', '') or ''
                if other is module or other_name.startswith(('graphtraj', 'graftling')):
                    try:
                        for key, value in list(vars(other).items()):
                            if value is original:
                                setattr(other, key, wrapper)
                    except TypeError:
                        continue
        _DONE.add((module_name, attribute))


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
        _patch()  # modules a late import brings (a module imported after a window still loses no later call)
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
                timed = {key: [value[0], round(value[1], 4), value[2]] for key, value in STATS.items()}
                STATS.clear()
            line = {'at': wall, 'wall': wall - begin_wall, 'cpu': cpu - begin_cpu, 'sampler_cpu': own - begin_own,
                    'ticks': ticks, 'timed': timed, 'threads': counts, 'wrapped': sorted('.'.join(x) for x in _DONE)}
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(line) + '\n')
            begin_wall, begin_cpu, begin_own, counts, ticks = wall, cpu, own, {}, 0


if 'graphtraj.execution.runner_worker' in getattr(sys, 'orig_argv', ()):
    import yaml

    _patch()
    threading.Thread(target=_run, daemon=True, name='prof531').start()
