"""A Runner Worker waiting on its working Claude member stays nearly idle (468)."""
import ctypes
import ctypes.util
import os
from pathlib import Path
import sys
import time

import yaml

from conftest import FakeCodex, InstalledCommands
from test_claude_runner import command, settled, setup
from test_task_recovery import events


IDLE_SECONDS = 6.0


def cpu_seconds(pid: int) -> float:
    """Return a live process's user plus system CPU time without extra packages."""
    if sys.platform == 'darwin':
        # proc_taskinfo (PROC_PIDTASKINFO = 4): total user and system time,
        # in Mach time units, are its third and fourth 64-bit fields.
        libc = ctypes.CDLL(ctypes.util.find_library('c'))
        info = (ctypes.c_uint64 * 12)()
        assert libc.proc_pidinfo(pid, 4, ctypes.c_uint64(0), info, ctypes.sizeof(info)) == ctypes.sizeof(info)
        timebase = (ctypes.c_uint32 * 2)()
        assert libc.mach_timebase_info(timebase) == 0
        return (info[2] + info[3]) * timebase[0] / timebase[1] / 1e9
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')


def test_worker_waiting_on_a_working_member_does_not_spin(
    installed_commands: InstalledCommands,
    temporary_git_repository: Path,
    fake_codex: FakeCodex,
    tmp_path: Path,
) -> None:
    """While the member's turn is open and silent, its Worker uses little CPU.

    The Task has an execution budget, so the Worker's budget monitor runs too.
    """
    root, environment = setup(installed_commands, temporary_git_repository, fake_codex, tmp_path)
    batch = root / 'probe.yml'
    batch.write_text(yaml.safe_dump({'tasks': [{'task_id': '320', 'role': 'researcher'}]}))
    launched = command(installed_commands, root, environment, '--swarm-input', str(batch))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    alias = yaml.safe_load(launched.stdout)['tasks'][0]['alias']
    settled(installed_commands, root, environment, alias)
    sent = command(installed_commands, root, environment, 'send', alias, '--instruction', 'wait',
                   '--caused-by-event-id', events(root)[-1]['event_id'])
    assert sent.returncode == 0, sent.stdout + sent.stderr
    mapping = yaml.safe_load((root / '.graphtraj/runner/sessions' / alias / 'mapping.yml').read_text())
    worker = mapping['worker_pid']
    time.sleep(2)  # Startup work is not the idle wait.

    before, started = cpu_seconds(worker), time.monotonic()
    time.sleep(IDLE_SECONDS)
    used = cpu_seconds(worker) - before
    elapsed = time.monotonic() - started
    print(f'worker {worker}: {used:.3f} CPU-s over {elapsed:.2f} s = {used / elapsed:.3f} CPU-s per s')
    assert used / elapsed < 0.07

    stopped = command(installed_commands, root, environment, 'interrupt', alias)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert settled(installed_commands, root, environment, alias)['last_outcome'] == 'interrupted'
