"""Task 575 verdicts read from a real ``claude -p --output-format stream-json --verbose`` run.

usage:
  judge575.py calls <stream.jsonl>
      Print every mcp__graphtraj__* tool call of the Session: its input and its tool result (first 400 chars).
  judge575.py expect <stream.jsonl> <label>=<tool>:<feature>:<mode>:<outcome> ...
      ``mode`` is ``file`` (the input names arguments_file) or ``inline`` (it does not). ``outcome`` is ``ok`` (a
      result without an error), ``denied`` (an error with code authority-denied), ``refused`` (any error) or
      ``code=<code>`` (an error carrying exactly that code: the host's JSON error or the mod's "<code>: " reason). Each
      label is judged on the LAST matching call of the Session; a label without a matching call is MISSING.
      Exit 0 only when every label has its outcome.

Only the Session's own records are read: its tool_use inputs and the tool_result blocks that answer them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def records(stream: Path) -> list[dict]:
    """The JSON records of one stream-json file; other lines are skipped."""
    found = []
    for line in stream.read_text(errors='replace').splitlines():
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def calls(stream: Path) -> list[dict]:
    """Every mcp__graphtraj__ tool call in order, with its result text and error flag."""
    uses, results = [], {}
    for record in records(stream):
        content = (record.get('message') or {}).get('content')
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get('type') == 'tool_use' and str(block.get('name', '')).startswith('mcp__graphtraj__'):
                uses.append(block)
            elif block.get('type') == 'tool_result':
                body = block.get('content')
                text = (''.join(item.get('text', '') for item in body if isinstance(item, dict))
                        if isinstance(body, list) else str(body))
                results[block.get('tool_use_id')] = (text, bool(block.get('is_error')))
    answered = []
    for use in uses:
        text, flagged = results.get(use.get('id'), ('(no tool result)', True))
        answered.append({'tool': use['name'].rsplit('__', 1)[-1], 'input': use.get('input') or {},
                         'text': text, 'is_error': flagged})
    return answered


def outcome(call: dict) -> str:
    """``ok``, ``denied`` (authority-denied) or ``error`` for one answered call."""
    try:
        document = json.loads(call['text'])
    except ValueError:
        document = None
    error = document.get('error') if isinstance(document, dict) else None
    if 'authority-denied' in call['text'] and (call['is_error'] or error):
        return 'denied'
    if call['is_error'] or error or document is None:
        return 'error'
    return 'ok'


def carries_code(call: dict, code: str) -> str | None:
    """Which form of a refusal with error ``code`` the failed call carries, or None.

    A refused host answers a call with ``{"error": {"code": ...}}``; when the
    mod's permission check is refused first, Claude Code shows its reason,
    which ``report_missing_host`` writes as ``<code>: <message>``.
    """
    if not call['is_error'] and 'error' not in call['text']:
        return None
    try:
        document = json.loads(call['text'])
    except ValueError:
        document = None
    error = document.get('error') if isinstance(document, dict) else None
    if isinstance(error, dict) and error.get('code') == code:
        return 'host result {"error": {"code": "%s"}}' % code
    if f'{code}: ' in call['text']:
        return f'permission check reason "{code}: ..."'
    return None


def main(argv: list[str]) -> int:
    """Run one subcommand; see the module docstring."""
    command, stream = argv[0], Path(argv[1])
    answered = calls(stream)
    if command == 'calls':
        for call in answered:
            print(f"{call['tool']} input={json.dumps(call['input'], ensure_ascii=False)}")
            print(f"  -> {outcome(call)} is_error={call['is_error']}: {call['text'][:400]}")
        print(f'{len(answered)} mcp__graphtraj__ call(s)')
        return 0

    if command == 'has':
        # has <stream> <tool> <feature> <needle>: the last arguments_file call's full result holds needle.
        tool, feature, needle = argv[2:5]
        matching = [call for call in answered if call['tool'] == tool and call['input'].get('feature') == feature
                    and 'arguments_file' in call['input']]
        found = bool(matching) and needle in matching[-1]['text']
        print(f"{tool} {feature} (file) result holds {needle!r}: {'YES -> PASS' if found else 'NO -> FAIL'}")
        return 0 if found else 1

    failed = 0
    for spec in argv[2:]:
        label, wanted = spec.split('=', 1)
        tool, feature, mode, expected = wanted.split(':')
        matching = [call for call in answered if call['tool'] == tool and call['input'].get('feature') == feature
                    and ('arguments_file' in call['input']) == (mode == 'file')]
        if not matching:
            print(f'{label}: MISSING (no {tool} {feature} call with mode {mode}) -> FAIL')
            failed += 1
            continue
        if expected.startswith('code='):
            # Only the named refusal passes; any other error or a success fails.
            form = carries_code(matching[-1], expected[len('code='):])
            got  = f'refused with {form}' if form else f'{outcome(matching[-1])} (not {expected})'
            good = form is not None
        else:
            got  = outcome(matching[-1])
            good = got == expected or (expected == 'refused' and got in {'denied', 'error'})
        failed += not good
        print(f"{label}: {tool} {feature} ({mode}) -> {got}; expected {expected} -> {'PASS' if good else 'FAIL'}")
        print(f"  result: {matching[-1]['text'][:300]}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
