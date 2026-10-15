"""Current termination through the Claude Adapter with owned OS peer processes."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import yaml

from graphtraj.runtimes.claude.adapter import ClaudeRuntimeAdapter
from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


@pytest.mark.parametrize('case', ['owned', 'other-session', 'orphan', 'newer-than-owner', 'exited'])
def test_current_group_requires_original_leader(tmp_path: Path, case: str) -> None:
    """Stop a matching group, but do not signal other Sessions or orphan groups."""
    session = 'controlled-original-session'
    peer = (
        "import signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])\n"
        "print('ready',flush=True)\n"
        + ("" if case == 'orphan' else "time.sleep(60)\n")
    )
    process = subprocess.Popen(
        [sys.executable, '-c', peer, '--print', '--input-format', 'stream-json',
         '--session-id', session if case != 'other-session' else 'unrelated-session'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        assert process.stdout.readline().strip() == 'ready'
        if case == 'orphan':
            process.wait(timeout=5)
        if case == 'exited':
            os.killpg(process.pid, signal.SIGKILL)
            time.sleep(0.05)  # Keep the unreaped leader to exercise kernel zombie state.
        (tmp_path / 'session.yml').write_text(yaml.safe_dump({'session': session}))
        mapping = {'session': session, 'execution_id': 'old-execution',
                   'worker_pid': os.getpid(), 'runtime_pid': process.pid,
                   'worktree_path': str(tmp_path)}
        (tmp_path / 'heartbeat.yml').write_text(yaml.safe_dump({
            'alias': 'fixture', 'worker_pid': os.getpid(), 'execution_id': 'old-execution',
            'updated_at': time.time() - (60 if case == 'newer-than-owner' else 0),
        }))
        request = {'runtime': 'claude', 'executable': sys.executable,
                   'worktree_path': str(tmp_path)}
        adapter = ClaudeRuntimeAdapter()
        if case in {'owned', 'exited'}:
            evidence = adapter.confirm_termination(tmp_path, mapping, request)
            assert evidence['method'] == 'current-process-group'
            assert evidence['signals'] == (['SIGTERM', 'SIGKILL'] if case == 'owned' else [])
            assert evidence['running_members'] == []
            # EOF also covers the child that inherited stdout in this fixture.
            process.communicate(timeout=5)
            assert process.returncode == -signal.SIGKILL
        else:
            with pytest.raises(RuntimeAdapterError):
                adapter.confirm_termination(tmp_path, mapping, request)
            os.killpg(process.pid, 0)
            if case == 'other-session':
                assert process.poll() is None
        assert not list(tmp_path.glob('claude-termination-*'))
    finally:
        # These are the exact subprocess/group created by this fixture.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin may reject signalling a group containing only zombies.
            if process.poll() is None:
                raise
        process.communicate(timeout=5)
