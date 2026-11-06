"""452: a process that ran create keeps the execution's owner until it ends.

A Runner member's agents call is answered on a daemon thread
(graftling/connection.py). A driver's owner thread started from there used to
inherit daemon=True, so the member's worker exited at the end of its turn and
the child's owner vanished without reporting an end (later: owner-exited).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / 'src'

# The child process: a daemon thread calls start; the main thread returns at once.
SCRIPT = textwrap.dedent('''
    import sys, threading, time
    from pathlib import Path
    from graftling import Run

    runtime, directory = sys.argv[1], Path(sys.argv[2])
    finished = directory / 'finished'

    class Turn:
        """Binds at once, then ends its native turn about 1.5 s later."""

        def __init__(self, *args, **kwargs):
            self.ready = args[3]
            self.accepted = threading.Event()
            self.unseen = []
            self.archive = None

        def take_unseen(self):
            return []

        def run(self):
            self.ready('session-452', 0)
            time.sleep(1.5)
            return {'outcome': 'completed'}

    class Events:
        def session(self, session): pass
        def process(self, **fields): pass
        def request(self, details): pass
        def receive_children(self, receive): pass
        def finished(self, outcome, **fields):
            finished.write_text(outcome)

    def ignore(turn, run):
        pass

    if runtime == 'claude':
        import graftling.claude.binding as binding, graftling.claude.driver as module
        binding.bind_run, module.ClaudeExecution = ignore, Turn
        driver = module.ClaudeDriver(directory, {})
    elif runtime == 'dsh':
        import graftling.dsh.binding as binding, graftling.dsh.driver as module
        binding.bind_run, module.DshExecution = ignore, Turn
        driver = module.DshDriver(directory, {})
    elif runtime == 'pi':
        import graftling.pi.driver as module
        module.PiExecution = Turn
        driver = module.PiDriver({})
    else:
        import graftling.codex.driver as module
        driver = module.CodexDriver(execution=Turn)

    run = Run(agent='child', execution='e452', runtime=runtime,
              settings={'adapter_request': {}}, message='hi', session=None,
              directory=directory, archive=None, events=Events())
    started = threading.Event()
    caller = threading.Thread(target=lambda: (driver.start(run), started.set()), daemon=True)
    caller.start()
    if not started.wait(10):
        sys.exit('start did not return')
    print('started', flush=True)
''')


@pytest.mark.parametrize('runtime', ['claude', 'codex', 'pi', 'dsh'])
def test_owner_started_from_daemon_caller_reports_its_end(runtime: str, tmp_path: Path) -> None:
    """The process outlives its main thread until the owner records the end."""
    result = subprocess.run(
        [sys.executable, '-c', SCRIPT, runtime, str(tmp_path)],
        env={'PYTHONPATH': str(SRC), 'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'started'
    finished = tmp_path / 'finished'
    assert finished.is_file(), 'the owner thread died with the process before reporting its end'
    assert finished.read_text() == 'completed'
