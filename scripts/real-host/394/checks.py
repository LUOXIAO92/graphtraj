"""The matrix criteria of the 394 real-host steps: 392's matrix (checks.py cell and matrix), unchanged
but for the renamed package. Each zsh matrix step runs ``python -E -s checks.py matrix <host>``.

Each cell drives a real host through rh394 and writes one PASS, FAIL or CANNOT line per criterion to
the step's summary. An unexpected error ends that one cell with a FAIL naming it, and the next cell
still runs, because the user is not available to debug.
"""
from __future__ import annotations

import sys
import traceback

from rh394 import (CHILD_CHOICE, OUT, RUNTIMES, SLEEP, Host, call, check, connection, error_code, judge,
                   last_result, note, script_prompt, shown_count)

WAIT = 240


def guarded(name: str, case, *arguments) -> None:
    """Run one case; an unexpected error is that case's FAIL, not the step's end."""
    try:
        case(*arguments)
    except Exception as error:
        (OUT / f'{name}.traceback.txt').write_text(traceback.format_exc())
        check('FAIL', f'{name}: the check itself stopped with {type(error).__name__}: {str(error)[:300]}; '
                      f'see {name}.traceback.txt')


def wait_call(agent: str = '<agent from 1>', seconds: int = WAIT) -> str:
    """Return one wait call."""
    return call('wait', agent=agent, timeout_seconds=seconds)


# -- the 16 cells ---------------------------------------------------------

def cell(kind: str, runtime: str) -> None:
    """One host and one child Runtime: create, status, send, interrupt, resume, retire."""
    name = f'{kind}-x-{runtime}'
    model, effort = CHILD_CHOICE[runtime]
    # 408: a Claude host's Pi child has no declared connection, so create's model is checked against
    # the catalog of pi on the host's PATH. Everywhere else the declared list avoids that query.
    declared = not (kind == 'claude' and runtime == 'pi')
    host = Host(kind, name, {runtime: None}, {'connections': {f'local-{runtime}': connection(runtime)}} if declared else {})
    sleep = SLEEP.format(seconds=120, answer='SLEPT') + ('' if runtime != 'dsh' else ' Your parent authorizes it.')
    first = host.turn(name + '-1', script_prompt([
        call('create', runtime=runtime, model=model, reasoning_effort=effort, name=f'c-{kind}-{runtime}',
             instruction='Do not use any tool. Reply with exactly: PONG-1'),
        wait_call(),
        call('status', agent='<agent from 1>'),
        call('send', agent='<agent from 1>', message='Do not use any tool. Reply with exactly: PONG-2'),
        wait_call(),
        call('send', agent='<agent from 1>', message=sleep),
        call('interrupt', agent='<agent from 1>'),
        wait_call(),
        call('resume', agent='<agent from 1>', message='Do not use any tool. Reply with exactly: PONG-3'),
        wait_call(),
        call('create', runtime=runtime, model='no-such-model-394', instruction='Reply OK.'),
    ], 'Then reply with one line: AGENT=<agent from 1>, and stop.'))
    created = first.created(runtime)
    if created is None:
        check('FAIL', f'{name} create: no child; results {[(d.get("action"), error_code(d)) for d in first.documents][:6]}; '
                      f'see {first.label}.stdout, .stderr')
        host.keep_data()
        return
    agent, session = created['agent'], created.get('session')
    identity = created['result']
    judge(identity.get('runtime') == runtime and identity.get('model') == model
          and identity.get('reasoning_effort') == effort,
          f'{name} create chooses Runtime, model and effort',
          {field: identity.get(field) for field in ('runtime', 'model', 'reasoning_effort', 'connection')})
    statuses = first.of('status', agent)
    shown = statuses[0]['result'] if statuses else {}
    judge(bool(statuses) and shown.get('agent') == agent and shown.get('parent') is None and shown.get('runtime') == runtime
          and (shown.get('creator') or {}).get('session') not in (None, ''),
          f'{name} status shows identity and parent',
          {field: shown.get(field) for field in ('agent', 'name', 'runtime', 'parent', 'creator', 'host')})
    second = host.turn(name + '-2', script_prompt([
        call('status', agent=agent),
        call('retire', agent=agent),
        call('retire', agent=agent),
    ]))
    turns = [first, second]
    judge(any(not error_code(d) for d in first.of('send', agent)) and shown_count(host, turns, agent, 'PONG-2') >= 1,
          f'{name} send reaches the child and its answer comes back',
          f"PONG-2 shown {shown_count(host, turns, agent, 'PONG-2')}")
    interrupts = [(d.get('result') or {}).get('interrupt') for d in first.of('interrupt', agent)]
    ended = [item for item in host.notices_of(agent) if item['event'] == 'interrupted']
    outcomes = [last_result(d).get('outcome') for d in first.of('wait', agent)]
    judge(any(item in ('requested', 'already-requested') for item in interrupts)
          and (bool(ended) or 'interrupted' in outcomes),
          f'{name} interrupt stops the child', f'interrupt {interrupts}; wait outcomes {outcomes}; notices {len(ended)}')
    resumed = [d for d in first.of('resume', agent) if not error_code(d)]
    judge(bool(resumed) and resumed[0].get('session') == session and shown_count(host, turns, agent, 'PONG-3') >= 1,
          f'{name} resume continues the same native Session',
          f"session {session} -> {resumed[0].get('session') if resumed else None}; "
          f"PONG-3 shown {shown_count(host, turns, agent, 'PONG-3')}")
    refused = [error_code(d) for d in first.of('create') if d is not created and d.get('agent') is None]
    judge('invalid-model' in refused, f'{name} an invalid model is refused by name', refused)
    later = second.of('status', agent)
    same = later[0]['result'] if later else {}
    judge(bool(later) and all(same.get(field) == shown.get(field) for field in ('agent', 'runtime', 'parent', 'creator', 'session')),
          f'{name} a new host process shows the same identity', {field: same.get(field) for field in ('agent', 'runtime', 'parent')})
    retires = [(d.get('result') or {}) for d in second.of('retire', agent)]
    judge(len(retires) >= 2 and retires[0].get('retired') is True and retires[1].get('duplicate') is True,
          f'{name} retire takes effect once', [(r.get('retired'), r.get('duplicate')) for r in retires])
    counts = {token: shown_count(host, turns, agent, token) for token in ('PONG-1', 'PONG-2', 'PONG-3')}
    judge(all(value == 1 for value in counts.values()), f'{name} each answer reaches the parent once', counts)
    if not declared:
        note(f'{name}: no connection declared; create accepted {model} and refused no-such-model-394 against the catalog '
             'of pi on PATH (408)')
    host.keep_data()


def matrix(kind: str) -> None:
    """One host's row of the matrix."""
    for runtime in RUNTIMES:
        guarded(f'{kind}-x-{runtime}', cell, kind, runtime)
    summary = (OUT / 'summary.txt').read_text().splitlines()
    table = []
    for runtime in RUNTIMES:
        name = f'{kind}-x-{runtime}'
        lines = [line for line in summary if line.split(' ', 1)[-1].startswith(name) and not line.startswith('note')]
        failed = [line for line in lines if line.startswith(('FAIL', 'CANNOT'))]
        table.append(f"{name}: {'NO RESULT' if not lines else 'FAIL' if failed else 'PASS'} ({len(lines) - len(failed)} of {len(lines)})")
    (OUT / 'matrix.txt').write_text('\n'.join(table) + '\n')
    print('\n'.join(table))


if __name__ == '__main__':
    guarded(sys.argv[1], globals()[sys.argv[1]], *sys.argv[2:])
