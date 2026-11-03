"""Run the 392 unattended steps one at a time; started by run-unattended.zsh.

Usage: python -I run_unattended.py <steps directory> <step> [<step> ...]

Each step runs as its own ``zsh <step>.zsh`` on this Terminal, in the foreground. A step's failure
never stops the run. A step with a finished result for this commit is skipped, so running again
continues. ``realhost/run-unattended/summary.txt`` is rewritten after each step.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

LIMIT_FLOOR_MINUTES = 45
# After the limit: time for the step's own shell to save, then for it to save once its children are gone.
TERM_SECONDS = 30
KILL_SECONDS = 20

STEPS_DIRECTORY = Path(sys.argv[1])
STEPS = sys.argv[2:]
AG = Path(os.environ['AGENTS_392_AG'])
REALHOST = Path(os.environ['AGENTS_392_REALHOST'])
COMMIT = os.environ['AGENTS_392_COMMIT']
FROM = os.environ.get('AGENTS_392_FROM')
RERUN = bool(os.environ.get('AGENTS_392_RERUN'))
OWN = REALHOST / ('run-rerun' if RERUN else 'run-unattended')
# Only the dry run sets these: a short limit, and a directory for a step that exists only there.
DRY_LIMIT = os.environ.get('AGENTS_392_DRY_LIMIT_SECONDS')
DRY_STEPS = os.environ.get('AGENTS_392_DRY_STEP_DIR')
DRY_SLEPT_STEP = os.environ.get('AGENTS_392_DRY_SLEPT_STEP')
DRY_SLEPT_SECONDS = os.environ.get('AGENTS_392_DRY_SLEPT_SECONDS', '0')
# A step whose two clocks differ by more than this slept.
SLEEP_SECONDS = 60


def rerun_start() -> str:
    """Return this rerun's start time; it is kept, so running again continues, until ``--restart``."""
    record = OWN / 'started.txt'
    if os.environ.get('AGENTS_392_RESTART') or not record.is_file():
        OWN.mkdir(parents=True, exist_ok=True)
        (OWN / 'elapsed.json').unlink(missing_ok=True)
        record.write_text(time.strftime('%Y%m%dT%H%M%S') + '\n')
    return record.read_text().strip()


# A result older than this does not count as finished. Empty outside a rerun, so nothing is older.
SINCE = rerun_start() if RERUN else ''


def step_file(step: str) -> Path:
    """Return the file of one step."""
    path = STEPS_DIRECTORY / f'{step}.zsh'
    return Path(DRY_STEPS) / f'{step}.zsh' if DRY_STEPS and not path.exists() else path


def limit_seconds(step: str) -> float:
    """Return a step's wall limit: the larger of 45 minutes and 3 times its expected minutes."""
    if DRY_LIMIT:
        return float(DRY_LIMIT)
    found = re.search(r'^step_begin \S+ (\d+)', step_file(step).read_text(), re.M)
    return 60 * max(LIMIT_FLOOR_MINUTES, 3 * int(found.group(1)) if found else 0)


def finished(step: str) -> bool:
    """Say whether this step already holds a finished result for this commit."""
    saved = REALHOST / step
    record = saved / 'run.txt'
    return (record.is_file() and f'code {COMMIT} ' in record.read_text(errors='replace')
            and record.read_text(errors='replace').split()[-1] >= SINCE
            and not (saved / 'slept.txt').is_file()
            and ((saved / 'finished.txt').is_file() or (saved / 'limit.txt').is_file()))


def counts(step: str) -> dict:
    """Return the PASS, FAIL and CANNOT lines of a step's saved summary."""
    found = {'PASS': 0, 'FAIL': 0, 'CANNOT': 0}
    summary = REALHOST / step / 'summary.txt'
    for line in summary.read_text(errors='replace').splitlines() if summary.is_file() else []:
        state = line.split(' ', 1)[0]
        if state in found:
            found[state] += 1
    return found


