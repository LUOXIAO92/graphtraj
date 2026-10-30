"""Shared stdio MCP framing and the independent authenticated agents client."""
from __future__ import annotations

import contextvars
import json
import re
import sys
import threading
import time
import traceback
from typing import Any, Callable, Mapping, TextIO

from agent_swarm import __version__
from agent_swarm.calls import Call, CallCancelled, current_call, running_call
from agent_swarm.connection import call_owner
from agent_swarm.discovery import INPUT_SCHEMA
from agent_swarm.tool import AgentsError

PROTOCOL_VERSION = '2025-06-18'


def result_response(request_id: Any, result: Mapping) -> dict:
    """Wrap a successful MCP protocol response."""
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def error_response(request_id: Any, code: int, message: str) -> dict:
    """Wrap a protocol error without pretending it is a business result."""
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def respond(
    message: Mapping,
    tools: Callable[[], list[dict]],
    call: Callable[[Any, Mapping], dict],
    server_info: dict,
) -> dict | None:
    """Dispatch standard MCP methods; the host retains business authorization."""
    method = message.get('method')
    if not isinstance(method, str) or 'id' not in message:
        return None
    request_id = message['id']
    params = message.get('params')
    if not isinstance(params, dict):
        params = {}
    if method == 'initialize':
        requested = params.get('protocolVersion')
        return result_response(request_id, {
            'protocolVersion': requested if isinstance(requested, str) else PROTOCOL_VERSION,
            'capabilities': {'tools': {}}, 'serverInfo': server_info,
        })
    if method == 'tools/list':
        return result_response(request_id, {'tools': tools()})
    if method == 'tools/call':
        return call(request_id, params)
    if method == 'ping':
        return result_response(request_id, {})
    return error_response(request_id, -32601, f'Unsupported method: {method}')


def serve(input_stream: TextIO, output_stream: TextIO, responder: Callable[[Mapping], dict | None]) -> None:
    """Serve newline-delimited MCP JSON-RPC using the supplied host dispatcher."""
    for line in input_stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = error_response(None, -32700, 'Parse error')
        else:
            reply = (responder(message) if isinstance(message, dict)
                     else error_response(None, -32600, 'Invalid request'))
        if reply is not None:
            output_stream.write(json.dumps(reply, ensure_ascii=False) + '\n')
            output_stream.flush()


class ClientGone(Exception):
    """The client's input ended, so nothing it was asked can be answered."""


# After input EOF, how long calls still running may finish before the host shuts
# down anyway, so its channel file and owned Agents are not left behind for them.
CLOSE_SECONDS = 10.0
# After SIGINT only enough for a call polling every calls.POLL_SECONDS to end its
# validation group: Claude Code's next signal kills the host before its channel unlink.
INTERRUPT_SECONDS = 0.05
# The stored answer of a client request the client itself cancelled.
_ANSWER_CANCELLED = object()
_LOG_LABEL = re.compile(r'[\w./-]{1,64}')


def _log_label(value: object) -> str:
    """Return a tool or feature name for the log; any other value is not logged."""
    return value if isinstance(value, str) and _LOG_LABEL.fullmatch(value) else '?'


