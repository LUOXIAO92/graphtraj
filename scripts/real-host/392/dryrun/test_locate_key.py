"""Dry check of locate_key.py against stub sessions with a planted value. Run with any Python 3."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

VALUE = 'sk-planted0123456789abcdefghij'
HERE = Path(__file__).resolve().parent.parent
LONG_OTHER = 'Z' * 25


def write(path: Path, records: list) -> None:
    """Write records as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(item if isinstance(item, str) else json.dumps(item) for item in records) + '\n')


def main() -> int:
    """Build a runs tree, run the script's Python and check its output."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runs, out = root / 'runs', root / 'out'
        out.mkdir()
        call = {'type': 'message', 'message': {'role': 'assistant', 'provider': 'deepseek', 'model': 'm', 'content': [
            {'type': 'toolCall', 'id': 'c1', 'name': 'bash', 'arguments': {'command': f'env | grep KEY {LONG_OTHER}'}}]}}
        # Two occurrences close together: the first window would cut the second if cut before replacing.
        result = {'type': 'message', 'message': {'role': 'toolResult', 'toolCallId': 'c1', 'toolName': 'bash', 'content': [
            {'type': 'text', 'text': f'{"x " * 40}DEEPSEEK_API_KEY={VALUE} {"y " * 25}again={VALUE} {LONG_OTHER} tail'}]}}
        after = {'type': 'message', 'message': {'role': 'assistant', 'stopReason': 'stop', 'content': []}}
        session = runs / '64-walk-pi-20261101T100000/out/pi-session.jsonl'
        write(session, [call, result, after, f'not json {VALUE}'])
        write(runs / '64-walk-pi-20261101T090000/out/pi-session.jsonl', [result])
        write(runs / '64-walk-pi-20261101T100000/out/pi-session-stdout.jsonl',
              [{'type': 'tool_execution_end', 'toolCallId': 'c9', 'toolName': 'bash', 'result': VALUE}])
        write(runs / '89-residual-416-20261101T100000/h/state/tasks/4-probe-pi/w/events.pi/session.jsonl',
              [{'type': 'custom_message', 'customType': 'x', 'content': VALUE}])
        write(runs / '70-suite-20261101T100000/out/other.jsonl', [{'clean': True}])
        write(runs / '81-residual-20261101T100000/out/holds.jsonl', [{'a': VALUE}])
        before = {path: path.read_bytes() for path in runs.rglob('*') if path.is_file()}
        done = subprocess.run([sys.executable, '-I', str(HERE / 'locate_key.py'), str(runs), str(out)],
                              env={**os.environ, 'DEEPSEEK_API_KEY': VALUE}, capture_output=True, text=True)
        locations = (out / 'locations.txt').read_text()
        others = (out / 'other-files.txt').read_text()
        rows = [json.loads(line.split('\t', 1)[1]) for line in locations.splitlines()]
        checks = {
            'exit 0': done.returncode == 0,
            'the planted value is absent from everything written and printed':
                VALUE not in locations + others + done.stdout + done.stderr,
            'no piece of the value survives': 'sk-planted' not in locations and 'ghij' not in locations.replace('<KEY>', ''),
            'other long runs are masked': LONG_OTHER not in locations and '<LONG>' in locations,
            'files changed: none': before == {path: path.read_bytes() for path in runs.rglob('*') if path.is_file()},
            'both occurrences are reported, plus the two other named files': len(rows) == 4,
            'the toolResult names its call, masked': rows[0].get('tool_call', {}).get('name') == 'bash'
                and '<LONG>' in rows[0]['tool_call']['arguments'],
            'role, tool name and length are there': rows[0]['role'] == 'toolResult' and rows[0]['toolName'] == 'bash'
                and rows[0]['leaf_length'] > 100,
            'later assistant entries are counted': rows[0]['assistant_entries_after'] == 1,
            'the context is 60 characters each side': len(rows[0]['context']) <= 60 * 2 + len('<KEY>') + 5,
            'the earlier run is not scanned': '20261101T090000' in others or '20261101T090000' not in locations,
            'other holders are named, a clean one is not': 'holds.jsonl' in others and 'other.jsonl' not in others,
            'the line outside JSON is counted': '1 other lines holding it' in done.stdout,
        }
        for name, passed in checks.items():
            print(('PASS ' if passed else 'FAIL ') + name)
        print(done.stdout[:400])
        return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
