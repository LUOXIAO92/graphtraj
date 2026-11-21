"""Task 544 P: throwaway stdio MCP server `probe` with one tool `send_note(to, message)` (543 Q4). No product code.

usage: python -I probe544.py            (Codex starts it from the isolated project's .codex/config.toml)

tools/call send_note returns
  content           = ONE text block: a fixed Markdown body (real newlines; a **bold** line, a `code` span and the
                      marker PROBE-BODY-544), then exactly three tail lines 'status: sent', 'from: main', '→ <to> [probe-id]'
  structuredContent = {"ok": true, "marker": "PROBE-SC-544"}
Pass criteria (543 Q4): collapsed card = `Called probe.send_note` + the 3 tail lines; `+ Show details` = the
arguments line + the full body; the model's reply carries PROBE-SC-544 and not PROBE-BODY-544 (it reads
structuredContent). Newline-delimited JSON-RPC 2.0 over stdin/stdout; nothing else is read or written.
"""
import json
import sys

BODY = [
    '## Probe note PROBE-BODY-544',
    '',
    'This line has **bold** text and a `code` span.',
    '- first item',
    '- second item',
]
TOOL = {
    'name': 'send_note',
    'description': 'Send a note to a member (Task 544 display probe).',
    'inputSchema': {'type': 'object', 'properties': {'to': {'type': 'string'}, 'message': {'type': 'string'}},
                    'required': ['to', 'message']},
}


def note(to: str) -> dict:
    text = '\n'.join(BODY + ['status: sent', 'from: main', f'→ {to} [probe-id]'])
    return {'content': [{'type': 'text', 'text': text}],
            'structuredContent': {'ok': True, 'marker': 'PROBE-SC-544'}, 'isError': False}


def answer(request: dict) -> dict | None:
    method, ident, params = request.get('method'), request.get('id'), request.get('params') or {}
    if ident is None:
        return None  # notification (notifications/initialized, cancelled, ...)
    if method == 'initialize':
        result = {'protocolVersion': params.get('protocolVersion') or '2025-06-18',
                  'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': 'probe', 'version': '544'}}
    elif method == 'tools/list':
        result = {'tools': [TOOL]}
    elif method == 'tools/call' and params.get('name') == 'send_note':
        result = note(str((params.get('arguments') or {}).get('to') or 'member-x'))
    elif method == 'ping':
        result = {}
    else:
        return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': f'unknown method {method}'}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        response = answer(request) if isinstance(request, dict) else None
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
            sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
