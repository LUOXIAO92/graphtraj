"""Task 613 local recording endpoint (stdlib only); never stores or prints a header value.

serve RECORDS PORTFILE DUMMYVAR [SECONDS]
    Listen on 127.0.0.1, a random port written to PORTFILE. Each request appends one JSON
    line to RECORDS: its number, method, path (no query), and for every auth-like header
    present only its lower-case name and whether its value equals the dummy (the value of
    the environment variable DUMMYVAR; for authorization also 'Bearer <dummy>'). Nothing
    else of the request is kept: no other header, no body, no value. A Messages request is
    answered with a minimal one-word reply ('ready'), streamed when asked; anything else 404.
    Stops after SECONDS (default 900). For x-claude-code-session-id the record also keeps
    the hex sha256 of its value (under 'sha256'), so the check can compare it with the
    child's native Session; the value itself is never stored.
check RECORDS EXPECT [DATAROOT]
    EXPECT 'none': PASS when no request arrived. EXPECT 'dummy' (step B), each a CHECK line:
    (a) at least one request; (b) no auth-like header but x-api-key and
    x-claude-code-session-id on any request; (c) at least one x-api-key, every one equal to
    the dummy; (d) every x-claude-code-session-id hashes to the native Session ('session'
    field) of the Agent record in DATAROOT/control/agents (the newest, step B creates one; if
    that field is still empty, the session_id graftling launched it with, in its diagnostics).
    A request without any auth-like header (Claude Code's HEAD probe) is allowed. Prints
    names, flags and 'hash matches/does not match' only, never a value or a hash; exit 1 on FAIL.
"""
import hashlib
import json
import os
import re
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

AUTH_LIKE = re.compile(r'auth|api[-_]?key|token|secret|credential|cookie|session|bearer|password', re.I)
SESSION_HEADER = 'x-claude-code-session-id'
ALLOWED = {'x-api-key', SESSION_HEADER}


def describe(headers, dummy: str) -> dict:
    """The record fields of one request's headers: auth-like names, equal-to-dummy flags, session hash."""
    auth, hashes = {}, {}
    for name, value in ((key.lower(), value) for key, value in headers.items()):
        if AUTH_LIKE.search(name):
            auth[name] = bool(dummy) and value in (dummy, 'Bearer ' + dummy)
            if name == SESSION_HEADER:
                hashes[name] = hashlib.sha256(value.encode()).hexdigest()
    return {'auth': auth, **({'sha256': hashes} if hashes else {})}


def serve(records: str, portfile: str, variable: str, seconds: float) -> None:
    dummy = os.environ.get(variable, '')
    lock, count = threading.Lock(), [0]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args) -> None:  # no request line, which could hold a query
            pass

        def record(self) -> None:
            fields = describe(self.headers, dummy)
            with lock:
                count[0] += 1
                entry = {'n': count[0], 'method': self.command, 'path': urlsplit(self.path).path, **fields}
                with open(records, 'a', encoding='utf-8') as stream:
                    stream.write(json.dumps(entry, sort_keys=True) + '\n')

        def reply(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self.record()
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            if not urlsplit(self.path).path.endswith('/messages'):
                return self.reply(404, b'{"type":"error","error":{"type":"not_found_error","message":"613 recorder"}}',
                                  'application/json')
            try:
                request = json.loads(raw or b'{}')
            except ValueError:
                request = {}
            model = request.get('model', 'claude-haiku-5-5')
            message = {'id': 'msg_613', 'type': 'message', 'role': 'assistant', 'model': model,
                       'content': [{'type': 'text', 'text': 'ready'}], 'stop_reason': 'end_turn',
                       'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
            if not request.get('stream'):
                return self.reply(200, json.dumps(message).encode(), 'application/json')
            events = [('message_start', {'type': 'message_start', 'message': {
                          **message, 'content': [], 'stop_reason': None}}),
                      ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                               'content_block': {'type': 'text', 'text': ''}}),
                      ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                               'delta': {'type': 'text_delta', 'text': 'ready'}}),
                      ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                      ('message_delta', {'type': 'message_delta', 'usage': {'output_tokens': 1},
                                         'delta': {'stop_reason': 'end_turn', 'stop_sequence': None}}),
                      ('message_stop', {'type': 'message_stop'})]
            body = ''.join(f'event: {name}\ndata: {json.dumps(data)}\n\n' for name, data in events).encode()
            self.reply(200, body, 'text/event-stream')

        def do_GET(self) -> None:
            self.record()
            self.reply(404, b'{"type":"error","error":{"type":"not_found_error","message":"613 recorder"}}',
                       'application/json')

        do_HEAD = do_GET

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    open(records, 'a').close()
    with open(portfile + '.tmp', 'w') as stream:
        stream.write(str(server.server_address[1]))
    os.replace(portfile + '.tmp', portfile)
    threading.Timer(seconds, server.shutdown).start()
    server.serve_forever()