class ConcurrentServer:
    """Serve newline-delimited MCP JSON-RPC with each ``tools/call`` on its own thread.

    The reader stays on the calling thread, so a signal still reaches it. It
    answers everything except ``tools/call`` itself, routes client responses by
    JSON-RPC id and applies ``notifications/cancelled``. A cancelled call's
    waits end at once and it sends no response. Input EOF ends the same waits;
    a response is still sent, and ``serve`` returns once every call has ended or
    ``CLOSE_SECONDS`` have passed.
    """

    def __init__(self, input_stream: TextIO, output_stream: TextIO) -> None:
        self.input = input_stream
        self.output = output_stream
        self.write_lock = threading.Lock()
        self.changed = threading.Condition()
        self.calls: dict[Any, tuple[Call, str, str]] = {}
        self.answers: dict[Any, Any] = {}
        self.threads: set[threading.Thread] = set()
        self.client_gone = False

    def send(self, message: Mapping) -> None:
        """Write one whole line; a closed client ends the waits instead of the writer."""
        line = json.dumps(message, ensure_ascii=False) + '\n'
        try:
            with self.write_lock:
                self.output.write(line)
                self.output.flush()
        except (OSError, ValueError):
            self._disconnect()

    def ask(self, message: Mapping, timeout: float) -> dict:
        """Send one client request and wait for the response with its id.

        Raises :class:`TimeoutError`, :class:`CallCancelled` (this call or the
        request itself was cancelled) or :class:`ClientGone`. A cancelled call
        never returns an answer, even one that arrived first.
        """
        identity, call = message['id'], running_call()
        with self.changed:
            if self.client_gone:
                raise ClientGone()
            self.answers[identity] = None
        self.send(message)

        def settled() -> bool:
            return (self.answers[identity] is not None or self.client_gone
                    or (call is not None and call.stop.is_set()))

        with self.changed:
            self.changed.wait_for(settled, timeout)
            answer = self.answers.pop(identity)
            gone = self.client_gone
        if gone:
            raise ClientGone()
        if answer is _ANSWER_CANCELLED or (call is not None and call.stop.is_set()):
            raise CallCancelled()
        if answer is None:
            raise TimeoutError()
        return answer

    def serve(self, responder: Callable[[Mapping], dict | None]) -> None:
        """Read until EOF, then let every running call end."""
        try:
            while line := self.input.readline():
                if line.strip():
                    self._dispatch(line, responder)
        except KeyboardInterrupt:
            self._close(INTERRUPT_SECONDS)
            raise
        except BaseException:
            self._disconnect()
            raise
        self._close(CLOSE_SECONDS)

    def _close(self, seconds: float) -> None:
        """Wake every waiter and give the running calls a bounded time to end."""
        self._disconnect()
        deadline = time.monotonic() + seconds
        for thread in list(self.threads):
            thread.join(max(0.0, deadline - time.monotonic()))
        for identity, (_, tool, feature) in list(self.calls.items()):
            self._log('still-running-at-close', identity, tool, feature)

    def _dispatch(self, line: str, responder: Callable[[Mapping], dict | None]) -> None:
        """Handle one client line without ever waiting for a tool call."""
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self.send(error_response(None, -32700, 'Parse error'))
            return
        if not isinstance(message, dict):
            self.send(error_response(None, -32600, 'Invalid request'))
        elif 'method' not in message:
            self._answer(message)
        elif message['method'] == 'notifications/cancelled':
            params = message.get('params')
            self._cancel(params.get('requestId') if isinstance(params, dict) else None)
        elif message['method'] == 'tools/call' and 'id' in message:
            self._start(message, responder)
        else:
            reply = responder(message)
            if reply is not None:
                self.send(reply)

    def _answer(self, message: dict) -> None:
        """Give a response to the request waiting for its id; any other decides nothing."""
        identity = message.get('id')
        with self.changed:
            if not isinstance(identity, str) or self.answers.get(identity, False) is not None:
                self._log('unmatched-response', identity)
                return
            self.answers[identity] = message
            self.changed.notify_all()

    def _cancel(self, identity: object) -> None:
        """Stop one running call, or end one waiting client request."""
        if not isinstance(identity, (str, int)):
            return
        with self.changed:
            running = self.calls.get(identity)
            if running is not None:
                call, tool, feature = running
                call.cancelled = True
                call.stop.set()
                self._log('cancelled', identity, tool, feature)
            elif self.answers.get(identity, False) is None:
                self.answers[identity] = _ANSWER_CANCELLED
                self._log('cancelled-request', identity)
            self.changed.notify_all()

    def _disconnect(self) -> None:
        """Wake every waiter: the client can answer nothing any more."""
        with self.changed:
            self.client_gone = True
            for call, _, _ in self.calls.values():
                call.stop.set()
            self.changed.notify_all()

    def _start(self, message: dict, responder: Callable[[Mapping], dict | None]) -> None:
        """Run one tools/call on its own thread with its own context."""
        identity = message['id']
        if not isinstance(identity, (str, int)) or identity in self.calls:
            self.send(error_response(None if not isinstance(identity, (str, int)) else identity,
                                     -32600, 'A tools/call needs an id that is not already running.'))
            return
        params = message.get('params')
        params = params if isinstance(params, dict) else {}
        arguments = params.get('arguments')
        tool = _log_label(params.get('name'))
        feature = _log_label(arguments.get('feature')) if isinstance(arguments, dict) else '?'
        call = Call()
        thread = threading.Thread(target=contextvars.copy_context().run, daemon=True,
                                  args=(self._run, call, identity, tool, feature, message, responder))
        with self.changed:
            self.calls[identity] = (call, tool, feature)
            self.threads.add(thread)
            if self.client_gone:
                call.stop.set()
        self._log('received', identity, tool, feature)
        thread.start()

    def _run(self, call: Call, identity: Any, tool: str, feature: str, message: dict,
             responder: Callable[[Mapping], dict | None]) -> None:
        """Execute one call; a cancelled one's result is discarded, never sent."""
        started, reply = time.monotonic(), None
        try:
            with current_call(call):
                if not call.cancelled:
                    reply = responder(message)
        except BaseException as error:  # noqa: BLE001 - this thread's last line of defence
            traceback.print_exc(file=sys.stderr)
            reply = error_response(identity, -32603, f'{type(error).__name__}: {error}')
        with self.changed:
            del self.calls[identity]
            cancelled = call.cancelled
            self.threads.discard(threading.current_thread())
        if cancelled:
            for discard in call.discards:
                try:
                    discard()
                except Exception:  # noqa: BLE001 - one failed undo must not stop the others
                    traceback.print_exc(file=sys.stderr)
        elif reply is not None:
            self.send(reply)
        result = (reply or {}).get('result')
        failed = 'error' in (reply or {}) or (isinstance(result, dict) and result.get('isError'))
        self._log('finished', identity, tool, feature, seconds=round(time.monotonic() - started, 3),
                  outcome='cancelled' if cancelled else 'failed' if failed else 'ok')

    def _log(self, event: str, identity: object, tool: str | None = None, feature: str | None = None,
             **facts: object) -> None:
        """Add one line to the host's diagnostics; never arguments or credentials."""
        now = time.time()
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now)) + f'.{int(now % 1 * 1000):03d}'
        fields = {'id': json.dumps(identity)[:64], 'tool': tool, 'feature': feature, **facts}
        details = ' '.join(f'{key}={value}' for key, value in fields.items() if value is not None)
        try:
            sys.stderr.write(f'{stamp}{time.strftime("%z")} agents-call {event} {details}\n')
            sys.stderr.flush()
        except (OSError, ValueError):
            pass


