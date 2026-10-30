#!/usr/bin/env python3
"""Print the agents tool results of one ``claude -p`` stream-json file and judge them (406)."""
import argparse
import json
from pathlib import Path


def text_of(content: object) -> str:
    """Return a tool result's text, whether a plain string or a list of text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(item.get('text', '') for item in content if isinstance(item, dict))
    return ''


def agents_results(path: Path) -> list[tuple[bool, str]]:
    """Return (is_error, text) of every result answering an agents tool call."""
    calls, results = set(), []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            document = json.loads(line)
        except ValueError:
            continue
        message = document.get('message') if isinstance(document, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'tool_use' and item.get('name') == 'mcp__agents__agents':
                calls.add(item.get('id'))
            elif item.get('type') == 'tool_result' and item.get('tool_use_id') in calls:
                results.append((bool(item.get('is_error')), text_of(item.get('content'))))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stream', type=Path)
    parser.add_argument('--discover', action='store_true', help='Pass on a real discover result.')
    parser.add_argument('--refused', help='Pass on a refusal naming host-busy and this text.')
    options = parser.parse_args()
    results = agents_results(options.stream)
    print('agents tool results:', len(results))
    for failed, text in results:
        print(f'  is_error={failed}: {text[:600]}')
    if options.discover:
        return 0 if any(not failed and '"features"' in text for failed, text in results) else 1
    if any('must be launched directly' in text for _, text in results):
        print('a result reports a CLI version mismatch')
        return 1
    return 0 if any('host-busy' in text and options.refused in text for _, text in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
