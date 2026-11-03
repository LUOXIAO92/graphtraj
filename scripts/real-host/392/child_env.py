"""Step 96: which credential NAMES a real child sees, on each of the four Runtimes (433 items 1 and 6, 439 item 1).

Run by 96-child-env.zsh as `python -E -s child_env.py`, from $RUN, after prepare_checks. Imports rh392 read-only.
Every command a model runs here prints variable names only: `cut -d= -f1` drops each value before anything
is printed, and `ps -E` output goes through the same cut. FAKE439_TOKEN is a fake marker the step exports.
"""
from __future__ import annotations

import re
import sys

from rh392 import Host, call, check, connection, judge, last_result, note

PATTERN = 'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|^FAKE'
NAMES = (f"echo NAMES-BEGIN; env | cut -d= -f1 | grep -E '{PATTERN}' | sort | tr '\\n' ' '; echo; "
         f"if ps -E -p $PPID >/dev/null 2>&1; then echo PSE-ALLOWED; "
         f"ps -E -p $PPID | tr ' ' '\\n' | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' | cut -d= -f1 | grep -E '{PATTERN}' "
         f"| sort -u | tr '\\n' ' '; echo; else echo PSE-DENIED; fi; echo NAMES-END")
ALLOWED = {'DEEPSEEK_API_KEY'}


def names(text: str) -> tuple[list[str], list[str], str] | None:
    """Return (environment names, parent names through ps -E, ps state) between the markers, or None."""
    match = re.search(r'NAMES-BEGIN(.*?)NAMES-END', text or '', re.S)
    if not match:
        return None
    lines = [line.strip() for line in match.group(1).strip().splitlines()]
    words = lambda line: [word for word in line.split() if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', word)]
    state = next((line for line in lines if line.startswith('PSE-')), 'PSE-unknown')
    after = lines[lines.index(state) + 1] if state in lines and lines.index(state) + 1 < len(lines) else ''
    return words(lines[0]) if lines else [], words(after) if state == 'PSE-ALLOWED' else [], state


def one(kind: str) -> None:
    """One host of ``kind`` runs the command itself, then has a child of the same Runtime run it."""
    name = f'child-env-{kind}'
    host = Host(kind, name, {kind: None}, {'connections': {f'local-{kind}': connection(kind)}})
    own = f'host-names-{kind}.txt'
    prompt = ('Do these in order, using only your shell tool and the agents tool. Do not print environment values. '
              f'1) Run exactly this with your shell tool: ( {NAMES} ) > {own} '
              f'2) Use the agents tool: {call("create", runtime=kind, connection=f"local-{kind}", instruction="Run exactly this one command with your shell tool, once, and reply with only its output: " + NAMES)} '
              '3) Wait for that child with the wait feature, timeout_seconds 240. If it asks permission to run that '
              'command, allow it with the agents tool and wait again, until it has finished. 4) Reply with one line: done.')
    turn = host.turn(name, prompt, limit=420)
    host.keep_data()
    try:
        own_text = (host.work / own).read_text(errors='replace')
        (host.work / own).unlink()
    except OSError:
        own_text = ''
    parsed = names(own_text)
    if parsed is None:
        check('CANNOT', f'{kind} host shell: the host did not run the names command')
    else:
        environment, _, state = parsed
        note(f'{kind} host shell sees: {environment}; ps -E {state}')
        if kind == 'codex':
            judge('FAKE439_TOKEN' in environment, '439 item 1: the top-level Codex host keeps the user environment',
                  'FAKE439_TOKEN present' if 'FAKE439_TOKEN' in environment else 'FAKE439_TOKEN absent')
    created = turn.created(kind)
    if not created:
        check('CANNOT', f'{kind} child: no child was created in {turn.seconds:.0f} s (exit {turn.exit_code})')
        return
    agent = created['agent']
    replies = [str(last_result(d).get('last_message') or '') for d in turn.of('wait', agent) + turn.of('status', agent)]
    parsed = next((item for item in map(names, replies) if item is not None), None)
    if parsed is None:
        check('CANNOT', f'{kind} child: its reply held no names output')
        return
    environment, parent, state = parsed
    extra = sorted(set(environment) - ALLOWED)
    judge(not extra, f'433 item 1: a {kind} child environment holds no credential name but its own key', extra or environment)
    judge('FAKE439_TOKEN' not in environment, f'439 item 1: a {kind} child does not see FAKE439_TOKEN',
          'absent' if 'FAKE439_TOKEN' not in environment else 'present')
    if state == 'PSE-DENIED':
        check('PASS', f'433 item 6: ps -E on the parent is denied inside a {kind} child')
    elif state == 'PSE-ALLOWED':
        judge(not set(parent) - ALLOWED, f'433 item 6: ps -E on the parent from a {kind} child shows no credential name but its own key',
              sorted(parent))
    else:
        check('CANNOT', f'433 item 6: {kind} child gave no ps -E state')


if __name__ == '__main__':
    for runtime in sys.argv[1:] or ['claude', 'codex', 'pi', 'dsh']:
        try:
            one(runtime)
        except Exception as error:  # one Runtime's failure must not hide the others
            check('FAIL', f'{runtime}: child_env.py stopped: {type(error).__name__}: {error}')
