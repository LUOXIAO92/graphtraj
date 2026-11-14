"""Live Claude collection costs grow with new records, not the Session (468)."""
import json
from pathlib import Path
import time

from graftling.sessions.archive import JsonlSessionStore, SessionArchive, archive_path
from graftling.sessions.claude import ClaudeJsonlCollector


def message(uid: str, parent: str | None, role: str, size: int = 50) -> dict:
    """One transcript entry of ``size`` characters of text."""
    return {'type': role, 'uuid': uid, 'parentUuid': parent, 'sessionId': 's',
            'timestamp': '2026-01-01T00:00:00Z',
            'message': {'role': role, 'id': 'api-' + uid, 'model': 'native-model',
                        'content': [{'type': 'text', 'text': 'x' * size}]}}


class Live:
    """A bound collector fed as the Claude owner feeds it: transcript line, then live record."""

    def __init__(self, root: Path) -> None:
        root.mkdir(exist_ok=True)
        self.path = root / 'native.jsonl'
        self.path.write_text('')
        self.archive = SessionArchive(root / 'swarm', save_normalized_sessions=True, backfill_history=True)
        self.collector = ClaudeJsonlCollector(self.archive, 's', root, 'execution')
        self.collector.bind(self.path)
        self.count, self.parent, self.position = 0, None, 0

    def batch(self, pairs: int, size: int = 50) -> float:
        """Write ``pairs`` user/assistant exchanges and collect them as one batch; return its CPU time."""
        records = []
        with self.path.open('a') as stream:
            for _ in range(pairs):
                for role in ('user', 'assistant'):
                    record = message(str(self.count), self.parent, role, size)
                    self.parent, self.count = record['uuid'], self.count + 1
                    stream.write(json.dumps(record) + '\n')
                    live = {key: value for key, value in record.items() if key != 'sessionId'}
                    self.position += 1
                    records.append(({**live, 'session_id': 's'}, self.position))
        started = time.process_time()
        self.collector.accept_batch(records)
        return time.process_time() - started

    def store(self) -> JsonlSessionStore:
        """Reopen the archive from disk, as an independent reader."""
        return JsonlSessionStore(archive_path(self.archive.root, 'claude:s'))


def test_a_batch_commits_once_not_once_per_record(tmp_path: Path) -> None:
    """Every record of a batch is archived by one atomic commit."""
    live = Live(tmp_path)
    live.batch(1)
    before = live.store().page()['revision']
    live.batch(5)
    after = live.store()
    assert after.page()['revision'] == before + 1
    assert [m['id'] for m in after.messages()] == [str(n) for n in range(12)]
    assert after.pending() == []


def test_batch_cost_does_not_grow_with_the_archived_history(tmp_path: Path) -> None:
    """The same batch costs about the same after a small or a 100x larger history.

    Both Sessions hold 200 records; only their content size differs (about
    0.1 MB and 8 MB). Reparsing, copying or re-encoding the old history would
    make the larger one tens of times slower.
    """
    costs = {}
    for size in (200, 20000):
        live = Live(tmp_path / str(size))
        for _ in range(10):
            live.batch(10, size)
        costs[size] = min(live.batch(1) for _ in range(5))
    print('per-batch CPU', costs)
    assert costs[20000] < max(3 * costs[200], 0.1)


def test_another_writer_between_batches_is_kept(tmp_path: Path) -> None:
    """A change by another writer is read before the next batch commits."""
    live = Live(tmp_path)
    live.batch(2)
    other = live.store()
    other.mark_boundary('other-writer', 7)
    live.batch(2)
    final = live.store()
    assert final.position('other-writer') == 7
    assert [m['id'] for m in final.messages()] == [str(n) for n in range(8)]


def test_many_sessions_through_one_archive_keep_few_files_open(tmp_path: Path) -> None:
    """Collecting many Sessions with one archive (as migration does) does not hold one file per Session."""
    import os

    archive = SessionArchive(tmp_path / 'swarm', save_normalized_sessions=True, backfill_history=True)
    before = len(os.listdir('/dev/fd'))
    for index in range(40):
        session = f's{index}'
        path = tmp_path / f'{session}.jsonl'
        records = [{**message('q', None, 'user'), 'sessionId': session},
                   {**message('a', 'q', 'assistant'), 'sessionId': session}]
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))
        ClaudeJsonlCollector(archive, session, tmp_path, 'execution').bind(path)
    assert len(os.listdir('/dev/fd')) - before <= 3
    for index in range(40):
        stored = JsonlSessionStore(archive_path(archive.root, f'claude:s{index}'))
        assert [m['id'] for m in stored.messages()] == ['q', 'a']


def test_a_rewritten_transcript_is_read_again(tmp_path: Path) -> None:
    """Only appended lines are parsed incrementally; a rewritten file is read whole."""
    live = Live(tmp_path)
    live.batch(2)
    lines = live.path.read_text().splitlines()
    changed = json.loads(lines[-1])
    changed['message']['content'][0]['text'] = 'y' * 50
    live.path.write_text('\n'.join(lines[:-1] + [json.dumps(changed)]) + '\n')
    live.collector.collect()
    gaps = [p for p in live.store().pending() if p['event']['native']['locator'] == 'history-gap']
    assert gaps and gaps[0]['event']['missing'][0]['reason'] == 'A published native UUID changed content.'
