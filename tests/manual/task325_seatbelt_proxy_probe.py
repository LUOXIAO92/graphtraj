"""Task325 transport probe: can a network-off Codex seatbelt reach a Unix socket?

Transport-layer evidence only; this is not CLI acceptance. It starts no Codex
daemon and makes no model call. ``codex app-server proxy --sock`` only
connects to the given socket path (codex-rs/cli/src/main.rs:1400-1408 at
rust-v0.163.0), and here that path is a temporary listener owned by this run.

Phase A connects to the listener from an unsandboxed child (control). Phase B
runs the proxy under ``codex sandbox -P :workspace --log-denials``, the formal
checker's permission profile, with no Unix-socket allowance. B accepted=false
with a socket denial in stderr shows the seatbelt blocks the connect;
accepted=true refutes that.

Phase C applies the checker profile GraphTraj requests on its fork (extends
:workspace, managed network enabled, only this run's socket allowed). C
accepted=true shows only that the allowed socket is reachable. Phase D uses the
documented ``--allow-unix-socket`` for this run's directory only; compare C and
D through their stderr tails. Phases E and F keep C's profile and check what it
does not allow: E connects to a second temporary socket that is not allowed
(expected denied), F connects over TCP to a 127.0.0.1 listener owned by this
run (expected denied; whatever happens is recorded). Only this run's temporary
socket is ever allowed.

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
    """Accept connections on a bound socket and record whether one came."""

    def __init__(self, address, family=socket.AF_UNIX) -> None:
        self.server = socket.socket(family, socket.SOCK_STREAM)
        self.server.bind(address)
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
    other = os.path.join(directory, 't')
    listener = other_listener = tcp_listener = None
    try:
        listener = Listener(path)
        other_listener = Listener(other)
        tcp_listener = Listener(('127.0.0.1', 0), socket.AF_INET)
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
            '--', codex, 'app-server', 'proxy', '--sock', path,
        ], 20)
        time.sleep(0.5)
        report['phase_b']['accepted'] = listener.accepted
        listener.reset()
        # Phase C: the same profile GraphTraj's checker fork requests
        # (app_server.CHECKER_PERMISSION_PROFILE), extending :workspace with
        # only this run's temporary socket, given as one-run `-c` overrides.
        profile = 'graphtraj_checker'
        report['phase_c'] = run([
            codex, 'sandbox',
            '-c', f'permissions.{profile}.extends=":workspace"',
            '-c', f'permissions.{profile}.network.enabled=true',
            '-c', f'permissions.{profile}.network.unix_sockets={{"{path}"="allow"}}',
            '-P', profile, '--log-denials',
            '--', codex, 'app-server', 'proxy', '--sock', path,
        ], 20)
        time.sleep(0.5)
        report['phase_c']['accepted'] = listener.accepted
        listener.reset()
        allowed_profile = [
            codex, 'sandbox',
            '-c', f'permissions.{profile}.extends=":workspace"',
            '-c', f'permissions.{profile}.network.enabled=true',
            '-c', f'permissions.{profile}.network.unix_sockets={{"{path}"="allow"}}',
            '-P', profile, '--log-denials', '--',
        ]
        # Phase E: C's profile, but a sibling socket that is not allowed.
        report['phase_e'] = run(allowed_profile + [codex, 'app-server', 'proxy', '--sock', other], 20)
        time.sleep(0.5)
        report['phase_e']['accepted'] = other_listener.accepted
        # Phase F: C's profile, a direct TCP connect to this run's loopback listener.
        port = tcp_listener.server.getsockname()[1]
        tcp = ('import socket,sys; s=socket.create_connection(("127.0.0.1", int(sys.argv[1])), 5); '
               's.close()')
        report['phase_f'] = run(allowed_profile + [sys.executable, '-c', tcp, str(port)], 20)
        report['phase_f']['port'] = port
        time.sleep(0.5)
        report['phase_f']['accepted'] = tcp_listener.accepted
        # Phase D: the documented `--allow-unix-socket` limited to this run's
        # directory, separating seatbelt socket rules from proxy startup.
        report['phase_d'] = run([
            codex, 'sandbox', '-P', ':workspace', '--allow-unix-socket', directory, '--log-denials',
            '--', codex, 'app-server', 'proxy', '--sock', path,
        ], 20)
        time.sleep(0.5)
        report['phase_d']['accepted'] = listener.accepted
    finally:
        for each in (listener, other_listener, tcp_listener):
            if each is not None:
                each.close()
        for each in (path, other):
            if os.path.exists(each):
                os.unlink(each)
        os.rmdir(directory)
        report['finished_at'] = now()
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
