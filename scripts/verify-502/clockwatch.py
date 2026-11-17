"""Task 502: watch the wall clock for backward steps while a test run loads the host.

    python -I clockwatch.py <seconds> <out-file>

Samples ``time.time_ns()`` (CLOCK_REALTIME, the clock behind Worldline's
``datetime.now()``) and ``time.monotonic_ns()`` every millisecond for
``<seconds>``, then exits by itself (nothing signals it). Writes one line per
wall-clock decrease between consecutive samples and per change above 2 ms in
the wall-minus-monotonic offset (a step or fast slew), then a summary line.
A Worldline append refuses with "system time precedes the chronologically last
event" only if the wall clock read went back across two appends, so a decrease
seen here during the same window shows such a step; none seen leaves it unshown.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime


def main() -> int:
    seconds, out = float(sys.argv[1]), sys.argv[2]
    end = time.monotonic_ns() + int(seconds * 1e9)
    wall, mono = time.time_ns(), time.monotonic_ns()
    offset = wall - mono
    samples = backward = jumps = 0
    largest_back = largest_jump = 0
    with open(out, 'w', encoding='utf-8') as log:
        log.write(f'clockwatch start {datetime.now().astimezone().isoformat()} for {seconds:.0f} s\n')
        log.flush()
        while mono < end:
            time.sleep(0.001)
            now_wall, now_mono = time.time_ns(), time.monotonic_ns()
            samples += 1
            stamp = datetime.fromtimestamp(now_wall / 1e9).astimezone().isoformat(timespec='microseconds')
            if now_wall < wall:
                backward += 1
                largest_back = max(largest_back, wall - now_wall)
                log.write(f'{stamp} BACKWARD wall {wall - now_wall} ns (monotonic +{now_mono - mono} ns)\n')
                log.flush()
            change = (now_wall - now_mono) - offset
            if abs(change) > 2_000_000:
                jumps += 1
                largest_jump = max(largest_jump, abs(change))
                log.write(f'{stamp} OFFSET {change:+d} ns\n')
                log.flush()
            wall, mono, offset = now_wall, now_mono, now_wall - now_mono
        log.write(f'clockwatch end: samples {samples}, backward {backward} (largest {largest_back} ns), '
                  f'offset changes >2 ms {jumps} (largest {largest_jump} ns)\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
