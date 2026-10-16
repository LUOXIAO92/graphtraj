"""Task325 transport probe: can a network-off Codex seatbelt reach a Unix socket?

Transport-layer evidence only; this is not CLI acceptance. It starts no Codex
daemon and makes no model call. ``codex app-server proxy --socket-path`` only
connects to the given socket path (codex-rs/cli/src/main.rs:1400-1408 at
rust-v0.163.0), and here that path is a temporary listener owned by this run.

Phase A connects to the listener from an unsandboxed child (control). Phase B
runs the proxy under ``codex sandbox -P :workspace --log-denials``, the formal
checker's permission profile, with no Unix-socket allowance. B accepted=false
with a socket denial in stderr shows the seatbelt blocks the connect;
accepted=true refutes that.

Run with the task venv's Python; the report is JSON on stdout.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

TAIL = 2000


def now() -> str:
    """Return the current UTC time for the report."""
    return datetime.now(timezone.utc).isoformat()


class Listener:
    """Accept one connection on a bound AF_UNIX socket and record whether it came."""

    def __init__(self, path: str) -> None:
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.server.settimeout(0.2)
        self.accepted = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        """Accept until stopped, closing each accepted connection immediately."""
        while not self.stop.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepted = True
            connection.close()

    def reset(self) -> None:
        """Forget earlier connections before the next phase."""
        self.accepted = False

    def close(self) -> None:
        """Stop accepting and close the listening socket."""
        self.stop.set()
        self.thread.join(timeout=2)
        self.server.close()


def run(command: list, timeout: float) -> dict:
    """Run one bounded child in its own process group and report its result."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
    return {'command': command, 'returncode': process.returncode, 'timed_out': timed_out,
            'stdout_tail': (stdout or '')[-TAIL:], 'stderr_tail': (stderr or '')[-TAIL:]}


def main() -> None:
    """Run the control and target phases, then remove only this run's files."""
    report = {'started_at': now(), 'python': sys.version}
    codex = shutil.which('codex') or '/opt/homebrew/bin/codex'
    report['codex_path'] = codex
    report['codex_version'] = run([codex, '--version'], 20)
    directory = tempfile.mkdtemp(prefix='t325-', dir='/tmp')
    path = os.path.join(directory, 's')
    listener = None
    try:
        listener = Listener(path)
        connect = ('import socket,sys; s=socket.socket(socket.AF_UNIX); '
                   's.connect(sys.argv[1]); s.close()')
        report['phase_a'] = run([sys.executable, '-c', connect, path], 15)
        time.sleep(0.5)
        report['phase_a']['accepted'] = listener.accepted
        listener.reset()
        # codex-cli 0.161.0 `codex sandbox --help`: `-P, --permission-profile`
        # applies a named profile; `--log-denials` prints macOS sandbox denials
        # after exit. `:workspace` is the formal checker's profile.
        report['phase_b'] = run([
            codex, 'sandbox', '-P', ':workspace', '--log-denials',
            '--', codex, 'app-server', 'proxy', '--socket-path', path,
        ], 20)
        time.sleep(0.5)
        report['phase_b']['accepted'] = listener.accepted
    finally:
        if listener is not None:
            listener.close()
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(directory)
        report['finished_at'] = now()
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