def native_session(root: str) -> tuple[str | None, str]:
    """The newest Agent record's native Session id under ROOT, and a description without its value."""
    records = sorted(Path(root, 'control', 'agents').glob('agent-*.json'), key=lambda p: p.stat().st_mtime)
    if not records:
        return None, f'no Agent record under {root}/control/agents'
    session = json.loads(records[-1].read_text()).get('session')
    if isinstance(session, str) and session:
        return session, f"Agent record {records[-1].name}, field 'session'"
    # Published only once Claude Code's start hook ran; before that graftling has the id it
    # launched with (claude --session-id) in the execution's diagnostics, field session_id.
    for diagnostics in sorted(Path(root, 'native', records[-1].stem).glob('claude-diagnostics-*.yml')):
        found = re.search(r"^session_id: '?([0-9a-fA-F-]+)'?$", diagnostics.read_text(), re.M)
        if found:
            return found.group(1), (f"Agent record {records[-1].name} field 'session' empty; "
                                    f"{diagnostics.name} field 'session_id'")
    return None, f"Agent record {records[-1].name}: field 'session' empty and no diagnostics session_id"


def check(records: str, expect: str, root: str | None = None) -> int:
    entries = [json.loads(line) for line in open(records, encoding='utf-8')] if os.path.exists(records) else []
    print(f'recorder: {len(entries)} request(s) in {records}')
    session, where = native_session(root) if root else (None, 'no data root given')
    expected = hashlib.sha256(session.encode()).hexdigest() if session else None
    if expect != 'none':
        print(f'native Session: {where}')

    def hashed(entry: dict) -> str:
        if SESSION_HEADER not in entry['auth']:
            return ''
        stored = (entry.get('sha256') or {}).get(SESSION_HEADER)
        if stored is None:
            return ' [session hash: not stored by this recorder version]'
        if expected is None:
            return ' [session hash: no native Session to compare]'
        return ' [session hash matches the native Session]' if stored == expected else \
            ' [session hash does NOT match the native Session]'

    for entry in entries:
        print(f"  #{entry['n']} {entry['method']} {entry['path']} auth headers: "
              + (', '.join(f"{name}={'equals dummy' if same else 'NOT the dummy'}"
                           for name, same in sorted(entry['auth'].items())) or 'none') + hashed(entry))
    if expect == 'none':
        failed = len(entries) != 0
        print(f"CHECK 613 recorder received no request: {'FAIL' if failed else 'PASS'}")
        return int(failed)
    keys = [entry['auth']['x-api-key'] for entry in entries if 'x-api-key' in entry['auth']]
    sessions = [entry for entry in entries if SESSION_HEADER in entry['auth']]
    stored = [(entry.get('sha256') or {}).get(SESSION_HEADER) for entry in sessions]
    results = [('(a) at least one request reached the recorder', len(entries) >= 1),
               ('(b) no auth-like header but x-api-key and x-claude-code-session-id (no authorization, cookie, token...)',
                all(set(entry['auth']) <= ALLOWED for entry in entries)),
               ('(c) at least one x-api-key, and every x-api-key equals the dummy (no host key or login)',
                bool(keys) and all(keys))]
    failed = 0
    for label, ok in results:
        print(f"CHECK 613 {label}: {'PASS' if ok else 'FAIL'}")
        failed |= not ok
    label = '(d) every x-claude-code-session-id is the child\'s native Session (sha256 match)'
    if any(item is None for item in stored):
        print(f'CHECK 613 {label}: NOT JUDGED (the records hold no session hash: an earlier recorder version)')
        failed = 1
    else:
        ok = expected is not None and all(item == expected for item in stored)
        print(f"CHECK 613 {label}: {'PASS' if ok else 'FAIL'}"
              + ('' if sessions else ' (no request carried the header)'))
        failed |= not ok
    return int(failed)


if __name__ == '__main__':
    if sys.argv[1] == 'serve':
        serve(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]) if len(sys.argv) > 5 else 900)
    else:
        sys.exit(check(*sys.argv[2:5]))
