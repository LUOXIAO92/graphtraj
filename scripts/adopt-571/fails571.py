"""571 (from 560's fails560.py): FAILED/ERROR lines of a full-suite run with the first assertion or error lines of each.
Read only.

usage: fails571.py <out failures.txt> <log> [<log> ...]

Writes one block per failed test id to <out>: the `FAILED <id>` line, then up to three `E ` lines of its section
(`____ <test name> ____` in pytest's -rA output) with the `file:line` that raised. Prints the same.
"""
import re
import sys

out, logs = sys.argv[1], sys.argv[2:]
text = ''
for log in logs:
    try:
        text += open(log, encoding='utf-8', errors='replace').read() + '\n'
    except OSError:
        pass
ids = sorted({(m.group(2), m.group(1)) for m in re.finditer(r'^(FAILED|ERROR) (\S+)', text, re.M)})
blocks = []
for test, kind in ids:
    name = test.split('::')[-1]
    # pytest pads the section title with underscores; a long title gets only one on each side. Frame separators inside
    # a traceback ('_ _ _ _') are not titles.
    section = re.search(r'^_+ (?:ERROR at \w+ of )?' + re.escape(name) + r' _+\n(.*?)(?=^_+ [^_\s].* _+$|^={3,} )', text, re.M | re.S)
    lines = []
    if section:
        body = section.group(1)
        lines = [l.rstrip() for l in body.splitlines() if l.startswith('E ')][:3]
        where = re.findall(r'^(\S+\.py:\d+): ', body, re.M)
        if where:
            lines.append('at ' + where[-1])
    blocks.append('\n'.join([kind + ' ' + test] +['    ' + l[:300] for l in lines or ['(no E line found in the logs)']]))
open(out, 'w', encoding='utf-8').write('\n'.join(blocks) + ('\n' if blocks else ''))
print('\n'.join(blocks) if blocks else '(no FAILED/ERROR lines)')
