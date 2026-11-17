"""Check the markers of the adopted Tasks 496 and 498 in a site-packages tree (499).

usage: markers.py <site-packages> <expect: present|absent>

Each marker is a line the diff 2da634af..871aaaa9 adds under src/ in the two changed modules,
graftling/control.py and graftling/tool_descendants.py. graftling/CHANGELOG.md and PUBLIC_API.md also changed; they
ARE installed (package-data in src/graftling/pyproject.toml; production has both), so proddiff.py compares them file
by file; they carry no code and get no marker. The files are read as text; nothing is imported. Exit 0 only when every marker is as
expected: ``present`` for the candidate or the installed venv (871aaaa9), ``absent`` for production (2da634af).
"""
import sys
from pathlib import Path

ADD = 'add'
MARKERS = [
    ('496 control._alive: an exiting or zombie Runtime is not alive', 'graftling/control.py',
     '    return not has_exited(pid)', ADD),
    ('496 has_exited reads the kernel exiting/zombie state', 'graftling/tool_descendants.py',
     'def has_exited(pid: int) -> bool:', ADD),
    ('498 verdict on a settled read', 'graftling/tool_descendants.py',
     'def _verdict(pid: int, marker: str, recorded: bool = False) -> str:', ADD),
    ('498 executed (P_EXEC) is a kernel fact', 'graftling/tool_descendants.py',
     'def _executed(pid: int) -> bool:', ADD),
    ('498 recorded entries are judged again (cascade)', 'graftling/tool_descendants.py',
     '    def _settle(self, live: dict[tuple[int, int], dict]) -> None:', ADD),
    ('498 cascade: entries recorded beneath a foreign one', 'graftling/tool_descendants.py',
     'def _beneath(live: dict[tuple[int, int], dict], roots: set[tuple[int, int]]) -> set[tuple[int, int]]:', ADD),
    ('498 stop time: the same verdict right before each signal', 'graftling/tool_descendants.py',
     '        if _alive(item) and _verdict(item.pid, marker, recorded=True) in (OURS, PROVISIONAL):', ADD),
    ('498 stop time: unsettled reads only under remaining', 'graftling/tool_descendants.py',
     "              'remaining': [entry(pid) for pid in sorted({*alive, *unsettled})]}", ADD),
]


def main() -> int:
    site, expect = Path(sys.argv[1]), sys.argv[2]
    bad = 0
    for label, relative, text, kind in MARKERS:
        path = site / relative
        found = path.is_file() and text in path.read_text(encoding='utf-8', errors='replace')
        ok = found if expect == 'present' else not found
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {label} [{kind}]: line {'found' if found else 'not found'} in {path}")
    print(f"markers expected {expect}: {'PASS' if bad == 0 else 'FAIL'} ({len(MARKERS) - bad}/{len(MARKERS)})")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
