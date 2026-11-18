"""Read only: per retained production Nw468-ps.txt, the Worker's CPU bursts (10 s windows above 0.5) and phases."""
import json, sys
from datetime import datetime
from pathlib import Path
def sec(t):
    d, _, t = t.rpartition('-'); s = 0.0
    for p in t.split(':'): s = s * 60 + float(p)
    return (int(d) if d else 0) * 86400 + s
for f in sys.argv[1:]:
    rows = [json.loads(l) for l in Path(f).read_text().splitlines() if l.strip()]
    pts = [(r['at'], sec(r['ps'].split()[3]), r.get('child_running')) for r in rows]
    first_child = next((a for a, _, c in pts if c), None)
    end_child = next((a for (a, _, c), (_, _, pc) in zip(pts[1:], pts) if pc and c is False), None)
    bursts, cur = [], None
    for (a0, c0, k0), (a1, c1, k1) in zip(pts, pts[1:]):
        rate = (c1 - c0) / max(a1 - a0, 1e-9)
        if rate > 0.5:
            cur = cur or [a0, a1, 0.0]; cur[1] = a1; cur[2] += c1 - c0
        elif cur:
            bursts.append(cur); cur = None
    if cur: bursts.append(cur)
    t0 = pts[0][0]
    tag = f.split('/tasks/')[1].split('/')[0]
    rel = lambda a: f'{a - t0:5.0f}s' if a is not None else '  n/a'
    print(f'{tag}: {len(pts)} samples over {pts[-1][0]-t0:.0f}s, total {pts[-1][1]-pts[0][1]:.0f} CPU-s; child created ~{rel(first_child)}, ended ~{rel(end_child)}')
    for b in bursts:
        print(f'   burst {rel(b[0])} .. {rel(b[1])}: {b[2]:5.1f} CPU-s ({b[2]/(b[1]-b[0]):.2f})')
