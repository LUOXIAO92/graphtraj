"""528 GR: classify the FAILED/ERROR lines of a G run as known-old or NEW. Read only. Copied from gr525.py; new
source '525 G' (525's accepted sharded run, adoption/G-8267f9e5-20261119T204121, whose one failure
test_team_replacement.py::test_interrupt_returns_after_slow_terminal_record 525 rounds/1/leader.md classifies
known/load).

usage: gr528.py <state tasks directory> <G run directory>

Known-old sources (each failure is printed with the first source that lists it):
  516       Task 516's list (state tasks/516-low-priority-flaky-tests/task.md): items 1-7 below, and any failure whose
            text names the clock step-back message of its 'not pursued' entry.
  523 F     the accepted full run of 523 (realhost/F-20261118T231935/pytest.txt)
  521 F     the accepted full run of 521 (realhost/F-summary.txt)
  518 G     the accepted sharded run of 518 (realhost/G-a9a54bba-gl-ed19e48-015240: suite.txt, shards/*.log)
A test id matches a source when the source names the same id; 516 items 1 and 2 name whole files (any test there).
Exit 0 when no failure is NEW (and the run ended: an 'exit=' line); 1 otherwise.
"""
import re
import sys
from pathlib import Path

T516_FILES = ['tests/test_claude_native_host.py::', 'tests/test_claude_codex_host_shutdown.py::']
T516_IDS = [
    'tests/test_tool_descendants_459.py::test_owner_killed_then_reconciliation_stops_the_recorded_shell_and_sleep',
    'tests/test_codex_app_server.py::test_unhandled_server_requests_fail_visibly_without_blocking_peers[absent-RUNTIME_REQUEST_UNHANDLED]',
    'tests/test_team_session_delivery.py::test_a_leader_dispatches_two_same_role_members_in_one_turn',
    'tests/test_claude_runner.py::test_child_registration_follows_its_owning_execution',
    'tests/test_claude_runner.py::test_public_interrupt_reconfirms_an_undrained_worker',
    'tests/test_claude_host_concurrent_calls.py::test_call_log_names_each_call_without_its_arguments',
]
CLOCK = 'system time precedes the chronologically last event'
T525 = '525-production-adoption-graftling-0-6-1'
G525 = 'G-8267f9e5-20261119T204121'
T525_ID = 'tests/test_team_replacement.py::test_interrupt_returns_after_slow_terminal_record'
LINE = re.compile(r'^(FAILED|ERROR) (tests/\S+)(?: - (.*))?$')


def failures(paths: list[Path]) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(errors='replace').splitlines():
            m = LINE.match(line.strip())
            if m:
                found.setdefault(m.group(2), m.group(3) or '')
    return found


def main() -> int:
    tasks, run = Path(sys.argv[1]), Path(sys.argv[2])
    sources = {
        '523 F': [tasks / '523-cleanup-worktree-busy-after-completion/realhost/F-20261118T231935/pytest.txt'],
        '521 F': [tasks / '521-read-only-result-references/realhost/F-summary.txt'],
        '518 G': [tasks / '518-worker-cpu-after-child-create/realhost/G-a9a54bba-gl-ed19e48-015240/suite.txt',
                  *sorted((tasks / '518-worker-cpu-after-child-create/realhost/G-a9a54bba-gl-ed19e48-015240/shards').glob('*.log'))],
        # 528: 525's accepted G (8267f9e5 + v0.6.1, 6 shards): 1 failure, classified known/load by 525's Leader.
        '525 G': [tasks / f'{T525}/adoption/{G525}/suite.txt', *sorted((tasks / f'{T525}/adoption/{G525}/shards').glob('*.log'))],
    }
    known = {name: failures(paths) for name, paths in sources.items()}
    for name, paths in sources.items():
        print(f'known source {name}: {len(known[name])} failures listed; files read: '
              f'{sum(p.is_file() for p in paths)}/{len(paths)}')
    decision = tasks / f'{T525}/teams/1/rounds/1/leader.md'
    text = decision.read_text(errors='replace') if decision.is_file() else ''
    print(f'known source 525 G decision: {decision} {"present" if decision.is_file() else "MISSING"}; names '
          f'{T525_ID.split("::")[1]} as known: {"yes" if T525_ID.split("::")[1] in text and "known" in text else "NO"}')
    t516 = tasks / '516-low-priority-flaky-tests/task.md'
    print(f'known source 516: {t516} {"present" if t516.is_file() else "MISSING"}; {len(T516_IDS)} test ids, '
          f'{len(T516_FILES)} files, clock message')
    logs = [run / 'suite.txt', *sorted((run / 'shards').glob('*.log'))]
    got = failures(logs)
    texts = '\n'.join(p.read_text(errors='replace') for p in logs if p.is_file())
    ended = re.search(r'^exit=\d+', texts, re.M)
    new = 0
    for test, message in sorted(got.items()):
        base = test.split('[')[0]
        why = None
        if any(test.startswith(f) for f in T516_FILES) or test in T516_IDS or base in T516_IDS or CLOCK in message:
            why = '516'
        else:
            why = next((name for name in known if test in known[name]), None)
        if why is None:
            new += 1
        print(f"  {'known (' + why + ')' if why else 'NEW'}  {test}{(' - ' + message[:160]) if message else ''}")
    summary = [l for l in texts.splitlines() if re.search(r'\d+ (passed|failed)', l)]
    print(f'G summary lines: {summary[-3:] or "none"}')
    print(f'G failures: {len(got)} | NEW: {new} | run ended: {"yes" if ended else "NO (still running?)"}')
    ok = new == 0 and bool(ended)
    print(f"CHECK 528 G no NEW failure (516 and the accepted 523/521/518/525 runs are known): {'PASS' if ok else ('FAIL' if ended else 'PENDING')}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
