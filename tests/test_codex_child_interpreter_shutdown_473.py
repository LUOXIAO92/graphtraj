"""473: a Codex child ends normally after its owning process's main thread has returned.

The Codex owner runs on a non-daemon thread, so a member Worker's interpreter
waits for it. But when the main thread ends, ``threading._shutdown`` first sets
``concurrent.futures``' global shutdown flag, and from then on every executor,
including ``asyncio.to_thread``, refuses work with "cannot schedule new futures
after interpreter shutdown". The owner's end processing used it to close its
connections, so the child ended ``RUNTIME_WORKER_FAILED`` and the rest of its
end processing (observer cleanup, ``stderr.log``) never ran.

Here a real owner process returns from its main thread while its child's turn
still runs (real interpreter shutdown); the controlled app-server peer then
completes the turn. Real ``/bin/sh`` and ``/bin/sleep`` tools; every process
this test stops is one it started, checked by pid and start time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from graftling.tool_descendants import identity
import test_codex_tool_reclaim_462 as reclaim

OWNER = r'''
import json, sys
from pathlib import Path
from graftling import AgentControl, Caller, bind
from graftling.codex.driver import CodexDriver
control = AgentControl(Path(sys.argv[1]), {'codex': CodexDriver(json.loads(sys.argv[2]))})
call = bind(control, Caller(*json.loads(sys.argv[3])))
print(json.dumps(call({'action': 'create', 'runtime': 'codex', 'instruction': 'tool-end'}).document), flush=True)
# The main thread returns while the child's turn still runs.
'''

native_settings = reclaim.native_settings


def test_child_ends_completed_after_the_owner_main_thread_returns(tmp_path: Path, native_settings: dict) -> None:
    """The turn completes during interpreter shutdown; the end processing runs in full."""
    root  = tmp_path / 'agents'
    since = identity(os.getpid()).start
    owner = subprocess.Popen(
        [sys.executable, '-c', OWNER, str(root), json.dumps(native_settings), json.dumps(reclaim.CALLER)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    found: dict = {}
    try:
        created = json.loads(owner.stdout.readline())
        found   = reclaim.wait_for(lambda: len(reclaim.tools(since)) == 3, 10) and reclaim.tools(since)
        assert found, 'the peer did not start the tool'

        # The process exits only after the non-daemon owner has finished the end processing.
        stdout, stderr = owner.communicate(timeout=30)
        print('owner exit:', owner.returncode, 'stderr:', stderr[-2000:])
        assert owner.returncode == 0, stderr

        execution = reclaim.record(root, created['agent'])
        print('end record:', json.dumps({key: execution.get(key) for key in ('state', 'outcome', 'error')}))
        assert execution['state'] == 'ended'
        assert execution['outcome'] == 'completed' and execution.get('error') is None, execution

        directory   = Path(execution['process']['tool_descendants']).parent
        termination = next(directory.glob('codex-termination-*.yml'), None)
        assert termination is not None, 'the owner-side reclaim did not record its end'
        report = yaml.safe_load(termination.read_text())['escaped_processes']
        assert sorted(item['pid'] for item in report['stopped']) == sorted([found['shell'].pid, found['sleep'].pid])
        assert not reclaim.is_alive(found['shell']) and not reclaim.is_alive(found['sleep'])
        assert reclaim.is_alive(found['other']), "another execution's process is untouched"
        assert (directory / 'stderr.log').is_file(), 'the end processing stopped before stderr.log'
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(5)
        reclaim.stop_own(list(found.values()) + [
            item for items in reclaim.ours(since).values() for item in items
            if reclaim.argv(item.pid).startswith(('/bin/sleep 303', sys.executable + ' -c'))
        ])