def write_summary(elapsed: dict) -> None:
    """Rewrite the run's summary and keep each step's minutes, so a partial run stays readable."""
    OWN.mkdir(parents=True, exist_ok=True)
    (OWN / 'elapsed.json').write_text(json.dumps(elapsed, indent=1))
    lines = [f'code {COMMIT}; updated {time.strftime("%Y-%m-%dT%H:%M:%S")}; one line per step: '
             'state PASS FAIL CANNOT minutes']
    for step in STEPS:
        saved = REALHOST / step
        state = ('not run' if step not in elapsed and not finished(step) else
                 f'slept {(saved / "slept.txt").read_text().strip()} min' if (saved / 'slept.txt').is_file() else
                 'limit' if (saved / 'limit.txt').is_file() else
                 'finished' if finished(step) else 'stopped early')
        # In a rerun, an earlier result's counts are not this run's.
        number = {'PASS': 0, 'FAIL': 0, 'CANNOT': 0} if RERUN and state == 'not run' else counts(step)
        minutes = f'{elapsed[step]:.1f}' if step in elapsed else '-'
        lines.append(f'{step}: {state}; PASS {number["PASS"]} FAIL {number["FAIL"]} CANNOT {number["CANNOT"]}; {minutes} min')
    temporary = OWN / 'summary.txt.tmp'
    temporary.write_text('\n'.join(lines) + '\n')
    temporary.replace(OWN / 'summary.txt')


def descendants(listing: str, root: int) -> list[tuple[int, str]]:
    """Return ``root`` and every process under it, as (pid, command), from ``ps -o pid=,ppid=,comm=`` text."""
    children: dict[int, list[tuple[int, str]]] = {}
    named = {root: ''}
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append((int(parts[0]), parts[2]))
            named[int(parts[0])] = parts[2]
    found, pending = [(root, named[root])], [root]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child[0])
    return found


def process_tree(root: int) -> list[tuple[int, str]]:
    """Return the step's processes now; only the root when the process list cannot be read."""
    try:
        listing = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,comm='], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ''
    return descendants(listing, root)


def signal_all(members: list[tuple[int, str]], number: int, skip: tuple = ()) -> None:
    """Signal each process except those whose command's last word is in ``skip``."""
    for pid, command in members:
        if command.rsplit('/', 1)[-1] not in skip:
            try:
                os.kill(pid, number)
            except OSError:
                pass


