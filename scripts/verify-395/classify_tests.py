"""Compute Graftling's test set from a GraphTraj checkout.

A test module belongs to Graftling when it mentions graftling (or its old name
agent_swarm) and neither it nor any tests/ module it imports (transitively,
excluding conftest) imports graphtraj. Helper modules and fixture files under
tests/fixtures that they name are included. Prints one repo-relative path per
line; names given as extra arguments are excluded explicitly."""
import ast, re, sys
from pathlib import Path
root = Path(sys.argv[1]); tests = root / 'tests'
EXCLUDE = set(sys.argv[2:])
mods = {p.stem: p for p in tests.glob('*.py')}
def imports(p):
    out = set()
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.Import): out |= {a.name.split('.')[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0: out.add(n.module.split('.')[0])
    return out
def closure(p):
    seen, todo = set(), [p]
    while todo:
        q = todo.pop()
        if q in seen: continue
        seen.add(q)
        todo += [mods[m] for m in imports(q) if m in mods and m != 'conftest']
        # Helpers a test copies or runs by file name (with_name('x.py'), tests/x.py).
        for name in re.findall(r"['\"/]([A-Za-z0-9_]+)\.py['\"]", q.read_text()):
            if name in mods and name != 'conftest':
                todo.append(mods[name])
    return seen
def direct_graphtraj(p):
    t = p.read_text()
    # Also an import inside a subprocess program held in a string.
    return ('graphtraj' in imports(p) or re.search(r"import_module\(\s*['\"]graphtraj", t)
            or re.search(r"(?m)(?:^|[\s;'\"(])(?:import|from)\s+graphtraj\b", t))
keep = set()
for p in sorted(tests.glob('test_*.py')):
    if p.name in EXCLUDE: continue
    t = p.read_text()
    if not ('graftling' in t or 'agent_swarm' in t or p.name == 'test_process_reclaim.py'): continue
    c = closure(p)
    if any(direct_graphtraj(q) for q in c): continue
    keep |= c
fixtures = set()
for p in keep:
    for name in re.findall(r"fixtures/([A-Za-z0-9_.\-]+)", p.read_text()):
        f = tests / 'fixtures' / name
        if f.exists(): fixtures.add(f)
for p in sorted(keep | fixtures): print(p.relative_to(root))
