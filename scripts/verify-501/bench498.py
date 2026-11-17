"""501: the CPU cost of one DescendantSampler.sample() (459/498), for one graftling source.

usage: python -I bench498.py <directory holding graftling/> <label> [samples]

It starts its own root shell with the member marker and six marked ``sleep`` tool processes below it
(like a Claude child holding six tool processes), samples them with that graftling's sampler, prints
the CPU seconds per sample (thread time) and what that costs at the sampler's 1 Hz, then stops only
the processes it started. Pre-498 is ``src/graftling`` at 2da634af (497); 498 is 871aaaa9; production
is graftling 0.5.2.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import graftling  # noqa: E402
from graftling import tool_descendants  # noqa: E402

label, count = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 60
marker = f'bench501-{os.getpid()}'
env = {**os.environ, tool_descendants.MEMBER_RUN_ENV: marker}
root = subprocess.Popen(['/bin/sh', '-c', 'sleep 301 & sleep 302 & sleep 303 & sleep 304 & sleep 305 & sleep 300'],
                        env=env, start_new_session=True)
try:
    time.sleep(1.0)
    with tempfile.TemporaryDirectory() as scratch:
        sampler = tool_descendants.DescendantSampler(Path(scratch) / 'sidecar.json', marker)
        sampler.prepare()
        sampler.runtime_pid = root.pid
        identity = tool_descendants.identity(root.pid)
        sampler._runtime_start = identity.start if identity is not None else None
        sampler.sample()  # first sample records the entries
        users = len(list(tool_descendants._user_pids()))
        began_cpu, began = time.thread_time(), time.perf_counter()
        for _ in range(count):
            sampler.sample()
        cpu, wall = time.thread_time() - began_cpu, time.perf_counter() - began
    print(f'{label}: graftling {graftling.__file__} | entries {len(sampler.entries)} | this user\'s pids {users} | '
          f'{count} samples: {cpu / count * 1000:.2f} ms CPU and {wall / count * 1000:.2f} ms wall per sample '
          f'= {cpu / count / tool_descendants.SAMPLE_SECONDS:.4f} CPU-s per wall-s at '
          f'{1 / tool_descendants.SAMPLE_SECONDS:.0f} Hz | error {sampler.error}')
finally:
    os.killpg(root.pid, 15)  # the group this script started
    root.wait()
