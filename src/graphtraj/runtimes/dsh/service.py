"""Own one authenticated DSH service without retaining launch credentials."""

from __future__ import annotations

import http.cookiejar
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from websockets.sync.client import connect

from graphtraj.runtimes.runtime_adapter import RuntimeAdapterError


# The Gateway forwards Agent-scoped approval waterfalls over this one internal
# stream; its ``ready`` frame carries the clientId later results must name.
APPROVAL_STREAM   = 'events'
APPROVAL_ENDPOINT = '$events'
APPROVAL_RESULT   = '$events/result'


class DshService:
    """Keep launch tokens/cookies in memory and reap only our own service.

    One service per Agent preserves the existing CLI's process-based caller
    identity. Sharing a service PID would alias different GraphTraj Agents.
    This is a Session worker resource, not a user-owned/global daemon.
    """

    def __init__(self, executable: str, cwd: Path, environment: dict[str, str]) -> None:
        """Capture launch settings without starting any native work."""
        self.executable = executable
        self.cwd = cwd
        self.environment = environment
        self.process: subprocess.Popen | None = None
        self.origin = ''
        self.cookie = ''
        self.socket = None
        self.client_id: str | None = None
        # Frames read while opening the approval channel are replayed to receive.
        self.backlog: list[dict] = []
        self.events: queue.Queue = queue.Queue()

    def start(self) -> None:
        """Launch an owned Web backend and exchange its single-use launch token."""
        urls: queue.Queue[str | None] = queue.Queue()
        try:
            self.process = subprocess.Popen(
                [self.executable, 'web', '--no-open', '--port', '0'],
                cwd=self.cwd, env=self.environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, start_new_session=True,
                text=True, bufsize=1,
            )
        except OSError as error:
            raise RuntimeAdapterError('RUNTIME_START_FAILED', 'Cannot start DSH.') from error

        def drain() -> None:
            """Consume native startup output without publishing authentication URLs."""
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                match = re.search(r'https?://(?:127\.0\.0\.1|localhost):\d+/[^\s]*token=[^\s]+', clean)
                if match:
                    urls.put(match.group())
            urls.put(None)

        threading.Thread(target=drain, daemon=True).start()
        try:
            launch = urls.get(timeout=45)
            if launch is None:
                raise RuntimeAdapterError('RUNTIME_START_FAILED', 'DSH exited before authentication.')
            parsed = urllib.parse.urlsplit(launch)
            self.origin = f'{parsed.scheme}://{parsed.netloc}'
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar),
            )
            with opener.open(launch, timeout=15) as response:
                response.read(1)
            self.cookie = '; '.join(f'{item.name}={item.value}' for item in jar)
            if not self.cookie:
                raise RuntimeAdapterError('RUNTIME_AUTH_FAILED', 'DSH returned no authenticated cookie.')
        except RuntimeAdapterError:
            raise
        except Exception:
            # Native authentication failures can contain the launch URL. Do
            # not retain even an exception-chain copy of that credential.
            raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED', 'DSH launch/authentication failed.') from None

    def rpc(self, method: str, request: dict | None = None) -> dict:
        """Call the native Remote envelope; a successful response is only a receipt."""
        return self._call(method, {} if request is None else {
            '_request' if method == 'session/list' else 'request': request,
        })

    def _call(self, method: str, args: dict) -> dict:
        """Call one native Remote method with its exact named wire arguments."""
        rpc_id = uuid.uuid4().hex
        body = {
            'type': 'client-request', 'rpcId': rpc_id, 'method': method,
            'payload': {'args': args},
        }
        call = urllib.request.Request(
            self.origin + '/api/' + method, data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Cookie': self.cookie, 'Origin': self.origin},
        )
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(call, timeout=20) as response:
                document = json.load(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', f'DSH {method} response body was not JSON.') from error
        except Exception as error:
            # Connection, HTTP-status and timeout failures share no native
            # outcome; report them as unconfirmed rather than as a native result.
            raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED', f'DSH {method} request failed.') from error

        try:
            if document.get('rpcId') != rpc_id:
                raise ValueError('Mismatched native response')
            result = document['result']
            if not result['ok']:
                code = result.get('error', {}).get('code', 'unknown')
                # Only the native code, never returned URL/header/body text.
                raise RuntimeAdapterError('RUNTIME_REQUEST_FAILED', f'DSH {method} failed ({code}).')
        except RuntimeAdapterError:
            raise
        except Exception as error:
            raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', f'DSH {method} response was not the native envelope.') from error

        # The Gateway's one-shot success envelope omits ``value`` entirely
        # (``return {ok: true, value: void 0}``), so only an explicit ``ok``
        # confirms the outcome; a missing value is confirmation, never a KeyError
        # and never an inferred success from an uncertain response.
        return result.get('value')

    def answer_approval(self, event_id: str, outcome: str) -> None:
        """Return one explicit outcome to the exact pending native approval request."""
        if self.client_id is None:
            raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', 'DSH approval channel is not open.')
        self._call(APPROVAL_RESULT, {
            'clientId': self.client_id, 'eventId': event_id,
            'outcome': {'kind': 'result', 'value': outcome},
        })

    def open_events(self) -> str:
        """Open the forwarded-event stream and require its native ready frame."""
        self._open_stream(APPROVAL_STREAM, APPROVAL_ENDPOINT, {})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            message = self._receive_message(max(0.01, deadline - time.monotonic()))
            if message.get('streamId') != APPROVAL_STREAM:
                # Session frames may interleave; retain them for the owner loop.
                if message:
                    self.backlog.append(message)
                continue
            value = message.get('value') or {}
            client_id = value.get('clientId')
            if value.get('type') == 'ready' and isinstance(client_id, str) and client_id:
                self.client_id = client_id
                return client_id
            raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', 'DSH approval channel did not open correctly.')
        raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED', 'DSH approval channel did not become ready.')

    def follow(self, session: str) -> dict:
        """Subscribe before prompt and return the native opening snapshot."""
        try:
            self.socket = connect(
                self.origin.replace('http:', 'ws:') + '/api/remote.mux',
                origin=self.origin, additional_headers={'Cookie': self.cookie},
                proxy=None, open_timeout=15, max_size=32 * 1024 * 1024,
            )
            self._open_stream('session', 'session/follow', {
                'request': {'address': {'kind': 'session', 'sessionId': session}},
            })
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                frame = self.receive(max(0.01, deadline - time.monotonic()))
                if frame.get('type') == 'snapshot':
                    if frame.get('header', {}).get('id') != session:
                        raise RuntimeAdapterError('RUNTIME_PROTOCOL_ERROR', 'DSH snapshot identity mismatch.')
                    return frame
            raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED', 'DSH subscription snapshot timed out.')
        except RuntimeAdapterError:
            raise
        except Exception as error:
            raise RuntimeAdapterError('RUNTIME_CONNECTION_FAILED', 'DSH subscription failed.') from error

    def receive(self, timeout: float = 1) -> dict:
        """Read one Session frame; queue approval-channel frames for the owner."""
        message = self.backlog.pop(0) if self.backlog else self._receive_message(timeout)
        if not message:
            return {}
        if message.get('streamId') == APPROVAL_STREAM:
            self.events.put(message.get('value') or {})
            return {}
        return message.get('value', {})

    def take_events(self) -> list[dict]:
        """Drain queued approval-channel frames without blocking."""
        frames = []
        while True:
            try:
                frames.append(self.events.get_nowait())
            except queue.Empty:
                return frames

    def _open_stream(self, stream_id: str, endpoint: str, args: dict) -> None:
        """Open one logical stream on the authenticated multiplexed socket."""
        self.socket.send(json.dumps({
            'type': 'open', 'streamId': stream_id, 'endpoint': endpoint,
            'payload': {'args': args},
        }))

    def _receive_message(self, timeout: float) -> dict:
        """Read one multiplexed frame, preserving native failure semantics."""
        try:
            message = json.loads(self.socket.recv(timeout=timeout))
            if message.get('type') in {'error', 'end'}:
                raise RuntimeAdapterError('RUNTIME_CONNECTION_CLOSED', 'DSH Session stream ended unexpectedly.')
            return message
        except TimeoutError:
            return {}
        except RuntimeAdapterError:
            raise
        except Exception as error:
            raise RuntimeAdapterError('RUNTIME_CONNECTION_CLOSED', 'DSH Session connection failed.') from error

    def close(self) -> None:
        """Close observation and stop only this owned service/process group."""
        if self.socket is not None:
            self.socket.close()
        if self.process is not None:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
                if self.process.poll() is not None:
                    break
                try:
                    os.killpg(self.process.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    continue
            if self.process.poll() is None:
                raise RuntimeAdapterError('RUNTIME_SHUTDOWN_FAILED', 'Owned DSH service did not stop.',
                                          terminal_confirmed=False)
        self.cookie = ''
