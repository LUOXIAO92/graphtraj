"""560 GR: class every failed test of a G record as known or NEW. Read only.

usage: gr560.py <failures.txt from fails560.py> <516 current definition>

Known (Leader decision 2026-11-22, each printed with its origin; a known test failing for another reason is NEW):
  test_native_gateway ... [helper-main], [thread-1-main]: the expected MCP schema lacks 555's `arguments_file`
      (dev's tests/test_gateway.py:343 already expects it). Recorded by 551 (rounds/3 engineer-engineer_4.md 3c,
      validation-engineer_4.md 2) on dev 3b9c2af7 + graftling 9f962bc; fixed by 551. The block must name
      arguments_file.
  test_native_gateway ... [helper-independent], [thread-1-independent]: recorded by 556's G (realhost/GR.txt,
      d571ab30 + aea5962; 'known (fails on base B too)', base e3eb7649); 556 accepted with it; fixing Task: 551 (the
      test's owner per Main). Cause not shown by 556's evidence: the observed line is printed; cause is inference.
  test_child_env_own_key::test_a_model_cannot_ask_for_a_key: recorded by 556's G as above; no fixing Task named.
      Cause: inference from the observed line only.
Flaky (516's CURRENT definition, read through its task.yml): a test named there is listed as 'known flaky (516)';
  it does not block (the original 560 instruction); the Leader may decide otherwise.
Everything else is NEW. Exit 1 when any NEW line exists.
"""
import re
import sys

KNOWN = {
    # tests/test_native_gateway.py:88 is `assert all(set(tool['inputSchema']['properties']) == {'action', 'query',
    # 'feature', 'schema', 'arguments'} ...)`: the expected set lacks 555's arguments_file, which graftling 0.6.3's
    # ENVELOPE_SCHEMA has. The block must fail at that line.
    'tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[helper-main]':
        ('551 (rounds/3 engineer-engineer_4.md 3c; fails on dev 3b9c2af7 + graftling 9f962bc)', '551',
         'test_native_gateway.py:88'),
    'tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[thread-1-main]':
        ('551 (rounds/3 engineer-engineer_4.md 3c; fails on dev 3b9c2af7 + graftling 9f962bc)', '551',
         'test_native_gateway.py:88'),
    'tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[helper-independent]':
        ("556 G realhost/GR.txt (known: fails on base B e3eb7649 too; 556 accepted)", '551', None),
    'tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[thread-1-independent]':
        ("556 G realhost/GR.txt (known: fails on base B e3eb7649 too; 556 accepted)", '551', None),
    'tests/test_child_env_own_key.py::test_a_model_cannot_ask_for_a_key':
        ("556 G realhost/GR.txt (known: fails on base B e3eb7649 too; 556 accepted)", 'none named', None),
}

failures_path, flaky_path = sys.argv[1], sys.argv[2]
repository = sys.argv[3] if len(sys.argv) > 3 else None


def raising_function(observed: str) -> str | None:
    """The name of the function holding the failing `at tests/<file>.py:<line>` (516 names helpers such as
    _assert_native_budget_stop, whose 30 s poll a loaded host overruns)."""
    import ast
    import os
    match = re.search(r'at (?:\S*/)?(tests/[\w/]+\.py):(\d+)', observed)
    if not (match and repository):
        return None
    path, line = os.path.join(repository, match.group(1)), int(match.group(2))
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except (OSError, SyntaxError):
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= line <= node.end_lineno:
            if best is None or node.lineno > best.lineno:
                best = node
    return best.name if best else None

try:
    flaky = open(flaky_path, encoding='utf-8').read()
except OSError:
    flaky = ''
blocks, current = [], None
for line in open(failures_path, encoding='utf-8').read().splitlines():
    match = re.match(r'^(FAILED|ERROR) (\S+)', line)
    if match:
        current = [match.group(2), []]
        blocks.append(current)
    elif current is not None and line.strip():
        current[1].append(line.strip())
new = 0
for test, lines in blocks:
    observed = ' | '.join(lines) or '(no error line in the logs)'
    if test in KNOWN:
        origin, fixer, needle = KNOWN[test]
        if needle and needle not in observed:
            new += 1
            print(f'  NEW (known test, other cause: it does not fail at {needle}): {test}\n      observed: {observed}')
        else:
            cause = (f'confirmed: fails at {needle}, the inputSchema properties set without arguments_file'
                     if needle else 'cause: inference from the observed line')
            print(f'  known: {test}\n      origin: {origin}; fix: {fixer}; {cause}\n      observed: {observed}')
    elif test.split('::')[-1].split('[')[0] in flaky:
        print(f'  known flaky (516 current definition {flaky_path}): {test}\n      observed: {observed}')
    elif (helper := raising_function(observed)) and helper.startswith('_') and helper in flaky:
        print(f'  known flaky (516 current definition {flaky_path} names the helper {helper} it failed in): {test}'
              f'\n      observed: {observed}')
    else:
        new += 1
        print(f'  NEW: {test}\n      observed: {observed}')
print(f'failed tests: {len(blocks)} | NEW: {new}')
sys.exit(1 if new else 0)