def wait_for(process: subprocess.Popen, seconds: float) -> bool:
    """Say whether the process ended within ``seconds``."""
    try:
        process.wait(seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def end_step(process: subprocess.Popen) -> None:
    """End a step at its limit, its children included, giving its own shell the chance to save.

    script(1) is left alone at first: closing its terminal would end the step's shell before it saved.
    """
    seen = process_tree(process.pid)
    signal_all(seen, signal.SIGTERM, skip=('script',))
    if not wait_for(process, TERM_SECONDS):
        members = process_tree(process.pid)
        seen += members
        signal_all(members, signal.SIGKILL, skip=('script', 'zsh'))
        if not wait_for(process, KILL_SECONDS):
            members = process_tree(process.pid)
            seen += members
            signal_all(members, signal.SIGKILL)
            process.kill()
            process.wait()
    # What outlived its parent, a stopped child for one, is still reachable by the pid seen above.
    signal_all(seen, signal.SIGKILL)
    subprocess.run(['/bin/stty', 'sane'], stderr=subprocess.DEVNULL)


def record_limit(step: str, started: str, seconds: float) -> None:
    """Make sure the evidence reached the Harness, then add the FAIL line naming the limit."""
    runs = sorted(path for path in (AG / 'runs').glob(f'{step}-*') if path.name.rsplit('-', 1)[-1] >= started)
    run = runs[-1] if runs else AG / 'runs' / f'{step}-{started}'
    evidence = run / 'out'
    evidence.mkdir(parents=True, exist_ok=True)
    record = evidence / 'run.txt'
    if not record.exists():
        record.write_text(f'step {step} code {COMMIT} started {started}\n')
    saved = REALHOST / step
    # A shell that saved before it ended left this same run.txt in the Harness.
    held = (saved / 'run.txt').read_text(errors='replace') if (saved / 'run.txt').is_file() else None
    if held != record.read_text(errors='replace'):
        subprocess.run([sys.executable, '-I', str(STEPS_DIRECTORY / 'save_step.py'), str(evidence), str(saved), str(run / 'saved.txt')])
    if not (run / 'saved.txt').is_file() and held != record.read_text(errors='replace'):
        print(f'NOT SAVED: the scan did not finish. Evidence stays in {evidence}.', flush=True)
        saved.mkdir(parents=True, exist_ok=True)
        (saved / 'run.txt').write_text(record.read_text())
    line = (f'FAIL {step} ended by the wall limit of the unattended run, {seconds / 60:.1f} minutes; what it had written '
            f'by then is here, and the rest of its scratch is in {run}\n')
    with (saved / 'summary.txt').open('a') as summary:
        summary.write(line)
    (saved / 'limit.txt').write_text(line)
    print(line, end='', flush=True)


def record_sleep(step: str, seconds: float) -> None:
    """Say so in the step's saved result if the Mac slept through it; a rerun then runs it again."""
    if seconds <= SLEEP_SECONDS:
        return
    minutes = f'{seconds / 60:.1f}'
    saved = REALHOST / step
    saved.mkdir(parents=True, exist_ok=True)
    line = f'CANNOT {step} the Mac slept {minutes} minutes during this step; its result says nothing and it needs a rerun\n'
    with (saved / 'summary.txt').open('a') as summary:
        summary.write(line)
    (saved / 'slept.txt').write_text(minutes + '\n')
    print(line, end='', flush=True)


def run_step(step: str) -> float:
    """Run one step to its end or its limit; return its elapsed minutes."""
    seconds = limit_seconds(step)
    print(f'\n===== {step}: at most {seconds / 60:.1f} minutes; nothing to type', flush=True)
    started = time.strftime('%Y%m%dT%H%M%S')
    begun = time.monotonic()
    wall = time.time()
    process = subprocess.Popen(['/bin/zsh', str(step_file(step))])
    if not wait_for(process, seconds):
        print(f'{step} reached its limit; ending it.', flush=True)
        end_step(process)
        record_limit(step, started, seconds)
    elif process.returncode not in (0, 1):
        print(f'{step} exited {process.returncode}; going on.', flush=True)
    # macOS's monotonic clock stops while the Mac sleeps; the wall clock does not.
    awake = time.monotonic() - begun
    faked = float(DRY_SLEPT_SECONDS) if step == DRY_SLEPT_STEP else 0
    record_sleep(step, time.time() - wall - awake + faked)
    return awake / 60


GATES = ('00-preflight', '01-install')


def gate_failing(step: str) -> list[str]:
    """Return the FAIL lines that stop a run after 00 or 01; with --despite-dsh, 00's dsh line does not."""
    summary = REALHOST / step / 'summary.txt'
    lines = summary.read_text(errors='replace').splitlines() if summary.is_file() else ['FAIL no summary was saved']
    return [line for line in lines if line.startswith('FAIL ')
            and not (os.environ.get('AGENTS_392_DESPITE_DSH') and line.startswith('FAIL dsh answers'))]


def main() -> int:
    """Run the steps in order; nothing here stops the run but the user's own interrupt."""
    print('Keep the lid open for the whole run: caffeinate -i stops idle sleep but does not hold a closed lid. '
          'A step the Mac sleeps through says nothing and needs a rerun.', flush=True)
    elapsed = json.loads((OWN / 'elapsed.json').read_text()) if (OWN / 'elapsed.json').is_file() else {}
    write_summary(elapsed)
    for step in STEPS[STEPS.index(FROM) if FROM else 0:]:
        if finished(step) and step != FROM:
            print(f'skipped {step}: realhost/{step} already holds a finished result for {COMMIT}', flush=True)
            continue
        try:
            elapsed[step] = run_step(step)
        except KeyboardInterrupt:
            print('\nInterrupted. Run the same command again to continue.', flush=True)
            return 130
        except Exception as error:
            print(f'{step}: the runner could not run it: {type(error).__name__}: {error}; going on.', flush=True)
        write_summary(elapsed)
        if step in GATES and gate_failing(step):
            print(f'STOP: realhost/{step}/summary.txt has a FAIL line, so the run ends here: '
                  f'{gate_failing(step)}. Tell Main.', flush=True)
            return 1
    print(f'\nSaved summary: {OWN / "summary.txt"}')
    print((OWN / 'summary.txt').read_text())
    print('Tell Main the rerun is finished.' if RERUN else 'Tell Main the run is finished.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