def serve_concurrent(input_stream: TextIO, output_stream: TextIO,
                     responder: Callable[[Mapping], dict | None]) -> None:
    """Serve MCP like :func:`serve`, without a tool call blocking other messages."""
    ConcurrentServer(input_stream, output_stream).serve(responder)


def tool_documents() -> list[dict]:
    """Expose only the lightweight agents entry in a Task-free host."""
    return [{'name': 'agents', 'description': 'Discover, describe, or execute an Agent feature.',
             'inputSchema': INPUT_SCHEMA}]


def call(request_id: Any, params: Mapping) -> dict:
    """Forward over the owning Runtime's authenticated channel; never fall back."""
    if params.get('name') != 'agents':
        return error_response(request_id, -32602, f"Unknown tool: {params.get('name')}")
    request = params.get('arguments', {})
    if not isinstance(request, dict):
        return error_response(request_id, -32602, 'Tool arguments must be an object.')
    try:
        result = call_owner(request, metadata=params.get('_meta'))
        document, failed = result.document, result.failed
    except AgentsError as error:
        document = {'error': {'code': error.code, 'message': error.message}}
        failed = True
    return result_response(request_id, {'content': [{'type': 'text', 'text': json.dumps(document, ensure_ascii=False)}],
                                         'structuredContent': document, 'isError': failed})


def main() -> None:
    """Run one stdio MCP entry over the owning Runtime's authenticated channel."""
    serve(sys.stdin, sys.stdout, lambda message: respond(
        message, tool_documents, call, {'name': 'agents', 'version': __version__}))


if __name__ == '__main__':
    main()
