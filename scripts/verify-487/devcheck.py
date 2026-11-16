"""Task 487 SUITE: rerun the candidate's failing ids' files once on the dev checkout (cwd); name the NEW ones.

    python -I devcheck.py <failures.txt> <seconds>

Run with the dev test venv's Python from the dev clone. One pytest ``-rA`` run over
the failing files (an absent node id would abort a run that names it), in its own
process group, stopped (SIGTERM, then SIGKILL) past ``seconds``. As verify-480's
basecheck: NEW = failing on the candidate and passing on dev, or absent from dev.
Exit 0 only when every id is classified and none is NEW.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path


def main(failures: Path, seconds: float) -> int:
    ids = sorted({line.split()[1] for line in failures.read_text().splitlines() if len(line.split()) > 1})
    files = sorted({node.split('::')[0] for node in ids})
    present = [file for file in files if Path(file).is_file()]
    print(f'candidate failures: {len(ids)} ids in {len(files)} files; files on dev: {len(present)}; '
          f'limit {seconds:.0f} s; TMPDIR {os.environ.get("TMPDIR", "/tmp")}', flush=True)
    outcome: dict[str, str] = {}
    complete = True
    if present:
        env = {**os.environ, 'PYTEST_GRAPHTRAJ_RUN': f'devcheck-{uuid.uuid4().hex[:12]}'}
        child = subprocess.Popen([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', '-rA', *present],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                                 start_new_session=True)
        try:
            text, _ = child.communicate(timeout=seconds)
            print(f'dev pytest rc={child.returncode}:', (text.strip().splitlines() or ['no output'])[-1], flush=True)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                text, _ = child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                text, _ = child.communicate()
            complete = False
            print(f'dev pytest exceeded {seconds:.0f} s and was stopped: classification incomplete', flush=True)
        for line in (text or '').splitlines():
            parts = line.split()
            if len(parts) > 1 and parts[0] in {'PASSED', 'FAILED', 'ERROR', 'SKIPPED', 'XFAIL', 'XPASS'}:
                outcome.setdefault(parts[1], parts[0])
    new, unclassified = [], []
    for node in ids:
        seen = outcome.get(node)
        if seen in {'FAILED', 'ERROR'}:
            verdict = 'fails on dev too'
        elif seen == 'PASSED':
            verdict = 'passes on dev -> NEW'
        elif seen is None and (complete or not Path(node.split('::')[0]).is_file()):
            verdict = 'absent on dev -> NEW'
        else:
            verdict = f'dev outcome {seen or "not reached"} (unclassified)'
            unclassified.append(node)
        print(f'  {node}: {verdict}')
        if 'NEW' in verdict:
            new.append(node)
    print(f'== NEW failures (fail on the candidate, pass or are absent on dev): {len(new)}')
    for node in new:
        print('  NEW', node)
    if unclassified:
        print(f'== unclassified: {len(unclassified)}')
    return 0 if not new and not unclassified else 1


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1]), float(sys.argv[2])))
