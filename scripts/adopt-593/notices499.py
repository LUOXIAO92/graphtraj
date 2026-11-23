"""499 (497 defect b): count the member's completed notices by the notice's own shape. Read only.

usage: notices499.py <N-main-notice.txt> [<member alias>]

A notice line, as Main receives it (497 raw N-main-notice.txt):
  [Graftling notice from <member alias> · completed · execution <hex>] Session execution ended: {...}
Only lines that START with that shape count (and, when an alias is given, name it). Main's explanatory or header
lines (for example '# Every notice of ...', or prose that quotes the word completed) are never counted.
Prints the count.
"""
import re, sys

# 593: also the GraphTraj Main notice title (main_continuity.py) and 591's DSH title; graftling's Claude title is unchanged.
SHAPE = re.compile(r'^\[(?:Graftling|GraphTraj|subagents) notice from (\S+) · completed · execution [0-9a-f]+\] ')
alias = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] not in ('', 'none') else None
with open(sys.argv[1], encoding='utf-8', errors='replace') as stream:
    print(sum(1 for line in stream if (m := SHAPE.match(line)) and (alias is None or m.group(1) == alias)))
