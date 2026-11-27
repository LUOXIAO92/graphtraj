"""653 V/I: is the difference between two graphtraj-claude-host copies exactly graftling's template change?

usage: plugin653.py <production copy> <candidate copy> <old host_context.mjs> <new host_context.mjs>

The hook copy is written by graftling.claude.plugin.claude_host_plugin from graftling/claude/host_context.mjs, with
its TOOLS and SERVER lines replaced by the values GraphTraj's runtimes/claude/host.py passes. GraphTraj's side is
unchanged between production (4ef36426) and the adoption commit, and graftling v0.10.2..v0.11.0 changes
host_context.mjs only (647 venv base interpreter, 652 Windows marketplace refusal), not plugin.py. So:
  - .claude-plugin/plugin.json and hooks/hooks.json: byte-identical;
  - hooks/host_context.mjs: its removed and added lines (difflib, no context) are exactly those of the old template
    against the new one (the two templates are git show v0.10.2 and v0.11.0 of src/graftling/claude/host_context.mjs);
  - no other file in either copy.
Read only. Exit 0 = exactly that; 1 = anything else (the step STOPs); 2 = the copies are identical (the prediction
is wrong: the plugin/hooks trust dialog would not be expected).
"""
import difflib
import sys
from pathlib import Path

SAME = ('.claude-plugin/plugin.json', 'hooks/hooks.json')
MODULE = 'hooks/host_context.mjs'


def files(root: Path) -> set[str]:
    """Return every file below ``root``, relative and POSIX-style."""
    return {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}


def changes(old: str, new: str) -> list[str]:
    """Return the removed (``-``) and added (``+``) lines of ``old`` -> ``new``, in order, without context."""
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm='', n=0)
    return [line for line in lines if line[:1] in '+-' and not line.startswith(('---', '+++'))]


def main(production: str, candidate: str, old_template: str, new_template: str) -> int:
    """Print the comparison and return the exit code described in the module docstring."""
    prod, cand = Path(production), Path(candidate)
    bad = 0

    # The same three files, and no other, in both copies.
    names = files(prod) | files(cand)
    expected = set(SAME) | {MODULE}
    if files(prod) != expected or files(cand) != expected:
        print(f'FILES   production {sorted(files(prod))} | candidate {sorted(files(cand))} | expected {sorted(expected)}')
        bad = 1
    for name in SAME:
        same = (prod / name).is_file() and (cand / name).is_file() and (prod / name).read_bytes() == (cand / name).read_bytes()
        print(f'{"SAME   " if same else "CHANGED"} {name} (expected SAME)')
        bad |= not same

    # The module: the copies' own change against the templates' change.
    got = changes((prod / MODULE).read_text(encoding='utf-8'), (cand / MODULE).read_text(encoding='utf-8')) \
        if MODULE in names and (prod / MODULE).is_file() and (cand / MODULE).is_file() else ['<missing>']
    want = changes(Path(old_template).read_text(encoding='utf-8'), Path(new_template).read_text(encoding='utf-8'))
    removed, added = sum(line[0] == '-' for line in got), sum(line[0] == '+' for line in got)
    print(f'{"CHANGED" if got else "SAME   "} {MODULE}: {removed} lines removed, {added} added '
          f'| graftling template v0.10.2 -> v0.11.0: {sum(l[0] == "-" for l in want)} removed, {sum(l[0] == "+" for l in want)} added')
    if not got and not bad:
        print('IDENTICAL: the copies are the same; the prediction (a changed host_context.mjs) is wrong')
        return 2
    if got != want:
        print('  the copies differ otherwise than the templates; first differing change lines:')
        for line in [l for l in difflib.unified_diff(want, got, 'template change', 'copy change', lineterm='', n=0)][:20]:
            print('   ', line[:200])
        bad = 1
    print('RESULT plugin653:', 'exactly the template change' if not bad else 'NOT the predicted difference')
    return bad


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
