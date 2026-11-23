"""Task 581: pytest node ids and error origins for SR, suite-base and SRX (read only on the files given).

usage:
  suiteids.py ids <pytest output>...           every FAILED/ERROR node id, one per line, deduplicated. The id ends at
                                               the ' - ' pytest puts before the message; a parametrized id ends at
                                               its matching ']'. When the ']' is not on the line (an id holding a
                                               newline, or cut), the id is reduced to file::function, which pytest
                                               runs with all its parameters. Specific ids covered by such a prefix
                                               are dropped.
  suiteids.py present <collected> <ids file>   the ids found in `pytest --collect-only -q` output (exact, or a
                                               prefix of a collected id), one per line; the others go to stderr
  suiteids.py classify <ids file> <base out> <candidate out>
                                               per id: fails on both (pre-existing) | candidate-only | passes on
                                               both now (not reproduced) | ... ; exit 1 when any is candidate-only
  suiteids.py errors <pytest output>...        per failing test section (FAILURES/ERRORS): its name, the first
                                               'E ' line and the raise location (the last 'file:line: Error' line)
"""
import re, sys

RESULT = re.compile(r'^(FAILED|ERROR|PASSED|XPASS|XFAIL|SKIPPED) (.+)$')


def node_id(rest):
    """The node id at the start of `rest` (after 'FAILED '), or file::function when a bracket is not closed."""
    head = rest.split(' - ')[0]
    if '[' not in head:
        return head.strip(), False
    start, depth = rest.index('['), 0
    for i in range(start, len(rest)):
        depth += {'[': 1, ']': -1}.get(rest[i], 0)
        if depth == 0:
            return rest[:i + 1], False
    return rest[:start], True


def ids(paths):
    found, prefixes = [], set()
    for path in paths:
        for line in open(path, errors='replace'):
            m = RESULT.match(line.rstrip('\n'))
            if not m or m.group(1) not in ('FAILED', 'ERROR'):
                continue
            nid, prefix = node_id(m.group(2))
            if prefix:
                prefixes.add(nid)
            if nid not in found:
                found.append(nid)
    return [n for n in found if n in prefixes or not any(n.startswith(p + '[') for p in prefixes)]


def outcomes(path, nid, prefix):
    """'failed' if any matching item failed, else 'passed' if one passed, else 'not run'."""
    got = set()
    for line in open(path, errors='replace'):
        m = RESULT.match(line.rstrip('\n'))
        if not m:
            continue
        rest = m.group(2)
        if rest == nid or rest.startswith(nid + ' - ') or (prefix and rest.startswith(nid + '[')):
            got.add(m.group(1))
    return 'failed' if got & {'FAILED', 'ERROR'} else 'passed' if got & {'PASSED', 'XPASS'} else 'not run'


def classify(ids_file, base, candidate):
    candidate_only = 0
    for nid in [l.rstrip('\n') for l in open(ids_file) if l.strip()]:
        prefix = '[' not in nid.split('::')[-1]
        b, c = outcomes(base, nid, prefix), outcomes(candidate, nid, prefix)
        verdict = {('failed', 'failed'): 'fails on both (pre-existing)',
                   ('passed', 'failed'): 'candidate-only',
                   ('not run', 'failed'): 'candidate-only (not run on base: missing there?)',
                   ('passed', 'passed'): 'passes on both now (not reproduced)',
                   ('failed', 'passed'): 'base-only (passes on the candidate)'}.get((b, c), f'base {b}, candidate {c}')
        candidate_only += verdict.startswith('candidate-only')
        print(f'{verdict}: {nid}   [base {b} | candidate {c}]')
    print(f'candidate-only: {candidate_only}')
    return 1 if candidate_only else 0


def present(collected, ids_file):
    have = [l.strip() for l in open(collected, errors='replace') if '::' in l]
    for nid in [l.rstrip('\n') for l in open(ids_file) if l.strip()]:
        ok = nid in have or any(h.startswith(nid + '[') or h.startswith(nid + '::') for h in have)
        print(nid, file=sys.stdout if ok else sys.stderr)
    return 0


# A test section header is '___ name ___', or '_ name _' when the name is long, and may lack its closing
# underscores (an id holding a newline continues on the next line). Traceback separators ('_ _ _ ...') are not
# headers: a name never starts with '_' or a space.
SECTION = re.compile(r'^_+ ([^_\s].*?)(?: _+)?$')
BANNER = re.compile(r'^={3,} ?(.*?) ?={3,}$')
LOCATION = re.compile(r'^(\S+\.py):(\d+): (\S.*)$')


def errors(paths):
    for path in paths:
        inside, name, first_e, where = False, None, None, None

        def flush():
            if name:
                print(f'{name}\n    first E: {first_e or "(none)"}\n    raised at: {where or "(no location line)"}')

        for line in open(path, errors='replace'):
            line = line.rstrip('\n')
            banner = BANNER.match(line)
            if banner:
                flush()
                name = None
                inside = banner.group(1) in ('FAILURES', 'ERRORS')
                continue
            if not inside:
                continue
            section = SECTION.match(line)
            if section:
                flush()
                name, first_e, where = section.group(1), None, None
            elif name and line.startswith('E ') and first_e is None:
                first_e = line[1:].strip()[:400]
            elif name and LOCATION.match(line):
                where = line[:300]
        flush()
    return 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['ids'] and len(a) >= 2:
        print('\n'.join(ids(a[1:])))
        sys.exit(0)
    if a[:1] == ['present'] and len(a) == 3:
        sys.exit(present(a[1], a[2]))
    if a[:1] == ['classify'] and len(a) == 4:
        sys.exit(classify(*a[1:]))
    if a[:1] == ['errors'] and len(a) >= 2:
        sys.exit(errors(a[1:]))
    print(__doc__)
    sys.exit(2)
