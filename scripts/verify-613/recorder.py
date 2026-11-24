"""Task 613 local recording endpoint (stdlib only); never stores or prints a header value.

serve RECORDS PORTFILE DUMMYVAR [SECONDS]
    Listen on 127.0.0.1, a random port written to PORTFILE. Each request appends one JSON
    line to RECORDS: its number, method, path (no query), and for every auth-like header
    present only its lower-case name and whether its value equals the dummy (the value of
    the environment variable DUMMYVAR; for authorization also 'Bearer <dummy>'). Nothing
    else of the request is kept: no other header, no body, no value. A Messages request is
    answered with a minimal one-word reply ('ready'), streamed when asked; anything else 404.
    Stops after SECONDS (default 900).
check RECORDS EXPECT
    EXPECT 'none': PASS when no request arrived. EXPECT 'dummy': PASS when at least one
    request arrived and every request carried exactly one auth-like header, x-api-key,
    equal to the dummy. Prints CHECK lines and the per-request summary; exit 1 on FAIL.
"""
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

AUTH_LIKE = re.compile(r'auth|api[-_]?key|token|secret|credential|cookie|session|bearer|password', re.I)


def serve(records: str, portfile: str, variable: str, seconds: float) -> None:
    dummy = os.environ.get(variable, '')
    lock, count = threading.Lock(), [0]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args) -> None:  # no request line, which could hold a query
            pass

        def record(self) -> None:
            auth = {}
            for name in {key.lower() for key in self.headers.keys()}:
                if AUTH_LIKE.search(name):
                    value = self.headers.get(name, '')
                    auth[name] = bool(dummy) and value in (dummy, 'Bearer ' + dummy)
            with lock:
                count[0] += 1
                entry = {'n': count[0], 'method': self.command, 'path': urlsplit(self.path).path, 'auth': auth}
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


def check(records: str, expect: str) -> int:
    entries = [json.loads(line) for line in open(records, encoding='utf-8')] if os.path.exists(records) else []
    print(f'recorder: {len(entries)} request(s) in {records}')
    for entry in entries:
        print(f"  #{entry['n']} {entry['method']} {entry['path']} auth headers: "
              + (', '.join(f"{name}={'equals dummy' if same else 'NOT the dummy'}"
                           for name, same in sorted(entry['auth'].items())) or 'none'))
    failed = 0
    if expect == 'none':
        failed = len(entries) != 0
        print(f"CHECK 613 recorder received no request: {'FAIL' if failed else 'PASS'}")
        return int(failed)
    results = [('at least one request reached the recorder', len(entries) >= 1),
               ('every request carried only x-api-key (no authorization, no other auth-like header)',
                all(set(entry['auth']) == {'x-api-key'} for entry in entries)),
               ('every x-api-key equals the dummy (no host key or login)',
                all(entry['auth'].get('x-api-key') is True for entry in entries))]
    for label, ok in results:
        print(f"CHECK 613 {label}: {'PASS' if ok and entries else 'FAIL'}")
        failed |= not (ok and entries)
    return int(failed)


if __name__ == '__main__':
    if sys.argv[1] == 'serve':
        serve(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5]) if len(sys.argv) > 5 else 900)
    else:
        sys.exit(check(sys.argv[2], sys.argv[3]))
