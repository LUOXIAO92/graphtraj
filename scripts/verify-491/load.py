"""Task 491: background CPU load for the repeat steps, bounded, with a loadavg log.

    python -I load.py <spinners> <seconds> <log file>

Starts <spinners> busy-looping Python processes, each ending by itself after <seconds>, and appends
``HH:MM:SS loadavg a b c`` to <log file> at start, every 15 s and at the end. SIGTERM (or <seconds>)
stops every spinner, writes the end line and exits.
"""
import os
import signal
import subprocess
import sys
import time

count, seconds, log = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
SPIN = 'import sys, time\nend = time.monotonic() + float(sys.argv[1])\nwhile time.monotonic() < end: pass\n'


def line(tag: str) -> None:
    with open(log, 'a') as stream:
        stream.write(f'{time.strftime("%H:%M:%S")} {tag} loadavg {" ".join(f"{x:.2f}" for x in os.getloadavg())}'
                     f' (spinners {count})\n')


spinners = [subprocess.Popen([sys.executable, '-I', '-c', SPIN, str(seconds)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL) for _ in range(count)]
stop = False


def end(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, end)
line('load start')
deadline = time.monotonic() + seconds
while not stop and time.monotonic() < deadline:
    for _ in range(150):
        if stop or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    else:
        line('during')
for spinner in spinners:
    spinner.kill()
for spinner in spinners:
    spinner.wait()
line('load end')
