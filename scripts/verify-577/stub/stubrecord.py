"""Rehearsal only (Task 577): the answer and agent record a real Main would leave, in the root the candidate picks.

STUB577_CHILD_ENV=0: the child lists neither name. STUB577_SECOND_HOST=1: a second host endpoint appears in the root.
"""
import json, os, uuid
from pathlib import Path


def answer(prompt: str, kind: str, config: str | None) -> str:
    """One line for a plain prompt; for a create prompt, one record under the chosen root and four lines."""
    if '"feature":"create"' not in prompt:
        return f'{kind}-stub-model (stub provider)'
    root = (Path(json.loads(Path(config).read_text())['root']) if config
            else Path(os.environ['GRAFTLING_DATA_ROOT']) if os.environ.get('GRAFTLING_DATA_ROOT')
            else Path.cwd() / '.agents-control')
    agent = f'agent-{uuid.uuid4().hex}'
    said = 'ready'
    if 'shell command' in prompt and os.environ.get('STUB577_CHILD_ENV') != '0':
        said = 'GRAFTLING_CONNECTION GRAFTLING_DATA_ROOT ready'
    (root / 'control' / 'agents').mkdir(parents=True, exist_ok=True)
    (root / 'live' / f'{kind}-host' / uuid.uuid4().hex[:8]).mkdir(parents=True, exist_ok=True)
    if os.environ.get('STUB577_SECOND_HOST'):
        (root / 'live' / f'{kind}-host' / uuid.uuid4().hex[:8]).mkdir()
    (root / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps({
        'agent': agent, 'runtime': 'dsh', 'session': str(uuid.uuid4()),
        'creator': {'host': f'{kind}-native', 'session': 'stub'},
        'executions': [{'state': 'ended', 'outcome': 'completed', 'last_message': said}]}))
    return f'AGENT: {agent}\nANSWER: {said}\nSTATUS: standby; delivered\nLISTED: {agent}'
