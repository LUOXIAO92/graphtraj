"""From Graftling's test set, the files GraphTraj can drop: no remaining GraphTraj
test or helper imports or names them (iterated to a fixed point)."""
import re, subprocess, sys
from pathlib import Path
root = Path(sys.argv[1]); graftling = set(Path(sys.argv[2]).read_text().split())
listing = subprocess.run(['git', '-C', str(root), 'ls-files', 'tests'], capture_output=True, text=True)
tracked = (set(listing.stdout.split()) if listing.returncode == 0 and listing.stdout
           else {str(p.relative_to(root)) for p in (root / 'tests').rglob('*') if p.is_file()})
move = graftling - {'tests/process_reclaim.py', 'tests/test_process_reclaim.py'}
while True:
    remaining = [p for p in tracked - move if p.endswith(('.py', '.mjs'))]
    text = {p: (root / p).read_text(errors='replace') for p in remaining}
    used = {m for m in move if any(re.search(r'\b' + re.escape(Path(m).stem) + r'\b', t) for t in text.values())}
    if not used: break
    move -= used
print('\n'.join(sorted(move)))
print('KEPT:', ' '.join(sorted(graftling - move)), file=sys.stderr)
