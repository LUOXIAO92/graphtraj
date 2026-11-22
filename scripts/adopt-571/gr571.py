"""571 GR: class every failed test of a G record as known flaky (516) or NEW. Read only.

usage: gr571.py <failures.txt from fails571.py> <516 current definition> [<repository>]

Known: only a test named in Task 516's CURRENT definition (read through 516's task.yml current_definition), or the
helper it failed in, is 'known flaky (516)' and does not block.

No other failure is known. 560's accepted G record (adoption/G-8949caff-20261122T214834) had five non-516 lines; the
latest accepted full-suite records show each fixed by a Task now on GraphTraj dev 11f84ed6, so on the 571 pair (dev +
graftling 0.7.0 = 551's graftling side + 569) each must pass. If one fails it is printed as NEW with its source:
  test_native_gateway ... [helper-main], [thread-1-main], [helper-independent], [thread-1-independent]:
      fixed by 551 (GraphTraj a57decf0 + graftling 79532b5): 551 realhost/main-raw/GR-v063.txt lists only
      test_child_env_own_key and the 516 claude_runner test ('2 failed, 3686 passed, 48 skipped').
  test_child_env_own_key::test_a_model_cannot_ask_for_a_key:
      fixed by 566 (f0cdfda7 + v0.6.3): 566 realhost/GR.txt Gt 'PASSED tests/test_child_env_own_key.py::
      test_a_model_cannot_ask_for_a_key' and its G lists no such line.
  test_pi_attachment_private_paths::test_graphtraj_collection_entry_protects_its_directory_and_declares_it (564):
      failed in 566's and 567's G (candidates without 565); fixed by 565 (38de25ac + v0.6.3): 565
      realhost/main-raw/GR.txt has no such line ('5 failed, 3650 passed, 48 skipped', all five 560-known lines).
Exit 1 when any NEW line exists.
"""
import re
import sys

T = '.graphtraj/core/state/tasks/'
FIXED_ON_DEV = {
    **{f'tests/test_native_gateway.py::test_codex_uses_progressive_mcp_with_native_session_authority[{p}]':
       f'fixed by 551: {T}551-task-free-children-reach-tasks-methods/realhost/main-raw/GR-v063.txt (a57decf0 + '
       '79532b5: no test_native_gateway line)' for p in ('helper-main', 'thread-1-main', 'helper-independent',
                                                        'thread-1-independent')},
    'tests/test_child_env_own_key.py::test_a_model_cannot_ask_for_a_key':
        f'fixed by 566: {T}566-child-env-own-key-test-expects-pre-555-response/realhost/GR.txt (Gt: PASSED)',
    'tests/test_pi_attachment_private_paths.py::test_graphtraj_collection_entry_protects_its_directory_and_declares_it':
        f'fixed by 565: {T}565-pi-collector-stdin-eof-under-click-8-2/realhost/main-raw/GR.txt (no such line)',
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
print(f'516 current definition read: {"yes" if flaky else "NO (every failure is NEW)"} ({flaky_path})')
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
    if test.split('::')[-1].split('[')[0] in flaky:
        print(f'  known flaky (516 current definition {flaky_path}): {test}\n      observed: {observed}')
    elif (helper := raising_function(observed)) and helper.startswith('_') and helper in flaky:
        print(f'  known flaky (516 current definition {flaky_path} names the helper {helper} it failed in): {test}'
              f'\n      observed: {observed}')
    elif test in FIXED_ON_DEV:
        new += 1
        print(f'  NEW (a 560-known line that dev fixed fails again; {FIXED_ON_DEV[test]}): {test}\n'
              f'      observed: {observed}')
    else:
        new += 1
        print(f'  NEW: {test}\n      observed: {observed}')
print(f'failed tests: {len(blocks)} | NEW: {new}')
sys.exit(1 if new else 0)
