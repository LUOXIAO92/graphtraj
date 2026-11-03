"""Step 96: which credential NAMES a real child sees, on each of the four Runtimes (433 items 1 and 6, 439 item 1).

Run by 96-child-env.zsh as `python -E -s child_env.py`, from $RUN, after prepare_checks. Imports rh392 read-only.
Every command a model runs here prints variable names only: `cut -d= -f1` drops each value before anything
is printed, and `ps -E` output goes through the same cut. FAKE439_TOKEN is a fake marker the step exports.
The markers are printed with printf, so the command's own text never holds NAMES-BEGIN or NAMES-END and a
copy of the command in a saved session cannot be read as its output.
"""
from __future__ import annotations

import re
import sys

from rh392 import CHILD_CHOICE, Host, call, check, connection, judge, last_result, note, script_prompt

PATTERN = 'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|^FAKE'
# Each name is followed by (set) or (empty): the value is only tested by [ -n ], never printed. ps -E tokens go
# through sed, which replaces NAME=value by NAME(set) or NAME(empty) before anything is printed.
NAMES = ("printf '%s-%s\\n' NAMES BEGIN; "
         f"for n in $(env | cut -d= -f1 | grep -E '{PATTERN}' | sort); do "
         "if [ -n \"$(printenv \"$n\")\" ]; then printf '%s(set) ' \"$n\"; else printf '%s(empty) ' \"$n\"; fi; done; echo; "
         "if ps -E -p $PPID >/dev/null 2>&1; then echo PSE-ALLOWED; "
         "ps -E -p $PPID | tr ' ' '\\n' | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "
         "| sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)=$/\\1(empty)/; s/^([A-Za-z_][A-Za-z0-9_]*)=.+$/\\1(set)/' "
         f"| grep -E '{PATTERN}' | sort -u | tr '\\n' ' '; echo; else echo PSE-DENIED; fi; printf '%s-%s\\n' NAMES END")
ALLOWED = {'DEEPSEEK_API_KEY'}
CHILD_INSTRUCTION = ('Run exactly this one command with your shell tool, once: ' + NAMES +
                     ' Then end with a final reply that repeats the command output exactly, nothing else.')


def names(text: str) -> tuple[list[str], list[str], str] | None:
    """Return (environment names, parent names through ps -E, ps state) of the last marked block, or None."""
    text = (text or '').replace('\\n', '\n')
    blocks = re.findall(r'NAMES-BEGIN(.*?)NAMES-END', text, re.S)
    if not blocks:
        return None
    lines = [line.strip() for line in blocks[-1].strip().splitlines()]
    # A word is NAME, NAME(set) or NAME(empty); the judged list keeps the marker so the summary shows it.
    words = lambda line: [word for word in line.split() if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\((set|empty)\))?', word)]
    state = next((line for line in lines if line.startswith('PSE-')), 'PSE-unknown')
    position = lines.index(state) if state in lines else -1
    after = lines[position + 1] if 0 <= position < len(lines) - 1 else ''
    return words(lines[0]) if lines else [], words(after) if state == 'PSE-ALLOWED' else [], state


def saved_text(host: Host) -> str:
    """Return the text of the host's saved data, where a child's own session holds its tool output."""
    parts = []
    for path in sorted(host.data.rglob('*')):
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 20_000_000:
            try:
                parts.append(path.read_text(errors='replace'))
            except OSError:
                continue
    return '\n'.join(parts)


def host_shell(kind: str, host: Host, name: str) -> None:
    """439 item 1: the top-level Codex host's own tool shell keeps the user environment."""
    own = host.work / f'host-names-{kind}.txt'
    own.unlink(missing_ok=True)
    host.turn(f'{name}-own', f'Run exactly this with your shell tool, once: ( {NAMES} ) > {own} '
              'Then reply with one line and stop.', limit=240)
    try:
        parsed = names(own.read_text(errors='replace'))
        own.unlink()
    except OSError:
        parsed = None
    if parsed is None:
        check('CANNOT', f'439 item 1: the {kind} host did not run the names command')
        return
    environment, _, state = parsed
    note(f'{kind} host shell sees: {environment}; ps -E {state}')
    present = [word for word in environment if word.split('(')[0] == 'FAKE439_TOKEN']
    judge(bool(present), '439 item 1: the top-level Codex host keeps the user environment',
          present[0] if present else 'FAKE439_TOKEN absent')


def one(kind: str) -> None:
    """One host of ``kind`` creates a child of the same Runtime, which runs the names command."""
    name = f'child-env-{kind}'
    host = Host(kind, name, {kind: None}, {'connections': {f'local-{kind}': connection(kind)}})
    if kind == 'codex':
        host_shell(kind, host, name)
    model, effort = CHILD_CHOICE[kind]
    turn = host.turn(name, script_prompt([
        call('create', runtime=kind, model=model, reasoning_effort=effort, name=f'env-{kind}', instruction=CHILD_INSTRUCTION),
        call('wait', agent='<agent from 1>', timeout_seconds=240),
        call('status', agent='<agent from 1>'),
    ], 'If the child asks permission to run that command, allow it with the agents tool and wait again until it has '
       'finished. Then reply with one line and stop.'), limit=480)
    host.keep_data()
    created = turn.created(kind)
    if not created:
        check('CANNOT', f'{kind} child: no child was created in {turn.seconds:.0f} s (exit {turn.exit_code})')
        return
    agent = created['agent']
    replies = [str(last_result(d).get('last_message') or '') for d in turn.of('wait', agent) + turn.of('status', agent)]
    parsed = next((item for item in map(names, replies) if item is not None), None)
    source = 'its reply'
    if parsed is None:
        parsed, source = names(saved_text(host)), 'its own saved session'
    if parsed is None:
        check('CANNOT', f'{kind} child: neither its reply nor its saved session held the names output')
        return
    environment, parent, state = parsed
    bare = lambda word: word.split('(')[0]
    extra = sorted(word for word in environment if bare(word) not in ALLOWED)
    judge(not extra, f'433 item 1: a {kind} child environment holds no credential name but its own key (from {source})',
          extra or environment)
    judge('FAKE439_TOKEN' not in map(bare, environment), f'439 item 1: a {kind} child does not see FAKE439_TOKEN',
          'absent' if 'FAKE439_TOKEN' not in map(bare, environment) else 'present')
    if state == 'PSE-DENIED':
        check('PASS', f'433 item 6: ps -E on the parent is denied inside a {kind} child')
    elif state == 'PSE-ALLOWED':
        judge(not {bare(word) for word in parent} - ALLOWED, f'433 item 6: ps -E on the parent from a {kind} child shows no credential name but its own key',
              sorted(parent))
    else:
        check('CANNOT', f'433 item 6: {kind} child gave no ps -E state')


if __name__ == '__main__':
    for runtime in sys.argv[1:] or ['claude', 'codex', 'pi', 'dsh']:
        try:
            one(runtime)
        except Exception as error:  # one Runtime's failure must not hide the others
            check('FAIL', f'{runtime}: child_env.py stopped: {type(error).__name__}: {error}')
