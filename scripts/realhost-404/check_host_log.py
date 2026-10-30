#!/usr/bin/env python3
"""Read one real-host run's evidence and print its raw lines and PASS/FAIL results (404)."""
import argparse
import json
from pathlib import Path


def stream_order(path: Path) -> list[str]:
    """Return the tool_use and tool_result order of one ``claude -p`` stream-json file."""
    calls, order = {}, []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        message = message.get('message') if isinstance(message, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use':
                calls[item['id']] = (item.get('input') or {}).get('feature')
                order.append(f"call {calls[item['id']]}")
            elif item.get('type') == 'tool_result':
                error = ' is_error' if item.get('is_error') else ''
                order.append(f"result {calls.get(item.get('tool_use_id'))}{error}")
    return order


def parse(line: str) -> dict:
    """Split one ``agents-call`` log line into its event and fields."""
    words = line.split()
    fields = dict(word.split('=', 1) for word in words[3:] if '=' in word)
    return {'event': words[2] if len(words) > 2 else '', **fields}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('stream', type=Path, nargs='?', help='Stream-json of a print-mode run; none for interactive.')
    parser.add_argument('--offset', type=int, default=0, help='Byte offset where this run starts in the log.')
    parser.add_argument('--long', default='task_integrate')
    parser.add_argument('--short', default='task_graph')
    parser.add_argument('--require-overlap', action='store_true')
    options = parser.parse_args()
    with options.log.open('rb') as stream:
        stream.seek(options.offset)
        text = stream.read().decode('utf-8', errors='replace')
    lines = [line for line in text.splitlines() if ' agents-call ' in line]
    print('raw host.log lines:')
    for line in lines:
        print('  ' + line)
    if options.stream is not None:
        print('stream-json order:', json.dumps(stream_order(options.stream)))
        streamed = options.stream.read_text(encoding='utf-8', errors='replace')
        print('mod refusal seen (Another agents call is pending):', 'Another agents call is pending' in streamed)
        print('association refusal seen (No matching current native call):', 'No matching current native call' in streamed)

    events = [parse(line) for line in lines]
    position = {(event['event'], event.get('feature')): index for index, event in reversed(list(enumerate(events)))}
    long_in = position.get(('received', options.long))
    long_out = position.get(('finished', options.long))
    short_in = position.get(('received', options.short))
    short_out = position.get(('finished', options.short))
    ends = [event for event in events if event['event'] == 'context-end']
    stale = bool(ends) and ends[-1].get('prepared') != '0'
    print('FAIL' if stale else 'PASS',
          'the last context-end leaves prepared=0 (the mod names the call it prepared)'
          + ('' if ends else ' (no context-end line in this run)'))
    if None in (long_in, long_out, short_in, short_out):
        print('FAIL both calls were received and finished in host.log')
        return 1
    overlap = long_in < short_out < long_out
    print('PASS' if overlap else 'FAIL', f'{options.short} finished while {options.long} was still in progress')
    if not overlap and short_in > long_out:
        print(f'observed: the host received {options.short} only after {options.long} finished, so this client '
              'did not send them together in this run; the host was not what held the second call.')
    elif not overlap:
        print(f'observed: the host received {options.short} during {options.long} but did not finish it first.')
    return 0 if overlap or not options.require_overlap else 1


if __name__ == '__main__':
    raise SystemExit(main())
