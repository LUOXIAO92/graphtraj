"""Rehearsal only: the agent record (and, with archiving on, the child's archive) a real host would leave.

STUB570_CHILD_FAIL=1: the child's execution fails (as the 'haiku' alias did), so the record holds a failed outcome.
"""
import hashlib, json, os, uuid
from pathlib import Path


def write(root: Path, runtime: str, host: str, word: str) -> str:
    agent, session = f'agent-{uuid.uuid4().hex}', str(uuid.uuid4())
    failed = bool(os.environ.get('STUB570_CHILD_FAIL'))
    execution = ({'state': 'ended', 'outcome': 'failed', 'error': {'code': 'RUNTIME_REQUEST_FAILED'}, 'last_message': None}
                 if failed else {'state': 'ended', 'outcome': 'completed', 'last_message': word})
    (root / 'control' / 'agents').mkdir(parents=True, exist_ok=True)
    (root / 'control' / 'agents' / f'{agent}.json').write_text(json.dumps({
        'agent': agent, 'runtime': runtime, 'session': session,
        'creator': {'host': host, 'session': 'stub'}, 'executions': [execution]}))
    config = root / 'config.yml'
    if config.is_file() and 'save_normalized_sessions: true' in config.read_text():
        identity = f'{runtime}:{session}'
        archive = root / 'sessions' / hashlib.sha256(identity.encode()).hexdigest() / 'session.jsonl'
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps({'archiveVersion': 1, 'header': {
            'id': identity, 'version': 5, 'native': {'runtime': runtime, 'sessionId': session}}}) + '\n')
    answer = 'failed' if failed else word
    return f'AGENT: {agent}\nANSWER: {answer}\nSTATUS: standby; delivered\nLISTED: {agent}'
